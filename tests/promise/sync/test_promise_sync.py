"""Tests for Promise.sync() — the synchronous alternative to await."""

import asyncio
from typing import NoReturn

import pytest

import promising
from promising.errors import SyncPromiseUsageError
from promising.promise import Promise

# ── Basic functionality ─────────────────────────────────────────


async def test_sync_returns_result_from_thread() -> None:
    """
    sync() called from a worker thread blocks until the
    Promise resolves and returns the result.
    """

    async def coro() -> str:
        return "hello from sync"

    promise = Promise(coro(), start_soon=True)

    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, promise.sync)
    assert result == "hello from sync"


async def test_sync_with_start_soon_false() -> None:
    """
    sync() triggers execution of a Promise that was created
    with start_soon=False (the coroutine hasn't started yet).
    """

    async def coro() -> str:
        return "lazy start"

    promise = Promise(coro(), start_soon=False)

    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, promise.sync)
    assert result == "lazy start"


async def test_sync_with_prefilled_promise() -> None:
    """
    sync() works with a prefilled Promise (immediate result).
    """
    promise = Promise(prefill_result=42)

    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, promise.sync)
    assert result == 42


async def test_sync_propagates_exception() -> None:
    """
    sync() propagates exceptions raised during Promise
    execution.
    """

    async def failing() -> NoReturn:
        raise ValueError("sync error")

    promise = Promise(failing(), start_soon=True)

    loop = asyncio.get_running_loop()
    with pytest.raises(ValueError, match="sync error"):
        await loop.run_in_executor(None, promise.sync)


async def test_sync_propagates_prefilled_exception() -> None:
    """
    sync() propagates a prefilled exception.
    """
    promise = Promise(prefill_exception=ValueError("prefilled"))

    loop = asyncio.get_running_loop()
    with pytest.raises(ValueError, match="prefilled"):
        await loop.run_in_executor(None, promise.sync)


# ── Event loop thread guard ─────────────────────────────────────


async def test_sync_raises_on_event_loop_thread() -> None:
    """
    sync() raises SyncPromiseUsageError when called from the event
    loop thread, because it would deadlock.
    """

    async def coro() -> str:
        return "unreachable"

    promise = Promise(coro(), start_soon=False)

    with pytest.raises(SyncPromiseUsageError, match="deadlock"):
        promise.sync()

    # Clean up — await the promise so asyncio doesn't warn
    await promise


async def test_sync_raises_on_event_loop_thread_prefilled() -> None:
    """
    sync() raises even for a prefilled Promise when called
    from the event loop thread — the guard is unconditional.
    """
    promise = Promise(prefill_result="already done")

    with pytest.raises(SyncPromiseUsageError, match="deadlock"):
        promise.sync()


# ── Integration with sync promising functions ────────────────────


async def test_sync_inside_sync_promising_function() -> None:
    """
    The primary use case: a sync promising function uses
    sync() to consume the result of another promise.
    """

    @promising.function
    async def async_greet(name: str) -> str:
        return f"hello, {name}"

    @promising.function
    def sync_caller() -> str:
        greeting_promise = async_greet("world", start_soon=False)
        return greeting_promise.sync()

    result = await sync_caller()
    assert result == "hello, world"


async def test_sync_exception_inside_sync_promising_function() -> None:
    """
    Exceptions from sync() propagate through the sync
    promising function's promise.
    """

    @promising.function
    async def failing_child() -> NoReturn:
        raise RuntimeError("child failed")

    @promising.function
    def sync_caller() -> str:
        return failing_child(start_soon=False).sync()

    with pytest.raises(RuntimeError, match="child failed"):
        await sync_caller()
