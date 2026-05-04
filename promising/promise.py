import asyncio
import concurrent.futures
import inspect
import logging
from asyncio import AbstractEventLoop, Task
from collections.abc import Awaitable, Generator
from typing import Any, Generic

from promising.errors import PromiseNotDoneError, PromiseNotFoundError, PromiseNotUnpackedError
from promising.logging_utils import PromiseUnpackingLogger
from promising.promising_context import PromisingContext
from promising.sentinels import (
    _CANCELLED_AFTER_UNPACKED_ONCE,
    _CANCELLED_BEFORE_UNPACKED_ONCE,
    _FINISHED,
    _PENDING,
    _UNPACKED_ONCE,
    INHERIT,
    UNCHANGED,
    Sentinel,
)
from promising.types import T_co
from promising.utils import awaitable_as_coroutine, resolve_namespace

_logger = logging.getLogger(__name__)
_unpacking_logger = PromiseUnpackingLogger(level=logging.DEBUG)


def wrap_awaitable(
    awaitable: Awaitable[Any] | None = None,
    *,
    namespace: str | None = None,
    loop: AbstractEventLoop | None = None,
    parent: "PromisingContext | None | Sentinel" = INHERIT,
    thread_pool: "concurrent.futures.ThreadPoolExecutor | Sentinel" = INHERIT,
    start_soon: bool | None | Sentinel = None,
    children_start_soon: bool | None | Sentinel = None,
    start_soon_default: bool | Sentinel = INHERIT,
    prefilled_result: T_co | Sentinel = UNCHANGED,
    prefilled_exception: BaseException | None = None,
) -> "Promise[Any]":
    return Promise(
        awaitable=awaitable,
        namespace=namespace,
        loop=loop,
        parent=parent,
        thread_pool=thread_pool,
        start_soon=start_soon,
        children_start_soon=children_start_soon,
        start_soon_default=start_soon_default,
        prefilled_result=prefilled_result,
        prefilled_exception=prefilled_exception,
    )


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


class Promise(PromisingContext, Generic[T_co]):
    """
    A Promise combines PromisingContext's hierarchical context management
    with asyncio Future functionality.

    Promise extends ``PromisingFuture`` — which itself combines
    ``PromisingContext`` and ``asyncio.Future`` — to provide:
    - Asynchronous computation backed by an awaitable
    - Result/exception propagation via the Future interface
    - Thread-safe synchronous access via concurrent.futures compatibility
    - Hierarchical parent-child relationships (inherited from
      PromisingContext)

    Parent-child relationships (inherited from PromisingContext):
    - If a Promise's awaitable creates other Promises or
      PromisingContexts during execution, they are attached as children
      of that context.
    - The exact time when a child's execution starts, finishes, or when
      its resolution is triggered does not matter; it is still registered
      as a child of the context whose awaitable created it.
    - If a parent is explicitly specified at creation time, that explicit
      parent takes precedence.

    Type Parameters:
        T_co: The covariant type of the Promise's result.

    Args:
        awaitable: The awaitable to execute. If not provided, the Promise must
            be prefilled with a result or exception.
        loop: Event loop to use. None (default) inherits from the parent
            context, or uses the currently running event loop at the root
            (raises ``NoRunningEventLoopError`` if no loop is running).
        namespace: Human-readable label for this Promise. Shows up in
            ``__repr__`` output (and, consequently, in promising traces). When
            created via ``@promising.function`` and not provided, defaults to
            the wrapped function's ``__qualname__``.
        parent: Parent context. Passed to PromisingContext; see
            PromisingContext.__init__ for inheritance behavior.
        start_soon: Whether associated work should start immediately (True) or
            not (False). None (default) defers to the parent's
            children_start_soon if enforced, otherwise falls back to
            start_soon_default. INHERIT copies the parent's start_soon
            directly.
        children_start_soon: (Also boolean or Sentinel.) Default start_soon
            value enforced on child Promises that left their start_soon setting
            as None. For the children_start_soon setting itself, None
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
            falling back to PROMISING_DEFAULT at the root. PROMISING_DEFAULT uses
            Defaults.PROMISING_THREAD_POOL. ASYNCIO_DEFAULT passes None to
            run_in_executor, letting the event loop use its own default
            executor. A concrete ThreadPoolExecutor instance can also be
            provided.
        start_soon_default: Local override for the global START_SOON_DEFAULT.
            INHERIT (default) propagates from the parent. PROMISING_DEFAULT reads
            the current global setting without inheriting.
        prefilled_result: Pre-set result value. Cannot be an awaitable (pass
            awaitables as the first positional argument instead). Cannot be
            combined with awaitable or prefilled_exception.
        prefilled_exception: Pre-set exception. Cannot be combined with awaitable
            or prefilled_result.

    Raises:
        ValueError: If invalid parameter combinations are provided.
        TypeError: If awaitable is not awaitable when provided.
    """

    # TODO [P1] Figure out how to support async generator interface as well
    #  (together with its "sync" counterpart)
    # TODO [P1] Make sure there is a clear mechanism of avoiding memory leaks,
    #  though, when sequences are enormously long and are not meant to be
    #  revisited by the user (e.g. a stream of events etc.)

    def __init__(
        self,
        awaitable: Awaitable[T_co | "Promise[Any]"] | None = None,
        *,
        namespace: str | None = None,
        loop: AbstractEventLoop | None = None,
        parent: "PromisingContext | None | Sentinel" = INHERIT,
        thread_pool: "concurrent.futures.ThreadPoolExecutor | Sentinel" = INHERIT,
        start_soon: bool | None | Sentinel = None,
        children_start_soon: bool | None | Sentinel = None,
        start_soon_default: bool | Sentinel = INHERIT,
        prefilled_result: T_co | Sentinel = UNCHANGED,
        prefilled_exception: BaseException | None = None,
    ) -> None:
        # Validate before super().__init__ to avoid registering an unsettled
        # child with the parent when arguments are invalid.
        self._validate_init_args(awaitable, prefilled_result, prefilled_exception)

        self._result: T_co | Sentinel = UNCHANGED
        self._exception: BaseException | None = None
        self._state: Sentinel = _PENDING

        self._intermediate_promise: Promise[T_co | Promise[Any]] | None = None
        self._awaitable = awaitable

        super().__init__(
            namespace=resolve_namespace(
                provided_explicitly=namespace,
                named_object_fallback=awaitable,
            ),
            loop=loop,
            parent=parent,
            thread_pool=thread_pool,
            children_start_soon=children_start_soon,
            start_soon_default=start_soon_default,
            close_context_immediately=awaitable is None,
        )
        self._start_soon = self._resolve_start_soon(start_soon)

        self._full_unpacking_task: Task[T_co] | None = None
        self._single_unpacking_task: Task[T_co | Promise[Any]] | None = None

        if self._awaitable is None:
            if prefilled_result is not UNCHANGED:
                self._set_result(prefilled_result)
            else:
                self._set_exception(prefilled_exception)

        if self._start_soon:
            # We don't know which thread the Promise is created in, so we
            # use the event loop's `call_soon_threadsafe` to "stay on the
            # safe side"
            self._call_soon_threadsafe(self._ensure_from_loop_full_unpacking_scheduled)

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
        current = cls.get_active_context(raise_if_none=False)
        while current is not None and not isinstance(current, Promise):
            current = current.get_parent_context(raise_if_none=False)

        if raise_if_none and current is None:
            raise PromiseNotFoundError("No active Promise found")
        return current

    def __await__(self) -> Generator[Any, None, T_co]:
        """
        Await the Promise, fully unpacking all nested Promises.

        If the Promise hasn't started yet, starts execution via
        _fully_unpack_from_loop(). If already started via start_soon,
        waits for the existing task to complete. Once the Promise resolves,
        recursively awaits the result as long as it is itself a Promise
        (non-Promise awaitables are auto-wrapped into Promises by
        ``set_result``), returning the final non-Promise value.

        Note that unpacking only traverses ``Promise`` instances specifically
        — it does not unpack arbitrary awaitables or ``PromisingFuture``
        objects in general.

        Returns:
            The fully unpacked result of the Promise (no remaining
            nested Promises).

        NOTE: This method can only be used from the event loop of the Promise.
        """
        self.assert_awaiting_on_correct_event_loop()

        self._ensure_from_loop_full_unpacking_scheduled()

        if self._full_unpacking_task is not None:
            yield from self._full_unpacking_task

        return self.result()

    def sync(self, *, timeout: float | None = None) -> T_co:
        """
        An alias for ``unpack_all_sync()`` — blocks the calling thread until
        all nested Promises are fully unpacked.

        Args:
            timeout: Maximum time to wait for the result in seconds.

        Returns:
            The fully unpacked result of the Promise (no remaining
            nested Promises).

        Raises:
            SyncUsageError: If called from the same thread as the event loop,
                which would deadlock.
            TimeoutError: If timeout expires before completion.

        NOTE: This method is thread-safe, but it is unavailable from the event
        loop of the Promise to avoid a deadlock.
        """
        self.assert_no_sync_usage_deadlock()

        if self.done():
            return self.result()

        concurrent_future = asyncio.run_coroutine_threadsafe(awaitable_as_coroutine(self), self.loop)
        return concurrent_future.result(timeout=timeout)

    async def unpack_once(self) -> "T_co | Promise[Any]":
        """
        NOTE: This method can only be used from the event loop of the Promise.
        """
        self.assert_awaiting_on_correct_event_loop()

        self._ensure_from_loop_single_unpacking_scheduled()

        if self._single_unpacking_task is not None:
            await self._single_unpacking_task

        intermediate_promise = self.intermediate_promise()

        if intermediate_promise is None:
            return self.result()
        return intermediate_promise

    def unpack_once_sync(self, *, timeout: float | None = None) -> "T_co | Promise[Any]":
        """
        NOTE: This method is thread-safe, but it is unavailable from the event
        loop of the Promise to avoid a deadlock.
        """
        self.assert_no_sync_usage_deadlock()

        if self.unpacked_once_or_done():
            intermediate_promise = self.intermediate_promise()

            if intermediate_promise is None:
                return self.result()
            return intermediate_promise

        concurrent_future = asyncio.run_coroutine_threadsafe(self.unpack_once(), self.loop)
        return concurrent_future.result(timeout=timeout)

    def done(self) -> bool:
        """
        Whether this Promise is "done", i.e. either finished (successfully or
        with an exception) or cancelled. Replaces the default behavior of the
        ``PromisingContext`` parent class which simply checks if the context is
        closed already.

        Returns:
            Whether this Promise is "done".

        NOTE: This method is thread-safe, including from the event loop of the
        Promise, because the state cannot go backwards (e.g. from
        _CANCELLED_XX or _FINISHED to _PENDING etc.)
        """
        state = self._state
        return state in (_FINISHED, _CANCELLED_BEFORE_UNPACKED_ONCE, _CANCELLED_AFTER_UNPACKED_ONCE)

    def unpacked_once(self) -> bool:
        """
        NOTE: This method is thread-safe, including from the event loop of the
        Promise, because the state cannot go backwards (e.g. from
        _CANCELLED_XX or _FINISHED to _PENDING etc.)
        """
        state = self._state
        return state in (_FINISHED, _UNPACKED_ONCE, _CANCELLED_AFTER_UNPACKED_ONCE)

    def unpacked_once_or_done(self) -> bool:
        """
        NOTE: This method is thread-safe, including from the event loop of the
        Promise, because the state cannot go backwards (e.g. from
        _CANCELLED_XX or _FINISHED to _PENDING etc.)
        """
        state = self._state
        return state in (_FINISHED, _CANCELLED_BEFORE_UNPACKED_ONCE, _UNPACKED_ONCE, _CANCELLED_AFTER_UNPACKED_ONCE)

    def cancelled(self) -> bool:
        """
        NOTE: This method is thread-safe, including from the event loop of the
        Promise, because the state cannot go backwards (e.g. from
        _CANCELLED_XX or _FINISHED to _PENDING etc.)
        """
        state = self._state
        return state in (_CANCELLED_BEFORE_UNPACKED_ONCE, _CANCELLED_AFTER_UNPACKED_ONCE)

    def result(self) -> T_co:
        """
        NOTE: This method is thread-safe, including from the event loop of the
        Promise, because the state cannot go backwards (e.g. from
        _CANCELLED_XX or _FINISHED to _PENDING etc.), and neither other
        attributes that were set as part of the Promise's lifecycle.
        """
        self._assert_done_and_not_cancelled()

        if self._exception is not None:
            raise self._exception

        if self._result is UNCHANGED:
            # Should not happen
            raise RuntimeError(
                f"Promise result is UNCHANGED even though the promise is done and there is no exception: {self!r}"
            )

        return self._result

    def intermediate_promise(self) -> "Promise[Any] | None":
        """
        NOTE: This method is thread-safe, including from the event loop of the
        Promise, because the state cannot go backwards (e.g. from
        _CANCELLED_XX or _FINISHED to _PENDING etc.), and neither other
        attributes that were set as part of the Promise's lifecycle.
        """
        if not self.unpacked_once_or_done():
            raise PromiseNotUnpackedError(f"Promise is not unpacked even once yet: {self!r}")

        if self._exception is not None and self._intermediate_promise is None:
            # Exception happened before the first unpacking was completed
            # TODO [P1] So, are we storing CancelledError in self._exception too ?
            raise self._exception

        return self._intermediate_promise

    def exception(self) -> BaseException | None:
        """
        NOTE: This method is thread-safe, including from the event loop of the
        Promise, because the state cannot go backwards (e.g. from
        _CANCELLED_XX or _FINISHED to _PENDING etc.), and neither other
        attributes that were set as part of the Promise's lifecycle.
        """
        self._assert_done_and_not_cancelled()
        return self._exception

    def cancel(self, msg: str | None = None) -> bool:
        """
        NOTE: This method is thread-safe, including from the event loop of the
        Promise.
        """
        if self.is_on_correct_running_loop():
            # We are on the event loop of the Promise, so we can cancel it
            # directly
            return self._cancel_from_loop(msg)

        # We are on a different thread, so we need to use a thread-safe
        # mechanism to cancel the Promise
        future = concurrent.futures.Future()

        def callback():
            try:
                result = self._cancel_from_loop(msg)
            except BaseException as exc:
                future.set_exception(exc)
            else:
                future.set_result(result)

        self.loop.call_soon_threadsafe(callback)
        return future.result()

    def _ensure_from_loop_single_unpacking_scheduled(self) -> None:
        """
        NOTE: This method can only be used from the event loop of the Promise.
        """
        _unpacking_logger.log_single_unpacking_scheduling(promise=self)
        if self._single_unpacking_task is None and not self.unpacked_once_or_done():
            self._single_unpacking_task = self.loop.create_task(
                self._unpack_once_from_loop(), name=str(self) + "-SingleUnpackingTask"
            )
            _unpacking_logger.log_single_unpacking_scheduled(promise=self)

    def _ensure_from_loop_full_unpacking_scheduled(self) -> None:
        """
        NOTE: This method can only be used from the event loop of the Promise.
        """
        _unpacking_logger.log_full_unpacking_scheduling(promise=self)
        if self._full_unpacking_task is None and not self.done():
            self._full_unpacking_task = self.loop.create_task(
                self._fully_unpack_from_loop(), name=str(self) + "-FullUnpackingTask"
            )
            _unpacking_logger.log_full_unpacking_scheduled(promise=self)

    async def _unpack_once_from_loop(self) -> None:
        """
        NOTE: This method can only be used from the event loop of the Promise.
        """
        try:
            _unpacking_logger.log_single_unpacking_started(promise=self)

            if self.unpacked_once_or_done():
                # Should not happen
                raise RuntimeError(
                    f"An attempt was made to _unpack_once_from_loop a Promise "
                    f"that was already unpacked once or done: {self!r}"
                )

            with self:
                result = await self._awaitable

            _unpacking_logger.log_single_unpacking_result(promise=self, result=result)

        except BaseException as exc:
            _unpacking_logger.log_unpacking_exception(promise=self, stage="unpack_once_from_loop", exc=exc)
            self._set_exception(exc)
        else:
            if isinstance(result, Promise):
                self._set_intermediate_promise(result)
            else:
                self._set_result(result)

        _unpacking_logger.log_single_unpacking_finished(promise=self)

    async def _fully_unpack_from_loop(self) -> None:
        """
        Execute the Promise's awaitable and manage its lifecycle.

        This method:
        1. Activates the Promise as the current context
        2. Executes the awaitable
        3. Sets the result or exception

        Raises:
            RuntimeError: If the Promise is already done or has no awaitable.

        NOTE: This method can only be used from the event loop of the Promise.
        """
        try:
            _unpacking_logger.log_full_unpacking_started(promise=self)

            if self.done():
                # When there are no more nested Promises to unpack, the Promise
                # becomes done already after unpack_once_from_loop completes
                return

            self._ensure_from_loop_single_unpacking_scheduled()
            if self._single_unpacking_task is not None:
                await self._single_unpacking_task

            if self.done():
                # Calling unpack_once alone was enough to finish the Promise
                return

            result = self._intermediate_promise

            # TODO [P1] What will cancelling do to this whole unpacking chain ?
            depth = 0
            while isinstance(result, Promise):
                result = await result
                depth += 1
                _unpacking_logger.log_unwrap_step(promise=self, depth=depth, result=result)

        except BaseException as exc:
            _unpacking_logger.log_unpacking_exception(promise=self, stage="fully_unpack_from_loop", exc=exc)
            self._set_exception(exc)
        else:
            self._set_result(result)

        _unpacking_logger.log_full_unpacking_finished(promise=self)

    def _set_intermediate_promise(self, promise: "Promise[Any]") -> None:
        """
        Record the intermediate Promise returned by a single unpacking step.
        No-op if already unpacked once or done.

        NOTE: This method can only be used from the event loop of the Promise.
        """
        try:
            if self._state is not _PENDING:
                # Should not happen
                raise RuntimeError(
                    f"Cannot set intermediate_promise on a promise because of the promise's current state: {self!r}"
                )
            self._intermediate_promise = promise
            self._set_state(_UNPACKED_ONCE)

        except BaseException as internal_error:
            self._force_finished_with_internal_error(internal_error)

    def _set_result(self, result: T_co) -> None:
        """
        Store the fully unpacked result. No-op if the Promise is already
        done (finished or cancelled).

        NOTE: This method can only be used from the event loop of the Promise.
        """
        try:
            if self._state not in (_PENDING, _UNPACKED_ONCE):
                # Should not happen
                raise RuntimeError(f"Cannot set result on a promise because of its current state: {self!r}")
            self._result = result
            self._set_state(_FINISHED)

        except BaseException as internal_error:
            self._force_finished_with_internal_error(internal_error)

    def _set_exception(self, exception: BaseException) -> None:
        """
        Store the exception. No-op if the Promise is already done
        (finished or cancelled).

        NOTE: This method can only be used from the event loop of the Promise.
        """
        try:
            if self._state not in (_PENDING, _UNPACKED_ONCE):
                # Should not happen
                raise RuntimeError(f"Cannot set exception on a promise because of its current state: {self!r}")

            self.set_as_promising_context_on_exception(exception)
            self._exception = exception
            self._set_state(_FINISHED)

        except BaseException as internal_error:
            # Bug in the Promise class itself, or a misuse of the state
            # machine. Chain the original exception so context is not lost,
            # then force the Promise into a terminal state.
            try:
                # TODO [P2] Only set it if it is not already set ? Or, maybe,
                # navigate all the way up the chain to the root where it can be
                # set ?
                internal_error.__context__ = exception
            except BaseException:
                _logger.debug("Failed to chain original exception onto internal_error", exc_info=True)
            self._force_finished_with_internal_error(internal_error)

    def _force_finished_with_internal_error(self, error: BaseException) -> None:
        """
        Last-resort recovery path. Force the Promise into _FINISHED with
        the given error, bypassing state validation. Each step is wrapped
        in try/except so a partial failure cannot leave the Promise stuck
        in a non-terminal state.

        Used when a regular ``_set_*`` call fails internally — typically
        because the state machine was already in an unexpected state, or
        because parent unregistration raised. Treating such failures as
        bugs in the Promise class itself, this method prioritizes reaching
        a terminal state over surfacing further errors.

        NOTE: This method can only be used from the event loop of the Promise.
        """
        try:
            _logger.debug("Force-finishing Promise %r with internal error", self, exc_info=error)
            self.set_as_promising_context_on_exception(error)
            self._exception = error
            self._set_state(_FINISHED)
        except BaseException:
            _logger.debug("Failed to force-finish Promise %r with internal error", self, exc_info=True)

    def _assert_done_and_not_cancelled(self) -> None:
        """
        NOTE: This method is thread-safe, including from the event loop of the
        Promise, because the state cannot go backwards (e.g. from
        _CANCELLED_XX or _FINISHED to _PENDING etc.)
        """
        if not self.done():
            raise PromiseNotDoneError(f"Promise is not done: {self!r}")

        if self.cancelled():
            # TODO [P1] Shouldn't CancelledError end up in self._exception instead ?
            # TODO [P2] Introduce a PromisingError subclass for this ?
            #  Should it be specific to "cancelled" ?
            #  Should it also inherit from asyncio.CancelledError AND
            #  concurrent.futures.CancelledError ?
            #  Isn't there a common builtin error for both - concurrent and
            #  asyncio - just like TimeoutError ?
            raise asyncio.CancelledError(f"Promise is cancelled: {self!r}")

    def _cancel_from_loop(self, msg: str | None = None) -> bool:
        """
        NOTE: This method can only be used from the event loop of the Promise.
        """
        # TODO [P1] Review this method and make sure it is in compliance with
        #  the way cancellations are done in asyncio
        if self.done():
            return False

        single_unpacking_cancelled = False
        full_unpacking_cancelled = False
        try:
            if self._single_unpacking_task is not None and not self.unpacked_once():
                single_unpacking_cancelled = self._single_unpacking_task.cancel(msg)

                if single_unpacking_cancelled:
                    self._set_state(_CANCELLED_BEFORE_UNPACKED_ONCE)

        finally:
            if self._full_unpacking_task is not None:
                full_unpacking_cancelled = self._full_unpacking_task.cancel(msg)

                if full_unpacking_cancelled and not single_unpacking_cancelled:
                    self._set_state(_CANCELLED_AFTER_UNPACKED_ONCE)

        return single_unpacking_cancelled or full_unpacking_cancelled

    def _set_state(self, new_state: Sentinel) -> None:
        self._state = new_state
        self._unregister_from_parent_if_time()

    def _unregister_from_parent_if_time(self) -> None:
        # Do not unregister from parent unless the Promise is done (even if it
        # is already closed)
        if self.done():
            super()._unregister_from_parent_if_time()

    def _resolve_start_soon(self, start_soon: bool | None | Sentinel) -> bool:
        if isinstance(start_soon, bool):
            # Concrete value was provided
            return start_soon

        if start_soon is None:
            parent_context = self.get_parent_context(raise_if_none=False)

            if parent_context is not None and parent_context._children_start_soon is not None:
                # The parent is enforcing this setting for its children
                return parent_context._children_start_soon

            # Use the default
            return self._start_soon_default

        # TODO Do we even need this kind of inheritance for start_soon ?
        #  Revisit all the settings after you develop some examples, and think
        #  again if the settings as they currently are make sense.
        if start_soon is INHERIT:
            parent_promise = self.get_parent_promise(raise_if_none=False)

            if parent_promise is None:
                # Use the default
                return self._start_soon_default

            # Inherit from the parent
            return parent_promise._start_soon

        raise ValueError(
            f"`start_soon` must be either None, INHERIT or a boolean value, but `{type(start_soon)}` was given instead"
        )

    @staticmethod
    def _validate_init_args(
        awaitable: Awaitable[Any] | None,
        prefilled_result: Any,
        prefilled_exception: BaseException | None,
    ) -> None:
        """
        Validate constructor args before ``super().__init__`` to prevent
        registering an unsettled child with the parent on bad input.
        """
        if awaitable is None:
            if prefilled_result is not UNCHANGED and prefilled_exception is not None:
                raise ValueError("Cannot provide both 'prefilled_result' and 'prefilled_exception' parameters")

            if prefilled_result is not UNCHANGED and inspect.isawaitable(prefilled_result):
                raise TypeError(
                    "Cannot pass an awaitable as 'prefilled_result'. Pass it as the first positional argument instead."
                )

            if prefilled_result is UNCHANGED and prefilled_exception is None:
                raise ValueError("Cannot create a Promise without an awaitable or prefilled result/exception")
        else:
            if not inspect.isawaitable(awaitable):
                raise TypeError(f"Promise must be created with an awaitable. Got {type(awaitable)}.")

            if prefilled_result is not UNCHANGED or prefilled_exception is not None:
                raise ValueError(
                    "Cannot provide both 'awaitable' and 'prefilled_result' or 'prefilled_exception' parameters"
                )

    def __repr__(self) -> str:
        return f"{super().__repr__()}.{self._state}"
