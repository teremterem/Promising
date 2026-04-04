"""
Tests that ``await_children`` correctly handles awaitable children that are
not Promise instances (e.g. custom awaitable PromisingContext subclasses).

Async variants — uses ``await`` and ``await_children``.
"""

import asyncio
import inspect

import promising
from promising.promise import Promise
from tests.utils_for_tests import AwaitableContext


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
    async def promise_child() -> str:
        await asyncio.sleep(0.1)
        execution_order.append("promise_child_done")
        return "promise"

    @promising.function
    async def parent_func() -> str:
        # Spawn a regular Promise child
        promise_child()

        # Spawn a non-Promise awaitable child registered in the same context
        AwaitableContext(slow_work())

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
        AwaitableContext(work("a"))
        AwaitableContext(work("b"))
        await promising.await_children()
        return "parent"

    promise = parent_func()
    await promise

    assert sorted(results) == ["a", "b"]


async def test_await_children_recursively_non_promise_grandchildren() -> None:
    """
    ``await_children(recursively=True)`` must correctly discard non-Promise
    awaitable *grandchildren* after awaiting them.

    Regression: the code discarded non-Promise awaitables from
    ``self._children`` (the root), but grandchildren live in their actual
    parent's ``_children``.  The discard was a no-op, causing
    ``collect_remaining_children`` to keep finding them → infinite loop.
    """
    execution_order: list[str] = []

    async def great_grandchild_1_non_promise() -> str:
        execution_order.append("non_promise_great_grandchild_1_done")
        return "great_grandchild_work"

    async def great_grandchild_2_non_promise() -> str:
        execution_order.append("non_promise_great_grandchild_2_done")
        return "great_grandchild_work"

    async def grandchild_non_promise() -> str:
        await asyncio.sleep(0.1)
        AwaitableContext(great_grandchild_2_non_promise())
        execution_order.append("non_promise_grandchild_done")
        return "grandchild_work"

    @promising.function
    async def grandchild_func() -> str:
        AwaitableContext(great_grandchild_1_non_promise())
        execution_order.append("grandchild_done")
        return "grandchild"

    @promising.function
    async def child_func() -> str:
        with promising.context() as ctx:
            awaitable_ctx = AwaitableContext(grandchild_non_promise())
            assert awaitable_ctx.get_parent_context() is ctx

        execution_order.append("child_done")
        return grandchild_func()

    @promising.function
    async def root_func() -> str:
        result = child_func()
        await asyncio.sleep(0.1)
        execution_order.append("root_coro_done")
        await promising.await_children(recursively=True)
        return result

    promise = root_func()
    result = await asyncio.wait_for(promise.unpack_all(), timeout=5)

    assert result == "grandchild"
    assert execution_order == [
        "child_done",
        "grandchild_done",
        "root_coro_done",
        "non_promise_great_grandchild_1_done",
        "non_promise_grandchild_done",
        "non_promise_great_grandchild_2_done",
    ]
