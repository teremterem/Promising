class Sentinel:
    def __bool__(self) -> bool:
        # TODO Should any other magic methods be defined like this to prevent reliance on Sentinel's truthiness ?
        raise RuntimeError("Sentinels should not be used in boolean expressions.")


NO_VALUE = Sentinel()
