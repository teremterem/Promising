class BasePromisingError(Exception):
    pass


class ContextAlreadyActiveError(BasePromisingError):
    pass


class ContextNotActiveError(BasePromisingError):
    pass


class ContextNotFoundError(BasePromisingError):
    pass


class ContextUsageError(BasePromisingError):
    pass


class DecorationError(BasePromisingError):
    pass


class EventLoopMismatchError(BasePromisingError):
    pass


class PromiseNotFoundError(BasePromisingError):
    pass


class SyncUsageError(BasePromisingError):
    pass
