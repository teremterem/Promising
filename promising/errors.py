class BasePromisingError(Exception):
    pass


class NoCurrentPromiseError(BasePromisingError):
    pass


class NoParentPromiseError(BasePromisingError):
    pass
