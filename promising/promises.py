import asyncio
import concurrent.futures
import contextvars
import itertools
from asyncio import AbstractEventLoop, Future, Task, coroutines
from contextvars import ContextVar
from typing import Any, Coroutine, Generator, Generic, Optional
from weakref import WeakSet

from promising.configs import PromiseConfig
from promising.errors import NoCurrentPromiseError, NoParentPromiseError
from promising.sentinels import NOT_SET, Sentinel
from promising.types import T_co


_promise_name_counter = itertools.count(1)


def get_current_promise(raise_if_none: bool = True) -> Optional["Promise[Any]"]:
    """
    Get the currently active Promise from context.

    Args:
        raise_if_none: If True, raises NoCurrentPromiseError when no current Promise is found.

    Returns:
        The currently active Promise instance, or None if no Promise is active and
        raise_if_none is False.

    Raises:
        NoCurrentPromiseError: If no current Promise is found and raise_if_none is True.
    """
    return Promise.get_current(raise_if_none=raise_if_none)


class Promise(Future, Generic[T_co]):
    """
    A Promise combines asyncio Future functionality with hierarchical context management.

    Promises extend asyncio Futures to provide:
    - Parent-child relationships between asynchronous operations
    - Configuration inheritance from parent Promises
    - Automatic child task management and waiting
    - Thread-safe concurrent.futures compatibility

    Parent-child relationships semantics:
    - If the coroutine of a Promise creates other Promise instances during its execution, those Promises are
      attached as children of that Promise.
    - The exact time when a child's execution starts, finishes, or when its resolution is triggered does not matter
      (it may occur outside of the parent's execution window); it is still registered as a child of the Promise whose
      coroutine created it.
    - If a parent is explicitly specified at creation time, that explicit parent takes precedence.

    Type Parameters:
        T_co: The covariant type of the Promise's result.

    Args:
        coro: The coroutine to execute. If None, the Promise must be prefilled with a result or exception.
        loop: The event loop to use. If not provided, inherits from the parent Promise. If no parent Promise, uses the
             current running loop. If provided explicitly and a parent Promise exists, must be the same event loop as
             the parent's loop.
        name: Human-readable name for the Promise. If None, generates a unique name ("Promise-N", where N is a number).
        parent: Parent Promise instance. If NOT_SET, uses the currently active Promise as parent.
        config: Configuration object. Cannot be combined with explicit config parameters.
        start_soon: Whether to start execution immediately. If NOT_SET, uses [inheritable] parent config setting.
        make_parent_wait: Whether parent should wait for this Promise. If NOT_SET, uses [inheritable] parent config
                         setting.
        config_inheritable: Whether this config can be inherited by children. If NOT_SET, defaults to True (unless the
                           default is overridden via PROMISING_DEFAULT_CONFIGS_INHERITABLE environment variable).
        prefill_result: Pre-set result value. Cannot be combined with coro or prefill_exception.
        prefill_exception: Pre-set exception. Cannot be combined with coro or prefill_result.

    Raises:
        ValueError: If invalid parameter combinations are provided. See parameter descriptions above.
        TypeError: If coro is not a coroutine when provided.
    """

    _current: ContextVar[Optional["Promise[Any]"]] = ContextVar("Promise._current", default=None)
    _previous_token: Optional[contextvars.Token] = None

    _task: Optional[Task[T_co]] = None

    # TODO [ALMOST READY] Support cancellation of the whole Promise tree

    def __init__(
        self,
        coro: Optional[Coroutine[Any, Any, T_co]] = None,
        *,
        loop: Optional[AbstractEventLoop] = None,
        name: Optional[str] = None,
        parent: Optional["Promise[Any]"] | Sentinel = NOT_SET,
        config: Optional[PromiseConfig] = None,
        # TODO Support optional `children_config` too
        start_soon: bool | Sentinel = NOT_SET,
        make_parent_wait: bool | Sentinel = NOT_SET,
        config_inheritable: bool | Sentinel = NOT_SET,
        prefill_result: Optional[T_co] | Sentinel = NOT_SET,
        prefill_exception: Optional[BaseException] = None,
    ) -> None:
        # TODO [ALMOST READY] Fix the following linting error:
        # pylint: disable=too-many-branches

        if parent is NOT_SET:
            self._parent = self.get_current(raise_if_none=False)
        else:
            self._parent = parent

        # TODO Is WeakSet below really going to work ? What about those child Promises that don't start_soon and the
        #  user did not keep a reference to them so they could be awaited later (and let's say they were marked as
        #  make_parent_wait) ? On one hand, they should not block the parent, because the parent will end up being
        #  blocked forever. On the other hand, what are implications of ignoring such promises ? This should be
        #  reconsidered when the library is used by MiniAgents and real life scenarios become clear.
        # TODO Issue a warning if start_soon is False, but make_parent_wait is True ? Prohibit such combinations
        #  altogether ?
        self._children: WeakSet[Promise[Any]] = WeakSet()

        if self._parent is not None:
            if loop is None:
                loop = self._parent._loop
            elif loop is not self._parent._loop:
                raise ValueError("Parent and child Promises must share the same event loop")

        if self._parent is not None:
            self._parent._children.add(self)

        # TODO Should we have a config setting to disable multithreading support ? Is there any speed benefit ?
        self._concurrent_future = _PromiseBackedConcurrentFuture(self)

        super().__init__(loop=loop)

        if name is None:
            name = f"Promise-{next(_promise_name_counter)}"
        self._name = name

        self._config = self._init_config(
            config,
            start_soon=start_soon,
            make_parent_wait=make_parent_wait,
            config_inheritable=config_inheritable,
        )

        self._coro = coro
        if self._coro is None:
            if prefill_result is not NOT_SET and prefill_exception is not None:
                raise ValueError("Cannot provide both 'prefill_result' and 'prefill_exception' parameters")

            if prefill_result is not NOT_SET:
                self.set_result(prefill_result)
            elif prefill_exception is not None:
                self.set_exception(prefill_exception)

            else:
                raise ValueError("Cannot create a Promise without a coroutine or prefilled result/exception")
        else:
            if not coroutines.iscoroutine(coro):
                raise TypeError(f"Promise must be created with a coroutine. Got {type(coro)}.")
            if prefill_result is not NOT_SET or prefill_exception is not None:
                raise ValueError("Cannot provide both 'coro' and 'prefill_result' or 'prefill_exception' parameters")

            if self._config.is_start_soon():
                self._task = self._loop.create_task(self._afulfill(), name=self._name + "-Task")

    def set_result(self, result: T_co) -> None:
        """
        Set the result of the Promise. This method is not intended to be called directly by users; it is managed by the
        Promise's lifecycle.

        Also sets the result on the concurrent.futures.Future for thread compatibility (see as_concurrent_future()
        method).

        Args:
            result: The result value to set.
        """
        super().set_result(result)
        self._concurrent_future.set_result(result)

    def set_exception(self, exception: BaseException) -> None:
        """
        Set an exception on the Promise. This method is not intended to be called directly by users; it is managed by
        the Promise's lifecycle.

        Also sets the exception on the concurrent.futures.Future for thread compatibility (see as_concurrent_future()
        method).

        Args:
            exception: The exception to set.
        """
        super().set_exception(exception)
        self._concurrent_future.set_exception(exception)

    async def _afulfill(self) -> None:
        """
        Execute the Promise's coroutine and manage its lifecycle.

        This method:
        1. Activates the Promise as the current context
        2. Executes the coroutine
        3. Waits for child Promises that have make_parent_wait=True
        4. Sets the result or exception

        Raises:
            RuntimeError: If the Promise is already done.
        """
        if self._coro is None:
            raise RuntimeError(f"An attempt was made to fulfill a Promise with no coroutine: {self.get_name()}")
        if self.done():
            raise RuntimeError(f"An attempt was made to fulfill a Promise that is already done: {self.get_name()}")

        result = NOT_SET
        exception = NOT_SET

        self._activate()
        try:
            result = await self._coro
        except BaseException as exc:  # pylint: disable=broad-except
            exception = exc
        finally:
            try:
                await self._afinalize()
            finally:
                if exception is not NOT_SET:
                    self.set_exception(exception)
                else:
                    self.set_result(result)

    def __await__(self) -> Generator[T_co, None, None]:
        """
        If the Promise hasn't started yet, start execution of the coro via _afullfil() and run it to completion.
        If already started via start_soon, wait for the existing task to complete.

        Returns:
            A generator for the await protocol that eventually returns the result of the Promise.
        """
        if not self.done():
            if self._task is None:
                yield from self._afulfill().__await__()  # pylint: disable=no-member
            else:
                yield from self._task
        return (yield from super().__await__())

    def _init_config(self, config: Optional[PromiseConfig], **kwargs) -> PromiseConfig:
        """
        Initialize the Promise configuration.

        Behavior:
        - If an explicit config object is provided, return it (as is).
        - Else, if all individual config kwargs are NOT_SET and a parent Promise exists, return the nearest inheritable
          parent configuration.
        - Else, construct and return a new PromiseConfig from the provided kwargs.

        Args:
            config: Explicit configuration object.
            **kwargs: Individual configuration parameters.

        Returns:
            A PromiseConfig instance.

        Raises:
            ValueError: If both a config object and any explicit config kwargs are provided.
        """
        if config is not None:
            if any(value is not NOT_SET for value in kwargs.values()):
                raise ValueError("Cannot provide both a 'config' object and explicit config kwargs")
            return config

        if self._parent is not None and all(value is NOT_SET for value in kwargs.values()):
            return self._parent.get_config().find_inheritable_config()

        return PromiseConfig(**kwargs)

    @classmethod
    def get_current(cls, *, raise_if_none: bool = True) -> Optional["Promise[Any]"]:
        """
        Get the currently active Promise from context variables.

        Args:
            raise_if_none: If True, raises an exception when no current Promise is found.

        Returns:
            The currently active Promise, or None if none exists and raise_if_none is False.

        Raises:
            NoCurrentPromiseError: If no current Promise exists and raise_if_none is True.
        """
        current = cls._current.get()
        if raise_if_none and current is None:
            raise NoCurrentPromiseError("No current Promise found")
        return current

    def get_parent(self, *, raise_if_none: bool = True) -> Optional["Promise[Any]"]:
        """
        Get the parent Promise of this Promise.

        Args:
            raise_if_none: If True, raises an exception when no parent exists.

        Returns:
            The parent Promise, or None if no parent exists and raise_if_none is False.

        Raises:
            NoParentPromiseError: If no parent exists and raise_if_none is True.
        """
        if raise_if_none and self._parent is None:
            raise NoParentPromiseError("No parent Promise found")
        return self._parent

    def is_active(self) -> bool:
        """
        TODO It is unclear what this method is going to be used for. Is this information going to be useful outside of
         the Promise class itself ?

        Returns:
            True if the Promise is currently active, False otherwise.
        """
        return self._previous_token is not None

    def get_name(self) -> str:
        """
        Get the human-readable name of this Promise.
        """
        return self._name

    def get_config(self) -> PromiseConfig:
        """
        Get the configuration object that controls the behavior of this Promise.

        Returns:
            The PromiseConfig instance associated with this Promise.
        """
        return self._config

    def get_pending_children(self) -> set["Promise[Any]"]:
        """
        Get child Promises that haven't completed yet (provided they are still reachable and weren't garbage collected
        yet).

        Handles potential race conditions when iterating over the WeakSet of children by retrying if the set changes
        during iteration.

        Returns:
            Set of child Promises that are not done.

        Raises:
            RuntimeError: If unable to get a stable view of children after 1000 attempts.
        """
        # # COPIED FROM asyncio.tasks::all_tasks():
        # Looping over a WeakSet (_all_tasks) isn't safe as it can be updated from another
        # thread while we do so. Therefore we cast it to list prior to filtering. The list
        # cast itself requires iteration, so we repeat it several times ignoring
        # RuntimeErrors (which are not very likely to occur). See issues 34970 and 36607 for
        # details.
        i = 0
        while True:
            try:
                children = list(self._children)  # In `asyncio.tasks` it was `_all_tasks` instead of `self._children`
            except RuntimeError:
                i += 1
                if i > 1000:
                    raise
            else:
                return {child for child in children if not child.done()}

    def as_concurrent_future(self) -> concurrent.futures.Future[T_co]:
        """
        Get a thread-safe concurrent.futures.Future view of this Promise.

        This allows the Promise to be used in multi-threaded contexts where concurrent.futures.Future objects are
        expected.

        Returns:
            A concurrent.futures.Future that mirrors this Promise's state.
        """
        # TODO Should we ever copy the context vars to the caller's thread (if this even makes sense) ?
        return self._concurrent_future

    def _activate(self) -> None:
        """
        Activate this Promise by setting it as the current context.

        Stores the previous context token for later restoration.
        """
        self._previous_token = self._current.set(self)

    async def await_for_children(self) -> None:
        """
        Await child Promises that should make the parent wait.
        """
        promises_to_await = [
            child for child in self.get_pending_children() if child.get_config().is_make_parent_wait()
        ]
        if promises_to_await:
            await asyncio.gather(*promises_to_await, return_exceptions=True)

    async def _afinalize(self) -> None:
        """
        Finalize the Promise execution by waiting for children and restoring context.

        Waits for all child Promises that have make_parent_wait=True, then deactivates this Promise by removing it from
        the context (and restoring the previous value for the respective context var).
        """
        await self.await_for_children()
        self._current.reset(self._previous_token)
        self._previous_token = None


class _PromiseBackedConcurrentFuture(concurrent.futures.Future):
    """
    A thread-safe concurrent.futures.Future backed by a Promise.

    This class provides a bridge between asyncio-based Promises and the concurrent.futures interface, allowing Promises
    to be used in multi-threaded contexts while maintaining proper result/exception synchronization.

    Args:
        promise: The Promise instance that backs this concurrent future.
    """

    def __init__(self, promise: "Promise[Any]") -> None:
        super().__init__()
        self._promise = promise

    def result(self, timeout: Optional[float] = None) -> Any:
        """
        Get the result of the Promise.

        This method blocks until the underlying Promise is done and ensures that the Promise's result is properly
        consumed (asyncio will not issue a warning about the Promise not having been awaited for).

        Args:
            timeout: Maximum time to wait for the result in seconds.

        Returns:
            The result value from the Promise.

        Raises:
            concurrent.futures.TimeoutError: If timeout expires before completion.
            Exception: Any exception that occurred during Promise execution.
        """
        try:
            # Let's block until the underlying Promise is done (it will set the result/exception on this concurrent
            # Future)
            result = super().result(timeout=timeout)
        finally:
            # Let's also read the result from the Promise directly, so it knows that its result has been consumed and
            # there is no need to issue a warning about the Promise not having been awaited for (which, by this point,
            # would be done already)
            try:
                self._promise.result()
            except BaseException:  # pylint: disable=broad-except
                # Suppress the error if any - if there's an error, it should come from super().result(), not from here
                pass
        # For consistency, let's return the result from this concurrent Future, even though it's going to be the
        # same as the result from the Promise
        return result

    def exception(self, timeout: Optional[float] = None) -> Optional[BaseException]:
        """
        Get the exception that occurred during Promise execution, if any.

        This method blocks until the underlying Promise is done and ensures that the Promise's exception is properly
        consumed (asyncio will not issue a warning about the exception not having been retrieved from the Promise).

        Args:
            timeout: Maximum time to wait for completion in seconds.

        Returns:
            The exception that occurred, or None if the Promise completed successfully.

        Raises:
            concurrent.futures.TimeoutError: If timeout expires before completion.
        """
        try:
            # Let's block until the underlying Promise is done (it will set the result/exception on this concurrent
            # Future)
            exception = super().exception(timeout=timeout)
        finally:
            # Let's also read the exception from the Promise directly, so it knows that its exception has been consumed
            # and there is no need to issue a warning about the exception never being retrieved from the Promise
            # (which, by this point, would be done already)
            try:
                self._promise.exception()
            except BaseException:  # pylint: disable=broad-except
                # Suppress the error if any - if there's an error, it should come from super().exception(), not from
                # here
                pass
        # For consistency, let's return the exception from this concurrent Future, even though it's going to be the
        # same as the exception from the Promise
        return exception
