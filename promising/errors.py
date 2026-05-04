import asyncio
import concurrent.futures


class PromisingError(Exception):
    """
    A base class for all promising errors.
    """


class DecorationError(PromisingError):
    pass


class PromiseNotFoundError(PromisingError):
    pass


class PromiseNotDoneError(
    PromisingError,
    asyncio.InvalidStateError,
    concurrent.futures.InvalidStateError,
):
    """
    Raised when a Promise is queried for a result/exception before it is done.
    """


class PromiseNotUnpackedError(
    PromisingError,
    asyncio.InvalidStateError,
    concurrent.futures.InvalidStateError,
):
    """
    Raised when a Promise's intermediate_promise is queried before the first
    unpacking.
    """


class SentinelUsageError(PromisingError):
    pass


class SyncUsageError(PromisingError):
    pass


# Context errors


class ContextError(PromisingError):
    """
    A base class for all context-related errors.
    """


class ContextAlreadyActiveError(ContextError):
    pass


class ContextAlreadyClosedError(ContextError):
    pass


class ContextNotActiveError(ContextError):
    pass


class ContextNotFoundError(ContextError):
    pass


# Event loop errors


class EventLoopError(PromisingError):
    """
    A base class for all event loop-related errors.
    """


class EventLoopMismatchError(EventLoopError, ValueError):
    pass


class NoRunningEventLoopError(EventLoopError, RuntimeError):
    pass
