import asyncio
import concurrent.futures
import contextvars
from asyncio import AbstractEventLoop
from contextvars import ContextVar
from weakref import WeakSet

from promising.errors import ContextNotFoundError, SyncPromiseUsageError
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
    return PromisingContext.get_current(raise_if_none=raise_if_none)


async def await_children(*, recursively: bool = False) -> None:
    """
    Wait for all child Promises to finish.

    Args:
        recursively: If True, wait for all children of all children, and so
            on, recursively.
    """
    return await get_active_context().await_children(recursively=recursively)


def await_children_sync(*, recursively: bool = False) -> None:
    """
    Wait for all child Promises to finish, blocking the calling thread.

    Args:
        recursively: If True, wait for all children of all children, and so
            on, recursively.
    """
    return get_active_context().await_children_sync(recursively=recursively)


class PromisingContext:
    _active_context = ContextVar["PromisingContext | None"]("PromisingContext._active_context", default=None)

    _previous_token: contextvars.Token | None

    # TODO Support cancellation of the whole PromisingContext tree
    # TODO Order the methods in this class in a more useful manner
    #  (do this after we spin off PromisingContext out of this class)

    def __init__(
        self,
        *,
        loop: AbstractEventLoop | None = None,
        parent: "PromisingContext | Sentinel | None" = INHERIT,
        start_soon: bool | Sentinel = NOT_SET,
        children_start_soon_by_default: bool | Sentinel = NOT_SET,
        everything_starts_soon_by_default: bool | Sentinel = INHERIT,
    ) -> None:
        self._previous_token = None

        if parent is INHERIT:
            self._parent = self.get_current(raise_if_none=False)
        elif parent is None or isinstance(parent, PromisingContext):
            self._parent = parent
        else:
            raise ValueError(
                "`parent` must be either INHERIT, another PromisingContext "
                f"or None, but `{type(parent)}` was given instead"
            )

        self._resolve_everything_starts_soon_by_default(everything_starts_soon_by_default)
        self._resolve_start_soon(start_soon)
        self._resolve_children_start_soon_by_default(children_start_soon_by_default)

        if self._parent is not None:
            if loop is None:
                loop = self._parent.loop
            elif loop is not self._parent.loop:
                raise ValueError("Parent and child PromisingContexts must share the same event loop")
        # TODO TODO TODO Get the current loop if none was resolved

        self._children = WeakSet[PromisingContext]()
        if self._parent is not None:
            self._parent._children.add(self)

    def await_children_sync(self, *, recursively: bool = False) -> None:
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
            self._loop.create_task(await_children_and_notify(), name=self._name + "-AwaitChildrenSync")

        self._loop.call_soon_threadsafe(schedule_await_children)
        # Should any error happen in the underlying async `await_children`,
        # the call below will re-raise it
        concurrent_future.result()

    def _assert_no_sync_usage_deadlock(self, message: str) -> None:
        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None

        if running_loop is self._loop:
            raise SyncPromiseUsageError(message)

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
            raise ContextNotFoundError("No active PromisingContext is found")
        return active

    def get_parent_context(self, *, raise_if_none: bool = True) -> "PromisingContext | None":
        """
        Get the parent PromisingContext of this PromisingContext.

        Args:
            raise_if_none: If True, raises an exception when no parent PromisingContext exists.

        Returns:
            The parent PromisingContext, or None if none exists and
            raise_if_none is False.

        Raises:
            ContextNotFoundError: If no parent PromisingContext exists and
                raise_if_none is True.
        """
        if raise_if_none and self._parent is None:
            raise ContextNotFoundError("No parent PromisingContext is found")
        return self._parent

    # TODO TODO TODO

    def get_still_existing_children(
        self,
        *,
        recursively: bool = False,
        exclude_done: bool = True,
    ) -> set["PromisingContext"]:
        """
        Get child PromisingContexts that weren't garbage collected and are still
        reachable. Those would be the ones that are either still in progress
        themselves, or have children of their own that are still in progress.

        Args:
            recursively: If True, return children of children, and so on
                (in the same set).
            exclude_done: If True, exclude child PromisingContexts that are done
                (i.e. have a result or exception set).

        Returns:
            Set of child PromisingContexts that are still existing.
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
                # In `asyncio.tasks` it was `_all_tasks` instead of
                # `self._children`
                children = list[PromisingContext](self._children)
            except RuntimeError:
                i += 1
                if i > 1000:  # noqa: PLR2004 (magic-value-comparison)
                    raise

            else:
                if exclude_done:
                    result = {child for child in children if not child.done()}
                else:
                    result = set[PromisingContext](children)

                if recursively:
                    # We are iterating over all the children, regardless of
                    # the exclude_done setting, because some children that are
                    # done might have children of their own that are still in
                    # progress.
                    for child in children:
                        result.update(child.get_still_existing_children(recursively=True, exclude_done=exclude_done))

                return result

    async def await_children(self, *, recursively: bool = False) -> None:
        """
        Wait for child Promises to finish.

        Args:
            recursively: If True, wait for all children of all children, and so
                on, recursively.
        """
        while children := self.get_still_existing_children(
            recursively=recursively,
            exclude_done=True,
        ):
            # The loop is needed because, in case of recursive awaiting, new
            # children may be spawned by existing ones while the existing ones
            # are being awaited
            await asyncio.gather(
                *children,
                # `return_exceptions` is set to True to make sure we wait for
                # ALL the children that are still in progress, regardless of
                # whether any of them fail (we don't just wait until the first
                # one fails)
                return_exceptions=True,
            )
        # TODO Ideally, a warning (or an optional exception ?) should be issued
        #  if any of the remaining children are configured with
        #  `start_soon=False`, because that would make it quite easy to
        #  introduce deadlocks.

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

    def _resolve_start_soon(self, start_soon: bool | Sentinel) -> None:
        if isinstance(start_soon, bool):
            # Concrete value was provided
            self._start_soon = start_soon
        elif start_soon is NOT_SET:
            # TODO Should there be any reason or scenario when
            #  `everything_starts_soon_by_default` takes precedence over the
            #  parent's `children_start_soon_by_default` ?
            if self._parent is not None and self._parent._children_start_soon_by_default is not NOT_SET:
                # The parent is enforcing this setting for its children
                self._start_soon = self._parent._children_start_soon_by_default
            else:
                # Use the default
                self._start_soon = self._everything_starts_soon_by_default
        elif start_soon is INHERIT:
            if self._parent is None:
                # Use the default
                self._start_soon = self._everything_starts_soon_by_default
            else:
                # Inherit from the parent
                self._start_soon = self._parent._start_soon
        else:
            raise ValueError(
                "`start_soon` must be either NOT_SET, INHERIT or a boolean value, "
                f"but `{type(start_soon)}` was given instead"
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
