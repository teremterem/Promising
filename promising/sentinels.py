class Sentinel:
    """
    A marker object used as a default parameter value to distinguish
    "not provided" from any real value (including ``None``).

    Sentinels intentionally raise ``RuntimeError`` when used in boolean
    expressions to prevent accidental truthiness checks — use ``is`` /
    ``is not`` identity comparisons instead.
    """

    def __bool__(self) -> bool:
        # TODO Should any other magic methods be defined like this to prevent
        #  reliance on Sentinel's truthiness ? We need to come up with a list
        #  of such magic methods.
        raise RuntimeError("Sentinels should not be used in boolean expressions.")


ASYNCIO_DEFAULT = Sentinel()
GLOBAL_DEFAULT = Sentinel()
INHERIT = Sentinel()
NOT_SET = Sentinel()
