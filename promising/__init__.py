from concurrent.futures import ThreadPoolExecutor

from promising.errors import (
    BasePromisingError,
    ContextAlreadyActiveError,
    ContextNotActiveError,
    ContextNotFoundError,
    ContextUsageError,
    DecorationError,
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


class Defaults:
    """
    Default values for the library's behavior. We use a class rather than
    module-level constants because ``from promising import SOME_CONSTANT``
    would copy the value into the importing module's namespace at import time,
    making it impossible to override the default later. With a class,
    ``Defaults.X`` always reads the current value from a single source.
    """

    START_SOON = True
    # TODO TODO TODO Allow overriding this executor in local promise configurations
    SYNC_THREAD_POOL = ThreadPoolExecutor(max_workers=128)
    # TODO What to do about potential deadlocks if recursive sync promises use up
    #  the executor's thread pool (when each such promise waits for its children to
    #  complete) ? Is setting `max_workers` to 128 just a provisional workaround,
    #  and we need our own mechanism ? Or is it enough to issue a warning / throw
    #  an error when the number of nested sync function calls approaches this
    #  number ?


__all__ = [
    "BasePromisingError",
    "Defaults",
    "GLOBAL_DEFAULT",
    "INHERIT",
    "NOT_SET",
    "ContextAlreadyActiveError",
    "ContextNotActiveError",
    "ContextNotFoundError",
    "ContextUsageError",
    "DecorationError",
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
]
