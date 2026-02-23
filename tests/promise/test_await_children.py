import asyncio
import time

import pytest

import promising


@pytest.mark.parametrize("await_children", [True, False])
async def test_await_children(*, await_children: bool) -> None:
    """
    Parametrized over await_children={True, False}.
    With True: the parent coro body explicitly calls
    await_children(), so the child completes before
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
    async def parent_func() -> str:
        nonlocal child_promise
        child_promise = child_func()
        execution_order.append("parent_coro_done")
        if await_children:
            await promising.await_children()
        return "parent"

    await parent_func()

    if await_children:
        assert execution_order == ["parent_coro_done", "child_done"]
    else:
        assert execution_order == ["parent_coro_done"]

    # Let's await for the child promise to complete, so that we don't get any
    # asyncio warnings about the child promise being not awaited (or being
    # cancelled).
    await child_promise


@pytest.mark.parametrize("recursively", [True, False])
async def test_await_children_recursively(*, recursively: bool) -> None:
    """
    Parametrized over recursively={True, False}.
    Three levels of nesting: root → child → grandchild → great-grandchild.
    With True: await_children(recursively=True) is called on the
    root, so every level completes before the root resolves.
    With False: await_children(recursively=False) only waits for
    direct children (child), so grandchild and great-grandchild may still
    be running when the root resolves.
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
    async def root_func() -> str:
        child_func()
        await asyncio.sleep(0.1)
        execution_order.append("root_coro_done")
        await promising.await_children(recursively=recursively)
        return "root"

    await root_func()

    if recursively:
        assert execution_order == ["child_done", "root_coro_done", "grandchild_done", "great_grandchild_done"]
    else:
        assert execution_order == ["child_done", "root_coro_done"]


@pytest.mark.parametrize("recursively", [True, False])
async def test_await_children_recursively_sync_children(
    *,
    recursively: bool,
) -> None:
    """
    Same as test_await_children_recursively but only the
    root is async — child, grandchild, and great-grandchild
    are all sync promising functions running in thread pools.
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
    async def root_func() -> str:
        child_func()
        await asyncio.sleep(0.1)
        execution_order.append("root_coro_done")
        await promising.await_children(recursively=recursively)
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
