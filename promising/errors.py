class BasePromisingError(Exception):
    pass


class PromiseError(BasePromisingError):
    pass


class BasePromiseConfigError(BasePromisingError):
    pass


class NoCurrentPromiseError(PromiseError):
    pass


class NoParentPromiseError(PromiseError):
    pass


class NoParentConfigError(BasePromiseConfigError):
    pass
