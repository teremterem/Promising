import asyncio
import time

import pytest

import promising

# ── Basic functionality ─────────────────────────────────────────


@pytest.mark.parametrize("await_children", [True, False])
async def test_await_children_sync(*, await_children: bool) -> None:
    """
    Parametrized over await_children={True, False}.
    With True: the sync parent calls
    await_children_sync(), so the child completes before
    the parent resolves. With False: the parent resolves
    without waiting for the child.
    """
    execution_order: list[str] = []
    child_promise = None

    @promising.function
    async def grandchild_func() -> str:
        await asyncio.sleep(0.2)
        execution_order.append("grandchild_done")
        return "grandchild"

    @promising.function
    async def child_func() -> str:
        grandchild_func()
        await asyncio.sleep(0.1)
        execution_order.append("child_done")
        return "child"

    @promising.function(use_thread_pool=True)
    def parent_func() -> str:
        nonlocal child_promise
        child_promise = child_func()
        execution_order.append("parent_coro_done")
        if await_children:
            promising.await_children_sync()
        return "parent"

    promise = parent_func()
    await promise

    if await_children:
        assert execution_order == [
            "parent_coro_done",
            "child_done",
            "grandchild_done",
        ]
    else:
        assert execution_order == ["parent_coro_done"]
        # Let's await for all the children to complete,
        # so that we don't get any asyncio warnings about
        # coroutines never being awaited
        await promise.await_children()


@pytest.mark.parametrize("recursively", [True, False])
async def test_await_children_sync_recursively(
    *,
    recursively: bool,
) -> None:
    """
    Three levels of nesting:
    sync root -> async child -> async grandchild
      -> async great-grandchild.
    With recursively=True: await_children_sync waits for
    every level to complete before the root resolves.
    """
    execution_order: list[str] = []

    @promising.function
    async def great_grandchild_func() -> str:
        await asyncio.sleep(0.3)
        execution_order.append("great_grandchild_done")
        return "great_grandchild"

    @promising.function
    async def grandchild_func() -> str:
        await asyncio.sleep(0.2)
        great_grandchild_func()
        execution_order.append("grandchild_done")
        return "grandchild"

    @promising.function
    async def child_func() -> str:
        grandchild_func()
        execution_order.append("child_done")
        return "child"

    @promising.function(use_thread_pool=True)
    def root_func() -> str:
        child_func()
        time.sleep(0.1)
        execution_order.append("root_coro_done")
        promising.await_children_sync(recursively=recursively)
        return "root"

    promise = root_func()
    await promise

    if recursively:
        assert execution_order == [
            "child_done",
            "root_coro_done",
            "grandchild_done",
            "great_grandchild_done",
        ]
    else:
        assert execution_order == [
            "child_done",
            "root_coro_done",
        ]
        # Let's await for all the children to complete anyway, so that we don't
        # get any asyncio warnings about coroutines never being awaited
        await promise.await_children(recursively=True)


@pytest.mark.parametrize("recursively", [True, False])
async def test_await_children_sync_recursively_all_sync(
    *,
    recursively: bool,
) -> None:
    """
    Same as test_await_children_sync_recursively but every
    promising function in the hierarchy is synchronous
    (runs in a thread pool).
    sync root -> sync child -> sync grandchild
      -> sync great-grandchild.
    """
    execution_order: list[str] = []

    @promising.function(use_thread_pool=True)
    def great_grandchild_func() -> str:
        time.sleep(0.3)
        execution_order.append("great_grandchild_done")
        return "great_grandchild"

    @promising.function(use_thread_pool=True)
    def grandchild_func() -> str:
        time.sleep(0.2)
        great_grandchild_func()
        execution_order.append("grandchild_done")
        return "grandchild"

    @promising.function(use_thread_pool=True)
    def child_func() -> str:
        grandchild_func()
        execution_order.append("child_done")
        return "child"

    @promising.function(use_thread_pool=True)
    def root_func() -> str:
        child_func()
        time.sleep(0.1)
        execution_order.append("root_coro_done")
        promising.await_children_sync(recursively=recursively)
        return "root"

    promise = root_func()
    await promise

    if recursively:
        assert execution_order == [
            "child_done",
            "root_coro_done",
            "grandchild_done",
            "great_grandchild_done",
        ]
    else:
        assert execution_order == [
            "child_done",
            "root_coro_done",
        ]
        # Let's await for all the children to complete anyway, so that we don't
        # get any asyncio warnings about coroutines never being awaited
        await promise.await_children(recursively=True)


# ── Event loop thread guard ─────────────────────────────────────


async def test_await_children_sync_raises_on_event_loop_thread() -> None:
    """
    await_children_sync() raises SyncUsageError
    when called from the event loop thread, because it
    would deadlock.
    """

    @promising.function
    async def some_async_func() -> None:
        with pytest.raises(
            promising.SyncUsageError,
            match="deadlock",
        ):
            promising.await_children_sync()

    await some_async_func()
