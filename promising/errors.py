class BasePromisingError(Exception):
    pass


class BasePromiseError(BasePromisingError):
    # TODO This name can be easily confused with BasePromisingError name above
    pass


class BasePromiseConfigError(BasePromisingError):
    pass


class NoCurrentPromiseError(BasePromiseError):
    pass


class NoParentPromiseError(BasePromiseError):
    pass


class NoParentConfigError(BasePromiseConfigError):
    pass
