import asyncio
import concurrent.futures
import contextvars
import inspect
from asyncio import AbstractEventLoop, Future
from contextvars import ContextVar
from weakref import WeakSet

from promising.errors import ContextNotFoundError, SyncUsageError
from promising.sentinels import GLOBAL_DEFAULT, INHERIT, NOT_SET, Sentinel


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
        children_start_soon_by_default: Default start_soon value enforced
            on child contexts that leave start_soon as NOT_SET. NOT_SET
            (default) means no enforcement. INHERIT copies the parent's
            setting.
        everything_starts_soon_by_default: Local override for the global
            EVERYTHING_STARTS_SOON_BY_DEFAULT. INHERIT (default)
            propagates from the parent. GLOBAL_DEFAULT reads the current
            global setting without inheriting.

    Raises:
        ValueError: If invalid parameter values or combinations are
            provided.
    """

    _active_context = ContextVar["PromisingContext | None"]("PromisingContext._active_context", default=None)
    _previous_token: contextvars.Token | None

    # TODO Support cancellation of the whole PromisingContext tree

    def __init__(
        self,
        *,
        loop: AbstractEventLoop | None = None,
        parent: "PromisingContext | Sentinel | None" = INHERIT,
        children_start_soon_by_default: bool | Sentinel = NOT_SET,
        everything_starts_soon_by_default: bool | Sentinel = INHERIT,
    ) -> None:
        self._previous_token = None

        if parent is INHERIT:
            self._parent = self.get_active_context(raise_if_none=False)
        elif parent is None or isinstance(parent, PromisingContext):
            self._parent = parent
        else:
            raise ValueError(
                "`parent` must be either INHERIT, another PromisingContext "
                f"or None, but `{type(parent)}` was given instead"
            )

        self._resolve_everything_starts_soon_by_default(everything_starts_soon_by_default)
        self._resolve_children_start_soon_by_default(children_start_soon_by_default)

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
        active = cls._active_context.get()
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
            self._ctx_loop.create_task(await_children_and_notify(), name=self._name + "-AwaitChildrenSync")

        self._ctx_loop.call_soon_threadsafe(schedule_await_children)
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

    def _resolve_everything_starts_soon_by_default(self, everything_starts_soon_by_default: bool | Sentinel) -> None:
        from promising import should_everything_start_soon_by_default  # noqa: PLC0415 (import-outside-top-level)

        if isinstance(everything_starts_soon_by_default, bool):
            # Concrete value was provided
            self._everything_starts_soon_by_default = everything_starts_soon_by_default
        elif everything_starts_soon_by_default is GLOBAL_DEFAULT:
            # Use the global default
            self._everything_starts_soon_by_default = should_everything_start_soon_by_default()
        elif everything_starts_soon_by_default is INHERIT:
            if self._parent is None:
                # Use the global default
                self._everything_starts_soon_by_default = should_everything_start_soon_by_default()
            else:
                # Inherit from the parent
                self._everything_starts_soon_by_default = self._parent._everything_starts_soon_by_default
        else:
            raise ValueError(
                "`everything_starts_soon_by_default` must be either GLOBAL_DEFAULT, INHERIT or a boolean value, "
                f"but `{type(everything_starts_soon_by_default)}` was given instead"
            )

    def _resolve_children_start_soon_by_default(self, children_start_soon_by_default: bool | Sentinel) -> None:
        if isinstance(children_start_soon_by_default, bool) or children_start_soon_by_default is NOT_SET:
            # Apart from the concrete value, we also want to allow
            # `self._children_start_soon_by_default` to stay as NOT_SET, so we
            # can later tell whether it is being enforced on children or not
            # (NOT_SET means "no enforcement").
            self._children_start_soon_by_default = children_start_soon_by_default
        elif children_start_soon_by_default is INHERIT:
            if self._parent is None:
                # Use the default
                self._children_start_soon_by_default = self._everything_starts_soon_by_default
            else:
                # Inherit from the parent
                self._children_start_soon_by_default = self._parent._children_start_soon_by_default
        else:
            raise ValueError(
                "`children_start_soon_by_default` must be either NOT_SET, INHERIT or a boolean value, "
                f"but `{type(children_start_soon_by_default)}` was given instead"
            )

    def _assert_no_sync_usage_deadlock(self, message: str) -> None:
        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None

        if running_loop is self._ctx_loop:
            raise SyncUsageError(message)
