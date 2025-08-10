class BasePromisingError(Exception):
    pass


class BasePromiseError(BasePromisingError):
    pass


class BasePromiseConfigError(BasePromisingError):
    pass


class NoCurrentPromiseError(BasePromiseError):
    pass


class NoParentPromiseError(BasePromiseError):
    pass


class NoParentConfigError(BasePromiseConfigError):
    pass
