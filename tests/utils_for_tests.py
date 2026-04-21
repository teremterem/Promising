import re
import threading
from collections.abc import Awaitable, Callable, Generator
from typing import Any

import promising


def normalize_object_repr(s: str) -> str:
    """
    Replace hex addresses and digit sequences with X for stable comparisons.
    """
    assert isinstance(s, str)
    s = re.sub(r"\d+", "999", s)
    # After the previous sub, hex addresses like "0x7f3a" have become
    # "999x999f999a". This pattern matches "999x" followed by any mix of
    # digits-turned-999 and hex letters, normalizing to "0xfff".
    s = re.sub(r"999x[9a-f]+", "0xfff", s)
    return s


def run_in_thread(fn: Callable[[], None], timeout: float | None = None) -> None:
    """Run *fn* in a dedicated thread, re-raising any error.

    Useful for tests that call .run() (which needs asyncio.run()) without
    interfering with the pytest-asyncio event loop.
    """
    error = None

    def _target():
        nonlocal error
        try:
            fn()
        except BaseException as exc:
            error = exc

    t = threading.Thread(target=_target, daemon=True)
    t.start()
    t.join(timeout=timeout)
    if timeout is not None:
        assert not t.is_alive(), "Thread did not finish in time"

    if error is not None:
        raise error


def collect_parent_contexts(ctx: promising.PromisingContext) -> list[promising.PromisingContext]:
    result = []
    while (parent := ctx.get_parent_context(raise_if_none=False)) is not None:
        result.append(parent)
        ctx = parent
    return result


def collect_parent_promises(ctx: promising.PromisingContext) -> list[promising.Promise[Any]]:
    result = []
    while (parent := ctx.get_parent_promise(raise_if_none=False)) is not None:
        result.append(parent)
        ctx = parent
    return result


class NonPromiseAwaitableContext(promising.PromisingContext):
    def __init__(
        self,
        coro: Awaitable[Any],
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._coro = coro

    def __await__(self) -> Generator[Any, None, Any]:
        if not self.done():
            # Here, a race condition is possible with multiple awaiters, but
            # for the purposes of testing, we will ignore such a possibility
            yield from self._fulfill().__await__()
        return (yield from super().__await__())

    async def _fulfill(self) -> None:
        try:
            self.set_result(await self._coro)
        except BaseException as exc:
            self.set_exception(exc)
