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
    async def child_func() -> str:
        await asyncio.sleep(0.1)
        execution_order.append("child_done")
        return "child"

    @promising.function
    def parent_func() -> str:
        nonlocal child_promise
        child_promise = child_func()
        execution_order.append("parent_coro_done")
        if await_children:
            promising.await_children_sync()
        return "parent"

    await parent_func()

    if await_children:
        assert execution_order == [
            "parent_coro_done",
            "child_done",
        ]
    else:
        assert execution_order == ["parent_coro_done"]

    # Let's await for the child promise to complete,
    # so that we don't get any asyncio warnings about the
    # child promise being not awaited (or being cancelled).
    await child_promise


@pytest.mark.parametrize("recursively", [True])
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

    @promising.function
    def root_func() -> str:
        child_func()
        time.sleep(0.1)
        execution_order.append("root_coro_done")
        promising.await_children_sync(recursively=recursively)
        return "root"

    await root_func()

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


@pytest.mark.parametrize("recursively", [True])
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

    @promising.function
    def great_grandchild_func() -> str:
        time.sleep(0.3)
        execution_order.append("great_grandchild_done")
        return "great_grandchild"

    @promising.function
    def grandchild_func() -> str:
        time.sleep(0.2)
        great_grandchild_func()
        execution_order.append("grandchild_done")
        return "grandchild"

    @promising.function
    def child_func() -> str:
        grandchild_func()
        execution_order.append("child_done")
        return "child"

    @promising.function
    def root_func() -> str:
        child_func()
        time.sleep(0.1)
        execution_order.append("root_coro_done")
        promising.await_children_sync(recursively=recursively)
        return "root"

    await root_func()

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


# ── Event loop thread guard ─────────────────────────────────────


async def test_await_children_sync_raises_on_event_loop_thread() -> None:
    """
    await_children_sync() raises SyncPromiseUsageError
    when called from the event loop thread, because it
    would deadlock.
    """

    @promising.function
    async def some_async_func() -> None:
        with pytest.raises(
            promising.SyncPromiseUsageError,
            match="deadlock",
        ):
            promising.await_children_sync()

    await some_async_func()
