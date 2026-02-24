import asyncio
import contextvars
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any
from weakref import WeakSet

from promising.errors import ContextNotFoundError, PromiseNotFoundError, SyncUsageError
from promising.sentinels import GLOBAL_DEFAULT, INHERIT, NOT_SET, Sentinel

if TYPE_CHECKING:
    from promising.promise import Promise


def get_current_context(*, raise_if_none: bool = True) -> "PromisingContext | None":
    """
    Get the currently active PromisingContext.

    Args:
        raise_if_none: If True, raises NoCurrentContextError when no active
            PromisingContext is found.

    Returns:
        The currently active PromisingContext instance, or None if no PromisingContext is active
        and raise_if_none is False.

    Raises:
        NoCurrentContextError: If no active PromisingContext is found and raise_if_none
            is True.
    """
    return PromisingContext.get_current_context(raise_if_none=raise_if_none)


async def await_children(*, recursively: bool = False) -> None:
    """
    Wait for all child Promises to finish.

    Args:
        recursively: If True, wait for all children of all children, and so on.
    """
    return await get_current_context().await_children(recursively=recursively)


def await_children_sync(*, recursively: bool = False) -> None:
    """
    Wait for all child Promises to finish, blocking the calling thread.

    Args:
        recursively: If True, wait for all children of all children, and so on.
    """
    return get_current_context().await_children_sync(recursively=recursively)


class PromisingContext:
    _current = ContextVar["PromisingContext | None"]("PromisingContext._current", default=None)
    _previous_token: contextvars.Token | None

    def __init__(
        self,
        *,
        parent_context: "PromisingContext | Sentinel | None" = INHERIT,
        associated_promise: "Promise[Any] | None" = None,
        start_soon: bool | Sentinel = NOT_SET,
        children_start_soon_by_default: bool | Sentinel = NOT_SET,
        everything_starts_soon_by_default: bool | Sentinel = INHERIT,
    ) -> None:
        self._previous_token = None
        self._associated_promise = associated_promise

        if parent_context is INHERIT:
            self._parent_context = self.get_current(raise_if_none=False)
        elif parent_context is None or isinstance(parent_context, PromisingContext):
            self._parent_context = parent_context
        else:
            raise ValueError(
                "`parent_context` must be either INHERIT, another PromisingContext or None, "
                f"but `{type(parent_context)}` was given instead"
            )

        self._resolve_everything_starts_soon_by_default(everything_starts_soon_by_default)
        self._resolve_start_soon(start_soon)
        self._resolve_children_start_soon_by_default(children_start_soon_by_default)

        self._child_contexts = WeakSet[PromisingContext]()
        if self._parent_context is not None:
            self._parent_context._child_contexts.add(self)

        self._parent_promise = None
        # Find the nearest parent Promise. (If any of the contexts in the
        # hierarchy were created by the user directly, they will not have an
        # associated Promise, hence we need "find" a parent Promise.)
        ctx = self
        while (ctx := ctx._parent_context) is not None:
            if ctx._associated_promise is None:
                continue
            self._parent_promise = ctx._associated_promise

    @classmethod
    def get_current_context(cls, *, raise_if_none: bool = True) -> "PromisingContext | None":
        """
        Get the currently active PromisingContext from context variables.

        Args:
            raise_if_none: If True, raises an exception when no active
                PromisingContext is found.

        Returns:
            The currently active PromisingContext, or None if none exists and
            raise_if_none is False.

        Raises:
            NoCurrentContextError: If no active PromisingContext exists and
                raise_if_none is True.
        """
        current = cls._current.get()
        if raise_if_none and current is None:
            raise ContextNotFoundError("No active PromisingContext found")
        return current

    def get_parent_context(self, *, raise_if_none: bool = True) -> "PromisingContext | None":
        """
        Get the parent PromisingContext of this PromisingContext.

        Args:
            raise_if_none: If True, raises an exception when no parent exists.

        Returns:
            The parent PromisingContext, or None if no parent exists and raise_if_none
            is False.

        Raises:
            ContextNotFoundError: If no parent exists and raise_if_none is
                True.
        """
        if raise_if_none and self._parent is None:
            raise ContextNotFoundError("This PromisingContext does not have a parent")
        return self._parent

    def get_parent_promise(self, *, raise_if_none: bool = True) -> "Promise[Any] | None":
        """
        Get the parent Promise of this PromisingContext.
        """
        if raise_if_none and self._parent_promise is None:
            raise PromiseNotFoundError("This PromisingContext does not have a parent Promise")
        return self._parent_promise

    def _assert_no_sync_usage_deadlock(self, message: str) -> None:
        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None

        if running_loop is self._loop:
            raise SyncUsageError(message)

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
