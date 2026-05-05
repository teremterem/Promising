import asyncio
import time

import pytest

import promising


@pytest.mark.parametrize("await_children", [True, False])
@pytest.mark.parametrize("start_soon", [True, False])
async def test_await_children(*, start_soon: bool, await_children: bool) -> None:
    """
    With await_children=True: the parent coro body explicitly calls
    await_children(), so the child completes before the parent resolves. With
    await_children=False: the parent resolves without waiting for the child.
    """
    execution_order: list[str] = []
    child_promise = None

    @promising.function(start_soon=start_soon)
    async def grandchild_func() -> str:
        await asyncio.sleep(0.2)
        execution_order.append("grandchild_done")
        return "grandchild"

    @promising.function(start_soon=start_soon)
    async def child_func() -> str:
        grandchild_func()
        await asyncio.sleep(0.1)
        execution_order.append("child_done")
        return "child"

    @promising.function(start_soon=start_soon)
    async def parent_func() -> str:
        nonlocal child_promise
        child_promise = child_func()
        execution_order.append("parent_coro_done")
        if await_children:
            await promising.await_children()
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


@pytest.mark.parametrize("whole_subtree", [True, False])
async def test_await_children_whole_subtree(*, whole_subtree: bool) -> None:
    """
    Parametrized over whole_subtree={True, False}.
    Three levels of nesting: root → child → grandchild → great-grandchild.
    With True: await_children(whole_subtree=True) is called on the
    root, so every level completes before the root resolves.
    With False: await_children(whole_subtree=False) only waits for
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
        # TODO Parametrize and check with and without await_children() to
        #  ensure it has effect ?
        await promising.await_children(whole_subtree=whole_subtree)
        return "root"

    promise = root_func()
    await promise

    if whole_subtree:
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
        await promise.await_children()


@pytest.mark.parametrize("whole_subtree", [True, False])
async def test_await_children_whole_subtree_sync_children(*, whole_subtree: bool) -> None:
    """
    Same as test_await_children_whole_subtree but every
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

    @promising.function
    async def root_func() -> str:
        child_func()
        await asyncio.sleep(0.1)
        execution_order.append("root_coro_done")
        # TODO Parametrize and check with and without await_children() to
        #  ensure it has effect ?
        await promising.await_children(whole_subtree=whole_subtree)
        return "root"

    promise = root_func()
    await promise

    if whole_subtree:
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
        await promise.await_children()


async def test_await_children_on_bare_context() -> None:
    """
    ``await_children`` works when called on a bare PromisingContext
    (not a Promise) that has Promise children spawned inside it.
    """
    execution_order: list[str] = []

    @promising.function
    async def child_func() -> str:
        await asyncio.sleep(0.1)
        execution_order.append("child_done")
        return "child"

    with promising.context() as ctx:
        assert isinstance(ctx, promising.PromisingContext)
        assert not isinstance(ctx, promising.Promise)

        child_func()
        child_func()

        execution_order.append("before_await")
        await ctx.await_children()

    assert execution_order == ["before_await", "child_done", "child_done"]


@pytest.mark.parametrize("whole_subtree", [True, False])
async def test_await_children_on_bare_context_whole_subtree(*, whole_subtree: bool) -> None:
    """
    ``await_children(whole_subtree=...)`` works on a bare PromisingContext
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

    with promising.context() as ctx:
        assert not isinstance(ctx, promising.Promise)

        child_func()

        await ctx.await_children(whole_subtree=whole_subtree)

    if whole_subtree:
        assert execution_order == ["child_done", "grandchild_done"]
    else:
        assert execution_order == ["child_done"]
        # Clean up remaining grandchild
        await ctx.await_children()


async def test_await_children_module_level_on_bare_context() -> None:
    """
    The module-level ``promising.await_children()`` works when the active
    context is a bare PromisingContext (not a Promise).
    """
    execution_order: list[str] = []

    @promising.function
    async def child_func() -> str:
        await asyncio.sleep(0.1)
        execution_order.append("child_done")
        return "child"

    with promising.context() as ctx:
        assert not isinstance(ctx, promising.Promise)

        child_func()

        # Use the module-level function (which finds the active context)
        # TODO Parametrize and check with and without await_children() to
        #  ensure it has effect ?
        await promising.await_children()

    assert execution_order == ["child_done"]


@pytest.mark.parametrize(
    "unpack_promises_fully",
    [
        pytest.param(True, id="unpack_fully"),
        pytest.param(False, id="unpack_once"),
        pytest.param(None, id="unpack_default"),
    ],
)
@pytest.mark.parametrize(
    "sleep_in_root",
    [
        pytest.param(True, id="root_sleeps"),
        pytest.param(False, id="root_nosleep"),
    ],
)
async def test_await_children_direct_only_but_unpack_promises_fully(
    *,
    sleep_in_root: bool,
    unpack_promises_fully: bool | None,
) -> None:
    """
    With ``whole_subtree=False``, ``await_children`` waits only for direct
    children.  When ``unpack_promises_fully`` is True (or default), the child's
    returned Promise is recursively unpacked, so the grandchild still runs.
    When ``unpack_promises_fully=False``, the grandchild is never awaited.
    """
    execution_order: list[str] = []

    @promising.function
    async def grandchild_func() -> str:
        await asyncio.sleep(0.2)
        execution_order.append("grandchild_done")
        return "grandchild"

    @promising.function
    async def child_func() -> str:
        grandchild = grandchild_func()
        execution_order.append("child_done")
        return grandchild

    @promising.function
    async def root_func() -> str:
        child_func()
        if sleep_in_root:
            await asyncio.sleep(0.1)
        execution_order.append("root_coro_done")

        # TODO Parametrize and check with and without await_children() to
        #  ensure it has effect ?
        kwargs = {}
        if unpack_promises_fully is not None:  # We use None to test the default
            kwargs["unpack_promises_fully"] = unpack_promises_fully
        await promising.await_children(whole_subtree=False, **kwargs)

        return "root"

    promise = root_func()
    assert await promise == "root"

    if sleep_in_root:
        if unpack_promises_fully is False:
            assert execution_order == [
                "child_done",
                "root_coro_done",
            ]
        else:
            # `unpack_promises_fully` is either True or None ("use default")
            assert execution_order == [
                "child_done",
                "root_coro_done",
                "grandchild_done",
            ]
    elif unpack_promises_fully is False:
        assert execution_order == [
            "root_coro_done",
            "child_done",
        ]
    else:
        # `unpack_promises_fully` is either True or None ("use default")
        assert execution_order == [
            "root_coro_done",
            "child_done",
            "grandchild_done",
        ]

    # Clean up remaining grandchild to avoid asyncio warnings
    await promise.await_children()
