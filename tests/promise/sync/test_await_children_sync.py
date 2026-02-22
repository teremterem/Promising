"""Tests for Promise.await_children_sync()."""

import asyncio
from typing import NoReturn

import pytest

import promising
from promising.errors import SyncPromiseUsageError
from promising.promise import Promise

# ── Basic functionality ─────────────────────────────────────────


async def test_await_children_sync_waits_for_all() -> None:
    """
    await_children_sync() blocks until every pending
    child Promise has resolved and returns their results.
    """
    execution_order: list[str] = []

    async def child_coro(label: str) -> str:
        await asyncio.sleep(0.1)
        execution_order.append(label)
        return label

    async def parent_coro() -> None:
        current = promising.get_current_promise()
        Promise(child_coro("a"), start_soon=True)
        Promise(child_coro("b"), start_soon=True)
        # Yield to let children register
        await asyncio.sleep(0)  # TODO TODO TODO Why do we need this ?
        # Now switch to sync to wait for them
        await asyncio.get_running_loop().run_in_executor(None, current.await_children_sync)

    parent = Promise(parent_coro(), start_soon=True)
    await parent
    assert sorted(execution_order) == ["a", "b"]


async def test_await_children_sync_no_pending() -> None:
    """
    When there are no pending children, returns an empty
    list immediately.
    """

    async def parent_coro() -> list:
        current = promising.get_current_promise()
        return await asyncio.get_running_loop().run_in_executor(None, current.await_children_sync)

    parent = Promise(parent_coro(), start_soon=True)
    result = await parent
    assert result == []


async def test_await_children_sync_starts_lazy_children() -> None:
    """
    Children created with start_soon=False are started by
    await_children_sync() and waited for.
    """

    async def child_coro() -> str:
        return "lazy child done"

    async def parent_coro() -> list:
        current = promising.get_current_promise()
        Promise(child_coro(), start_soon=False)
        return await asyncio.get_running_loop().run_in_executor(None, current.await_children_sync)

    parent = Promise(parent_coro(), start_soon=True)
    results = await parent
    assert results == ["lazy child done"]


# ── Exception handling ──────────────────────────────────────────


async def test_await_children_sync_raises_child_exception() -> None:
    """
    With return_exceptions=False (default), an exception
    from a child is raised.
    """

    async def failing() -> NoReturn:
        await asyncio.sleep(0.1)
        raise ValueError("child boom")

    async def parent_coro() -> None:
        current = promising.get_current_promise()
        Promise(failing(), start_soon=True)
        await asyncio.get_running_loop().run_in_executor(None, current.await_children_sync)

    parent = Promise(parent_coro(), start_soon=True)
    with pytest.raises(ValueError, match="child boom"):
        await parent


async def test_await_children_sync_return_exceptions() -> None:
    """
    With return_exceptions=True, child exceptions appear
    in the results list instead of being raised.
    """

    async def ok() -> str:
        await asyncio.sleep(0.1)
        return "ok"

    async def failing() -> NoReturn:
        await asyncio.sleep(0.1)
        raise RuntimeError("fail")

    async def parent_coro() -> list:
        current = promising.get_current_promise()
        Promise(ok(), start_soon=True)
        Promise(failing(), start_soon=True)
        return await asyncio.get_running_loop().run_in_executor(
            None,
            lambda: current.await_children_sync(return_exceptions=True),
        )

    parent = Promise(parent_coro(), start_soon=True)
    results = await parent
    assert len(results) == 2
    values = [r for r in results if not isinstance(r, BaseException)]
    exceptions = [r for r in results if isinstance(r, BaseException)]
    assert values == ["ok"]
    assert len(exceptions) == 1
    assert isinstance(exceptions[0], RuntimeError)
    assert str(exceptions[0]) == "fail"


# ── Event loop thread guard ─────────────────────────────────────


async def test_await_children_sync_raises_on_event_loop_thread() -> None:
    """
    await_children_sync() raises SyncPromiseUsageError when
    called from the event loop thread.
    """

    async def coro() -> str:
        return "unreachable"

    parent = Promise(coro(), start_soon=False)

    with pytest.raises(SyncPromiseUsageError, match="deadlock"):
        parent.await_children_sync()

    await parent


# ── Integration with sync promising functions ────────────────────


async def test_await_children_sync_in_sync_promising_func() -> None:
    """
    Primary use case: a sync promising function spawns
    async children and waits for them via
    await_children_sync().
    """

    @promising.function
    async def async_child(value: int) -> int:
        await asyncio.sleep(0.1)
        return value * 10

    @promising.function
    def sync_parent() -> list:
        current = promising.get_current_promise()
        async_child(1, start_soon=False)
        async_child(2, start_soon=False)
        async_child(3, start_soon=False)
        return current.await_children_sync()

    results = await sync_parent()
    assert sorted(results) == [10, 20, 30]


async def test_await_children_sync_exception_in_sync_promising_func() -> None:
    """
    Exception from a child propagates through
    await_children_sync() inside a sync promising
    function.
    """

    @promising.function
    async def failing_child() -> NoReturn:
        raise RuntimeError("child error")

    @promising.function
    def sync_parent() -> list:
        current = promising.get_current_promise()
        failing_child(start_soon=False)
        return current.await_children_sync()

    with pytest.raises(RuntimeError, match="child error"):
        await sync_parent()
