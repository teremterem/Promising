import asyncio
import itertools
from typing import Optional


_promise_name_counter = itertools.count(1).__next__
# TODO Also maintain UUIDs for promises ?


# TODO There should be a global default PromisingContext instance


class PromisingContext:
    def __init__(self, *, loop: Optional[asyncio.AbstractEventLoop] = None, name: Optional[str] = None) -> None:
        # TODO Introduce PromisingConfig (should support "chaining" with deeper-level configs overriding higher-level
        #  ones)
        if loop is None:
            # TODO Get event loop from the outer PromisingContext when possible
            self._loop = asyncio.get_event_loop()
        else:
            # TODO Should it be disallowed to set an event loop that is different from the outer one ?
            self._loop = loop
        if name is None:
            self._name = f"PromisingContext-{_promise_name_counter()}"
        else:
            self._name = name

    def get_loop(self) -> asyncio.AbstractEventLoop:
        return self._loop

    def get_name(self) -> str:
        return self._name

    def __enter__(self) -> None:
        # TODO
        pass

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        # TODO
        pass
