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
    Get the currently active Promise in the current context.

    Args:
        raise_if_none: If True, raises NoCurrentPromiseError when no current Promise is found.
                      If False, returns None instead.

    Returns:
        The currently active Promise instance, or None if no Promise is active and
        raise_if_none is False.

    Raises:
        NoCurrentPromiseError: If no current Promise is found and raise_if_none is True.
    """
    return Promise.get_current(raise_if_none=raise_if_none)


class Promise(Future, Generic[T_co]):
    """
    A Promise implementation that extends asyncio.Future with context management and tree structure.

    Promise provides a context-aware asynchronous execution model where promises can form
    hierarchical relationships with parent-child dependencies. Each Promise can be configured
    with behavior settings that control execution timing and inheritance patterns.

    The Promise maintains context variables to track the currently active promise and supports
    concurrent execution through both asyncio and concurrent.futures interfaces.
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
        Initialize a new Promise instance.

        Args:
            coro: The coroutine to execute. If None, the Promise must be prefilled with a result
                 or exception.
            loop: The event loop to use. If not provided, inherits from parent or uses default.
            name: Human-readable name for the Promise. If None, generates a unique name.
            parent: Parent Promise instance. If NOT_SET, uses current Promise as parent.
            config: Configuration object. Cannot be combined with explicit config parameters.
            start_soon: Whether to start execution immediately. Defaults to config or parent setting.
            make_parent_wait: Whether parent should wait for this Promise. Defaults to config.
            config_inheritable: Whether this config can be inherited by children.
            prefill_result: Pre-set result value. Cannot be combined with coro or prefill_exception.
            prefill_exception: Pre-set exception. Cannot be combined with coro or prefill_result.

        Raises:
            ValueError: If invalid parameter combinations are provided.
            TypeError: If coro is not a coroutine when provided.
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
        Set the result of the Promise and its concurrent future.

        Args:
            result: The result value to set.
        """
        super().set_result(result)
        self._concurrent_future.set_result(result)

    def set_exception(self, exception: BaseException) -> None:
        """
        Set an exception on the Promise and its concurrent future.

        Args:
            exception: The exception to set.
        """
        super().set_exception(exception)
        self._concurrent_future.set_exception(exception)

    async def _afulfill(self) -> None:
        """
        Internal method to execute the Promise's coroutine and handle completion.

        This method activates the Promise context, executes the coroutine, handles any
        exceptions, and finalizes by waiting for child promises and cleaning up context.

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
        Make Promise awaitable by implementing the await protocol.

        If the Promise hasn't started execution, starts it immediately.
        Otherwise awaits the existing task.

        Returns:
            Generator that yields the Promise result when complete.
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

        Args:
            config: Explicit configuration object.
            **kwargs: Individual configuration parameters.

        Returns:
            The initialized PromiseConfig instance.

        Raises:
            ValueError: If both config object and kwargs are provided.
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
        Get the parent Promise of this instance.

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
        Check if this Promise is currently active in the context.

        Returns:
            True if the Promise is currently active (has set context), False otherwise.
        """
        return self._previous_token is not None

    def get_name(self) -> str:
        """
        Get the human-readable name of this Promise.

        Returns:
            The Promise's name string.
        """
        return self._name

    def get_config(self) -> PromiseConfig:
        """
        Get the configuration object for this Promise.

        Returns:
            The PromiseConfig instance associated with this Promise.
        """
        return self._config

    def get_pending_children(self) -> set["Promise[Any]"]:
        """
        Get all child Promises that are not yet completed.

        This method safely iterates through the WeakSet of children, handling
        potential RuntimeError exceptions that can occur during iteration.

        Returns:
            A set of child Promise instances that are still pending.

        Raises:
            RuntimeError: If unable to safely iterate children after 1000 attempts.
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
        Get a concurrent.futures.Future interface to this Promise.

        This allows the Promise to be used in multi-threaded contexts where
        concurrent.futures.Future objects are expected.

        Returns:
            A concurrent.futures.Future that mirrors this Promise's state.
        """
        # TODO Should we ever copy the context vars to the caller's thread ?
        return self._concurrent_future

    def _activate(self) -> None:
        """
        Activate this Promise by setting it as the current context.

        Stores the previous context token for later restoration.
        """
        self._previous_token = self._current.set(self)

    async def _afinalize(self) -> None:
        """
        Finalize the Promise execution by waiting for children and restoring context.

        Waits for all child promises that have make_parent_wait=True, then
        restores the previous context state.
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
    A concurrent.futures.Future implementation backed by a Promise.

    This class provides a bridge between asyncio-based Promises and the
    concurrent.futures interface, allowing Promises to be used in multi-threaded
    contexts while maintaining proper result/exception synchronization.
    """

    def __init__(self, promise: "Promise[Any]") -> None:
        """
        Initialize the concurrent future with a backing Promise.

        Args:
            promise: The Promise instance that backs this concurrent future.
        """
        super().__init__()
        self._promise = promise

    def result(self, timeout: Optional[float] = None) -> Any:
        """
        Get the result of the Promise, blocking until completion.

        This method blocks until the underlying Promise is done and ensures
        that the Promise's result is properly consumed.

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
        Get the exception that occurred during Promise execution, if any.

        This method blocks until the underlying Promise is done and ensures
        that the Promise's exception is properly consumed.

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
