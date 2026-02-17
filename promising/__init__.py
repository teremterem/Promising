from promising.promise import Promise, get_current_promise
from promising.promising_function import PromisingFunction, function
from promising.sentinels import INHERIT, NOT_SET, Sentinel

START_SOON_BY_DEFAULT = True


def should_start_soon_by_default() -> bool:
    """
    We don't want to import `START_SOON_BY_DEFAULT` from this module directly,
    because we want to allow users to override the default value if they want.
    Importing `START_SOON_BY_DEFAULT` directly would copy the concrete value
    into the other modules' namespaces at the time of import.
    """
    return START_SOON_BY_DEFAULT


__all__ = [
    "INHERIT",
    "NOT_SET",
    "Promise",
    "PromisingFunction",
    "START_SOON_BY_DEFAULT",
    "Sentinel",
    "function",
    "get_current_promise",
    "should_start_soon_by_default",
]
