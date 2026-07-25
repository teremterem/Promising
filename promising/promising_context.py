import asyncio
import concurrent.futures
import contextvars
import functools
import inspect
import logging
from asyncio import AbstractEventLoop
from collections.abc import Callable
from contextvars import ContextVar
from types import TracebackType
from typing import TYPE_CHECKING, Any

from promising.decorator_support import _SETTINGS_AS_DICT_KEY, PromisingDecorator
from promising.errors import (
    ContextAlreadyActiveError,
    ContextAlreadyClosedError,
    ContextNotActiveError,
    ContextNotFoundError,
    DecorationError,
    EventLoopMismatchError,
    NoRunningEventLoopError,
    PromiseNotFoundError,
    SyncUsageError,
)
from promising.logging_utils import PromisingHierarchyLogger
from promising.sentinels import ASYNCIO_DEFAULT, AUTO, INHERIT, PROMISING_DEFAULT, UNCHANGED, Sentinel
from promising.types import DecoratableFunctionType
from promising.utils import get_running_asyncio_loop

if TYPE_CHECKING:
    from promising.promise import Promise


_logger = logging.getLogger(__name__)
_hierarchy_logger = PromisingHierarchyLogger(level=logging.DEBUG)


class context(PromisingDecorator):  # noqa: N801 (invalid-class-name)
    """
    Decorator and context manager that creates a hierarchical context node
    tracking parent-child relationships between promises and groups of
    promises, without creating an actual ``Promise``.

    Use ``promising.context`` when you need a parent node that groups child
    promises but does not represent an asynchronous computation itself. You may
    want it to do ``await_children()`` on such a ``PromisingContext`` later, or
    to override the default settings for a specific block of code, etc.

    ``PromisingContext`` can also be instantiated directly for advanced use
    cases, but ``promising.context`` is the recommended entry point.

    As a **context manager**::

        with promising.context() as ctx:
            # Promises created here become children of `ctx`
            ...
        ...
        await ctx.await_children()

    As a **decorator** (wraps a function so every call runs inside a fresh
    ``PromisingContext``)::

        @promising.context(children_start_soon=False)
        async def process(items):
            # Promises created here become children of a fresh PromisingContext
            ...

    Compare with ``@promising.function``, which *does* create a ``Promise``:
    calling a ``@promising.function``-decorated function returns a ``Promise``
    whose result must be awaited, whereas calling a ``@promising.context``
    -decorated function executes the function as is, and returns its result as
    is. The only special thing it does is provide a ``PromisingContext`` around
    its body. (NOTE: If the decorated function is async, the result will still
    need to be awaited, of course.)

    Args:
        namespace: Human-readable label for the underlying
            ``PromisingContext``. Shows up in ``__repr__`` output (and,
            consequently, in promising traces). When used as a decorator and
            not provided, defaults to the wrapped function's ``__qualname__``.
        loop: Event loop to use. None (default) inherits from the parent
            context, or uses the currently running event loop at the root
            (raises ``NoRunningEventLoopError`` if no loop is running).
        parent: Parent ``PromisingContext``. ``AUTO`` (default) uses the
            currently active context. ``None`` creates a root context with no
            parent.
        thread_pool: Thread pool executor used to run sync promising functions.
            ``INHERIT`` (default) inherits from the parent context, falling
            back to ``PROMISING_DEFAULT`` at the root. ``PROMISING_DEFAULT`` uses
            ``Defaults.PROMISING_THREAD_POOL``. ``ASYNCIO_DEFAULT`` passes ``None``
            to ``run_in_executor``, letting the event loop use its own default
            executor. A concrete ``ThreadPoolExecutor`` instance can also be
            provided.
        children_start_soon: Default ``start_soon`` value enforced on child
            Promises whose own ``start_soon`` is None. Controls whether
            they start executing immediately (i.e. as soon as the event loop
            allows), or defer until awaited one way or another. ``INHERIT``
            (default) copies the parent's setting. Note: this defaults to
            ``INHERIT`` (unlike ``promising`` functions, which default to
            ``None``), so that a ``PromisingContext`` is transparent by
            default — settings flow through from the enclosing ``Promise``.
        start_soon_default: Local override for the global
            ``Defaults.START_SOON``, effective in the whole subtree of this
            context. ``INHERIT`` (default) propagates from the parent.
        collapse_tracebacks: When True (the default), tracebacks of
            exceptions that propagate out of this context (or its subtree)
            are rendered without the noisy promising-internal frames, so the
            user sees only the application-level frames that actually
            originated the failure. Set to False to keep the full,
            uncollapsed traceback (useful when debugging the promising
            library itself). Local override for the global
            ``Defaults.COLLAPSE_TRACEBACKS``, effective in the whole subtree
            of this context. ``INHERIT`` (default) propagates from the
            parent.
    """

    def __init__(
        self,
        func_or_method: DecoratableFunctionType | None = None,
        *,
        namespace: str | None = None,
        loop: AbstractEventLoop | None = None,
        parent: "PromisingContext | None | Sentinel" = AUTO,
        children_start_soon: bool | None | Sentinel = INHERIT,
        start_soon_default: bool | Sentinel = INHERIT,
        collapse_tracebacks: bool | Sentinel = INHERIT,
        thread_pool: concurrent.futures.ThreadPoolExecutor | Sentinel = INHERIT,
    ) -> None:
        super().__init__(
            func_or_method,
            namespace=namespace,
            children_start_soon=children_start_soon,
            start_soon_default=start_soon_default,
            collapse_tracebacks=collapse_tracebacks,
            thread_pool=thread_pool,
        )
        self.loop = loop
        self.parent = parent

        self._promising_context = None

    def __enter__(self) -> "PromisingContext":
        """
        If this method was called, then it means that this `promising.context`
        instance is being used as a context manager. We need to create a new
        PromisingContext instance and activate it.
        """
        if self.__wrapped__ is not None:
            raise DecorationError(
                "The same instance of `promising.context` cannot serve both "
                "as a context manager and as a decorator simultaneously"
            )

        if self._promising_context is None:
            self._promising_context = PromisingContext(
                namespace=self.namespace,
                loop=self.loop,
                parent=self.parent,
                thread_pool=self.thread_pool,
                children_start_soon=self.children_start_soon,
                start_soon_default=self.start_soon_default,
                collapse_tracebacks=self.collapse_tracebacks,
            )
        return self._promising_context.__enter__()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        if self._promising_context is None:
            raise ContextNotActiveError("No PromisingContext was associated with this context manager instance")

        result = self._promising_context.__exit__(exc_type, exc_value, traceback)
        self._promising_context = None
        return result

    def __call__(
        self,
        *args: Any,
        namespace: str | None | Sentinel = UNCHANGED,
        loop: AbstractEventLoop | None | Sentinel = UNCHANGED,
        parent: "PromisingContext | None | Sentinel" = UNCHANGED,
        children_start_soon: bool | None | Sentinel = UNCHANGED,
        start_soon_default: bool | Sentinel = UNCHANGED,
        collapse_tracebacks: bool | Sentinel = UNCHANGED,
        thread_pool: concurrent.futures.ThreadPoolExecutor | Sentinel = UNCHANGED,
        **kwargs: Any,
    ) -> Any | DecoratableFunctionType:
        settings_as_dict = kwargs.pop(_SETTINGS_AS_DICT_KEY, {})

        if loop is not UNCHANGED:
            settings_as_dict["loop"] = loop
        if parent is not UNCHANGED:
            settings_as_dict["parent"] = parent

        return super().__call__(
            *args,
            namespace=namespace,
            children_start_soon=children_start_soon,
            start_soon_default=start_soon_default,
            collapse_tracebacks=collapse_tracebacks,
            thread_pool=thread_pool,
            **kwargs,
            **{_SETTINGS_AS_DICT_KEY: settings_as_dict},
        )

    def _call_wrapped(self, *args: Any, settings_as_dict: dict[str, Any], **kwargs: Any) -> Any:
        ctx = PromisingContext(
            namespace=settings_as_dict.get("namespace", self.namespace),
            loop=settings_as_dict.get("loop", self.loop),
            parent=settings_as_dict.get("parent", self.parent),
            thread_pool=settings_as_dict.get("thread_pool", self.thread_pool),
            children_start_soon=settings_as_dict.get("children_start_soon", self.children_start_soon),
            start_soon_default=settings_as_dict.get("start_soon_default", self.start_soon_default),
            collapse_tracebacks=settings_as_dict.get("collapse_tracebacks", self.collapse_tracebacks),
        )

        if self._is_wrapped_async:
            # If there is an argument mismatch, we want to raise an error as
            # early as possible, so we create the coroutine here and not in the
            # `_async_wrapper`
            wrapped_coro = self._wrapped_as_callable(*args, **kwargs)

            @functools.wraps(self.__wrapped__)
            async def _async_wrapper() -> Any:
                with ctx:
                    return await wrapped_coro

            return _async_wrapper()

        # Wrapped function or method is sync
        with ctx:
            return self._wrapped_as_callable(*args, **kwargs)


def get_active_context(*, raise_if_none: bool = True) -> "PromisingContext | None":
    """
    Get the currently active PromisingContext from context.

    Args:
        raise_if_none: If True, raises ContextNotFoundError when no active
            PromisingContext is found.

    Returns:
        The currently active PromisingContext instance, or None if no PromisingContext is active
        and raise_if_none is False.

    Raises:
        ContextNotFoundError: If no active PromisingContext is found and raise_if_none
            is True.
    """
    return PromisingContext.get_active_context(raise_if_none=raise_if_none)


async def await_children(*, whole_subtree: bool = True, unpack_promises_fully: bool = True) -> None:
    """
    Wait for all awaitable children of the active context to finish.

    Args:
        whole_subtree: If True (the default), wait for all descendants,
            not just direct children.
        unpack_promises_fully: If True (the default), each Promise child
            is fully awaited. If False, Promise children are only unpacked
            one level (via ``unpack_once()``).
    """
    return await get_active_context().await_children(
        whole_subtree=whole_subtree,
        unpack_promises_fully=unpack_promises_fully,
    )


def await_children_sync(
    *,
    whole_subtree: bool = True,
    unpack_promises_fully: bool = True,
    timeout: float | None = None,
) -> None:
    """
    Wait for all awaitable children of the active context to finish,
    blocking the calling thread.

    This is the synchronous counterpart of ``await_children()`` — intended
    for use inside sync promising functions that run in a thread pool
    executor, where ``await`` is not available.

    Args:
        whole_subtree: If True (the default), wait for all descendants,
            not just direct children.
        unpack_promises_fully: If True (the default), each Promise child
            is fully awaited. If False, Promise children are only unpacked
            one level (via ``unpack_once()``).
        timeout: Maximum time to wait in seconds.
    """
    return get_active_context().await_children_sync(
        whole_subtree=whole_subtree,
        unpack_promises_fully=unpack_promises_fully,
        timeout=timeout,
    )


def collect_unsettled_children(
    *,
    whole_subtree: bool = True,
    awaitables_only: bool = True,
) -> set["PromisingContext"]:
    """
    Collect child contexts of the active context that are still being
    tracked by their parent (i.e. they have not yet been unregistered
    after being closed and having all of their own descendants drain).

    This is the module-level counterpart of
    ``PromisingContext.collect_unsettled_children()``.

    Args:
        whole_subtree: If True (default), include descendants at all levels,
            not just direct children.
        awaitables_only: If True (default), exclude children that are not
            awaitable (i.e. plain ``PromisingContext`` nodes created via
            ``promising.context``, which do not implement ``__await__``).

    Returns:
        Set of child PromisingContexts matching the filter criteria.
    """
    return get_active_context().collect_unsettled_children(
        whole_subtree=whole_subtree,
        awaitables_only=awaitables_only,
    )


def get_trace(*, ancestors_first: bool = True) -> "list[PromisingContext]":
    """
    Return a list of PromisingContext objects in the trace of the active
    context. If *ancestors_first* is True (the default), the list is ordered
    from the topmost parent down to the active context; otherwise from the
    active context up.
    """
    return get_active_context().get_trace(ancestors_first=ancestors_first)


def format_trace(*, ancestors_first: bool = True) -> "list[str]":
    """
    Return a list of string representations of each PromisingContext
    in the trace of the active context. If *ancestors_first* is True (the
    default), the list is ordered from the topmost parent down to the active
    context; otherwise from the active context up.
    """
    return get_active_context().format_trace(ancestors_first=ancestors_first)


def print_trace(*, ancestors_first: bool = True) -> None:
    """
    Print each PromisingContext in the trace of the active context on a
    separate line. If *ancestors_first* is True (the default), the list is
    ordered from the topmost parent down to the active context; otherwise
    from the active context up.
    """
    get_active_context().print_trace(ancestors_first=ancestors_first)


class PromisingContext:
    """
    Hierarchical context node that tracks parent-child relationships between
    promises. Usually created via ``promising.context``; see
    :class:`promising.context` for usage details and parameter descriptions.

    .. note::
       **Extending as an awaitable.** If you subclass ``PromisingContext``
       and define ``__await__``, see the warning on :meth:`done` — you must
       either enter the context inside ``__await__`` (``with self: ...``)
       or override :meth:`done` to track a non-lifecycle condition.
       Otherwise ``await_children()`` will silently hang on instances of
       your subclass.
    """

    namespace: str | None

    __active_context = ContextVar["PromisingContext | None"]("PromisingContext.__active_context", default=None)

    # TODO [CANCELLATION] Support cancellation of the whole PromisingContext tree
    # TODO [CANCELLATION] Offer a setting to cancel children when parent task fails ?

    def __init__(
        self,
        *,
        namespace: str | None = None,
        loop: AbstractEventLoop | None = None,
        parent: "PromisingContext | None | Sentinel" = AUTO,
        thread_pool: "concurrent.futures.ThreadPoolExecutor | Sentinel" = INHERIT,
        children_start_soon: bool | None | Sentinel = INHERIT,
        start_soon_default: bool | Sentinel = INHERIT,
        collapse_tracebacks: bool | Sentinel = INHERIT,
        # TODO Introduce inheritable promise_class parameter
        #  (and promise_class_default) ?
        close_context_immediately: bool = False,
        register_with_parent: bool = True,
    ) -> None:
        self.namespace = namespace
        self._previous_token: contextvars.Token | None = None

        if parent is AUTO:
            self._parent = self.get_active_context(raise_if_none=False)
        elif parent is None or isinstance(parent, PromisingContext):
            self._parent = parent
        else:
            raise ValueError(
                f"`parent` must be either AUTO, another PromisingContext "
                f"or None, but `{type(parent)}` was given for {self!r} instead"
            )

        self._start_soon_default = self._resolve_start_soon_default(start_soon_default)
        self._children_start_soon = self._resolve_children_start_soon(children_start_soon)
        self._collapse_tracebacks = self._resolve_collapse_tracebacks(collapse_tracebacks)
        self._thread_pool = self._resolve_thread_pool(thread_pool)

        if loop is None:
            if self._parent is None:
                self._loop = get_running_asyncio_loop(raise_if_none=True)
            else:
                self._loop = self._parent.loop
        else:
            if self._parent is not None and loop is not self._parent.loop:
                raise ValueError(
                    f"Parent and child PromisingContexts must share the same event loop.\n"
                    f"Parent: {self._parent!r}\n"
                    f"Child: {self!r}"
                )
            self._loop = loop

        self._context_closed = close_context_immediately
        self._unsettled_children = set[PromisingContext]()

        if register_with_parent:
            # No other code has a reference to this PromisingContext yet, so we
            # can just register it with the parent in a thread-unsafe manner
            self._register_with_parent_thread_unsafe()

    @property
    def loop(self) -> AbstractEventLoop:
        return self._loop

    @classmethod
    def get_active_context(cls, *, raise_if_none: bool = True) -> "PromisingContext | None":
        """
        Get the currently active PromisingContext from context variables.

        Args:
            raise_if_none: If True, raises an exception when no active
                PromisingContext is found.

        Returns:
            The currently active PromisingContext, or None if none exists and
            raise_if_none is False.

        Raises:
            ContextNotFoundError: If no active PromisingContext exists and
                raise_if_none is True.
        """
        active = cls.__active_context.get()
        if raise_if_none and active is None:
            raise ContextNotFoundError("No active PromisingContext found")
        return active

    def closed(self) -> bool:
        """
        Whether this context is closed.

        A ``PromisingContext`` is "open" from the moment it is constructed
        until ``close_context_threadsafe()`` runs (which happens automatically
        when the ``with`` block exits). Closed contexts are still kept around
        in their parent's ``_unsettled_children`` until their own unsettled
        descendants drain (they do not accept new children anymore).
        """
        return self._context_closed

    def done(self) -> bool:
        """
        Whether this context is "done". For vanilla ``PromisingContext``,
        same as ``closed()`` — i.e. flips ``True`` on ``__exit__``.

        Child classes can override this method to redefine what "done" means
        for them (see ``Promise.done()`` for an example).

        .. warning::
           If you make a ``PromisingContext`` subclass awaitable (define
           ``__await__``), you MUST do one of the following:

           1. Enter and exit the context inside ``__await__``
              (``with self: ...``). See
              ``tests/utils_for_tests.py::NonPromiseAwaitableContext``.
           2. Override ``done()`` to track a condition independent of
              the context-manager lifecycle (see ``Promise.done()``,
              which ties it to its own result/cancellation state machine).

           Otherwise ``closed()`` stays ``False`` forever, ``done()``
           stays ``False``, and any parent's ``await_children()`` will
           hang on this instance with no error.

        Returns:
            Whether this context is "done" (for vanilla ``PromisingContext``,
            the same as ``closed()``).
        """
        return self.closed()

    def get_parent_context(self, *, raise_if_none: bool = True) -> "PromisingContext | None":
        """
        Get the immediate parent PromisingContext of this PromisingContext.

        Args:
            raise_if_none: If True, raises an exception when no parent
                PromisingContext exists.

        Returns:
            The parent PromisingContext, or None if none exists and
            raise_if_none is False.

        Raises:
            ContextNotFoundError: If no parent PromisingContext exists and
                raise_if_none is True.
        """
        if raise_if_none and self._parent is None:
            raise ContextNotFoundError(f"No parent PromisingContext found for {self!r}")
        return self._parent

    def get_parent_promise(self, *, raise_if_none: bool = True) -> "Promise[Any] | None":
        """
        Get the nearest ancestor Promise of this context (skipping over any
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
        from promising.promise import Promise  # noqa: PLC0415 (import-outside-top-level)

        parent = self.get_parent_context(raise_if_none=False)
        while parent is not None and not isinstance(parent, Promise):
            parent = parent.get_parent_context(raise_if_none=False)

        if raise_if_none and parent is None:
            raise PromiseNotFoundError(f"No parent Promise found for {self!r}")
        return parent

    def get_trace(self, *, ancestors_first: bool = True) -> "list[PromisingContext]":
        """
        Return a list of PromisingContext objects in the trace. If
        *ancestors_first* is True (the default), the list is ordered from the
        topmost parent down to this context; otherwise from this context up.
        """
        trace = []
        current = self

        while current is not None:
            trace.append(current)
            current = current._parent

        if ancestors_first:
            trace.reverse()
        return trace

    def format_trace(self, *, ancestors_first: bool = True) -> "list[str]":
        """
        Return a list of string representations of each
        PromisingContext in the trace. If *ancestors_first* is True (the
        default), the list is ordered from the topmost parent down to this
        context; otherwise from this context up.
        """
        # TODO [TRACES] Reconcile this with the excepthooks in errors.py ?
        return [str(ctx) for ctx in self.get_trace(ancestors_first=ancestors_first)]

    def print_trace(self, *, ancestors_first: bool = True) -> None:
        """
        Print each PromisingContext in the trace on a separate line. If
        *ancestors_first* is True (the default), the list is ordered from the
        topmost parent down to this context; otherwise from this context up.
        """
        # TODO [TRACES] Reconcile this with the excepthooks in errors.py ?
        for line in self.format_trace(ancestors_first=ancestors_first):
            print(line)

    async def await_children(self, *, whole_subtree: bool = True, unpack_promises_fully: bool = True) -> None:
        """
        Wait for all awaitable children to finish.

        Repeatedly gathers awaitable children until none remain, since
        children may spawn new children while being awaited.

        Args:
            whole_subtree: If True (the default), wait for all descendants,
                not just direct children.
            unpack_promises_fully: If True (the default), each Promise child
                is fully awaited. If False, Promise children are only unpacked
                one level (``child.unpack_once()``).
        """
        from promising.promise import Promise  # noqa: PLC0415 (import-outside-top-level)

        self._assert_awaiting_on_correct_event_loop()

        _hierarchy_logger.log_awaiting_children_started(parent=self)

        # The loop is needed because, in case of recursive awaiting, new
        # children may be spawned by existing ones while the existing ones
        # are being awaited
        while children := self.collect_unsettled_children(
            whole_subtree=whole_subtree,
            awaitables_only=True,
        ):
            children = [
                child
                for child in children
                if not (
                    # The nested conditional expression below is intentional:
                    # it picks which "doneness" check to apply per child based
                    # on the unpacking mode. A flatter chain of boolean
                    # conditions covering the same logic would be harder to
                    # follow.
                    child.done()
                    if unpack_promises_fully or not isinstance(child, Promise)
                    else child.unpacked_once_or_done()
                )
            ]
            if not children:
                # Additional checkpoint to break the await loop
                break

            _hierarchy_logger.log_awaiting_children(parent=self, children=children)

            # TODO Safeguard from awaiting a child that happens to be the
            #  currently active context (or a parent of the currently active
            #  context ?)
            await asyncio.gather(
                *[
                    child if unpack_promises_fully or not isinstance(child, Promise) else child.unpack_once()
                    for child in children
                ],
                # `return_exceptions` is set to True to make sure we wait for
                # ALL the children that are still in progress, regardless of
                # whether any of them fail (we don't want to wait only until
                # the first one, if any, fails)
                return_exceptions=True,
            )

        _hierarchy_logger.log_children_awaited(parent=self)

    def await_children_sync(
        self,
        *,
        whole_subtree: bool = True,
        unpack_promises_fully: bool = True,
        timeout: float | None = None,
    ) -> None:
        """
        Wait for all awaitable children to finish, blocking the calling
        thread.

        This is the synchronous counterpart of ``await_children()`` — intended
        for use inside sync promising functions that run in a thread pool
        executor, where ``await`` is not available.

        Args:
            whole_subtree: If True (the default), wait for all descendants,
                not just direct children.
            unpack_promises_fully: If True (the default), each Promise child
                is fully awaited. If False, Promise children are only
                unpacked one level (via ``unpack_once()``).
            timeout: Maximum time to wait in seconds.

        Raises:
            SyncUsageError: If called from the event loop thread, because this
                would cause a deadlock.
            TimeoutError: If timeout expires before
                completion.
        """
        self._guard_against_sync_op_deadlock()

        concurrent_future = asyncio.run_coroutine_threadsafe(
            self.await_children(
                whole_subtree=whole_subtree,
                unpack_promises_fully=unpack_promises_fully,
            ),
            self.loop,
        )
        return concurrent_future.result(timeout=timeout)

    def collect_unsettled_children(
        self,
        *,
        whole_subtree: bool = True,
        awaitables_only: bool = True,
    ) -> set["PromisingContext"]:
        """
        Collect children that are still tracked by this context.

        Children register themselves in ``_unsettled_children`` (a strong-ref
        ``set`` guarded by a lock) at construction time and unregister
        themselves once they are closed *and* have no unsettled descendants
        of their own. Filtering options allow narrowing the set further.

        A child is considered "awaitable" if it implements ``__await__``
        (e.g. a ``Promise``, or any custom ``PromisingContext`` subclass that
        defines ``__await__``). Plain ``PromisingContext`` nodes — typically
        created via ``promising.context`` — are not awaitable on their own
        and are excluded by default.

        Args:
            whole_subtree: If True (default), include descendants at all
                levels, not just direct children.
            awaitables_only: If True (default), exclude children that are not
                awaitable (i.e. plain ``PromisingContext`` nodes created via
                ``promising.context``).

        Returns:
            Set of child PromisingContexts matching the filter criteria.
        """
        # TODO [NEW SYNC] Send this operation to the loop.
        #  (This operation only ? Or the whole method ?)
        children = list[PromisingContext](self._unsettled_children)

        if awaitables_only:
            result = {child for child in children if inspect.isawaitable(child)}
        else:
            result = set[PromisingContext](children)

        if whole_subtree:
            # We are iterating over all the children, regardless of the
            # `awaitables_only` parameter, because some children may be
            # considered "unsettled" only because they still have "unsettled"
            # children of their own (even if they themselves are already
            # closed, done, etc.)
            for child in children:
                result.update(
                    child.collect_unsettled_children(
                        whole_subtree=True,
                        awaitables_only=awaitables_only,
                    )
                )
        return result

    def get_thread_pool_executor(self) -> concurrent.futures.ThreadPoolExecutor | None:
        """
        Return the thread pool executor for ``loop.run_in_executor``.
        """
        return self._thread_pool

    def __enter__(self) -> "PromisingContext":
        # TODO [RACE CONDITIONS] Is the following GitHub issue relevant ?
        #  https://github.com/teremterem/Promising/issues/98
        if self._previous_token is not None:
            raise ContextAlreadyActiveError(f"{self!r} is already active")
        if self._context_closed:
            raise ContextAlreadyClosedError(f"{self!r} has already been closed and cannot be re-entered")

        self._previous_token = self.__active_context.set(self)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        if exc_value is not None:
            # Attach this context to the in-flight exception as it leaves
            # the ``with`` block.
            self.try_to_link_exception(exc_value)

        try:
            if self._previous_token is None:
                raise ContextNotActiveError(f"{self!r} is not active")

            self.__active_context.reset(self._previous_token)
            self._previous_token = None

        except BaseException as exc:
            if exc_value is None:
                raise exc
            else:
                raise exc from exc_value

        finally:
            self.close_context_threadsafe()

        return False  # Let's not suppress any exceptions

    def close_context_threadsafe(self) -> None:
        """
        Mark this context as closed and unregister it from its parent if
        no unsettled descendants remain. Safe to call from any thread.

        Called automatically by ``__exit__`` (so a normal ``with`` block
        always closes the context). For a ``Promise``, the context is
        also entered and exited from inside ``_unpack_once_unsafe``
        around the awaiting of the wrapped awaitable, so the close happens
        in lockstep with the unpacking step that produced its first
        result. After this runs, any further attempt to enter the context
        or to register children on it raises ``ContextAlreadyClosedError``.
        """
        # TODO [NEW SYNC] Send this whole method to the loop
        self._context_closed = True
        self._unregister_from_parent_if_time()

    def try_to_link_exception(self, exception: BaseException) -> None:
        """
        Attach this context to the given exception by setting two
        attributes on it:

        - ``__promising_context__`` — this ``PromisingContext`` instance
          (consumed by the ``sys.excepthook`` / ``threading.excepthook``
          overrides in ``promising/errors.py`` to render the
          promising-context trace alongside the standard traceback).
        - ``__promising_collapse_traceback__`` — a boolean snapshot of
          this context's resolved ``collapse_tracebacks`` setting,
          telling the renderer whether to drop promising-internal frames.

        Idempotent (deepest level wins): if ``__promising_context__`` is
        already set on the exception, this call is a no-op, so a nested
        context that already attributed itself is preserved. Failures
        to set either attribute (e.g. on a frozen exception type) are
        swallowed and logged at debug level — losing the breadcrumb must
        not affect exception handling.
        """
        try:
            if hasattr(exception, "__promising_context__"):
                # We only let it be set at the deepest level of the promise
                # hierarchy
                return
            exception.__promising_context__: PromisingContext = self
            exception.__promising_collapse_traceback__: bool = self._collapse_tracebacks
        except BaseException:
            # TODO Should it be just `Exception` ? Any danger that
            #  `KeyboardInterrupt` would get swallowed here ?
            #  Contemplate on this GitHub issue along the way:
            #  https://github.com/teremterem/Promising/issues/105
            _logger.debug(
                "Failed to attach either __promising_context__ or "
                "__promising_collapse_traceback__ to exception %r on %r",
                exception,
                self,
                exc_info=True,
            )
            # TODO [TRACES] Should any kind of warning be printed besides the
            #  debug log ?

    def is_on_correct_running_loop(self, *, raise_thread_loop_not_running: bool = False) -> bool:
        running_loop = get_running_asyncio_loop(raise_if_none=raise_thread_loop_not_running)
        return running_loop is self.loop

    def __repr__(self) -> str:
        namespace_prefix = "" if self.namespace is None else f"{self.namespace!r} "
        return f"<{namespace_prefix}{self.__class__.__name__} id={id(self)}>"

    def _register_with_parent_thread_unsafe(self) -> None:
        """
        TODO Add a "This method can only be used from the event loop of the
         Promise." NOTE to the docstring ?
        """
        # It is thread-safe for the parent but is unsafe for the child itself
        if self._parent is not None and not self.done():
            self._parent._register_children_threadsafe(self)

    def _unregister_from_parent_if_time(self) -> None:
        if self.done() and self._parent is not None and not self._unsettled_children:
            _hierarchy_logger.log_unregistering_from_parent(parent=self._parent, child=self)

            # TODO [NEW SYNC] Send this operation to the loop.
            #  (This operation only ? Or the whole method ?)
            self._parent._unregister_children_threadsafe(self)

    def _register_children_threadsafe(self, *children: "PromisingContext") -> None:
        for child in children:
            if not isinstance(child, PromisingContext):
                raise TypeError(
                    f"Expected a PromisingContext as a child, got {type(child).__name__}.\n"
                    f"Context: {self!r}\nChild: {child!r}"
                )

        if self.closed():
            raise ContextAlreadyClosedError(
                f"Cannot register children in a context that has already been closed.\n"
                f"Context: {self!r}\nChildren: {children!r}"
            )
        self._unsettled_children.update(children)

        _hierarchy_logger.log_children_registered(parent=self, children=children)

    def _unregister_children_threadsafe(self, *children: "PromisingContext") -> None:
        self._unsettled_children.difference_update(children)

        _hierarchy_logger.log_children_unregistered(parent=self, children=children)

        self._unregister_from_parent_if_time()

    def _resolve_start_soon_default(self, start_soon_default: bool | Sentinel) -> bool:
        from promising import Defaults  # noqa: PLC0415 (import-outside-top-level)

        if isinstance(start_soon_default, bool):
            # Concrete value was provided
            return start_soon_default

        if start_soon_default is PROMISING_DEFAULT:
            # Use the global default
            return Defaults.START_SOON

        if start_soon_default is INHERIT:
            if self._parent is None:
                # Use the global default
                return Defaults.START_SOON

            # Inherit from the parent
            return self._parent._start_soon_default

        raise ValueError(
            f"`start_soon_default` must be either PROMISING_DEFAULT, INHERIT or a boolean value, "
            f"but `{type(start_soon_default)}` was given for {self!r} instead"
        )

    def _resolve_collapse_tracebacks(self, collapse_tracebacks: bool | Sentinel) -> bool:
        from promising import Defaults  # noqa: PLC0415 (import-outside-top-level)

        if isinstance(collapse_tracebacks, bool):
            return collapse_tracebacks

        if collapse_tracebacks is PROMISING_DEFAULT:
            return Defaults.COLLAPSE_TRACEBACKS

        if collapse_tracebacks is INHERIT:
            if self._parent is None:
                return Defaults.COLLAPSE_TRACEBACKS

            return self._parent._collapse_tracebacks

        raise ValueError(
            f"`collapse_tracebacks` must be either PROMISING_DEFAULT, INHERIT or a boolean value, "
            f"but `{type(collapse_tracebacks)}` was given for {self!r} instead"
        )

    def _resolve_children_start_soon(self, children_start_soon: bool | None | Sentinel) -> bool | None:
        if isinstance(children_start_soon, bool) or children_start_soon is None:
            # Apart from the concrete value, we also want to allow
            # `self._children_start_soon` to stay as None, so we
            # can later tell whether it is being enforced on children or not
            # (None means "no enforcement").
            return children_start_soon

        if children_start_soon is INHERIT:
            if self._parent is None:
                # Use the default
                return self._start_soon_default

            # Inherit from the parent
            return self._parent._children_start_soon

        raise ValueError(
            f"`children_start_soon` must be either None, INHERIT or a boolean value, "
            f"but `{type(children_start_soon)}` was given for {self!r} instead"
        )

    def _resolve_thread_pool(
        self,
        thread_pool: "concurrent.futures.ThreadPoolExecutor | Sentinel",
    ) -> "concurrent.futures.ThreadPoolExecutor | None":
        from promising import Defaults  # noqa: PLC0415 (import-outside-top-level)

        if isinstance(thread_pool, concurrent.futures.ThreadPoolExecutor):
            return thread_pool

        if thread_pool is ASYNCIO_DEFAULT:
            # Use the event loop's default executor
            return None

        if thread_pool is PROMISING_DEFAULT:
            # Use the Promising framework's default thread pool
            return Defaults.PROMISING_THREAD_POOL

        if thread_pool is INHERIT:
            if self._parent is None:
                # INHERIT, when there is no parent, is the same as
                # PROMISING_DEFAULT (the framework's default thread pool)
                return Defaults.PROMISING_THREAD_POOL
            return self._parent._thread_pool

        raise ValueError(
            f"`thread_pool` must be either INHERIT, PROMISING_DEFAULT, ASYNCIO_DEFAULT "
            f"or a ThreadPoolExecutor instance, but `{type(thread_pool)}` was given for {self!r} instead"
        )

    def _assert_promise_loop_running_for_sync_op(self) -> None:
        """
        Assert that the event loop of the PromisingContext itself is running
        (regardless of whether we are on the same thread or not).
        """
        if not self.loop.is_running():
            raise NoRunningEventLoopError(
                f"Synchronous operations on {self!r} can only be performed if its event loop is running"
            )

    def _guard_against_sync_op_deadlock(self) -> None:
        if self.is_on_correct_running_loop(raise_thread_loop_not_running=False):
            raise SyncUsageError(
                f"Synchronous operations of {self!r} cannot be performed on "
                f"its own event loop thread, as that typically leads to a "
                f"deadlock. Use awaitable operations instead."
            )
        # If we are on a different thread indeed, then let's make sure the event
        # loop of the PromisingContext itself is running, so we don't end up
        # waiting for something that might not happen at all
        self._assert_promise_loop_running_for_sync_op()

    def _assert_awaiting_on_correct_event_loop(self) -> None:
        """
        Guard against awaiting from a wrong event loop.

        Python's asyncio has a native guard for this (``Task.__step`` raises
        ``RuntimeError: Task <...> got Future <...> attached to a different
        loop``), but it only fires when a pending ``Future`` is actually
        yielded to the wrong loop. A Promise that is already done never
        yields one, so awaiting it from a wrong loop would quietly succeed.
        Whether a cross-loop await blows up would then depend on the
        Promise's completion state at that moment — a race the user has no
        control over. This check makes the behavior deterministic: awaiting
        from a wrong loop always fails, regardless of the Promise's status.

        As a bonus, it fails fast (before any unpacking tasks get scheduled
        on the Promise's own loop) and raises a typed ``EventLoopMismatchError``
        with a cleaner message instead of a generic ``RuntimeError`` and a
        noisy message.
        """
        if not self.is_on_correct_running_loop(raise_thread_loop_not_running=True):
            raise EventLoopMismatchError(
                f"Cannot await {self!r} from a different event loop than the one it belongs to."
            )

    def _send_sync_op_to_loop(
        self,
        callable: Callable[[], Any],
        *,
        send_and_forget: bool,
        fail_if_loop_not_running: bool,
    ) -> Any:
        """
        TODO [NEW SYNC] Explain in the docstring that this private method is
         the central primitive in solving synchronization between synchronous
         and asynchronous paradigms combined by this framework.
        """
        if self.is_on_correct_running_loop(raise_thread_loop_not_running=False):
            # We are on the event loop of the Promise, so we can call the
            # callable directly
            result = callable()
            if send_and_forget:
                # TODO [NEW SYNC] What to do about potential exceptions from the
                #  callable ? Let them bubble up ?
                return None

            return result

        if fail_if_loop_not_running:
            self._assert_promise_loop_running_for_sync_op()

        # We are on a different thread, so we need to schedule the callable on
        # the loop
        if not send_and_forget:
            # We are interested in the result, so we need to use a future to
            # wait for it and get it
            future = concurrent.futures.Future()

            def callback():
                try:
                    result = callable()
                except BaseException as exc:
                    # TODO [NEW SYNC] Set as an internal error on the Promise itself
                    #  instead ? (Would require moving the method to the
                    #  Promise class.)
                    future.set_exception(exc)
                else:
                    future.set_result(result)

            self.loop.call_soon_threadsafe(callback)
            return future.result()

        # We don't care about the result (send_and_forget=True), so we don't
        # wait for anything
        self.loop.call_soon_threadsafe(callable)
