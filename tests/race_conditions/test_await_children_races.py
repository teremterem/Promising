"""
``await_children`` / ``await_children_sync`` completeness under thread
churn.

``await_children()`` repeatedly collects unsettled children and gathers
them until none remain, because children may spawn new children while
being awaited — including from pool threads, where registration races the
collector. ``await_children_sync()`` adds another layer: it dispatches the
whole wait onto the loop via ``run_coroutine_threadsafe`` from a pool
thread.

Contract pinned down here:

- descendants spawned from worker threads (at any depth, alternating
  async/sync levels) are never missed;
- concurrent ``await_children_sync()`` calls from sibling pool functions
  don't deadlock or cross-wait;
- ``await_children()`` tolerates the children being simultaneously
  consumed via ``sync()`` from external threads;
- ``unpack_promises_fully=False`` waits only for the first unpacking step
  even while full resolution is still blocked.
"""

import asyncio
import functools
import threading

import pytest

import promising
from promising import Promise
from tests.race_conditions.utils_for_race_tests import (
    RACE_ITERATIONS,
    AtomicCounter,
    assert_no_errors,
    make_child_creator,
    run_racers,
)

pytestmark = pytest.mark.timeout(30)


@promising.function
async def _async_spawner_node(depth: int, counter: AtomicCounter) -> int:
    if depth > 0:
        _sync_spawner_node(depth - 1, counter)  # fire-and-forget
    counter.increment()
    return depth


@promising.function(use_thread_pool=True)
def _sync_spawner_node(depth: int, counter: AtomicCounter) -> int:
    if depth > 0:
        _async_spawner_node(depth - 1, counter)  # fire-and-forget, from a pool thread
    counter.increment()
    return depth


async def test_await_children_catches_alternating_thread_spawned_descendants() -> None:
    """
    A chain of fire-and-forget descendants alternating between the event
    loop and pool threads (each level registering with a parent that is
    about to finish). ``await_children()`` on the enclosing context must
    return only after the entire chain has completed.
    """
    for _ in range(20):
        counter = AtomicCounter()
        with promising.context() as ctx:
            _async_spawner_node(4, counter)
            await ctx.await_children()
        # Depth 4 → 5 nodes in the chain, every one must have finished
        # BEFORE await_children() returned (the with block exited).
        assert counter.value == 5


@promising.function
async def _slow_tick(counter: AtomicCounter) -> None:
    await asyncio.sleep(0.001)
    counter.increment()


@promising.function(use_thread_pool=True)
def _sibling_with_own_children(n: int) -> int:
    counter = AtomicCounter()
    for _ in range(n):
        _slow_tick(counter)
    # Each sibling waits for ITS OWN children only — several of these run
    # concurrently in pool threads, all dispatching await_children onto
    # the same event loop at once.
    promising.await_children_sync(timeout=10)
    return counter.value


async def test_concurrent_await_children_sync_in_sibling_pool_functions() -> None:
    """
    Several sync promising functions in pool threads each spawn children
    and call ``await_children_sync()`` simultaneously. Each must see all
    of its own children completed, with no deadlock and no cross-talk.
    """
    for _ in range(10):
        siblings = [_sibling_with_own_children(3) for _ in range(4)]
        results = [await sibling for sibling in siblings]
        assert results == [3, 3, 3, 3]


@promising.function
async def _short_task(value: int) -> list[int]:
    await asyncio.sleep(0.001)
    return [value]


async def test_await_children_racing_external_sync_consumers() -> None:
    """
    The parent context awaits its children while external threads
    simultaneously consume those same children via ``sync()``. Both
    waiting mechanisms must complete and agree on the results.
    """
    for _ in range(20):
        with promising.context() as ctx:
            kids = [_short_task(i) for i in range(4)]
            racers_future = asyncio.ensure_future(
                run_racers(*[functools.partial(kid.sync, timeout=5) for kid in kids])
            )
            await ctx.await_children()
            results, errors = await racers_future

        assert_no_errors(errors)
        assert results == [[0], [1], [2], [3]]
        assert all(kid.done() for kid in kids)


@promising.function(use_thread_pool=True)
def _outer_returns_detached(gate: asyncio.Event, loop: asyncio.AbstractEventLoop) -> Promise[str]:
    async def _gated() -> str:
        await gate.wait()
        return "final"

    # parent=None detaches the returned promise from the hierarchy: it is
    # NOT a child of the context under test, only the *return value* of
    # one — so full unpacking of the outer promise blocks on the gate, but
    # the first unpacking step does not.
    return Promise(_gated(), parent=None, loop=loop, start_soon=True)


async def test_await_children_unpack_once_only_mode_under_thread_churn() -> None:
    """
    ``await_children(unpack_promises_fully=False)`` must return once every
    child (produced by pool threads) has completed its first unpacking
    step — even though the promises the children *returned* are still
    blocked. Full awaiting afterwards must resolve everything.
    """
    loop = asyncio.get_running_loop()

    for _ in range(10):
        gate = asyncio.Event()
        with promising.context() as ctx:
            outers = [_outer_returns_detached(gate, loop) for _ in range(4)]

            await ctx.await_children(unpack_promises_fully=False)
            for outer in outers:
                assert outer.unpacked_once()
                detached = outer.intermediate_promise()
                assert isinstance(detached, Promise)
                assert not detached.done(), "Partial await_children should not have waited for the gate"

            gate.set()
            await ctx.await_children()

        for outer in outers:
            assert outer.result() == "final"


@promising.function
async def _lazy_leaf(counter: AtomicCounter) -> list[str]:
    counter.increment()
    return ["lazy-leaf"]


@promising.function(use_thread_pool=True)
def _spawn_lazy_children(counter: AtomicCounter, children: list, children_lock: threading.Lock, n: int) -> int:
    for _ in range(n):
        child = _lazy_leaf(counter, start_soon=False)
        with children_lock:
            children.append(child)
    return n


async def test_await_children_triggers_lazy_children_racing_external_consumers() -> None:
    """
    Lazy (``start_soon=False``) children created in pool threads are
    *triggered* by the parent's ``await_children()`` — awaiting a deferred
    Promise starts it — while external threads simultaneously trigger the
    same children via ``sync()``. Both trigger paths race per child; each
    child must still execute exactly once and everything must settle.
    """
    for _ in range(10):
        counter = AtomicCounter()
        children: list = []
        children_lock = threading.Lock()

        with promising.context() as ctx:
            spawners = [_spawn_lazy_children(counter, children, children_lock, 2) for _ in range(3)]
            for spawner in spawners:
                assert await spawner == 2
            assert len(children) == 6
            assert counter.value == 0, "Lazy children must not have started before anything awaited them"

            racers_future = asyncio.ensure_future(
                run_racers(*[functools.partial(child.sync, timeout=5) for child in children])
            )
            await ctx.await_children()
            results, errors = await racers_future

        assert_no_errors(errors)
        assert all(result == ["lazy-leaf"] for result in results)
        assert counter.value == 6, f"Each lazy child must run exactly once; observed {counter.value} executions"
        assert all(child.done() for child in children)


async def test_concurrent_await_children_tasks_on_same_context() -> None:
    """
    Two ``await_children()`` calls on the same context run concurrently
    (as separate tasks on the loop) while descendants keep being spawned
    and finished in pool threads. Both waiters must return, and only after
    the entire alternating async/sync chain has completed.
    """
    for _ in range(10):
        counter = AtomicCounter()
        with promising.context() as ctx:
            _sync_spawner_node(4, counter)
            waiter_a = asyncio.create_task(ctx.await_children())
            waiter_b = asyncio.create_task(ctx.await_children())
            await asyncio.gather(waiter_a, waiter_b)
        # Depth 4 → 5 nodes; both waiters must have covered all of them.
        assert counter.value == 5


@promising.function(use_thread_pool=True)
def _impatient_parent(counter: AtomicCounter, n: int) -> int:
    for _ in range(n):
        _slow_tick(counter)
    attempts = 0
    while True:
        try:
            promising.await_children_sync(timeout=0.0005)
            break
        except TimeoutError:  # noqa: PERF203 - retry loop is the point
            attempts += 1
            assert attempts < 100_000, "await_children_sync never succeeded despite retries"
    return counter.value


async def test_await_children_sync_timeout_retry_under_churn() -> None:
    """
    ``await_children_sync()`` with a timeout shorter than the children's
    runtime, retried in a loop from a pool thread. Every timed-out attempt
    abandons an ``await_children()`` coroutine that keeps running on the
    loop, so the retries pile up concurrent waiters over the same context.
    The timeouts must not corrupt child tracking: the eventually-successful
    attempt must observe every child completed.
    """
    for _ in range(10):
        assert await _impatient_parent(AtomicCounter(), 3) == 3


async def test_late_registration_racing_await_children_final_sweep_is_never_lost() -> None:
    """
    A raw thread registers a brand-new child on an OPEN context at the
    very moment ``await_children()`` finishes its final sweep (the
    "no unsettled children left" check and the return are not one atomic
    step). The in-flight ``await_children()`` may legitimately return
    without the newcomer — but the child must never be silently dropped:
    it must remain tracked, and a subsequent ``await_children()`` must
    wait for it.
    """
    loop = asyncio.get_running_loop()

    for _ in range(RACE_ITERATIONS):
        with promising.context() as ctx:
            executions = AtomicCounter()
            box: dict = {}

            racers_future = asyncio.ensure_future(run_racers(make_child_creator(ctx, loop, executions, box)))
            await ctx.await_children()
            _, errors = await racers_future
            assert_no_errors(errors)

            # The context is still open, so the creation must have been
            # accepted (a rejection here would itself be a bug).
            child = box["child"]
            assert child.done() or child in ctx.collect_unsettled_children(), (
                "Late-registered child was silently dropped from tracking"
            )
            await ctx.await_children()
            assert child.done()
            assert executions.value == 1
