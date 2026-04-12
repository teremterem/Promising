"""Tests for Promise(prefilled_result=<awaitable>) — the context must stay
open long enough for set_result to wrap the awaitable in a child Promise."""

import asyncio

import pytest

from promising import Promise


async def test_prefilled_coroutine_result_async() -> None:
    """Promise(prefilled_result=<coroutine>) should resolve to the coroutine's
    return value. The parent context must not close before set_result wraps
    the awaitable into a child Promise."""

    async def my_coro() -> str:
        return "from coroutine"

    promise: Promise[str] = Promise(prefilled_result=my_coro())

    assert await promise == "from coroutine"


async def test_prefilled_coroutine_result_sync() -> None:
    """Same as above but exercising the sync() path."""

    async def my_coro() -> str:
        return "from coroutine sync"

    promise: Promise[str] = Promise(prefilled_result=my_coro())
    loop = asyncio.get_running_loop()

    assert await loop.run_in_executor(None, promise.sync) == "from coroutine sync"


async def test_prefilled_coroutine_result_unpack_once() -> None:
    """unpack_once should return the child Promise wrapping the coroutine."""

    async def my_coro() -> str:
        return "from coroutine unpack"

    promise: Promise[str] = Promise(prefilled_result=my_coro())

    result = await promise.unpack_once()
    # set_result wraps non-Promise awaitables → child Promise
    assert isinstance(result, Promise)
    assert await result == "from coroutine unpack"


async def test_prefilled_coroutine_result_with_explicit_parent() -> None:
    """prefilled_result=<coroutine> should also work when an explicit parent
    is provided."""

    async def root_coro() -> str:
        async def inner_coro() -> str:
            return "inner value"

        parent_promise = Promise.get_active_promise()
        child = Promise(prefilled_result=inner_coro(), parent=parent_promise)
        return await child

    promise: Promise[str] = Promise(root_coro())
    assert await promise == "inner value"


@pytest.mark.parametrize("start_soon", [True, False])
async def test_prefilled_coroutine_result_start_soon(*, start_soon: bool) -> None:
    """prefilled_result=<coroutine> works regardless of start_soon setting."""

    async def my_coro() -> str:
        return "start_soon_value"

    promise: Promise[str] = Promise(prefilled_result=my_coro(), start_soon=start_soon)

    assert await promise == "start_soon_value"
