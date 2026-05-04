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
        raise SentinelUsageError(
            f"Sentinel {self._name} cannot be cast to boolean. "
            f"Use `is` / `is not` identity comparisons instead (e.g. `value is {self._name}`)."
        )


ASYNCIO_DEFAULT = Sentinel("ASYNCIO_DEFAULT")
AUTO = Sentinel("AUTO")
INHERIT = Sentinel("INHERIT")
PROMISING_DEFAULT = Sentinel("PROMISING_DEFAULT")
WHOLE_SUBTREE = Sentinel("WHOLE_SUBTREE")
UNCHANGED = Sentinel("UNCHANGED")

_PENDING = Sentinel("_PENDING")
_CANCELLED_BEFORE_UNPACKED_ONCE = Sentinel("_CANCELLED_BEFORE_UNPACKED_ONCE")
_UNPACKED_ONCE = Sentinel("_UNPACKED_ONCE")
_CANCELLED_AFTER_UNPACKED_ONCE = Sentinel("_CANCELLED_AFTER_UNPACKED_ONCE")
_FINISHED = Sentinel("_FINISHED")
