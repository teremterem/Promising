import asyncio
import contextvars
import itertools
from asyncio import AbstractEventLoop
from contextvars import ContextVar
from typing import Optional
import weakref

from promising.errors import (
    ContextAlreadyActiveError,
    ContextNotActiveError,
    NoCurrentContextError,
)


_promise_name_counter = itertools.count(1).__next__
# TODO Also maintain UUIDs for promises ?


def get_promising_context() -> "PromisingContext":
    return PromisingContext.get_current()


# TODO Merge this class with the Promise itself that extends asyncio.Future
class PromisingContext:

    _current: ContextVar[Optional["PromisingContext"]] = ContextVar("PromisingContext._current", default=None)

    def __init__(self, *, loop: Optional[AbstractEventLoop] = None, name: Optional[str] = None) -> None:
        # TODO Introduce PromisingConfig (should support "chaining" with deeper-level configs overriding
        #  higher-level ones) ?

        self._parent: Optional["PromisingContext"] = self.get_current()
        self._children: set[PromisingContext] = weakref.WeakSet()  # TODO TODO TODO
        # TODO It should be set at the level of the child Promise, whether it should be waited by parent or not

        if loop is None:
            if self._parent is not None:
                self._loop = self._parent.get_loop()
            else:
                self._loop = asyncio.get_event_loop()
        else:
            # TODO Should it be disallowed to set an event loop that is different from the outer one ?
            self._loop = loop

        if name is None:
            self._name = f"PromisingContext-{_promise_name_counter()}"
        else:
            self._name = name

        self._previous_ctx_token: Optional[contextvars.Token] = None

    @classmethod
    def get_current(cls) -> "PromisingContext":
        """
        Get the current PromisingContext.

        Returns:
            The current PromisingContext instance.

        Raises:
            NoCurrentContextError: If no current context exists.
        """
        current = cls._current.get()
        if current is None:
            raise NoCurrentContextError("No current PromisingContext is active")
        return current

    def get_parent(self) -> Optional["PromisingContext"]:
        return self._parent

    def get_loop(self) -> asyncio.AbstractEventLoop:
        return self._loop

    def get_name(self) -> str:
        return self._name

    def is_active(self) -> bool:
        return self._previous_ctx_token is not None

    def activate(self) -> "PromisingContext":
        """
        Activate this PromisingContext.

        Returns:
            This PromisingContext instance.

        Raises:
            ContextAlreadyActiveError: If this context is already active.
        """
        if self._previous_ctx_token is not None:
            raise ContextAlreadyActiveError(f"PromisingContext '{self._name}' is already active")
        self._previous_ctx_token = self._current.set(self)
        return self

    async def afinalize(self) -> None:
        """
        Finalize this PromisingContext and restore the previous context.

        Raises:
            ContextNotActiveError: If this context is not currently active.
        """
        if self._previous_ctx_token is None:
            raise ContextNotActiveError(f"PromisingContext '{self._name}' is not currently active")
        self._current.reset(self._previous_ctx_token)
        self._previous_ctx_token = None

    async def __aenter__(self) -> "PromisingContext":
        return self.activate()

    async def __aexit__(self, exc_type, exc_value, traceback) -> None:
        # TODO How to treat errors ?
        await self.afinalize()

    # TODO TODO TODO Various methods to run stuff directly like in MiniAgents ?
