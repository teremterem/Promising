"""
Tests for detecting cyclic promise resolution (sync variants).

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


@pytest.mark.xfail_cycle_detection_gh_issue_66(skip_entirely=True)
@pytest.mark.parametrize("await_before_return", [False, True], ids=["return_as_is", "await_first"])
async def test_promise_resolving_to_itself(*, await_before_return: bool) -> None:
    """
    A promising function that returns get_active_promise() creates a
    direct self-reference: the promise resolves to itself. Calling .sync()
    should raise a clear error, not RecursionError.
    """

    @promising.function
    async def self_referencing() -> promising.Promise:
        p = promising.get_active_promise()
        if await_before_return:
            return await p
        return p

    @promising.function(use_thread_pool=True)
    def caller() -> None:
        promise = self_referencing()
        # TODO Replace PromisingError with the dedicated cycle error once defined
        with pytest.raises(promising.PromisingError):
            promise.sync()

    await caller()


@pytest.mark.xfail_cycle_detection_gh_issue_66(skip_entirely=True)
@pytest.mark.parametrize("await_before_return", [False, True], ids=["return_as_is", "await_first"])
async def test_inner_returns_parent_promise(*, await_before_return: bool) -> None:
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

    @promising.function(use_thread_pool=True)
    def caller() -> None:
        promise = outer()
        # TODO Replace PromisingError with the dedicated cycle error once defined
        with pytest.raises(promising.PromisingError):
            promise.sync()

    await caller()


@pytest.mark.xfail_cycle_detection_gh_issue_66(skip_entirely=True)
@pytest.mark.parametrize("await_before_return", [False, True], ids=["return_as_is", "await_first"])
async def test_indirect_promise_cycle(*, await_before_return: bool) -> None:
    """
    Two promising functions that return each other's promises form an
    indirect cycle. Calling .sync() on either should raise a clear error,
    not RecursionError.
    """

    promise_a = None

    @promising.function
    async def func_a() -> promising.Promise:
        p = func_b()
        if await_before_return:
            return await p
        return p

    @promising.function
    async def func_b() -> promising.Promise:
        if await_before_return:
            return await promise_a
        return promise_a

    @promising.function(use_thread_pool=True)
    def caller() -> None:
        nonlocal promise_a
        promise_a = func_a()
        # TODO Replace PromisingError with the dedicated cycle error once defined
        with pytest.raises(promising.PromisingError):
            promise_a.sync()

    await caller()


# ── await_children_sync on bare PromisingContext ───────────────
# await_children_sync, when called from a sync promising function inside
# a bare PromisingContext, ends up waiting for itself (the sync_waiter
# Promise is a child of the bare context too). This is a form of cycle
# that should be detected.


@pytest.mark.xfail_cycle_detection_gh_issue_66(skip_entirely=True)
async def test_self_cycle_on_bare_context() -> None:
    """
    ``await_children_sync`` on a bare PromisingContext that has Promise
    children spawned inside it. The waiter is itself a child of the
    bare context, creating a cycle.
    """

    @promising.function
    async def child_func() -> str:
        await asyncio.sleep(0.1)
        return "child"

    @promising.function(use_thread_pool=True)
    def sync_waiter() -> None:
        promising.get_active_promise().get_parent_context().await_children_sync()

    with promising.context() as ctx:
        assert isinstance(ctx, PromisingContext)
        assert not isinstance(ctx, promising.Promise)

        child_func()
        child_func()

        # TODO Replace PromisingError with the dedicated cycle error once defined
        with pytest.raises(promising.PromisingError):
            await sync_waiter()


@pytest.mark.xfail_cycle_detection_gh_issue_66(skip_entirely=True)
@pytest.mark.parametrize("whole_subtree", [True, False])
async def test_self_cycle_on_bare_context_whole_subtree(*, whole_subtree: bool) -> None:
    """
    ``await_children_sync(whole_subtree=...)`` on a bare PromisingContext
    with nested Promise children (child -> grandchild). The waiter is
    itself a child of the bare context, creating a cycle.
    """

    @promising.function
    async def grandchild_func() -> str:
        await asyncio.sleep(0.2)
        return "grandchild"

    @promising.function
    async def child_func() -> str:
        grandchild_func()
        await asyncio.sleep(0.1)
        return "child"

    @promising.function(use_thread_pool=True)
    def sync_waiter() -> None:
        promising.get_active_promise().get_parent_context().await_children_sync(
            whole_subtree=whole_subtree,
        )

    with promising.context() as ctx:
        assert not isinstance(ctx, promising.Promise)

        child_func()

        # TODO Replace PromisingError with the dedicated cycle error once defined
        with pytest.raises(promising.PromisingError):
            await sync_waiter()
