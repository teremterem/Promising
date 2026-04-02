"""
Tests for detecting cyclic promise resolution.

When a Promise resolves to itself (directly or through a chain), the library
should raise a clear error instead of hitting infinite recursion.

TODO Unskip tests after the following issue is taken care of:
https://github.com/teremterem/Promising/issues/66
"""

import asyncio

import pytest

import promising
from promising.promising_context import PromisingContext

# ── Cyclic promise resolution ──────────────────────────────────


@pytest.mark.skip(reason="Cycle detection not implemented yet (issue #66)")
@pytest.mark.parametrize("await_before_return", [False, True], ids=["return_as_is", "await_first"])
async def test_promise_resolving_to_itself(await_before_return: bool) -> None:
    """
    A promising function that returns get_active_promise() creates a
    direct self-reference: the promise resolves to itself. Awaiting it
    should raise a clear error, not RecursionError.
    """

    @promising.function
    async def self_referencing() -> promising.Promise:
        p = promising.get_active_promise()
        if await_before_return:
            return await p
        return p

    promise = self_referencing()
    # TODO Replace PromisingError with the dedicated cycle error once defined
    with pytest.raises(promising.PromisingError):
        await promise


@pytest.mark.skip(reason="Cycle detection not implemented yet (issue #66)")
@pytest.mark.parametrize("await_before_return", [False, True], ids=["return_as_is", "await_first"])
async def test_inner_returns_parent_promise(await_before_return: bool) -> None:
    """
    An inner promising function returns get_parent_promise(), which is the
    outer promise. When the outer awaits the inner, unpacking leads back to
    the outer — a cycle.
    """

    @promising.function
    async def inner() -> promising.Promise:
        p = promising.get_active_promise().get_parent_promise()
        if await_before_return:
            return await p
        return p

    @promising.function
    async def outer() -> promising.Promise:
        return await inner()

    promise = outer()
    # TODO Replace PromisingError with the dedicated cycle error once defined
    with pytest.raises(promising.PromisingError):
        await promise


@pytest.mark.skip(reason="Cycle detection not implemented yet (issue #66)")
@pytest.mark.parametrize("await_before_return", [False, True], ids=["return_as_is", "await_first"])
async def test_indirect_promise_cycle(await_before_return: bool) -> None:
    """
    Two promising functions that return each other's promises form an
    indirect cycle. Awaiting either should raise a clear error, not
    RecursionError.
    """

    @promising.function
    async def func_a() -> promising.Promise:
        p = func_b()
        if await_before_return:
            return await p
        return p

    @promising.function
    async def func_b() -> promising.Promise:
        p = promising.get_active_promise()
        if await_before_return:
            return await p
        return p

    promise_a = func_a()
    # TODO Replace PromisingError with the dedicated cycle error once defined
    with pytest.raises(promising.PromisingError):
        await promise_a


# ── await_children_sync on bare PromisingContext ───────────────
# These tests deadlock because await_children_sync, when called from a
# sync promising function inside a bare PromisingContext, ends up waiting
# for itself (the sync_waiter Promise is a child of the bare context too).


@pytest.mark.skip(reason="Deadlocks — await_children_sync waits for itself")
async def test_await_children_sync_on_bare_context() -> None:
    """
    ``await_children_sync`` on a bare PromisingContext that has Promise
    children spawned inside it.
    """
    execution_order: list[str] = []

    @promising.function
    async def child_func() -> str:
        await asyncio.sleep(0.05)
        execution_order.append("child_done")
        return "child"

    @promising.function(use_thread_pool=True)
    def sync_waiter() -> None:
        promising.get_active_promise().get_parent_context().await_children_sync()

    with promising.context() as ctx:
        assert isinstance(ctx, PromisingContext)
        assert not isinstance(ctx, promising.Promise)

        child_func()
        child_func()

        execution_order.append("before_await")
        await sync_waiter()

    assert execution_order == ["before_await", "child_done", "child_done"]


@pytest.mark.skip(reason="Deadlocks — await_children_sync waits for itself")
@pytest.mark.parametrize("recursively", [True, False])
async def test_await_children_sync_on_bare_context_recursively(
    *,
    recursively: bool,
) -> None:
    """
    ``await_children_sync(recursively=...)`` on a bare PromisingContext
    with nested Promise children (child -> grandchild).
    """
    execution_order: list[str] = []

    @promising.function
    async def grandchild_func() -> str:
        await asyncio.sleep(0.1)
        execution_order.append("grandchild_done")
        return "grandchild"

    @promising.function
    async def child_func() -> str:
        grandchild_func()
        await asyncio.sleep(0.05)
        execution_order.append("child_done")
        return "child"

    @promising.function(use_thread_pool=True)
    def sync_waiter() -> None:
        promising.get_active_promise().get_parent_context().await_children_sync(
            recursively=recursively,
        )

    with promising.context() as ctx:
        assert not isinstance(ctx, promising.Promise)

        child_func()

        await sync_waiter()

    if recursively:
        assert execution_order == ["child_done", "grandchild_done"]
    else:
        assert execution_order == ["child_done"]
        # Clean up remaining grandchild
        await ctx.await_children(recursively=True)


@pytest.mark.skip(reason="Deadlocks — await_children_sync waits for itself")
async def test_await_children_sync_module_level_on_bare_context() -> None:
    """
    The module-level ``promising.await_children_sync()`` called from a sync
    promising function whose parent is a bare PromisingContext.
    """
    execution_order: list[str] = []

    @promising.function
    async def child_func() -> str:
        await asyncio.sleep(0.05)
        execution_order.append("child_done")
        return "child"

    @promising.function(use_thread_pool=True)
    def sync_waiter() -> None:
        promising.get_active_promise().get_parent_context().await_children_sync()

    with promising.context() as ctx:
        assert not isinstance(ctx, promising.Promise)

        child_func()

        await sync_waiter()

    assert execution_order == ["child_done"]
