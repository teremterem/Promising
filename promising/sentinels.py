from promising.errors import SentinelUsageError


class Sentinel:
    """
    A marker object used as a default parameter value to distinguish
    "not provided" from any real value (including ``None``).

    Sentinels intentionally raise ``SentinelUsageError`` when used in
    boolean expressions to prevent accidental truthiness checks — use
    ``is`` / ``is not`` identity comparisons instead.
    """

    def __init__(self, name: str) -> None:
        self._name = name

    def __repr__(self) -> str:
        return self._name

    def __bool__(self) -> bool:
        # TODO Should any other magic methods be defined like this to prevent
        #  reliance on Sentinel's truthiness ? We need to come up with a list
        #  of such magic methods.
        raise SentinelUsageError(
            f"Sentinel {self._name} cannot be cast to boolean. "
            f"Use `is` / `is not` identity comparisons instead (e.g. `value is {self._name}`)."
        )


ASYNCIO_DEFAULT = Sentinel("ASYNCIO_DEFAULT")
INHERIT = Sentinel("INHERIT")
PROMISING_DEFAULT = Sentinel("PROMISING_DEFAULT")
RECURSIVELY = Sentinel("RECURSIVELY")
UNCHANGED = Sentinel("UNCHANGED")
