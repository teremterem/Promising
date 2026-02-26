import asyncio
import concurrent.futures
import itertools
from asyncio import AbstractEventLoop, Future, Task, coroutines
from collections.abc import Coroutine, Generator
from typing import Any, Generic

from promising.errors import PromiseNotFoundError
from promising.promising_context import PromisingContext
from promising.sentinels import INHERIT, NOT_SET, Sentinel
from promising.types import T_co

# TODO This is not thread-safe anymore - promises and contexts can be created
#  in other threads now
_promise_name_counter = itertools.count(1)


def get_active_promise(*, raise_if_none: bool = True) -> "Promise[Any] | None":
    """
    Get the currently active Promise from context (skipping over any
    PromisingContexts that aren't Promises).

    Args:
        raise_if_none: If True, raises PromiseNotFoundError when no active
            Promise is found.

    Returns:
        The currently active Promise instance, or None if no Promise is active
        and raise_if_none is False.

    Raises:
        PromiseNotFoundError: If no active Promise is found and raise_if_none
            is True.
    """
    return Promise.get_active_promise(raise_if_none=raise_if_none)


class Promise(PromisingContext, Future, Generic[T_co]):
    """
    A Promise combines PromisingContext's hierarchical context management
    with asyncio Future functionality.

    Promise extends both PromisingContext and asyncio Future to provide:
    - Asynchronous computation backed by a coroutine
    - Result/exception propagation via the Future interface
    - Thread-safe synchronous access via concurrent.futures compatibility
    - Hierarchical parent-child relationships (inherited from
      PromisingContext)

    Parent-child relationships (inherited from PromisingContext):
    - If a Promise's coroutine creates other Promises or
      PromisingContexts during execution, they are attached as children
      of that context.
    - The exact time when a child's execution starts, finishes, or when
      its resolution is triggered does not matter; it is still registered
      as a child of the context whose coroutine created it.
    - If a parent is explicitly specified at creation time, that explicit
      parent takes precedence.

    Type Parameters:
        T_co: The covariant type of the Promise's result.

    Args:
        coro: The coroutine to execute. If None, the Promise must be
            prefilled with a result or exception.
        loop: The event loop to use. Passed to PromisingContext; see
            PromisingContext.__init__ for inheritance behavior.
        name: Human-readable name for the Promise. If None, generates a
            unique name ("Promise-N", where N is a number).
        parent: Parent context. Passed to PromisingContext; see
            PromisingContext.__init__ for inheritance behavior.
        start_soon: Whether to start executing the coroutine immediately
            upon creation. Passed to PromisingContext; see
            PromisingContext.__init__ for inheritance behavior.
        children_start_soon_by_default: Default start_soon value enforced
            on child contexts. Passed to PromisingContext; see
            PromisingContext.__init__ for inheritance behavior.
        everything_starts_soon_by_default: Local override for the global
            EVERYTHING_STARTS_SOON_BY_DEFAULT. Passed to PromisingContext;
            see PromisingContext.__init__ for inheritance behavior.
        prefill_result: Pre-set result value. Cannot be combined with coro
            or prefill_exception.
        prefill_exception: Pre-set exception. Cannot be combined with coro
            or prefill_result.
        # TODO Better to explain `start_soon` related parameters here, and not
        #  refer the reader to the PromisingContext docstring

    Raises:
        ValueError: If invalid parameter combinations are provided.
        TypeError: If coro is not a coroutine when provided.
    """

    _task: Task[T_co] | None

    # TODO TODO TODO Order the methods in this class in a more useful manner

    def __init__(
        self,
        coro: Coroutine[Any, Any, T_co] | None = None,
        *,
        loop: AbstractEventLoop | None = None,
        name: str | None = None,
        parent: "PromisingContext | Sentinel | None" = INHERIT,
        start_soon: bool | Sentinel = NOT_SET,
        children_start_soon_by_default: bool | Sentinel = NOT_SET,
        everything_starts_soon_by_default: bool | Sentinel = INHERIT,
        prefill_result: T_co | Sentinel | None = NOT_SET,
        # TODO Use NOT_SET instead of None below as well, for consistency ?
        prefill_exception: BaseException | None = None,
    ) -> None:
        PromisingContext.__init__(
            self,
            loop=loop,
            parent=parent,
            start_soon=start_soon,
            children_start_soon_by_default=children_start_soon_by_default,
            everything_starts_soon_by_default=everything_starts_soon_by_default,
        )
        Future.__init__(
            self,
            # We will use the loop that PromisingContext resolved for us in its
            # __init__, instead of letting Future's __init__ decide how to
            # interpret the loop directly parameter (specifically when it's
            # None)
            loop=self._ctx_loop,
        )

        self._task = None
        self._concurrent_future = _AsyncioBackedConcurrentFuture(self)

        # TODO TODO TODO Move the support of `name` to the level of
        #  PromisingContext
        if name is None:
            name = f"Promise-{next(_promise_name_counter)}"
        # TODO Implement custom __str__ and __repr__ methods and use this name
        #  in them ?
        self._name = name

        self._coro = coro
        self._finish_initialization(
            prefill_result=prefill_result,
            prefill_exception=prefill_exception,
        )

    def sync(self) -> T_co:
        """
        Synchronously wait for and return the Promise result, blocking the
        calling thread.

        This is the synchronous counterpart of `await promise` — intended for
        use inside sync promising functions that run in a thread pool executor.
        It schedules the Promise's execution on the event loop via
        `call_soon_threadsafe` and blocks until the result (or exception) is
        available.
        # TODO The reader does not need to be bothered by the implementation
        #  details of this method.

        Returns:
            The resolved value of the Promise.

        Raises:
            SyncPromiseUsageError: If called from the same thread as the event
                loop, which would deadlock.
        """
        self._assert_no_sync_usage_deadlock(
            "`promise.sync()` cannot be called from the "
            "event loop thread because it would deadlock. "
            "Use `await promise` instead."
        )

        self._loop.call_soon_threadsafe(self._ensure_task_scheduled)
        return self.as_concurrent_future().result()

    def _ensure_task_scheduled(self) -> None:
        if self._task is None and not self.done():
            self._task = self._loop.create_task(self._fulfill(), name=self._name + "-Task")

    def set_result(self, result: T_co) -> None:
        """
        Set the result of the Promise. This method is not intended to be called
        directly by users; it is managed by the Promise's lifecycle.

        Also sets the result on the concurrent.futures.Future for thread
        compatibility (see `as_concurrent_future()` method).

        Args:
            result: The result value to set.
        """
        super().set_result(result)
        self._concurrent_future.set_result(result)

    def set_exception(self, exception: BaseException) -> None:
        """
        Set an exception on the Promise. This method is not intended to be
        called directly by users; it is managed by the Promise's lifecycle.

        Also sets the exception on the concurrent.futures.Future for thread
        compatibility (see `as_concurrent_future()` method).

        Args:
            exception: The exception to set.
        """
        super().set_exception(exception)
        self._concurrent_future.set_exception(exception)

    async def _fulfill(self) -> None:
        """
        Execute the Promise's coroutine and manage its lifecycle.

        This method:
        1. Activates the Promise as the current context
        2. Executes the coroutine
        3. Sets the result or exception

        Raises:
            RuntimeError: If the Promise is already done or has no coroutine.
        """
        if self.done():
            # Should not happen
            raise RuntimeError(f"An attempt was made to fulfill a Promise that is already done: {self.get_name()}")
        if self._coro is None:
            # Should not happen
            raise RuntimeError(f"An attempt was made to fulfill a Promise with no coroutine: {self.get_name()}")

        result = NOT_SET
        exception = NOT_SET

        try:
            # Activate this Promise by setting it as the current context and
            # store the previous context token for later restoration
            # TODO TODO TODO Move to the level of PromisingContext
            #  (as a context manager)
            self._previous_token = self._active_context.set(self)

            result = await self._coro

        except BaseException as exc:  # noqa: BLE001 (blind-except)
            exception = exc
        finally:
            try:
                # Finalize the Promise execution by restoring context
                # (removing this Promise from the context and restoring the
                # previous value for the respective context var)
                # TODO TODO TODO Move to the level of PromisingContext
                #  (as a context manager)
                if self._previous_token is not None:
                    self._active_context.reset(self._previous_token)
                    self._previous_token = None

            finally:
                if exception is not NOT_SET:
                    self.set_exception(exception)
                else:
                    self.set_result(result)

    def __await__(self) -> Generator[Any, None, T_co]:
        """
        If the Promise hasn't started yet, start execution of the coro via
        _fulfill() and run it to completion. If already started via
        start_soon, wait for the existing task to complete.

        Returns:
            A generator for the await protocol that eventually returns the
            result of the Promise.
        """
        # TODO Ensure we are in the same thread as the Promise's event loop is
        #  running
        if self.done():
            return self.result()

        self._ensure_task_scheduled()

        yield from self._task
        return (yield from super().__await__())

    @classmethod
    def get_active_promise(cls, *, raise_if_none: bool = True) -> "Promise[Any] | None":
        """
        Get the currently active Promise from context variables (skipping over
        any PromisingContexts that aren't Promises).

        Args:
            raise_if_none: If True, raises an exception when no active Promise
                is found.

        Returns:
            The currently active Promise, or None if none exists and
            raise_if_none is False.

        Raises:
            PromiseNotFoundError: If no active Promise exists and
                raise_if_none is True.
        """
        # TODO Unit tests are needed for this method: specifically for the
        #  cases when active context and active promise are at different levels
        #  (with and without other contexts separating them). Also, we need to
        #  verify correct behavior when there are more than two promises in the
        #  hierarchy.
        current = cls.get_active_context(raise_if_none=False)
        while current is not None and not isinstance(current, Promise):
            current = current.get_parent_context(raise_if_none=False)

        if raise_if_none and current is None:
            raise PromiseNotFoundError("No active Promise found")
        return current

    def get_parent_promise(self, *, raise_if_none: bool = True) -> "Promise[Any] | None":
        """
        Get the parent Promise of this Promise (skipping over any
        PromisingContexts that aren't Promises).

        Args:
            raise_if_none: If True, raises an exception when no parent exists.

        Returns:
            The parent Promise, or None if no parent exists and raise_if_none
            is False.

        Raises:
            PromiseNotFoundError: If no parent exists and raise_if_none is
                True.
        """
        # TODO Unit tests are needed for this method: specifically for the
        #  cases when parent context and parent promise are at different levels
        #  (with and without other contexts separating them). Also, we need to
        #  verify correct behavior when there are more than two promises in the
        #  hierarchy.
        parent = self.get_parent_context(raise_if_none=False)
        while parent is not None and not isinstance(parent, Promise):
            parent = parent.get_parent_context(raise_if_none=False)

        if raise_if_none and parent is None:
            raise PromiseNotFoundError("No parent Promise found")
        return parent

    def get_name(self) -> str:
        """
        Get the human-readable name of this Promise.
        """
        return self._name

    def as_concurrent_future(self) -> concurrent.futures.Future[T_co]:
        """
        Get a thread-safe `concurrent.futures.Future` view of this Promise.

        This allows the Promise to be used in multi-threaded contexts where
        `concurrent.futures.Future` objects are expected.

        Returns:
            A `concurrent.futures.Future` that mirrors this Promise's state.
        """
        return self._concurrent_future

    def _finish_initialization(
        self,
        *,
        prefill_result: T_co | Sentinel | None,
        prefill_exception: BaseException | None,
    ) -> None:
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
            if not coroutines.iscoroutine(self._coro):
                raise TypeError(f"Promise must be created with a coroutine. Got {type(self._coro)}.")
            if prefill_result is not NOT_SET or prefill_exception is not None:
                raise ValueError("Cannot provide both 'coro' and 'prefill_result' or 'prefill_exception' parameters")

            if self._start_soon:
                # We don't know which thread the Promise is created in, so we
                # use `self._loop.call_soon_threadsafe` to "stay on the safe
                # side"
                self._loop.call_soon_threadsafe(self._ensure_task_scheduled)


class _AsyncioBackedConcurrentFuture(concurrent.futures.Future):
    """
    A thread-safe `concurrent.futures.Future` backed by an `asyncio.Future`.

    This class provides a bridge between asyncio-based Futures and the
    `concurrent.futures.Future` interface, allowing `asyncio.Future` instances
    to be used in multi-threaded contexts while maintaining proper
    result/exception synchronization.

    Args:
        asyncio_future: The `asyncio.Future` instance that backs this
            `concurrent.futures.Future`.
    """

    def __init__(self, asyncio_future: asyncio.Future[Any]) -> None:
        super().__init__()
        self._asyncio_future = asyncio_future

    def result(self, timeout: float | None = None) -> Any:
        """
        Get the result of the `asyncio.Future`.

        This method blocks until the underlying `asyncio.Future` is done and ensures
        that the `asyncio.Future`'s result is properly consumed (`asyncio` will not issue
        a warning about the `asyncio.Future` not having been awaited for).

        Args:
            timeout: Maximum time to wait for the result in seconds.

        Returns:
            The result value from the `asyncio.Future`.

        Raises:
            concurrent.futures.TimeoutError: If timeout expires before
                completion.
            Exception: Any exception that occurred during `asyncio.Future`
                execution.
        """
        try:
            # Let's block until the underlying `asyncio.Future` is done (it will
            # set the result/exception on this `concurrent.futures.Future`)
            result = super().result(timeout=timeout)
        finally:
            # Let's also read the result from the asyncio Future directly, so
            # it knows that its result has been consumed and there is no need
            # to issue a warning about the `asyncio.Future` not having been
            # awaited for (which, by this point, would be done already)
            try:
                self._asyncio_future.result()
            except BaseException:  # noqa: BLE001 (blind-except)
                # Suppress the error if any - if there's an error, it should
                # come from super().result(), not from here
                pass
        # For consistency, let's return the result from this concurrent Future,
        # even though it's going to be the same as the result from the asyncio
        # Future
        return result

    def exception(self, timeout: float | None = None) -> BaseException | None:
        """
        Get the exception that occurred during asyncio Future execution, if
        any.

        This method blocks until the underlying `asyncio.Future` is done and
        ensures that the `asyncio.Future`'s exception is properly consumed
        (asyncio will not issue a warning about the exception not having
        been retrieved from the `asyncio.Future`).

        Args:
            timeout: Maximum time to wait for completion in seconds.

        Returns:
            The exception that occurred, or None if the `asyncio.Future`
            completed successfully.

        Raises:
            concurrent.futures.TimeoutError: If timeout expires before
                completion.
        """
        try:
            # Let's block until the underlying `asyncio.Future` is done
            # (it will set the result/exception on this
            # `concurrent.futures.Future`)
            exception = super().exception(timeout=timeout)
        finally:
            # Let's also read the exception from the `asyncio.Future` directly,
            # so it knows that its exception has been consumed and there is no
            # need to issue a warning about the exception never being retrieved
            # from the `asyncio.Future` (which, by this point, would be done
            # already)
            try:
                self._asyncio_future.exception()
            except BaseException:  # noqa: BLE001 (blind-except)
                # Suppress the error if any - if there's an error, it should
                # come from super().exception(), not from here
                pass
        # For consistency, let's return the exception from this
        # `concurrent.futures.Future`, even though it's going to be the same as
        # the exception from the `asyncio.Future`
        return exception
