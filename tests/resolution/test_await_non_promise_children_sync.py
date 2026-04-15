"""
Tests that ``await_children_sync`` correctly handles awaitable children that
are not Promise instances (e.g. custom awaitable PromisingContext subclasses).

Sync variants — uses ``await_children_sync`` from thread-pool functions.
"""

import asyncio
import time

import promising
from tests.utils_for_tests import NonPromiseAwaitableContext


async def test_await_children_with_non_promise_awaitable() -> None:
    """
    ``await_children_sync`` should await non-Promise awaitable children
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

    @promising.function(use_thread_pool=True)
    def parent_func() -> str:
        # Spawn a regular Promise child
        promise_child()

        # Spawn a non-Promise awaitable child registered in the same context
        NonPromiseAwaitableContext(slow_work())

        execution_order.append("parent_coro_done")
        # TODO Parametrize and check with and without await_children() to
        #  ensure it has effect ?
        promising.await_children_sync()
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
    ``await_children_sync`` works when ALL children are non-Promise awaitables.
    """
    results: list[str] = []

    async def work(label: str) -> None:
        await asyncio.sleep(0.1)
        results.append(label)

    @promising.function(use_thread_pool=True)
    def parent_func() -> str:
        NonPromiseAwaitableContext(work("a"))
        NonPromiseAwaitableContext(work("b"))
        # TODO Parametrize and check with and without await_children() to
        #  ensure it has effect ?
        promising.await_children_sync()
        return "parent"

    promise = parent_func()
    await promise

    assert sorted(results) == ["a", "b"]


async def test_await_children_whole_subtree_non_promise_grandchildren() -> None:
    """
    ``await_children_sync()`` must correctly discard
    non-Promise awaitable *grandchildren* after awaiting them.

    Regression: the code discarded non-Promise awaitables from
    ``self._unsettled_children`` (the root), but grandchildren live in their
    actual parent's ``_unsettled_children``.  The discard was a no-op, causing
    ``collect_unsettled_children`` to keep finding them → infinite loop.
    """
    execution_order: list[str] = []

    async def great_grandchild_1_non_promise() -> str:
        promising.Promise[str](prefilled_result="prefilled_great_grandchild")
        execution_order.append("non_promise_great_grandchild_1_done")
        return "great_grandchild_work"

    async def great_grandchild_2_non_promise() -> str:
        execution_order.append("non_promise_great_grandchild_2_done")
        return "great_grandchild_work"

    async def grandchild_non_promise() -> str:
        await asyncio.sleep(0.1)
        NonPromiseAwaitableContext(great_grandchild_2_non_promise())
        execution_order.append("non_promise_grandchild_done")
        return "grandchild_work"

    @promising.function(use_thread_pool=True)
    def grandchild_func() -> str:
        NonPromiseAwaitableContext(great_grandchild_1_non_promise())
        execution_order.append("grandchild_done")
        return "grandchild"

    @promising.function(use_thread_pool=True)
    def child_func() -> str:
        promising.Promise[str](prefilled_result="prefilled_grandchild_1")
        with promising.context() as ctx:
            promising.Promise[str](prefilled_result="prefilled_grandchild_2")
            awaitable_ctx = NonPromiseAwaitableContext(grandchild_non_promise())
            assert awaitable_ctx.get_parent_context() is ctx

        execution_order.append("child_done")
        return grandchild_func()

    @promising.function(use_thread_pool=True)
    def root_func() -> str:
        result = child_func()
        time.sleep(0.1)
        execution_order.append("root_coro_done")
        # TODO Parametrize and check with and without await_children() to
        #  ensure it has effect ?
        promising.await_children_sync()
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
