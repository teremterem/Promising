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
from promising.promise import Promise, PromiseBackedConcurrentFuture, get_active_promise
from promising.promising_context import (
    PromisingContext,
    await_children,
    await_children_sync,
    collect_remaining_children,
    context,
    format_trace,
    get_active_context,
    get_trace,
    print_trace,
)
from promising.promising_function import PromisingFunction, function
from promising.sentinels import ASYNCIO_DEFAULT, INHERIT, PROMISING_DEFAULT, UNCHANGED, Sentinel


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


__all__ = [
    "ASYNCIO_DEFAULT",
    "BasePromisingError",
    "ContextAlreadyActiveError",
    "ContextNotActiveError",
    "ContextNotFoundError",
    "ContextUsageError",
    "DecorationError",
    "Defaults",
    "INHERIT",
    "PROMISING_DEFAULT",
    "Promise",
    "PromiseNotFoundError",
    "PromiseBackedConcurrentFuture",
    "PromisingContext",
    "PromisingFunction",
    "Sentinel",
    "SyncUsageError",
    "UNCHANGED",
    "await_children",
    "await_children_sync",
    "collect_remaining_children",
    "context",
    "function",
    "get_active_context",
    "get_active_promise",
    "get_trace",
    "format_trace",
    "print_trace",
]
