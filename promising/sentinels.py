class Sentinel:
    def __bool__(self) -> bool:
        # TODO Should any other magic methods be defined like this to prevent
        #  reliance on Sentinel's truthiness ? We need to come up with a list
        #  of such magic methods if we want to take care of this TODO.
        # TODO Extend this class from Sentinel in typing_extensions ?
        raise RuntimeError("Sentinels should not be used in boolean expressions.")


GLOBAL_DEFAULT = Sentinel()
INHERIT = Sentinel()
NOT_SET = Sentinel()
