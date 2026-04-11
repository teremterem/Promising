import asyncio
import time

import pytest

import promising


@pytest.mark.parametrize("await_children", [True, False])
@pytest.mark.parametrize("start_soon", [True, False])
async def test_await_children(*, start_soon: bool, await_children: bool) -> None:
    """
    Parametrized over await_children={True, False}.
    With True: the sync parent calls
    await_children_sync(), so the child completes before
    the parent resolves. With False: the parent resolves
    without waiting for the child.
    """
    execution_order: list[str] = []
    child_promise = None

    @promising.function(start_soon=start_soon, use_thread_pool=True)
    def grandchild_func() -> str:
        time.sleep(0.2)
        execution_order.append("grandchild_done")
        return "grandchild"

    @promising.function(start_soon=start_soon, use_thread_pool=True)
    def child_func() -> str:
        grandchild_func()
        time.sleep(0.1)
        execution_order.append("child_done")
        return "child"

    @promising.function(start_soon=start_soon, use_thread_pool=True)
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
        # Let's await for all the children to complete, so that we don't
        # get any asyncio warnings about coroutines never being awaited
        await promise.await_children()


@pytest.mark.parametrize("recursively", [True, False])
async def test_await_children_recursively(*, recursively: bool) -> None:
    """
    Parametrized over recursively={True, False}.
    Three levels of nesting: root → child → grandchild → great-grandchild.
    With True: await_children_sync(recursively=True) is called on the
    root, so every level completes before the root resolves.
    With False: await_children_sync(recursively=False) only waits for
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
async def test_await_children_recursively_sync_children(
    *,
    recursively: bool,
) -> None:
    """
    Same as test_await_children_recursively but every
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


async def test_await_children_on_bare_context() -> None:
    """
    ``await_children_sync`` works when called on a bare PromisingContext
    (not a Promise) that has Promise children spawned inside it.
    """
    execution_order: list[str] = []

    @promising.function
    async def child_func() -> str:
        await asyncio.sleep(0.1)
        execution_order.append("child_done")
        return "child"

    loop = asyncio.get_running_loop()
    with promising.context() as ctx:
        assert isinstance(ctx, promising.PromisingContext)
        assert not isinstance(ctx, promising.Promise)

        child_func()
        child_func()

        execution_order.append("before_await")
        await loop.run_in_executor(None, ctx.await_children_sync)

    assert execution_order == ["before_await", "child_done", "child_done"]


@pytest.mark.parametrize("recursively", [True, False])
async def test_await_children_on_bare_context_recursively(
    *,
    recursively: bool,
) -> None:
    """
    ``await_children_sync(recursively=...)`` works on a bare PromisingContext
    with nested Promise children (child -> grandchild).
    """
    execution_order: list[str] = []

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

    loop = asyncio.get_running_loop()
    with promising.context() as ctx:
        assert not isinstance(ctx, promising.Promise)

        child_func()

        await loop.run_in_executor(
            None,
            lambda: ctx.await_children_sync(recursively=recursively),
        )

    if recursively:
        assert execution_order == ["child_done", "grandchild_done"]
    else:
        assert execution_order == ["child_done"]
        # Clean up remaining grandchild
        await ctx.await_children(recursively=True)


async def test_await_children_module_level_on_bare_context() -> None:
    """
    The module-level ``promising.await_children_sync()`` works when the active
    context is a bare PromisingContext (not a Promise).
    """
    execution_order: list[str] = []

    @promising.function
    async def child_func() -> str:
        await asyncio.sleep(0.1)
        execution_order.append("child_done")
        return "child"

    loop = asyncio.get_running_loop()
    with promising.context() as ctx:
        assert not isinstance(ctx, promising.Promise)

        child_func()

        await loop.run_in_executor(None, ctx.await_children_sync)

    assert execution_order == ["child_done"]


async def test_await_children_raises_on_event_loop_thread() -> None:
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
