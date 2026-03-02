from promising.errors import (
    BasePromisingError,
    ContextAlreadyActiveError,
    ContextNotActiveError,
    ContextNotFoundError,
    PromiseNotFoundError,
    SyncUsageError,
)
from promising.promise import Promise, get_active_promise
from promising.promising_context import (
    PromisingContext,
    await_children,
    await_children_sync,
    context,
    get_active_context,
)
from promising.promising_function import PromisingFunction, function
from promising.sentinels import GLOBAL_DEFAULT, INHERIT, NOT_SET, Sentinel

START_SOON_DEFAULT = True


def should_start_soon_by_default() -> bool:
    """
    We don't want to import `START_SOON_DEFAULT` from this
    module directly, because we want to allow users to override the default
    value if they want. Importing `START_SOON_DEFAULT` directly
    would copy the concrete value into the other modules' namespaces at the
    time of import.
    """
    return START_SOON_DEFAULT


__all__ = [
    "BasePromisingError",
    "START_SOON_DEFAULT",
    "GLOBAL_DEFAULT",
    "INHERIT",
    "NOT_SET",
    "ContextAlreadyActiveError",
    "ContextNotActiveError",
    "ContextNotFoundError",
    "context",
    "PromiseNotFoundError",
    "Promise",
    "PromisingContext",
    "PromisingFunction",
    "SyncUsageError",
    "Sentinel",
    "await_children",
    "await_children_sync",
    "function",
    "get_active_context",
    "get_active_promise",
    "should_start_soon_by_default",
]
