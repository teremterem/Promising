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

import pytest

import promising
from promising import Promise
from tests.race_conditions.utils_for_race_tests import (
    AtomicCounter,
    assert_no_errors,
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
