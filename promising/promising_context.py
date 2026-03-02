import asyncio
import concurrent.futures
import contextvars
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
from promising.sentinels import GLOBAL_DEFAULT, INHERIT, NOT_SET, Sentinel
from promising.types import DecoratableFunctionType
from promising.utils import DecoratorSupport

if TYPE_CHECKING:
    from promising.promise import Promise


class context(DecoratorSupport):  # noqa: N801 (invalid-class-name)
    """
    # TODO Explain in docstring, when it comes to using it as a decorator, why
    #  does it exist separately from @promising.function ? What's the
    #  difference between the two ?
    """

    def __init__(
        self,
        func_or_method: DecoratableFunctionType | None = None,
        *,
        loop: AbstractEventLoop | None = None,
        parent: "PromisingContext | Sentinel | None" = INHERIT,
        children_start_soon: bool | Sentinel = INHERIT,
        start_soon_default: bool | Sentinel = INHERIT,
    ) -> None:
        super().__init__(func_or_method)
        self._ctx_loop = loop
        self._parent = parent
        self._children_start_soon = children_start_soon
        self._start_soon_default = start_soon_default

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
                loop=self._ctx_loop,
                parent=self._parent,
                children_start_soon=self._children_start_soon,
                start_soon_default=self._start_soon_default,
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
            loop=self._ctx_loop,
            parent=self._parent,
            children_start_soon=self._children_start_soon,
            start_soon_default=self._start_soon_default,
        )

        if self._is_wrapped_async:
            # Wrapped function or method is async

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
    """
    # TODO We need unit tests that ensure this function works correctly even
    #  when called on a bare PromisingContext, and not on a Promise.
    return await get_active_context().await_children(recursively=recursively)


def await_children_sync(*, recursively: bool = False) -> None:
    """
    Wait for all awaitable children of the active context to finish,
    blocking the calling thread.
    # TODO Elaborate more on why this method exists.
    #  See promising/promise.py::Promise.sync() for more details.

    Args:
        recursively: If True, wait for all descendants, not just direct
            children.
    """
    # TODO We need unit tests that ensure this function works correctly even
    #  when called on a bare PromisingContext, and not on a Promise.
    return get_active_context().await_children_sync(recursively=recursively)


class PromisingContext:
    """
    Create a new PromisingContext.

    A PromisingContext provides hierarchical context management for
    asynchronous operations. It tracks parent-child relationships,
    manages configuration inheritance (e.g. start_soon behavior), and
    maintains a weak set of child contexts for awaiting.

    Args:
        loop: The event loop to use. If not provided, inherits from the
            parent context. If no parent exists, uses the current event
            loop. If provided explicitly and a parent exists, must be the
            same event loop as the parent's.
        parent: Parent PromisingContext. If INHERIT (default), uses the
            currently active context as parent. If None, the context has
            no parent.
        children_start_soon: Default start_soon value enforced on child
            contexts that leave start_soon as NOT_SET. NOT_SET means no
            enforcement. INHERIT (default) copies the parent's setting of
            the same name.
        start_soon_default: Local override for the global START_SOON_DEFAULT.
            INHERIT (default) propagates from the parent. GLOBAL_DEFAULT reads
            the current global setting without inheriting.

    Raises:
        ValueError: If invalid parameter values or combinations are provided.
    """

    ctx_namespace: str | None = None

    __active_context = ContextVar["PromisingContext | None"]("PromisingContext.__active_context", default=None)

    # TODO Support cancellation of the whole PromisingContext tree

    def __init__(
        self,
        *,
        loop: AbstractEventLoop | None = None,
        name: str | None = None,
        parent: "PromisingContext | Sentinel | None" = INHERIT,
        children_start_soon: bool | Sentinel = INHERIT,
        start_soon_default: bool | Sentinel = INHERIT,
    ) -> None:
        self.ctx_namespace = name
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

    def __repr__(self) -> str:
        if self.ctx_namespace:
            return f"{self.ctx_namespace}-{self.__class__.__name__}-{id(self)}"
        return f"{self.__class__.__name__}-{id(self)}"

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
                *children,
                # `return_exceptions` is set to True to make sure we wait for
                # ALL the children that are still in progress, regardless of
                # whether any of them fail (we don't want to wait only until
                # the first one, if any, fails)
                return_exceptions=True,
            )

    def await_children_sync(self, *, recursively: bool = False) -> None:
        """
        Wait for all awaitable children to finish, blocking the calling
        thread.

        This is the synchronous counterpart of await_children() — intended
        for use from threads that are not running the event loop.
        # TODO Elaborate more on why this method exists.
        #  See promising/promise.py::Promise.sync() for more details.

        Args:
            recursively: If True, wait for all descendants, not just direct
                children.

        Raises:
            SyncUsageError: If called from the event loop thread, because this
                would cause a deadlock.
        """
        self._assert_no_sync_usage_deadlock(
            "`await_children_sync()` cannot be called from the "
            "event loop thread because it would deadlock. Use "
            "`await promise.await_children()` or "
            "`await promising.await_children()` instead."
        )
        concurrent_future = concurrent.futures.Future[None]()

        async def await_children_and_notify() -> None:
            try:
                await self.await_children(recursively=recursively)
            except BaseException as exc:  # noqa: BLE001 (blind-except)
                concurrent_future.set_exception(exc)
            else:
                concurrent_future.set_result(None)

        def schedule_await_children() -> None:
            self._ctx_loop.create_task(await_children_and_notify(), name=str(self) + "-AwaitChildrenSyncTask")

        self._call_soon_threadsafe(schedule_await_children)
        # Should any error happen in the underlying async `await_children`,
        # the call below will re-raise it
        concurrent_future.result()

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

        except BaseException as exc:  # noqa: BLE001 (blind-except)
            if exc_value is None:
                raise exc
            else:
                raise exc from exc_value

        return False  # Let's not suppress any exceptions

    def _resolve_start_soon_default(self, start_soon_default: bool | Sentinel) -> bool:
        from promising import should_start_soon_by_default  # noqa: PLC0415 (import-outside-top-level)

        if isinstance(start_soon_default, bool):
            # Concrete value was provided
            return start_soon_default

        if start_soon_default is GLOBAL_DEFAULT:
            # Use the global default
            return should_start_soon_by_default()

        if start_soon_default is INHERIT:
            if self._parent is None:
                # Use the global default
                return should_start_soon_by_default()

            # Inherit from the parent
            return self._parent._start_soon_default

        raise ValueError(
            "`start_soon_default` must be either GLOBAL_DEFAULT, INHERIT or a boolean value, "
            f"but `{type(start_soon_default)}` was given instead"
        )

    def _resolve_children_start_soon(self, children_start_soon: bool | Sentinel) -> bool | Sentinel:
        if isinstance(children_start_soon, bool) or children_start_soon is NOT_SET:
            # Apart from the concrete value, we also want to allow
            # `self._children_start_soon` to stay as NOT_SET, so we
            # can later tell whether it is being enforced on children or not
            # (NOT_SET means "no enforcement").
            return children_start_soon

        if children_start_soon is INHERIT:
            if self._parent is None:
                # Use the default
                return self._start_soon_default

            # Inherit from the parent
            return self._parent._children_start_soon

        raise ValueError(
            "`children_start_soon` must be either NOT_SET, INHERIT or a boolean value, "
            f"but `{type(children_start_soon)}` was given instead"
        )

    def _assert_no_sync_usage_deadlock(self, message: str) -> None:
        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None

        if running_loop is self._ctx_loop:
            raise SyncUsageError(message)

    def _call_soon_threadsafe(self, callback: Callable[[], Any]) -> None:
        if not self._ctx_loop.is_running():
            raise SyncUsageError(
                "The event loop that would monitor a synchronous operation "
                f"in this {self.__class__.__name__} is not running"
            )

        self._ctx_loop.call_soon_threadsafe(callback)
