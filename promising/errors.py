class BasePromisingError(Exception):
    pass


class ContextNotFoundError(BasePromisingError):
    pass


class PromiseNotFoundError(BasePromisingError):
    pass


class SyncUsageError(BasePromisingError):
    pass
