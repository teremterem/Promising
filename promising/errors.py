class PromisingError(Exception):
    """A base class for all promising errors."""


class DecorationError(PromisingError):
    pass


class PromiseNotFoundError(PromisingError):
    pass


class SentinelUsageError(PromisingError):
    pass


class SyncUsageError(PromisingError):
    pass


# Context errors


class ContextError(PromisingError):
    """A base class for all context-related errors."""


class ContextAlreadyActiveError(ContextError):
    pass


class ContextNotActiveError(ContextError):
    pass


class ContextNotFoundError(ContextError):
    pass


# Event loop errors


class EventLoopError(PromisingError):
    """A base class for all event loop-related errors."""


class EventLoopMismatchError(EventLoopError):
    pass


class NoEventLoopError(EventLoopError):
    pass
