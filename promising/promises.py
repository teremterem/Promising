from asyncio import AbstractEventLoop
import asyncio
from contextvars import ContextVar
import itertools
from typing import Optional


_promise_name_counter = itertools.count(1).__next__
# TODO Also maintain UUIDs for promises ?


def get_promising_context() -> "PromisingContext":
    return PromisingContext.get_current()


class PromisingContext:

    _current: ContextVar[Optional["PromisingContext"]] = ContextVar("PromisingContext._current", default=None)

    def __init__(self, *, loop: Optional[AbstractEventLoop] = None, name: Optional[str] = None) -> None:
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
        self._previous_ctx_token = None

    @classmethod
    def get_current(cls) -> Optional["PromisingContext"]:
        return cls._current.get()

    def get_loop(self) -> asyncio.AbstractEventLoop:
        return self._loop

    def get_name(self) -> str:
        return self._name

    def activate(self) -> "PromisingContext":
        # TODO Raise an error if this context is already active (token attribute is not None)
        self._previous_ctx_token = self._current.set(self)
        return self

    async def afinalize(self) -> None:
        # TODO Raise an error if this context is not active (token attribute is None)
        self._current.reset(self._previous_ctx_token)

    async def __aenter__(self) -> "PromisingContext":
        return self.activate()

    async def __aexit__(self, exc_type, exc_value, traceback) -> None:
        await self.afinalize()


_global_promising_context: PromisingContext = PromisingContext()
_global_promising_context.activate()
# TODO How and when to deactivate the global promising context ? (Should we care about it at all ?)
