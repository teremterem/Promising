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
        raise_if_none: If True, raises NoCurrentPromiseError when no Promise is active.
                       If False, returns None when no Promise is active.

    Returns:
        The currently active Promise, or None if raise_if_none is False and no Promise is active.

    Raises:
        NoCurrentPromiseError: If raise_if_none is True and no Promise is active.
    """
    return Promise.get_current(raise_if_none=raise_if_none)


class Promise(Future, Generic[T_co]):
    """
    A Promise combines asyncio Future functionality with hierarchical context management.

    Promises extend asyncio Futures to provide:
    - Parent-child relationships between asynchronous operations
    - Context variable propagation across async boundaries
    - Configuration inheritance from parent Promises
    - Automatic child task management and waiting
    - Thread-safe concurrent.futures compatibility

    Type Parameters:
        T_co: The covariant type of the Promise's result.

    Attributes:
        _current: ContextVar tracking the currently active Promise.
        _previous_token: Token for restoring previous context when Promise deactivates.
        _task: The underlying asyncio Task if Promise was started with start_soon=True.
        _parent: Reference to the parent Promise if this is a child Promise.
        _children: WeakSet of child Promises created while this Promise was active.
        _concurrent_future: Thread-safe concurrent.futures.Future backing this Promise.
        _name: Human-readable name for debugging and logging.
        _config: Configuration object controlling Promise behavior.
        _coro: The coroutine to execute for this Promise.
    """

    _current: ContextVar[Optional["Promise[Any]"]] = ContextVar("Promise._current", default=None)
    _previous_token: Optional[contextvars.Token] = None

    _task: Optional[Task[T_co]] = None

    # TODO Support cancellation of the whole Promise tree

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
        """
        Initialize a new Promise.

        Args:
            coro: Coroutine to execute. If None, must provide prefill_result or prefill_exception.
            loop: Event loop to use. If None, uses parent's loop or current running loop.
            name: Human-readable name. If None, auto-generates "Promise-N".
            parent: Parent Promise. If NOT_SET, uses current Promise from context. If None, no parent.
            config: Configuration object. If None, inherits from parent or uses defaults.
            start_soon: If True, starts execution immediately. If NOT_SET, uses config default.
            make_parent_wait: If True, parent waits for this Promise. If NOT_SET, uses config default.
            config_inheritable: If True, child Promises inherit this config. If NOT_SET, uses config default.
            prefill_result: Pre-set result value (only if coro is None).
            prefill_exception: Pre-set exception (only if coro is None).

        Raises:
            ValueError: If conflicting parameters are provided (e.g., both coro and prefill_result).
            TypeError: If coro is not a coroutine.
        """
        # TODO Fix the following linting error:
        # pylint: disable=too-many-branches

        if parent is NOT_SET:
            self._parent = self.get_current(raise_if_none=False)
        else:
            self._parent = parent

        self._children: WeakSet[Promise[Any]] = WeakSet()

        if self._parent is not None:
            if loop is None:
                loop = self._parent._loop
                # TODO What if both, loop and parent loop are None ? That would NOT necessarily mean that they end up
                #  in the same loop !
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
        Set the result of the Promise.

        Also sets the result on the backing concurrent.futures.Future for thread compatibility.

        Args:
            result: The result value to set.
        """
        super().set_result(result)
        self._concurrent_future.set_result(result)

    def set_exception(self, exception: BaseException) -> None:
        """
        Set an exception on the Promise.

        Also sets the exception on the backing concurrent.futures.Future for thread compatibility.

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
        3. Waits for child Promises if configured
        4. Sets the result or exception

        Raises:
            RuntimeError: If the Promise is already done.
        """
        # TODO Raise an error if there is no coroutine
        if self.done():
            raise RuntimeError("Promise is already done")  # TODO Come up with a better error message

        result = NOT_SET
        exception = NOT_SET

        self._activate()
        try:
            result = await self._coro
        except BaseException as exc:  # pylint: disable=broad-except
            exception = exc
        finally:
            await self._afinalize()  # TODO Should we try-except this line too ?

            if exception is not NOT_SET:
                self.set_exception(exception)
            else:
                self.set_result(result)

    def __await__(self) -> Generator[T_co, None, None]:
        """
        Make Promise awaitable.

        If the Promise hasn't started yet, starts execution.
        If already started via start_soon, waits for the existing task.

        Returns:
            Generator for the await protocol.
        """
        if not self.done():
            if self._task is None:
                yield from self._afulfill().__await__()  # pylint: disable=no-member
            else:
                yield from self._task
        return (yield from super().__await__())

    def _init_config(self, config: Optional[PromiseConfig], **kwargs) -> PromiseConfig:
        """
        Initialize the Promise's configuration.

        Args:
            config: Explicit configuration object.
            **kwargs: Individual configuration parameters.

        Returns:
            Initialized PromiseConfig object.

        Raises:
            ValueError: If both config object and explicit kwargs are provided.
        """
        # TODO If config is provided and any of the kwarg values are not NOT_SET, raise a ValueError

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
        Get the currently active Promise from context.

        Args:
            raise_if_none: If True, raises NoCurrentPromiseError when no Promise is active.

        Returns:
            The currently active Promise, or None if raise_if_none is False.

        Raises:
            NoCurrentPromiseError: If raise_if_none is True and no Promise is active.
        """
        current = cls._current.get()
        if raise_if_none and current is None:
            raise NoCurrentPromiseError("No current Promise found")
        return current

    def get_parent(self, *, raise_if_none: bool = True) -> Optional["Promise[Any]"]:
        """
        Get this Promise's parent.

        Args:
            raise_if_none: If True, raises NoParentPromiseError when no parent exists.

        Returns:
            The parent Promise, or None if raise_if_none is False.

        Raises:
            NoParentPromiseError: If raise_if_none is True and no parent exists.
        """
        if raise_if_none and self._parent is None:
            raise NoParentPromiseError("No parent Promise found")
        return self._parent

    def is_active(self) -> bool:
        """
        Check if this Promise is currently active in context.

        Returns:
            True if the Promise is the current active Promise, False otherwise.
        """
        return self._previous_token is not None

    def get_name(self) -> str:
        """
        Get the Promise's name.

        Returns:
            The human-readable name of this Promise.
        """
        return self._name

    def get_config(self) -> PromiseConfig:
        """
        Get the Promise's configuration.

        Returns:
            The PromiseConfig object controlling this Promise's behavior.
        """
        return self._config

    def get_pending_children(self) -> set["Promise[Any]"]:
        """
        Get all child Promises that haven't completed yet.

        Handles potential race conditions when iterating over the WeakSet of children
        by retrying if the set changes during iteration.

        Returns:
            Set of child Promises that are not done.

        Raises:
            RuntimeError: If unable to get a stable view of children after 1000 attempts.
        """
        # TODO Copy the explanation from asyncio.tasks::all_children() here
        i = 0
        while True:
            try:
                children = list(self._children)
            except RuntimeError:
                i += 1
                if i > 1000:
                    raise
            else:
                return {child for child in children if not child.done()}

    def as_concurrent_future(self) -> concurrent.futures.Future[T_co]:
        """
        Get a thread-safe concurrent.futures.Future view of this Promise.

        Allows waiting for Promise completion from synchronous/threaded code.

        Returns:
            A concurrent.futures.Future that mirrors this Promise's state.
        """
        # TODO Should we ever copy the context vars to the caller's thread ?
        return self._concurrent_future

    def _activate(self) -> None:
        """
        Activate this Promise as the current context.

        Stores the previous context token for later restoration.
        """
        self._previous_token = self._current.set(self)

    async def _afinalize(self) -> None:
        """
        Finalize the Promise execution.

        Waits for child Promises configured with make_parent_wait=True,
        then restores the previous context.
        """
        # TODO Move this to wait_for_children() public method
        promises_to_await = [
            child for child in self.get_pending_children() if child.get_config().is_make_parent_wait()
        ]
        if promises_to_await:
            # TODO Do errors disappear from stdout/stderr when they are "gathered" like this ? Do they make it to
            #  stdout/stderr only when the whole python process exits ? We should somehow show the errors to the user
            #  as soon as they happen (for all children, not just the ones that make the parent wait).
            await asyncio.gather(*promises_to_await, return_exceptions=True)

        self._current.reset(self._previous_token)
        self._previous_token = None


class _PromiseBackedConcurrentFuture(concurrent.futures.Future):
    """
    Thread-safe concurrent.futures.Future that backs a Promise.

    Provides synchronous/threaded code access to Promise results,
    ensuring proper result/exception propagation between async and sync contexts.
    """

    def __init__(self, promise: "Promise[Any]") -> None:
        """
        Initialize the concurrent Future backed by a Promise.

        Args:
            promise: The Promise this Future represents.
        """
        super().__init__()
        self._promise = promise

    def result(self, timeout: Optional[float] = None) -> Any:
        """
        Get the result of the Promise, blocking if necessary.

        Args:
            timeout: Maximum time to wait in seconds. None means wait forever.

        Returns:
            The result value from the Promise.

        Raises:
            TimeoutError: If timeout expires before Promise completes.
            Exception: Any exception set on the Promise.
        """
        try:
            # Let's block until the underlying Promise is done (it will set the result/exception on this concurrent
            # Future)
            result = super().result(timeout=timeout)
        finally:
            # Let's also read the result from the Promise directly, so it knows that its result has been consumed and
            # there is no need to issue a warning about the promise not having been awaited for (which, by this point,
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
        Get the exception from the Promise, blocking if necessary.

        Args:
            timeout: Maximum time to wait in seconds. None means wait forever.

        Returns:
            The exception set on the Promise, or None if result was set instead.

        Raises:
            TimeoutError: If timeout expires before Promise completes.
        """
        try:
            # Let's block until the underlying Promise is done (it will set the result/exception on this concurrent
            # Future)
            exception = super().exception(timeout=timeout)
        finally:
            # Let's also read the exception from the Promise directly, so it knows that its exception has been consumed
            # and there is no need to issue a warning about the exception never being retrieved from the promise
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
