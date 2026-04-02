"""
Tests that ``await_children`` correctly handles awaitable children that are
not Promise instances (e.g. custom awaitable PromisingContext subclasses).
"""

import asyncio
import inspect

import promising
from promising.promise import Promise
from promising.promising_context import PromisingContext


class AwaitableContext(PromisingContext):
    """
    A PromisingContext subclass that is awaitable (has ``__await__``) but is
    NOT a Promise.  Simulates a third-party or user-defined awaitable child.
    """

    def __init__(self, coro, **kwargs):
        super().__init__(**kwargs)
        self._coro = coro
        self._task: asyncio.Task | None = None

    def __await__(self):
        if self._task is None:
            self._task = asyncio.ensure_future(self._coro)
        return self._task.__await__()


async def test_awaitable_context_is_awaitable_but_not_promise() -> None:
    """Sanity check: AwaitableContext is awaitable but not a Promise."""
    loop = asyncio.get_running_loop()
    with promising.context(loop=loop) as ctx:
        child = AwaitableContext(asyncio.sleep(0), parent=ctx, loop=loop)
        assert inspect.isawaitable(child)
        assert not isinstance(child, Promise)
        # Clean up
        await child


async def test_await_children_with_non_promise_awaitable() -> None:
    """
    ``await_children`` should await non-Promise awaitable children
    directly instead of calling ``unpack_once()`` on them.
    """
    execution_order: list[str] = []

    async def slow_work() -> str:
        await asyncio.sleep(0.1)
        execution_order.append("awaitable_child_done")
        return "done"

    @promising.function
    async def parent_func() -> str:
        ctx = promising.get_active_context()

        # Spawn a regular Promise child
        @promising.function
        async def promise_child() -> str:
            await asyncio.sleep(0.1)
            execution_order.append("promise_child_done")
            return "promise"

        promise_child()

        # Spawn a non-Promise awaitable child registered in the same context.
        # Must keep a strong reference since _children is a WeakSet.
        _keep_alive = AwaitableContext(slow_work(), parent=ctx, loop=ctx._ctx_loop)  # noqa: F841

        execution_order.append("parent_coro_done")
        await promising.await_children()
        return "parent"

    promise = parent_func()
    await promise

    assert "parent_coro_done" in execution_order
    assert "awaitable_child_done" in execution_order
    assert "promise_child_done" in execution_order
    assert execution_order.index("parent_coro_done") < execution_order.index("awaitable_child_done")
    assert execution_order.index("parent_coro_done") < execution_order.index("promise_child_done")


async def test_await_children_only_non_promise_awaitables() -> None:
    """
    ``await_children`` works when ALL children are non-Promise awaitables.
    """
    results: list[str] = []

    async def work(label: str) -> None:
        await asyncio.sleep(0.1)
        results.append(label)

    @promising.function
    async def parent_func() -> str:
        ctx = promising.get_active_context()
        # Must keep strong references since _children is a WeakSet.
        _keep = [  # noqa: F841
            AwaitableContext(work("a"), parent=ctx, loop=ctx._ctx_loop),
            AwaitableContext(work("b"), parent=ctx, loop=ctx._ctx_loop),
        ]
        await promising.await_children()
        return "parent"

    promise = parent_func()
    await promise

    assert sorted(results) == ["a", "b"]
