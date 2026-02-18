class BasePromisingError(Exception):
    pass


class PromiseError(BasePromisingError):
    pass


class BasePromisingConfigError(BasePromisingError):
    pass


class NoCurrentPromiseError(PromiseError):
    pass


class NoParentPromiseError(PromiseError):
    pass


class NoParentConfigError(BasePromisingConfigError):
    pass
