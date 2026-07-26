import asyncio
import concurrent.futures
import inspect
import logging
import os
import traceback
from asyncio import AbstractEventLoop, Task
from collections.abc import Awaitable, Generator
from functools import partial
from traceback import FrameSummary
from typing import Any, Generic

from promising.errors import (
    PromiseNotDoneError,
    PromiseNotFoundError,
    PromiseNotUnpackedError,
    install_promising_tracebacks,
)
from promising.logging_utils import PromiseUnpackingLogger
from promising.promising_context import PromisingContext
from promising.sentinels import (
    _CANCELLED_AFTER_UNPACKED_ONCE,
    _CANCELLED_BEFORE_UNPACKED_ONCE,
    _FINISHED,
    _PENDING,
    _UNPACKED_ONCE,
    AUTO,
    INHERIT,
    UNCHANGED,
    Sentinel,
)
from promising.types import T_co
from promising.utils import (
    attach_context_to_error_chain_root,
    awaitable_as_coroutine,
    resolve_namespace,
)

_logger = logging.getLogger(__name__)
_unpacking_logger = PromiseUnpackingLogger(level=logging.DEBUG)

# TODO [TRACES] Is it ok that we are not using Pathlib here ?
# TODO [TRACES] A unit test is needed to check that the path is correct
_MODULE_ABS_PATH: str = os.path.abspath(__file__)


def wrap_awaitable(
    awaitable: Awaitable[Any] | None = None,
    *,
    namespace: str | None = None,
    loop: AbstractEventLoop | None = None,
    parent: "PromisingContext | None | Sentinel" = AUTO,
    thread_pool: "concurrent.futures.ThreadPoolExecutor | Sentinel" = INHERIT,
    start_soon: bool | None | Sentinel = None,
    children_start_soon: bool | None | Sentinel = None,
    start_soon_default: bool | Sentinel = INHERIT,
    collapse_tracebacks: bool | Sentinel = INHERIT,
    prefilled_result: T_co | Sentinel = UNCHANGED,
    prefilled_exception: BaseException | None = None,
) -> "Promise[Any]":
    """
    Wrap an arbitrary awaitable (typically a bare coroutine that wasn't
    decorated with ``@promising.function``) in a ``Promise`` so it
    participates in the ``PromisingContext`` hierarchy.

    Thin convenience over the ``Promise`` constructor; accepts the same
    keyword arguments. See :class:`Promise` for parameter semantics.
    """
    return Promise(
        awaitable=awaitable,
        namespace=namespace,
        loop=loop,
        parent=parent,
        thread_pool=thread_pool,
        start_soon=start_soon,
        children_start_soon=children_start_soon,
        start_soon_default=start_soon_default,
        collapse_tracebacks=collapse_tracebacks,
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
    A first-class awaitable that runs a coroutine, caches its result, and
    plugs into the ``PromisingContext`` hierarchy as an awaitable child.

    Promise implements:
    - Asynchronous computation backed by an awaitable
    - Result/exception caching, with both async (``await``, ``unpack_once``)
      and thread-safe sync (``sync``, ``unpack_once_sync``) consumption
    - A two-step unpacking model: a single unpacking step that produces an
      intermediate Promise (if the awaitable returned one), and a full
      unpacking that recursively chases nested Promises down to a concrete
      value
    - Cancellation that is safe to invoke from any thread
    - Construction-time stack capture (``frame_summary_tuple``) consumed
      by the ``sys.excepthook`` / ``threading.excepthook`` overrides
      installed via ``install_promising_tracebacks()`` to render
      promising-aware tracebacks (optionally collapsing
      promising-internal frames via ``collapse_tracebacks``)

    From ``PromisingContext`` it inherits the hierarchical parent-child
    machinery — automatic registration as a child of the currently active
    context, propagation of configuration through the tree, and
    ``await_children()`` / ``collect_unsettled_children()``.

    Attributes:
        frame_summary_tuple: Snapshot of the call stack captured at
            construction time (excluding the ``Promise.__init__`` frame
            itself), as a tuple of ``traceback.FrameSummary`` objects in
            innermost-first order. The promising excepthook overrides
            read this attribute on each ``Promise`` returned by
            ``get_trace(ancestors_first=True)`` to render the
            promising-context trace. Subclasses (or other contexts that
            want to participate in the rendered trace) can expose a
            matching attribute; contexts without it are skipped.

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
        start_soon_default: Local override for the global Defaults.START_SOON.
            INHERIT (default) propagates from the parent. PROMISING_DEFAULT reads
            the current global setting without inheriting.
        collapse_tracebacks: When True (the default), tracebacks of
            exceptions that propagate out of this Promise (or its subtree)
            are rendered without the noisy promising-internal frames, so the
            user sees only the application-level frames that actually
            originated the failure. Set to False to keep the full,
            uncollapsed traceback (useful when debugging the promising
            library itself). Local override for the global
            Defaults.COLLAPSE_TRACEBACKS. INHERIT (default) propagates from
            the parent. PROMISING_DEFAULT reads the current global setting
            without inheriting.
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
    # TODO Do we want to implement _add_done_callback() and
    #  _add_unpacked_once_callback() ? Any other callbacks ?

    def __init__(
        self,
        awaitable: Awaitable[T_co | "Promise[Any]"] | None = None,
        *,
        namespace: str | None = None,
        loop: AbstractEventLoop | None = None,
        parent: "PromisingContext | None | Sentinel" = AUTO,
        thread_pool: "concurrent.futures.ThreadPoolExecutor | Sentinel" = INHERIT,
        start_soon: bool | None | Sentinel = None,
        children_start_soon: bool | None | Sentinel = None,
        start_soon_default: bool | Sentinel = INHERIT,
        collapse_tracebacks: bool | Sentinel = INHERIT,
        prefilled_result: T_co | Sentinel = UNCHANGED,
        prefilled_exception: BaseException | None = None,
    ) -> None:
        # Validate before super().__init__ to avoid registering an unsettled
        # child with the parent when arguments are invalid.
        self._validate_init_args(awaitable, prefilled_result, prefilled_exception)

        # TODO [TRACES] Introduce some sort of `DEBUG` boolean flag (like in
        #  Django) to avoid extracting the stack trace in production due to
        #  performance reasons
        # TODO [TRACES] Modify excepthooks accordingly: when the
        #  frame_summary_tuple is None, just print the list of promises one
        #  after another and then the final traceback. (Keep collapsing
        #  framework frames, though ?)
        self.frame_summary_tuple = tuple[FrameSummary, ...](
            traceback.StackSummary.extract(traceback.walk_stack(None), lookup_lines=False)[1:]
        )

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
            collapse_tracebacks=collapse_tracebacks,
            close_context_immediately=awaitable is None,
            # We will do the registering with parent at the very end, to make
            # sure any construction errors happen before the Promise is
            # registered with the parent
            register_with_parent=False,
        )
        self._start_soon = self._resolve_start_soon(start_soon)

        self._full_unpacking_task: Task[T_co] | None = None
        self._single_unpacking_task: Task[T_co | Promise[Any]] | None = None

        if self._awaitable is None:
            # No outside code has any reference to this Promise yet, so we can
            # set the result/exception directly, no matter which thread the
            # constructor is currently running in
            if prefilled_result is not UNCHANGED:
                self._set_result_unsafe(prefilled_result)
            else:
                self._set_exception_unsafe(prefilled_exception)

        # TODO [NEW SYNC] Send operations below to the loop
        self._register_with_parent_unsafe()
        if self._start_soon and self._awaitable is not None:
            self._ensure_full_unpacking_scheduled_unsafe_wrapper()

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
        ``_fully_unpack_unsafe()``. If already started via start_soon,
        waits for the existing task to complete. Once the Promise resolves,
        recursively awaits the result as long as it is itself a Promise,
        returning the final non-Promise value.

        Note that unpacking only traverses ``Promise`` instances specifically
        — it does not unpack arbitrary awaitables in general.

        Returns:
            The fully unpacked result of the Promise (no remaining
            nested Promises).

        NOTE: This method should only be called from the event loop of the
        Promise.
        """
        self._assert_awaiting_on_correct_event_loop()

        self._ensure_full_unpacking_scheduled_unsafe()

        if self._full_unpacking_task is not None:
            yield from self._full_unpacking_task

        return self.result()

    def sync(self, *, timeout: float | None = None) -> T_co:
        """
        Synchronous counterpart of ``await promise`` — blocks the calling
        thread until all nested Promises are fully unpacked, then returns
        the concrete (non-Promise) result.

        Internally this dispatches the awaiting onto the Promise's own event
        loop via ``asyncio.run_coroutine_threadsafe`` (so the Promise still
        gets driven from its own loop) and blocks the calling thread on the
        resulting ``concurrent.futures.Future``.

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
        self._guard_against_sync_op_deadlock()

        if self.done():
            return self.result()

        concurrent_future = asyncio.run_coroutine_threadsafe(awaitable_as_coroutine(self), self.loop)
        return concurrent_future.result(timeout=timeout)

    async def unpack_once(self) -> "T_co | Promise[Any]":
        """
        Resolve the Promise's awaitable one level only.

        If the awaitable resolved to another Promise, return that
        intermediate Promise. Otherwise return the final concrete value.
        Use ``await promise`` (or ``promise.sync()``) when you want the fully
        unpacked value instead.

        Returns:
            Either the intermediate ``Promise`` produced by the first
            unpacking step, or the final concrete value if no nested
            Promise was returned.

        Raises:
            EventLoopMismatchError: If awaited from a different event loop
                than the one this Promise belongs to.

        NOTE: This method should only be called from the event loop of the
        Promise.
        """
        self._assert_awaiting_on_correct_event_loop()

        self._ensure_single_unpacking_scheduled_unsafe()

        if self._single_unpacking_task is not None:
            await self._single_unpacking_task

        intermediate_promise = self.intermediate_promise()

        if intermediate_promise is None:
            return self.result()
        return intermediate_promise

    def unpack_once_sync(self, *, timeout: float | None = None) -> "T_co | Promise[Any]":
        """
        Synchronous counterpart of ``unpack_once()`` — blocks the calling
        thread until the Promise has been unpacked at least one level, then
        returns either the intermediate ``Promise`` or the final concrete
        value.

        If the Promise has already been unpacked once (or finished), returns
        the cached value directly without dispatching anything onto the event
        loop. Otherwise schedules ``unpack_once()`` on the Promise's own
        event loop via ``asyncio.run_coroutine_threadsafe`` and waits.

        Args:
            timeout: Maximum time to wait for one unpacking step in seconds.

        Returns:
            Either the intermediate ``Promise`` produced by the first
            unpacking step, or the final concrete value if no nested
            Promise was returned.

        Raises:
            SyncUsageError: If called from the same thread as the event loop,
                which would deadlock.
            TimeoutError: If timeout expires before completion.

        NOTE: This method is thread-safe, but it is unavailable from the event
        loop of the Promise to avoid a deadlock.
        """
        self._guard_against_sync_op_deadlock()

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
        with an exception) or cancelled. Overrides ``PromisingContext.done()``,
        which by default just tracks the context-manager lifecycle (``closed()``)
        — for a Promise, "done" is tied to the result lifecycle instead, so
        that a parent's ``await_children()`` waits for the actual computation
        (which may be prolonged due to the "full unpacking" behavior) rather
        than just for the ``with`` block exit.

        Returns:
            Whether this Promise is "done".

        NOTE: This method is thread-safe, including from the event loop of the
        Promise.

        Thread-safety contract for ``Promise`` state-reading methods (this
        method and the ones below referencing it):

        The Promise state machine is monotonic — once advanced past
        ``_PENDING`` (to ``_UNPACKED_ONCE``, ``_FINISHED``, or one of the
        ``_CANCELLED_XX`` states), the state never moves backwards. The
        writers (``_set_intermediate_promise_unsafe`` /
        ``_set_result_unsafe`` / ``_set_exception_unsafe``) write the
        corresponding attribute (``_intermediate_promise``, ``_result``,
        ``_exception``) *before* advancing the state via ``_set_state``, so a
        reader that observes a state past ``_PENDING`` is guaranteed to also
        observe the matching attribute.

        This relies on single-attribute reads and writes being atomic across
        threads — which holds under CPython's reference (GIL-backed)
        interpreter. Under a free-threaded CPython build the GIL no longer
        provides that guarantee, and the reader/writer pair would need
        explicit synchronization (e.g. a lock or memory fence) to remain
        correct. Promising does not currently target free-threaded
        interpreters.
        # TODO Future-proof it ?
        #  https://github.com/teremterem/Promising/pull/102#discussion_r3197680342
        """
        state = self._state
        return state in (_FINISHED, _CANCELLED_BEFORE_UNPACKED_ONCE, _CANCELLED_AFTER_UNPACKED_ONCE)

    def unpacked_once(self) -> bool:
        """
        Whether the Promise's awaitable has produced its first result —
        either an intermediate Promise (which means a further unpacking
        step is still pending) or a final concrete value (in which case
        the Promise is also ``done()``).

        NOTE: This method is thread-safe, including from the event loop of the
        Promise — see ``done()`` for the thread-safety contract.
        """
        state = self._state
        return state in (_FINISHED, _UNPACKED_ONCE, _CANCELLED_AFTER_UNPACKED_ONCE)

    def unpacked_once_or_done(self) -> bool:
        """
        Convenience predicate: True if the Promise is at least one-level
        unpacked, fully done, or cancelled. Used internally as the readiness
        check for one-level (non-recursive) consumers.

        NOTE: This method is thread-safe, including from the event loop of the
        Promise — see ``done()`` for the thread-safety contract.
        """
        state = self._state
        return state in (_FINISHED, _CANCELLED_BEFORE_UNPACKED_ONCE, _UNPACKED_ONCE, _CANCELLED_AFTER_UNPACKED_ONCE)

    def cancelled(self) -> bool:
        """
        Whether the Promise has been cancelled (either before or after the
        first unpacking step).

        NOTE: This method is thread-safe, including from the event loop of the
        Promise — see ``done()`` for the thread-safety contract.
        """
        state = self._state
        return state in (_CANCELLED_BEFORE_UNPACKED_ONCE, _CANCELLED_AFTER_UNPACKED_ONCE)

    def result(self) -> T_co:
        """
        Return the fully unpacked result of the Promise.

        Raises:
            PromiseNotDoneError: If the Promise is not done yet.
            asyncio.CancelledError: If the Promise was cancelled.
            BaseException: Re-raises whatever exception the Promise finished
                with (if any).

        NOTE: This method is thread-safe, including from the event loop of the
        Promise — see ``done()`` for the thread-safety contract.
        """
        self._assert_done()

        if self._exception is not None:
            raise self._exception

        if self._result is UNCHANGED:
            # Should not happen: _assert_done() above guarantees a terminal
            # state, and the only way to reach _FINISHED without an
            # exception is via _set_result_unsafe (which sets _result).
            raise RuntimeError(
                f"Promise result is UNCHANGED even though the promise is done and there is no exception: {self!r}"
            )

        return self._result

    def intermediate_promise(self) -> "Promise[Any] | None":
        """
        Return the intermediate ``Promise`` produced by the first unpacking
        step, or ``None`` if the awaitable's first result was already a
        non-Promise value.

        Raises:
            PromiseNotUnpackedError: If the Promise has not yet been unpacked
                even one level.
            BaseException: Re-raises the underlying exception if the first
                unpacking step itself failed before producing an intermediate
                Promise.

        NOTE: This method is thread-safe, including from the event loop of the
        Promise — see ``done()`` for the thread-safety contract.
        """
        if not self.unpacked_once_or_done():
            raise PromiseNotUnpackedError(f"Promise is not unpacked even once yet: {self!r}")

        if self._exception is not None and self._intermediate_promise is None:
            # Exception (including CancelledError) happened before the first
            # unpacking step produced an intermediate Promise — re-raise it.
            # When the cancellation arrived AFTER the first unpacking step,
            # `_intermediate_promise` is still set, so we return it as usual.
            raise self._exception

        return self._intermediate_promise

    def exception(self) -> BaseException | None:
        """
        Return the exception the Promise finished with, or ``None`` if it
        finished successfully.

        Mirrors ``asyncio.Future.exception()``: when the Promise was
        cancelled, the stored ``CancelledError`` is re-raised rather than
        returned.

        Raises:
            PromiseNotDoneError: If the Promise is not done yet.
            asyncio.CancelledError: If the Promise was cancelled.

        NOTE: This method is thread-safe, including from the event loop of the
        Promise — see ``done()`` for the thread-safety contract.
        """
        self._assert_done()

        if self.cancelled():
            # Match asyncio.Future.exception() semantics: raise the
            # CancelledError instead of returning it.
            raise self._exception

        return self._exception

    def cancel(self, msg: str | None = None) -> bool:
        """
        Request cancellation of the Promise.

        Mirrors ``asyncio.Future.cancel()`` / ``asyncio.Task.cancel()``: the
        return value reports whether cancellation was *requested* — the
        Promise's terminal cancelled state is reached only once the
        ``CancelledError`` actually propagates through the underlying
        unpacking task and is stored via ``_set_exception_unsafe``. Until
        then, ``cancelled()`` may still return ``False``.

        For a Promise whose underlying task hasn't been scheduled yet (e.g.
        ``start_soon=False`` and never awaited), the cancellation is
        synthesized as a ``CancelledError`` stored directly via
        ``_set_exception_unsafe``, with no task involvement — analogous to
        ``Future.cancel()`` on a not-yet-running future.

        When called from the Promise's own event loop thread the cancellation
        is dispatched directly. When called from any other thread it is
        scheduled onto the Promise's event loop via
        ``call_soon_threadsafe`` and the call blocks only long enough for the
        scheduled dispatch to finish (it does not wait for the cancellation
        itself to land).

        Returns:
            ``True`` if cancellation was requested for at least one
            underlying task, or synthesized for a not-yet-started Promise;
            ``False`` if the Promise was already done.

        NOTE: This method is thread-safe, including from the event loop of the
        Promise.
        """
        return self._send_sync_op_to_loop(
            partial[bool](self._cancel_unsafe, msg),
            send_and_forget=False,
            fail_if_loop_not_running=True,
        )

    def _ensure_single_unpacking_scheduled_unsafe(self) -> None:
        """
        NOTE: This method should only be called from the event loop of the
        Promise.
        """
        _unpacking_logger.log_single_unpacking_scheduling(promise=self)

        if self._single_unpacking_task is None and not self.unpacked_once_or_done():
            self._single_unpacking_task = self.loop.create_task(
                self._unpack_once_unsafe(), name=str(self) + "-SingleUnpackingTask"
            )
            self._single_unpacking_task.add_done_callback(self._unpacking_task_done_callback)

            _unpacking_logger.log_single_unpacking_scheduled(promise=self)

    def _ensure_full_unpacking_scheduled_unsafe(self) -> None:
        """
        NOTE: This method should only be called from the event loop of the
        Promise.
        """
        _unpacking_logger.log_full_unpacking_scheduling(promise=self)

        if self._full_unpacking_task is None and not self.done():
            self._full_unpacking_task = self.loop.create_task(
                self._fully_unpack_unsafe(), name=str(self) + "-FullUnpackingTask"
            )
            self._full_unpacking_task.add_done_callback(self._unpacking_task_done_callback)

            _unpacking_logger.log_full_unpacking_scheduled(promise=self)

    def _ensure_full_unpacking_scheduled_unsafe_wrapper(self) -> None:
        """
        ``call_soon_threadsafe``-safe wrapper around
        ``_ensure_full_unpacking_scheduled_unsafe``.

        Used by the ``start_soon=True`` path in ``__init__``, where scheduling
        is deferred to the event loop via ``call_soon_threadsafe``. Any
        exception raised from that callback would otherwise propagate to the
        loop's default exception handler and leave the Promise stuck in a
        non-terminal state. This wrapper instead routes the exception through
        ``_force_internal_error_finish_unsafe`` so the Promise is settled
        as an internal error.

        NOTE: This method should only be called from the event loop of the
        Promise.
        """
        try:
            self._ensure_full_unpacking_scheduled_unsafe()
        except BaseException as exc:
            self._force_internal_error_finish_unsafe(exc)

    def _unpacking_task_done_callback(self, task: Task[Any]) -> None:
        """
        Bridge the case where ``task.cancel()`` lands between
        ``create_task`` and the first ``__step``: ``CancelledError`` is
        thrown into a not-yet-started coroutine and propagates out
        without entering the ``try/except BaseException`` inside
        ``_unpack_once_unsafe`` / ``_fully_unpack_unsafe``, leaving
        the Promise non-terminal even though the Task ended cancelled.
        """
        # TODO [NEW SYNC] Rename this method to ..._unsafe_calback (with a
        #  respective docstring NOTE) for consistency ?
        # Early return if the task wasn't cancelled, or if the Promise (self)
        # is already done
        if not task.cancelled() or self.done():
            return

        # Recover the original cancel message from the Task by inspecting the
        # ``CancelledError`` re-raised by ``task.result()``
        msg: str | None = None
        try:
            task.result()
        except asyncio.CancelledError as exc:
            # Using ``exc.args[0]`` (rather than ``str(exc)``) preserves the
            # distinction between an empty-string msg and no msg at all
            if exc.args:
                msg = exc.args[0]

        self._synthesize_cancellation_unsafe(msg)

    async def _unpack_once_unsafe(self) -> None:
        """
        Drive a single unpacking step on the event loop.

        Activates the Promise as the current ``PromisingContext`` (so that
        promises created during this step are registered as its children),
        awaits the wrapped awaitable, and stores either an intermediate Promise
        or a final value/exception. The state machine is moved forward via
        ``_set_intermediate_promise_unsafe`` / ``_set_result_unsafe`` /
        ``_set_exception_unsafe``.

        Backs ``unpack_once()`` (and the first leg of
        ``_fully_unpack_unsafe``).

        NOTE: This method should only be called from the event loop of the
        Promise.
        """
        try:
            _unpacking_logger.log_single_unpacking_started(promise=self)

            if self.unpacked_once_or_done():
                # Should not happen: this method is only scheduled by
                # _ensure_single_unpacking_scheduled_unsafe, which guards
                # on `not unpacked_once_or_done()`.
                raise RuntimeError(
                    f"An attempt was made to _unpack_once_unsafe a Promise "
                    f"that was already unpacked once or done: {self!r}"
                )

            # TODO [TRACES] Introduce some sort of `DEBUG` boolean flag (like in
            #  Django) to know when to avoid installing these excepthooks in
            #  production ?
            install_promising_tracebacks()

            with self:
                result = await self._awaitable

            _unpacking_logger.log_single_unpacking_result(promise=self, result=result)

        except BaseException as exc:
            _unpacking_logger.log_unpacking_exception(promise=self, stage="_unpack_once_unsafe", exc=exc)
            self._set_exception_unsafe(exc)
        else:
            if isinstance(result, Promise):
                self._set_intermediate_promise_unsafe(result)
            else:
                self._set_result_unsafe(result)

        _unpacking_logger.log_single_unpacking_finished(promise=self)

    async def _fully_unpack_unsafe(self) -> None:
        """
        Drive the Promise to completion on the event loop, recursively
        unpacking nested Promises.

        Ensures the single-unpacking task is scheduled and awaits it. If
        that produced an intermediate Promise, awaits it (and any further
        nested Promises) until a non-Promise value is reached, then stores
        that value as the final result. Any exception from the chain is
        captured via ``_set_exception_unsafe``.

        Backs ``__await__`` (and, indirectly, ``sync()``).

        NOTE: This method should only be called from the event loop of the
        Promise.
        """
        try:
            _unpacking_logger.log_full_unpacking_started(promise=self)

            if self.done():
                # When there are no more nested Promises to unpack, the Promise
                # becomes done already after _unpack_once_unsafe completes
                return

            self._ensure_single_unpacking_scheduled_unsafe()
            if self._single_unpacking_task is not None:
                await self._single_unpacking_task

            if self.done():
                # Calling unpack_once alone was enough to finish the Promise
                return

            result = self._intermediate_promise

            # Note: cancelling this Promise does NOT propagate cancellation
            # into the nested Promise being awaited below — asyncio's
            # task-cancellation lands on this task and unwinds upward; the
            # inner Promise's own task keeps running independently.
            # TODO [CANCELLATION] Decide the philosophy on hierarchical
            #  promises vs. "promises that return other promises" — should
            #  subtree cancellation and cancellation of nested (returned)
            #  Promises be treated as the same thing ?
            depth = 0
            while isinstance(result, Promise):
                result = await result
                # TODO I suspect that logging of `depth` is currently broken -
                #  full unpacking happens recursively, and this loop
                #  (supposedly) always runs only once
                depth += 1
                _unpacking_logger.log_unwrap_step(promise=self, depth=depth, result=result)

        except BaseException as exc:
            _unpacking_logger.log_unpacking_exception(promise=self, stage="_fully_unpack_unsafe", exc=exc)
            self._set_exception_unsafe(exc)
        else:
            self._set_result_unsafe(result)

        _unpacking_logger.log_full_unpacking_finished(promise=self)

    def _set_intermediate_promise_unsafe(self, promise: "Promise[Any]") -> None:
        """
        Record the intermediate Promise returned by a single unpacking step.
        No-op if already unpacked once or done.

        NOTE: This method should only be called from the event loop of the
        Promise.
        """
        try:
            if self._state is not _PENDING:
                # Should not happen: only called from _unpack_once_unsafe
                # when the awaitable resolved to a Promise. The only steps
                # between the awaitable resolving and this call are the
                # synchronous `with self:` exit and a logger call —
                # neither yields, so state stays _PENDING.
                raise RuntimeError(
                    f"Cannot set intermediate_promise on a promise because of the promise's current state: {self!r}"
                )
            self._intermediate_promise = promise
            self._set_state(_UNPACKED_ONCE)

        except BaseException as internal_error:
            self._force_internal_error_finish_unsafe(internal_error)

    def _set_result_unsafe(self, result: T_co) -> None:
        """
        Store the fully unpacked result. No-op if the Promise is already
        done (finished or cancelled).

        NOTE: This method should only be called from the event loop of the
        Promise.
        """
        try:
            if self._state not in (_PENDING, _UNPACKED_ONCE):
                # Should not happen: all callsites reach this with state in
                # (_PENDING, _UNPACKED_ONCE) — prefill in __init__, the
                # non-Promise branch of _unpack_once_unsafe, or the end
                # of _fully_unpack_unsafe's unwrap chain.
                raise RuntimeError(f"Cannot set result on a promise because of its current state: {self!r}")
            self._result = result
            self._set_state(_FINISHED)

        except BaseException as internal_error:
            self._force_internal_error_finish_unsafe(internal_error)

    def _set_exception_unsafe(self, exception: BaseException) -> None:
        """
        Store the exception and move the Promise into a terminal state. The
        cancelled state is an *effect* of storing a ``CancelledError``, not a
        precondition for it — ``CancelledError`` deliberately extends
        ``BaseException`` rather than ``Exception``, so it flows through this
        method like any other exception, and the terminal state is chosen based
        on whether the first unpacking step had completed.

        A ``CancelledError`` arriving on an already-terminal Promise is
        silently dropped. Any other exception arriving in that state is treated
        as a framework bug and raises ``RuntimeError``.

        NOTE: This method should only be called from the event loop of the
        Promise.
        """
        try:
            if self._state is _PENDING:
                terminal_state = (
                    _CANCELLED_BEFORE_UNPACKED_ONCE if isinstance(exception, asyncio.CancelledError) else _FINISHED
                )
            elif self._state is _UNPACKED_ONCE:
                terminal_state = (
                    _CANCELLED_AFTER_UNPACKED_ONCE if isinstance(exception, asyncio.CancelledError) else _FINISHED
                )
            elif self.done() and isinstance(exception, asyncio.CancelledError):
                # Cancellation can land on both the single and full
                # unpacking tasks, so the same CancelledError can reach
                # this method twice — the second arrival sees a Promise
                # that's already cancelled. Drop it; the original wins.
                return
            else:
                # Should not happen: any non-CancelledError exception
                # arriving on a non-_PENDING / non-_UNPACKED_ONCE Promise
                # implies the framework's state machine is broken
                # (legitimate user-triggered cancellation races are
                # caught by the elif above).
                raise RuntimeError(f"Cannot set exception on a promise because of its current state: {self!r}")

            # The context was probably already attached to the exception by the
            # ``with self:`` block of ``_unpack_once_unsafe``, but it is
            # also possible that the exception occurred outside the
            # ``with self:`` block (e.g. a framework bug), so lets try to
            # attach it here too.
            self.try_to_link_exception(exception)
            self._exception = exception
            self._set_state(terminal_state)
            # TODO The fact that we have no "exception was never fetched"
            #  warning might be a problem. (What about "result was never
            #  fetched", is it a thing too ?)

        except BaseException as internal_error:
            # Bug in the Promise class itself, or a misuse of the state
            # machine. Chain the original exception so context is not lost,
            # then force the Promise into a terminal state.
            try:
                attach_context_to_error_chain_root(internal_error, context=exception)
            except BaseException:
                # TODO Should it be just `Exception` ? Any danger that
                #  `KeyboardInterrupt` would get swallowed here ?
                #  Contemplate on this GitHub issue along the way:
                #  https://github.com/teremterem/Promising/issues/105
                _logger.debug("Failed to chain original exception onto internal_error", exc_info=True)
            self._force_internal_error_finish_unsafe(internal_error)

    def _force_internal_error_finish_unsafe(self, error: BaseException) -> None:
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

        NOTE: This method should only be called from the event loop of the
        Promise.
        """
        try:
            _logger.debug("Force-finishing Promise %r with internal error", self, exc_info=error)
            # ``error`` is synthesized in the framework's except handlers
            # after ``with self:`` has already exited, so it never passes
            # through ``__exit__``'s attribution. Attach the context
            # explicitly here.
            self.try_to_link_exception(error)
            self._exception = error
            self._set_state(_FINISHED)
            # TODO The fact that we have no "exception was never fetched"
            #  warning might be a problem. (What about "result was never
            #  fetched", is it a thing too ?)

        except BaseException:
            _logger.debug("Failed to force-finish Promise %r with internal error", self, exc_info=True)
            raise

    def _assert_done(self) -> None:
        """
        NOTE: This method is thread-safe, including from the event loop of the
        Promise — see ``done()`` for the thread-safety contract.
        """
        if not self.done():
            raise PromiseNotDoneError(f"Promise is not done: {self!r}")

    def _cancel_unsafe(self, msg: str | None = None) -> bool:
        """
        Request cancellation of the underlying unpacking task(s) — or, when
        no task has been scheduled yet, synthesize the cancellation directly
        (see ``_synthesize_cancellation_unsafe``).

        The state machine is *not* moved here. Instead, the ``CancelledError``
        propagates through ``_unpack_once_unsafe`` /
        ``_fully_unpack_unsafe`` (``except BaseException`` catches it) and
        is stored via ``_set_exception_unsafe``.

        NOTE: This method should only be called from the event loop of the
        Promise.
        """
        if self.done():
            return False

        cancellation_requested = False
        if self._single_unpacking_task is not None and not self._single_unpacking_task.done():
            cancellation_requested |= self._single_unpacking_task.cancel(msg)
        if self._full_unpacking_task is not None and not self._full_unpacking_task.done():
            cancellation_requested |= self._full_unpacking_task.cancel(msg)

        if cancellation_requested:
            return True

        # No task is currently running cancellation through — synthesize the
        # CancelledError and store it directly. Covers the
        # `start_soon=False`/never-awaited case as well as the rare race
        # where every task has finished but the Promise hasn't transitioned
        # to a terminal state yet.
        self._synthesize_cancellation_unsafe(msg)

        return self.cancelled()

    def _synthesize_cancellation_unsafe(self, msg: str | None = None) -> None:
        """
        Drive the Promise into a cancelled terminal state without relying
        on a running unpacking task to surface the ``CancelledError``.
        Mirrors ``Future.cancel()`` on a not-yet-running future.

        Shared by ``_cancel_unsafe`` (synthesize path, no task ever
        scheduled) and ``_unpacking_task_done_callback`` (task cancelled
        between ``create_task`` and its first ``__step``, so the body's
        ``except BaseException`` never saw the ``CancelledError``).

        NOTE: This method should only be called from the event loop of the
        Promise.
        """
        # `_unpack_once_unsafe` would normally close the context via
        # `with self:`. Without this, `_context_closed` stays False and the
        # child never unregisters from its parent.
        self.close_context_threadsafe()

        self._set_exception_unsafe(asyncio.CancelledError(msg) if msg is not None else asyncio.CancelledError())

        # Close the wrapped awaitable so a never-driven coroutine doesn't
        # trigger a "coroutine was never awaited" warning at GC time —
        # asyncio-equivalent of letting a cancelled Task clean up its own
        # coroutine.
        awaitable = self._awaitable
        if awaitable is not None:
            close = getattr(awaitable, "close", None)
            if callable(close):
                try:
                    close()
                except BaseException:
                    # TODO Should it be just `Exception` ? Any danger that
                    #  `KeyboardInterrupt` would get swallowed here ?
                    #  Contemplate on this GitHub issue along the way:
                    #  https://github.com/teremterem/Promising/issues/105
                    _logger.debug("Failed to close awaitable on cancellation of %r", self, exc_info=True)

    def _set_state(self, new_state: Sentinel) -> None:
        # TODO [NEW SYNC] Rename this method to _set_state_unsafe and explain
        #  in a docstring NOTE its connection to race conditions against
        #  unsettled children ?
        self._state = new_state
        # TODO [NEW SYNC] A better comment is needed. The one below does not
        #  explain why are we closing the context UNCONDITIONALLY. (Good thing
        #  that commenting out the closing operation fails a whole bunch of
        #  tests - we can at least be certain that it is not being done for no
        #  reason.)
        # Force-close the context just in case (it was most likely closed by
        # the `with` block already, but it might also have been
        # `_force_internal_error_finish_unsafe`) and unregister from parent
        # "if time":
        self.close_context_threadsafe()

    def _resolve_start_soon(self, start_soon: bool | None | Sentinel) -> bool:
        """
        Resolve the effective ``start_soon`` for this Promise.

        Precedence: concrete bool > parent's ``children_start_soon`` (when
        the parent is enforcing one) > ``start_soon_default``. ``INHERIT``
        copies the parent Promise's own ``start_soon`` directly.
        """
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
