class Sentinel:
    def __bool__(self) -> bool:
        # TODO Should any other magic methods be defined like this to prevent
        #  reliance on Sentinel's truthiness ? We need to come up with a list
        #  of such magic methods if we want to take care of this TODO.
        raise RuntimeError("Sentinels should not be used in boolean expressions.")


NOT_SET = Sentinel()
INHERIT = Sentinel()
