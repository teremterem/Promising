class BasePromisingError(Exception):
    pass


class PromiseError(BasePromisingError):
    # TODO This name can be easily confused with BasePromisingError name above
    pass


class BasePromiseConfigError(BasePromisingError):
    pass


class NoCurrentPromiseError(PromiseError):
    pass


class NoParentPromiseError(PromiseError):
    pass


class NoParentConfigError(BasePromiseConfigError):
    pass
