import concurrent.futures
from asyncio import AbstractEventLoop, Future, Task, coroutines
from collections.abc import Coroutine, Generator
from typing import Any, Generic

from promising.errors import PromiseNotFoundError
from promising.promising_context import PromisingContext
from promising.sentinels import INHERIT, NOT_SET, Sentinel
from promising.types import T_co
from promising.utils import assert_no_sync_usage_deadlock, resolve_namespace


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
        namespace: Optional human-readable namespace string. Used in
            ``__repr__`` output. Passed to PromisingContext.
        parent: Parent context. Passed to PromisingContext; see
            PromisingContext.__init__ for inheritance behavior.
        start_soon: Whether associated work should start immediately (True) or
            not (False). NOT_SET (default) defers to the parent's
            children_start_soon if enforced, otherwise falls back to
            start_soon_default. INHERIT copies the parent's start_soon
            directly.
        children_start_soon: (Also boolean or Sentinel.) Default start_soon
            value enforced on child Promises that left their start_soon setting
            as NOT_SET. For the children_start_soon setting itself, NOT_SET
            (default) means no enforcement. INHERIT in children_start_soon
            copies the parent's children_start_soon setting.
            NOTE: The default for children_start_soon is different in Promise
            than it is in PromisingContext (the latter defaults to INHERIT).
            This is to ensure that the enforcement by the Promise is meant to
            be an explicit choice. PromisingContext, on the other hand, which
            is usually created via `promising.context` context manager (and
            decorator), is meant to be a transparent grouping layer that,
            unless explicitly specified otherwise, simply passes the parent's
            policy through.
        thread_pool: Thread pool executor used to run sync promising
            functions. INHERIT (default) inherits from the parent context,
            falling back to GLOBAL_DEFAULT at the root. GLOBAL_DEFAULT uses
            Defaults.SYNC_THREAD_POOL. ASYNCIO_DEFAULT passes None to
            run_in_executor, letting the event loop use its own default
            executor. A concrete ThreadPoolExecutor instance can also be
            provided.
        start_soon_default: Local override for the global START_SOON_DEFAULT.
            INHERIT (default) propagates from the parent. GLOBAL_DEFAULT reads
            the current global setting without inheriting.
        prefill_result: Pre-set result value. Cannot be combined with coro
            or prefill_exception.
        prefill_exception: Pre-set exception. Cannot be combined with coro
            or prefill_result.

    Raises:
        ValueError: If invalid parameter combinations are provided.
        TypeError: If coro is not a coroutine when provided.
    """

    # TODO TODO TODO Figure out how to support async generator interface as
    #  well (together with its "sync" counterpart)

    def __init__(
        self,
        coro: Coroutine[Any, Any, T_co] | None = None,
        *,
        namespace: str | None = None,
        loop: AbstractEventLoop | None = None,
        parent: "PromisingContext | None | Sentinel" = INHERIT,
        thread_pool: "concurrent.futures.ThreadPoolExecutor | Sentinel" = INHERIT,
        start_soon: bool | Sentinel = NOT_SET,
        children_start_soon: bool | Sentinel = NOT_SET,
        start_soon_default: bool | Sentinel = INHERIT,
        prefill_result: T_co | None | Sentinel = NOT_SET,
        prefill_exception: BaseException | None = None,
    ) -> None:
        PromisingContext.__init__(
            self,
            namespace=namespace,
            loop=loop,
            parent=parent,
            thread_pool=thread_pool,
            children_start_soon=children_start_soon,
            start_soon_default=start_soon_default,
        )
        Future.__init__(
            self,
            # We will use the loop that PromisingContext resolved for us in its
            # __init__, instead of letting Future's __init__ decide how to
            # interpret the loop directly parameter (specifically when it's
            # None)
            loop=self._ctx_loop,
        )
        self._task: Task[T_co] | None = None
        self._concurrent_future = PromiseBackedConcurrentFuture[T_co](self)

        self._start_soon = self._resolve_start_soon(start_soon)

        self._coro = coro
        self._finish_initialization(
            prefill_result=prefill_result,
            prefill_exception=prefill_exception,
        )

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

    def __await__(self) -> Generator[Any, None, T_co]:
        """
        If the Promise hasn't started yet, start execution of the coro via
        _fulfill() and run it to completion. If already started via
        start_soon, wait for the existing task to complete.

        Returns:
            A generator for the await protocol that eventually returns the
            result of the Promise.
        """
        # TODO TODO TODO If the underlying coroutine upon awaiting also returns
        #  a Promise, we need to seamlessly await it as well !!! (Should also
        #  work with another Promise as a prefilled result)
        # TODO Ensure we are in the thread where the Promise's event loop is
        #  running
        if self.done():
            return self.result()

        self._ensure_task_scheduled()

        yield from self._task
        return (yield from super().__await__())

    def sync(self, *, timeout: float | None = None) -> T_co:
        """
        Synchronously wait for and return the Promise result, blocking the
        calling thread.

        This is the synchronous counterpart of ``await promise`` — intended for
        use inside sync promising functions that run in a thread pool executor.

        Args:
            timeout: Maximum time to wait for the result in seconds.

        Returns:
            The resolved value of the Promise.

        Raises:
            SyncUsageError: If called from the same thread as the event loop,
                which would deadlock.
            concurrent.futures.TimeoutError: If timeout expires before
                completion.
        """
        return self.as_concurrent_future().result(timeout=timeout)

    def as_concurrent_future(self) -> "PromiseBackedConcurrentFuture[T_co]":
        """
        Get a thread-safe `concurrent.futures.Future` view of this Promise.

        This allows the Promise to be used in multi-threaded contexts where
        `concurrent.futures.Future` objects are expected.

        Returns:
            A `concurrent.futures.Future` that mirrors this Promise's state.
        """
        return self._concurrent_future

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
        # ruff: BLE001 (blind-except)
        if self.done():
            # Should not happen
            raise RuntimeError(f"An attempt was made to fulfill a Promise that is already done: {self}")
        if self._coro is None:
            # Should not happen
            raise RuntimeError(f"An attempt was made to fulfill a Promise with no coroutine: {self}")

        result = NOT_SET
        exception = NOT_SET

        try:
            with self:
                result = await self._coro

        except BaseException as exc:
            exception = exc
            try:
                # TODO Make it possible to disable setting this trace ?
                # TODO Borrow from MiniAgents the mechanism that logs this
                #  "promising breadcrumb" together with the error tracebacks
                if not hasattr(exception, "__promising_context__"):
                    # We only let it be set at the deepest level of the promise
                    # hierarchy
                    exception.__promising_context__ = self
            except BaseException:  # noqa: BLE001 (blind-except)
                # Suppress the error if any - failure to store the trace should
                # not affect the exception handling
                pass
        finally:
            if exception is not NOT_SET:
                self.set_exception(exception)
            else:
                self.set_result(result)

    def _ensure_task_scheduled(self) -> None:
        if self._task is None and not self.done():
            self._task = self._ctx_loop.create_task(self._fulfill(), name=str(self) + "-Task")

    def _resolve_start_soon(self, start_soon: bool | Sentinel) -> bool:
        if isinstance(start_soon, bool):
            # Concrete value was provided
            return start_soon

        if start_soon is NOT_SET:
            parent_context = self.get_parent_context(raise_if_none=False)

            if parent_context is not None and parent_context._children_start_soon is not NOT_SET:
                # The parent is enforcing this setting for its children
                return parent_context._children_start_soon

            # Use the default
            return self._start_soon_default

        if start_soon is INHERIT:
            parent_promise = self.get_parent_promise(raise_if_none=False)

            if parent_promise is None:
                # Use the default
                return self._start_soon_default

            # Inherit from the parent
            return parent_promise._start_soon

        raise ValueError(
            "`start_soon` must be either NOT_SET, INHERIT or a boolean value, "
            f"but `{type(start_soon)}` was given instead"
        )

    def _finish_initialization(
        self,
        *,
        prefill_result: T_co | None | Sentinel,
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
                # use the event loop's `call_soon_threadsafe` to "stay on the
                # safe side"
                self._call_soon_threadsafe(self._ensure_task_scheduled)

    def __repr__(self) -> str:
        return self._repr_context(
            resolve_namespace(
                provided_explicitly=self.namespace,
                named_object_fallback=self._coro,
            ),
        )

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
        # TODO Account for the fact that the concurrent future itself might be
        #  cancelled by the user:
        #  https://github.com/teremterem/Promising/pull/57#discussion_r2864024491
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
        # TODO Account for the fact that the concurrent future itself might be
        #  cancelled by the user:
        #  https://github.com/teremterem/Promising/pull/57#discussion_r2864024491
        self._concurrent_future.set_exception(exception)


class PromiseBackedConcurrentFuture(concurrent.futures.Future, Generic[T_co]):
    """
    A thread-safe `concurrent.futures.Future` backed by a ``Promise``.

    This class provides a bridge between asyncio-based Promises and the
    `concurrent.futures.Future` interface, allowing Promises to be used in
    multi-threaded contexts while maintaining proper result/exception
    synchronization.

    Before blocking, both ``result()`` and ``exception()`` ensure that the
    Promise's task is scheduled on the event loop, so that the Promise will
    actually make progress while the calling thread waits.

    Args:
        promise: The ``Promise`` instance that backs this
            `concurrent.futures.Future`.
    """

    def __init__(self, promise: Promise[T_co]) -> None:
        super().__init__()
        self._promise = promise

    def result(self, timeout: float | None = None, *, ensure_task_scheduled: bool = True) -> T_co:
        """
        Get the result of the Promise.

        This method ensures the Promise's task is scheduled, then blocks until
        the Promise is done. It also consumes the result from the underlying
        asyncio Future so that asyncio will not issue a warning about the
        Future not having been awaited for.

        Args:
            timeout: Maximum time to wait for the result in seconds.
            ensure_task_scheduled: If True (the default), schedules the
                Promise's task on the event loop before blocking, so the
                Promise can make progress while this thread waits. This
                parameter is not part of the standard
                ``concurrent.futures.Future`` interface.

        Returns:
            The result value from the Promise.

        Raises:
            SyncUsageError: If called from the same thread as the event loop,
                which would deadlock.
            concurrent.futures.TimeoutError: If timeout expires before
                completion.
            Exception: Any exception that occurred during Promise execution.
        """
        assert_no_sync_usage_deadlock(
            self._promise.get_loop(),
            "`promise.as_concurrent_future().result()` cannot be called "
            "from the event loop thread because it would deadlock. "
            "Use `await promise` instead.",
        )
        if ensure_task_scheduled and not self.done():
            self._promise._call_soon_threadsafe(self._promise._ensure_task_scheduled)

        try:
            result = super().result(timeout=timeout)
        finally:
            # Let's also read the result from the asyncio Future directly, so
            # it knows that its result has been consumed and there is no need
            # to issue a warning about the Future not having been awaited for
            # (which, by this point, would be done already)
            try:
                self._promise.result()
            except BaseException:  # noqa: BLE001 (blind-except)
                # Suppress the error if any - if there's an error, it should
                # come from super().result(), not from here
                pass
        # For consistency, let's return the result from this concurrent Future,
        # even though it's going to be the same as the result from the Promise
        return result

    def exception(self, timeout: float | None = None, *, ensure_task_scheduled: bool = True) -> BaseException | None:
        """
        Get the exception that occurred during Promise execution, if any.

        This method ensures the Promise's task is scheduled, then blocks until
        the Promise is done. It also consumes the exception from the underlying
        asyncio Future so that asyncio will not issue a warning about the
        exception not having been retrieved.

        Args:
            timeout: Maximum time to wait for completion in seconds.
            ensure_task_scheduled: If True (the default), schedules the
                Promise's task on the event loop before blocking, so the
                Promise can make progress while this thread waits. This
                parameter is not part of the standard
                ``concurrent.futures.Future`` interface.

        Returns:
            The exception that occurred, or None if the Promise completed
            successfully.

        Raises:
            SyncUsageError: If called from the same thread as the event loop,
                which would deadlock.
            concurrent.futures.TimeoutError: If timeout expires before
                completion.
        """
        assert_no_sync_usage_deadlock(
            self._promise.get_loop(),
            "`promise.as_concurrent_future().exception()` cannot be called "
            "from the event loop thread because it would deadlock. "
            "Use `await promise` with a try/except block instead.",
        )
        if ensure_task_scheduled and not self.done():
            self._promise._call_soon_threadsafe(self._promise._ensure_task_scheduled)

        try:
            exception = super().exception(timeout=timeout)
        finally:
            # Let's also read the exception from the Promise directly, so it
            # knows that its exception has been consumed and there is no need
            # to issue a warning about the exception never being retrieved
            # (which, by this point, would be done already)
            try:
                self._promise.exception()
            except BaseException:  # noqa: BLE001 (blind-except)
                # Suppress the error if any - if there's an error, it should
                # come from super().exception(), not from here
                pass
        # For consistency, let's return the exception from this
        # concurrent.futures.Future, even though it's going to be the same as
        # the exception from the Promise
        return exception
