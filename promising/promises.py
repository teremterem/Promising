from asyncio import AbstractEventLoop, Future, coroutines
from typing import Any, Coroutine, Generic, Optional

from promising.sentinels import NO_VALUE, Sentinel
from promising.typing import T_co


class Promise(Future, Generic[T_co]):
    def __init__(
        self,
        coro: Optional[Coroutine[Any, Any, T_co]] = None,
        *,
        loop: Optional[AbstractEventLoop] = None,
        start_soon: bool | Sentinel = NO_VALUE,  # TODO
        make_parent_wait: bool | Sentinel = NO_VALUE,  # TODO
    ):
        # TODO Get the loop from the "parent" Promise if not explicitly provided ?
        # TODO Disallow passing a loop if it's not the same as the parent's loop ?
        super().__init__(loop=loop)
        if coro is not None and not coroutines.iscoroutine(coro):
            raise TypeError("Promise must be created with a coroutine.")
        self._coro = coro
