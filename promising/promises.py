import asyncio


# TODO There should be a global default PromisingContext instance


class PromisingContext:
    def __init__(self, name: str | None = None, event_loop: asyncio.AbstractEventLoop | None = None) -> None:
        self.name = name
        if event_loop is None:
            # TODO Get event loop from the outer PromisingContext when possible
            self.event_loop = asyncio.get_event_loop()
        else:
            # TODO Should it be disallowed to set an event loop that is different from the outer one ?
            self.event_loop = event_loop
        # TODO Introduce PromisingConfig (should support "chaining" with deeper-level configs overriding higher-level
        #  ones)

    def __enter__(self) -> None:
        # TODO
        pass

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        # TODO
        pass
