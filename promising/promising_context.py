import asyncio
import concurrent.futures
import contextvars
import functools
import inspect
from asyncio import AbstractEventLoop, Future
from collections.abc import Callable
from contextvars import ContextVar
from types import TracebackType
from typing import TYPE_CHECKING, Any
from weakref import WeakSet

from promising.errors import (
    ContextAlreadyActiveError,
    ContextNotActiveError,
    ContextNotFoundError,
    ContextUsageError,
    PromiseNotFoundError,
    SyncUsageError,
)
from promising.sentinels import ASYNCIO_DEFAULT, GLOBAL_DEFAULT, INHERIT, Sentinel
from promising.types import DecoratableFunctionType
from promising.utils import DecoratorSupport, assert_no_sync_usage_deadlock, is_func_or_method_async

if TYPE_CHECKING:
    from promising.promise import Promise


class context(DecoratorSupport):  # noqa: N801 (invalid-class-name)
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
        await ctx.await_children(recursively=True)

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
            ``PromisingContext``. Shows up in ``__repr__`` output and (planned)
            error breadcrumbs. When used as a decorator and not provided,
            defaults to the wrapped function's ``__qualname__``.
            # TODO Planned feature: Namespaces will show up in the form of
            #  breadcrumbs in error logs to help trace the source of errors.
            # TODO Anything else we could do with namespaces ?
        loop: Event loop to use. None (default) inherits from the
            parent context, or falls back to ``asyncio.get_event_loop()`` at
            the root.
        parent: Parent ``PromisingContext``. ``INHERIT`` (default) uses the
            currently active context. ``None`` creates a root context with no
            parent.
        thread_pool: Thread pool executor used to run sync promising functions.
            ``INHERIT`` (default) inherits from the parent context, falling
            back to ``GLOBAL_DEFAULT`` at the root. ``GLOBAL_DEFAULT`` uses
            ``Defaults.SYNC_THREAD_POOL``. ``ASYNCIO_DEFAULT`` passes ``None``
            to ``run_in_executor``, letting the event loop use its own default
            executor. A concrete ``ThreadPoolExecutor`` instance can also be
            provided.
        children_start_soon: Default ``start_soon`` value enforced on child
            Promises whose own ``start_soon`` is None. Controls whether
            they start executing immediately (i.e. as soon as the event loop
            allows), or defer until awaited one way or another. ``INHERIT``
            (default) copies the parent's setting.
        start_soon_default: Local override for the global
            ``Defaults.START_SOON``, effective in the whole subtree of this
            context. ``INHERIT`` (default) propagates from the parent.
    """

    def __init__(
        self,
        func_or_method: DecoratableFunctionType | None = None,
        *,
        namespace: str | None = None,
        loop: AbstractEventLoop | None = None,
        parent: "PromisingContext | None | Sentinel" = INHERIT,
        thread_pool: "concurrent.futures.ThreadPoolExecutor | Sentinel" = INHERIT,
        children_start_soon: bool | None | Sentinel = INHERIT,
        start_soon_default: bool | Sentinel = INHERIT,
    ) -> None:
        super().__init__(func_or_method, namespace=namespace)

        self.ctx_loop = loop
        self.parent = parent
        self.thread_pool = thread_pool
        self.children_start_soon = children_start_soon
        self.start_soon_default = start_soon_default

        self._promising_context = None

    def __enter__(self) -> "PromisingContext":
        """
        If this method was called, then it means that this `promising.context`
        instance is being used as a context manager. We need to create a new
        PromisingContext instance and activate it.
        """
        if self.__wrapped__ is not None:
            raise ContextUsageError(
                "The same instance of `promising.context` cannot serve both "
                "as a context manager and as a decorator simultaneously"
            )

        if self._promising_context is None:
            self._promising_context = PromisingContext(
                namespace=self.namespace,
                loop=self.ctx_loop,
                parent=self.parent,
                thread_pool=self.thread_pool,
                children_start_soon=self.children_start_soon,
                start_soon_default=self.start_soon_default,
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

    def __call__(self, *args: Any, **kwargs: Any) -> Any | DecoratableFunctionType:
        if self.__wrapped__ is None:
            # We are still in the process of decorating a function or method
            # (because this decorator was used with parameters) - let's finish
            # the decoration process
            if len(args) != 1 or kwargs:
                raise ContextUsageError(
                    "The decorator must be called with exactly one positional "
                    "argument after its parameters were already provided, and "
                    "it should be a strictly positional argument: a function "
                    "or method to decorate."
                )
            self._update_wrapper(args[0])
            return self

        # The function or method was already decorated and the decorator is now
        # being called with arguments - let's pass this call through to the
        # underlying function or method
        ctx = PromisingContext(
            namespace=self.namespace,
            loop=self.ctx_loop,
            parent=self.parent,
            thread_pool=self.thread_pool,
            children_start_soon=self.children_start_soon,
            start_soon_default=self.start_soon_default,
        )

        if is_func_or_method_async(self.__wrapped__):
            # Wrapped function or method is async

            @functools.wraps(self.__wrapped__)
            async def _async_wrapper() -> Any:
                with ctx:
                    return await self._wrapped_as_callable(*args, **kwargs)

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


async def await_children(*, recursively: bool = False) -> None:
    """
    Wait for all awaitable children of the active context to finish.

    Args:
        recursively: If True, wait for all descendants, not just direct
            children.
            # TODO Why is it False by default, and not True ? Either change
            #  or explain in the docstring.
    """
    # TODO We need unit tests that ensure this function works correctly even
    #  when called on a bare PromisingContext, and not on a Promise.
    # TODO Do we need a check that ensures that this function was called in a
    #  thread that contains the event loop of this particular
    #  PromisingContext ? What other functions or methods might we need it in ?
    return await get_active_context().await_children(recursively=recursively)


def await_children_sync(*, recursively: bool = False, timeout: float | None = None) -> None:
    """
    Wait for all awaitable children of the active context to finish,
    blocking the calling thread.

    This is the synchronous counterpart of ``await_children()`` — intended
    for use inside sync promising functions that run in a thread pool
    executor, where ``await`` is not available.

    Args:
        recursively: If True, wait for all descendants, not just direct
            children.
            # TODO Why is it False by default, and not True ? Either change
            #  or explain in the docstring.
        timeout: Maximum time to wait in seconds.
    """
    # TODO We need unit tests that ensure this function works correctly even
    #  when called on a bare PromisingContext, and not on a Promise.
    return get_active_context().await_children_sync(recursively=recursively, timeout=timeout)


class PromisingContext:
    """Hierarchical context node that tracks parent-child relationships
    between promises. Usually created via ``promising.context``; see
    :class:`promising.context` for usage details and parameter
    descriptions."""

    namespace: str | None

    __active_context = ContextVar["PromisingContext | None"]("PromisingContext.__active_context", default=None)

    # TODO [P1] Support cancellation of the whole PromisingContext tree

    def __init__(
        self,
        *,
        namespace: str | None = None,
        loop: AbstractEventLoop | None = None,
        parent: "PromisingContext | None | Sentinel" = INHERIT,
        thread_pool: "concurrent.futures.ThreadPoolExecutor | Sentinel" = INHERIT,
        children_start_soon: bool | None | Sentinel = INHERIT,
        start_soon_default: bool | Sentinel = INHERIT,
    ) -> None:
        self.namespace = namespace
        self._previous_token: contextvars.Token | None = None

        if parent is INHERIT:
            self._parent = self.get_active_context(raise_if_none=False)
        elif parent is None or isinstance(parent, PromisingContext):
            self._parent = parent
        else:
            raise ValueError(
                "`parent` must be either INHERIT, another PromisingContext "
                f"or None, but `{type(parent)}` was given instead"
            )

        self._start_soon_default = self._resolve_start_soon_default(start_soon_default)
        self._children_start_soon = self._resolve_children_start_soon(children_start_soon)
        self._thread_pool = self._resolve_thread_pool(thread_pool)

        if loop is None:
            if self._parent is None:
                self._ctx_loop = asyncio.get_event_loop()
            else:
                self._ctx_loop = self._parent._ctx_loop
        else:
            if self._parent is not None and loop is not self._parent._ctx_loop:
                raise ValueError("Parent and child PromisingContexts must share the same event loop")
            self._ctx_loop = loop

        self._children = WeakSet[PromisingContext]()
        if self._parent is not None:
            self._parent._children.add(self)

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
            raise ContextNotFoundError("No parent PromisingContext found")
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
            raise PromiseNotFoundError("No parent Promise found")
        return parent

    async def await_children(self, *, recursively: bool = False) -> None:
        """
        Wait for all awaitable children to finish.

        Repeatedly gathers awaitable children until none remain, since
        children may spawn new children while being awaited.

        Args:
            recursively: If True, wait for all descendants, not just direct
                children.
                # TODO Why is it False by default, and not True ? Either change
                #  or explain in the docstring.
        """
        while children := self.collect_remaining_children(
            recursively=recursively,
            exclude_non_awaitable=True,
            exclude_done=True,
        ):
            # The loop is needed because, in case of recursive awaiting, new
            # children may be spawned by existing ones while the existing ones
            # are being awaited
            await asyncio.gather(
                *[child.unpack_once() for child in children],
                # `return_exceptions` is set to True to make sure we wait for
                # ALL the children that are still in progress, regardless of
                # whether any of them fail (we don't want to wait only until
                # the first one, if any, fails)
                return_exceptions=True,
            )

    def await_children_sync(self, *, recursively: bool = False, timeout: float | None = None) -> None:
        """
        Wait for all awaitable children to finish, blocking the calling
        thread.

        This is the synchronous counterpart of ``await_children()`` — intended
        for use inside sync promising functions that run in a thread pool
        executor, where ``await`` is not available.

        Args:
            recursively: If True, wait for all descendants, not just direct
                children.
                # TODO Why is it False by default, and not True ? Either change
                #  or explain in the docstring.
            timeout: Maximum time to wait in seconds.

        Raises:
            SyncUsageError: If called from the event loop thread, because this
                would cause a deadlock.
            TimeoutError: If timeout expires before
                completion.
        """
        assert_no_sync_usage_deadlock(
            self._ctx_loop,
            "`await_children_sync()` cannot be called from the "
            "event loop thread because it would deadlock. Use "
            "`await promise.await_children()` or "
            "`await promising.await_children()` instead.",
        )
        concurrent_future = concurrent.futures.Future[None]()

        async def await_children_and_notify() -> None:
            try:
                await self.await_children(recursively=recursively)
            except BaseException as exc:
                # This ideally should not happen (provided there are no bugs in
                # the framework) - `await_children` gathers all exceptions from
                # the children and suppresses them
                concurrent_future.set_exception(exc)
            else:
                concurrent_future.set_result(None)

        def schedule_await_children() -> None:
            self._ctx_loop.create_task(await_children_and_notify(), name=str(self) + "-AwaitChildrenSyncTask")

        self._call_soon_threadsafe(schedule_await_children)
        concurrent_future.result(timeout=timeout)

    def collect_remaining_children(
        self,
        *,
        recursively: bool = False,
        exclude_non_awaitable: bool = True,
        exclude_done: bool = True,
    ) -> set["PromisingContext"]:
        """
        Collect child contexts that haven't been garbage collected.

        Children are held via a WeakSet, so only children that are still
        strongly referenced elsewhere will be returned. Filtering options
        allow narrowing the set to awaitable and/or in-progress children.

        A child is considered "awaitable" if ``inspect.isawaitable()``
        returns True for it (e.g. Promises, which are Futures). A child is
        considered "done" if it is an asyncio Future whose ``done()`` method
        returns True.

        Args:
            recursively: If True, include descendants at all levels, not
                just direct children.
            exclude_non_awaitable: If True (default), exclude children that
                are not awaitable (i.e. plain PromisingContexts that are not
                Futures).
            exclude_done: If True (default), exclude children that weren't
                garbage collected yet, but are done nonetheless (i.e. Futures
                with a result or exception already set).

        Returns:
            Set of child PromisingContexts matching the filter criteria.
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
                # In `asyncio.tasks::all_tasks()` it was `_all_tasks` instead of
                # `self._children`
                children = list[PromisingContext](self._children)
            except RuntimeError:
                i += 1
                if i > 1000:  # noqa: PLR2004 (magic-value-comparison)
                    raise

            else:
                result = {
                    child
                    for child in children
                    if (not exclude_non_awaitable or inspect.isawaitable(child))
                    and (not exclude_done or not isinstance(child, Future) or not child.done())
                }

                if recursively:
                    # We are iterating over all the children, regardless of
                    # the exclude_done and exclude_non_awaitable settings,
                    # because some children that are done or non-awaitable
                    # might have children of their own which are awaitable and
                    # are still in progress and so on. (This works because
                    # those children of children prevent their parents from
                    # being garbage collected, since they, while themselves
                    # being active, still hold a strong reference to their
                    # parents.)
                    for child in children:
                        result.update(
                            child.collect_remaining_children(
                                recursively=True,
                                exclude_non_awaitable=exclude_non_awaitable,
                                exclude_done=exclude_done,
                            )
                        )

                return result

    def __enter__(self) -> "PromisingContext":
        if self._previous_token is not None:
            raise ContextAlreadyActiveError("This PromisingContext is already active")

        self._previous_token = self.__active_context.set(self)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        try:
            if self._previous_token is None:
                raise ContextNotActiveError("This PromisingContext is not active")

            self.__active_context.reset(self._previous_token)
            self._previous_token = None

        except BaseException as exc:
            if exc_value is None:
                raise exc
            else:
                raise exc from exc_value

        return False  # Let's not suppress any exceptions

    # TODO Implement `get_promising_trace(only_with_namespaces: bool = True)`
    #  method

    def _resolve_start_soon_default(self, start_soon_default: bool | Sentinel) -> bool:
        from promising import Defaults  # noqa: PLC0415 (import-outside-top-level)

        if isinstance(start_soon_default, bool):
            # Concrete value was provided
            return start_soon_default

        if start_soon_default is GLOBAL_DEFAULT:
            # Use the global default
            return Defaults.START_SOON

        if start_soon_default is INHERIT:
            if self._parent is None:
                # Use the global default
                return Defaults.START_SOON

            # Inherit from the parent
            return self._parent._start_soon_default

        raise ValueError(
            "`start_soon_default` must be either GLOBAL_DEFAULT, INHERIT or a boolean value, "
            f"but `{type(start_soon_default)}` was given instead"
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
            "`children_start_soon` must be either None, INHERIT or a boolean value, "
            f"but `{type(children_start_soon)}` was given instead"
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

        if thread_pool is GLOBAL_DEFAULT:
            # Use the Promising framework's default thread pool
            return Defaults.SYNC_THREAD_POOL

        if thread_pool is INHERIT:
            if self._parent is None:
                # INHERIT, when there is no parent, is the same as
                # GLOBAL_DEFAULT (the framework's default thread pool)
                return Defaults.SYNC_THREAD_POOL
            return self._parent._thread_pool

        raise ValueError(
            "`thread_pool` must be either INHERIT, GLOBAL_DEFAULT, ASYNCIO_DEFAULT "
            f"or a ThreadPoolExecutor instance, but `{type(thread_pool)}` was given instead"
        )

    def get_thread_pool_executor(self) -> concurrent.futures.ThreadPoolExecutor | None:
        """
        Return the thread pool executor for ``loop.run_in_executor``.
        """
        return self._thread_pool

    def _repr_context(self, namespace: str | None = None) -> str:
        namespace = "" if namespace is None else f"{namespace!r} "
        return f"<{namespace}{self.__class__.__name__} id={id(self)}>"

    def __repr__(self) -> str:
        return self._repr_context(self.namespace)

    def _call_soon_threadsafe(self, callback: Callable[[], Any]) -> None:
        if not self._ctx_loop.is_running():
            raise SyncUsageError(
                "The event loop that would monitor a synchronous operation "
                f"in this {self.__class__.__name__} is not running"
            )

        self._ctx_loop.call_soon_threadsafe(callback)
