import os
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
    PromiseInvalidStateError,
    PromiseNotDoneError,
    PromiseNotFoundError,
    PromiseNotUnpackedError,
    PromisingError,
    SentinelUsageError,
    SyncUsageError,
    install_promising_tracebacks,
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

# TODO [TRACES] Is it ok that we are not using Pathlib here ?
# TODO [TRACES] A unit test is needed to check that the path is correct
_PACKAGE_ABS_PATH: str = os.path.dirname(os.path.abspath(__file__)) + os.sep


class Defaults:
    """
    Default values for the library's behavior. We use a class rather than
    module-level constants because ``from promising import SOME_CONSTANT``
    would copy the value into the importing module's namespace at import time,
    making it impossible to override the default later. With a class,
    ``Defaults.X`` always reads the current value from a single source.

    Attributes:
        START_SOON: Global default for eager execution. When ``True`` (the
            default), Promises start running as soon as they are created;
            set to ``False`` for lazy execution. Used as the fallback at
            the root of the parent chain by ``start_soon_default``.
        COLLAPSE_TRACEBACKS: Global default for whether tracebacks of
            exceptions that propagate out of a Promise (or its subtree)
            are rendered with the promising-internal frames collapsed
            (``True``, the default) or in full (``False``, useful when
            debugging the library itself). Consumed by the
            ``sys.excepthook`` / ``threading.excepthook`` overrides
            installed by ``install_promising_tracebacks()``.
        PROMISING_THREAD_POOL: The global ``ThreadPoolExecutor`` used by
            sync promising functions when ``thread_pool`` resolves to
            ``PROMISING_DEFAULT``.
        QUALNAMES_IN_NAMESPACES: When ``True`` (the default), auto-derived
            namespaces include the fully qualified name
            (``module::qualname``). When ``False``, only the short
            ``__name__`` is used.
    """

    # TODO Make these configurable via environment variables

    START_SOON = True
    COLLAPSE_TRACEBACKS = True
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
    "PromiseInvalidStateError",
    "PromiseNotDoneError",
    "PromiseNotFoundError",
    "PromiseNotUnpackedError",
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
    "install_promising_tracebacks",
    "print_trace",
    "wrap_awaitable",
]
