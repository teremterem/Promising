class BasePromisingError(Exception):
    pass


class DecorationError(BasePromisingError):
    pass


class PromiseNotFoundError(BasePromisingError):
    pass


class SentinelUsageError(BasePromisingError):
    pass


class SyncUsageError(BasePromisingError):
    pass


# Context errors


class BaseContextError(BasePromisingError):
    pass


class ContextAlreadyActiveError(BaseContextError):
    pass


class ContextNotActiveError(BaseContextError):
    pass


class ContextNotFoundError(BaseContextError):
    pass


# Event loop errors


class BaseEventLoopError(BasePromisingError):
    pass


class EventLoopMismatchError(BaseEventLoopError):
    pass


class NoEventLoopError(BaseEventLoopError):
    pass
