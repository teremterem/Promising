from promising.errors import (
    BasePromisingError,
    ContextNotFoundError,
    PromiseNotFoundError,
    SyncUsageError,
)
from promising.promise import Promise, get_active_promise
from promising.promising_context import PromisingContext, await_children, await_children_sync, get_active_context
from promising.promising_function import PromisingFunction, function
from promising.sentinels import GLOBAL_DEFAULT, INHERIT, NOT_SET, Sentinel

EVERYTHING_STARTS_SOON_BY_DEFAULT = True


def should_everything_start_soon_by_default() -> bool:
    """
    We don't want to import `EVERYTHING_STARTS_SOON_BY_DEFAULT` from this
    module directly, because we want to allow users to override the default
    value if they want. Importing `EVERYTHING_STARTS_SOON_BY_DEFAULT` directly
    would copy the concrete value into the other modules' namespaces at the
    time of import.
    """
    return EVERYTHING_STARTS_SOON_BY_DEFAULT


__all__ = [
    "BasePromisingError",
    "EVERYTHING_STARTS_SOON_BY_DEFAULT",
    "GLOBAL_DEFAULT",
    "INHERIT",
    "NOT_SET",
    "ContextNotFoundError",
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
    "should_everything_start_soon_by_default",
]
