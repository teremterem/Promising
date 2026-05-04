from concurrent.futures import ThreadPoolExecutor

from promising.errors import (
    ContextAlreadyActiveError,
    ContextAlreadyClosedError,
    ContextError,
    ContextNotActiveError,
    ContextNotFoundError,
    DecorationError,
    EventLoopError,
    EventLoopMismatchError,
    NoRunningEventLoopError,
    PromiseNotFoundError,
    PromisingError,
    SentinelUsageError,
    SyncUsageError,
)
from promising.promise import Promise, get_active_promise, wrap_awaitable
from promising.promising_context import (
    PromisingContext,
    await_children,
    await_children_sync,
    collect_unsettled_children,
    context,
    format_trace,
    get_active_context,
    get_trace,
    print_trace,
)
from promising.promising_function import PromisingFunction, function
from promising.sentinels import (
    ASYNCIO_DEFAULT,
    AUTO,
    INHERIT,
    PROMISING_DEFAULT,
    UNCHANGED,
    WHOLE_SUBTREE,
    Sentinel,
)


class Defaults:
    """
    Default values for the library's behavior. We use a class rather than
    module-level constants because ``from promising import SOME_CONSTANT``
    would copy the value into the importing module's namespace at import time,
    making it impossible to override the default later. With a class,
    ``Defaults.X`` always reads the current value from a single source.
    """

    START_SOON = True
    PROMISING_THREAD_POOL = ThreadPoolExecutor(max_workers=128)
    # TODO Raise a disableable error when synchronous function call depth
    #  reaches the maximum number of workers in the thread pool, to prevent
    #  potential deadlocks (The deepest synchronous function might be waiting
    #  for an even deeper promise, which, in turn, cannot be scheduled because
    #  the thread pool is already fully occupied exactly with the promise chain
    #  that is awaiting)
    # TODO Introduce a "promise factory" setting, both - as a global default
    #  and as an inheritable setting ?
    QUALNAMES_IN_NAMESPACES = True


__all__ = [
    "ASYNCIO_DEFAULT",
    "AUTO",
    "ContextAlreadyActiveError",
    "ContextAlreadyClosedError",
    "ContextError",
    "ContextNotActiveError",
    "ContextNotFoundError",
    "DecorationError",
    "Defaults",
    "EventLoopError",
    "EventLoopMismatchError",
    "INHERIT",
    "NoRunningEventLoopError",
    "PROMISING_DEFAULT",
    "Promise",
    "PromiseNotFoundError",
    "PromisingContext",
    "PromisingError",
    "PromisingFunction",
    "Sentinel",
    "SentinelUsageError",
    "SyncUsageError",
    "UNCHANGED",
    "WHOLE_SUBTREE",
    "await_children",
    "await_children_sync",
    "collect_unsettled_children",
    "context",
    "format_trace",
    "function",
    "get_active_context",
    "get_active_promise",
    "get_trace",
    "print_trace",
    "wrap_awaitable",
]
