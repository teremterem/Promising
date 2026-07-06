"""
The unregistration cascade under simultaneous finishes across threads.

When a context settles (done + no unsettled descendants), it unregisters
from its parent, which may in turn unregister from *its* parent, and so
on. The cascade involves ``_unregister_from_parent_if_time``, which reads
``_unsettled_children`` **outside** the lock in the current
implementation — the prime suspect when many descendants settle at the
same moment from different threads.

Contract pinned down here:

- nothing is *lost*: ``await_children()`` on an ancestor returns only
  after every descendant (including ones spawned from pool threads) has
  settled;
- nothing *lingers*: once everything settled, ``collect_unsettled_children``
  is empty at the root — a leaked registration would keep an already-dead
  subtree pinned (and would make a later ``await_children()`` hang).
"""

import asyncio
import threading

import pytest

import promising
from promising import PromisingContext
from tests.race_conditions.utils_for_race_tests import (
    RACE_ITERATIONS,
    AtomicCounter,
    assert_no_errors,
    make_child_creator,
    run_racers,
    verify_atomic_creation_outcome,
)

pytestmark = pytest.mark.timeout(30)


@promising.function
async def _leaf(counter: AtomicCounter) -> str:
    counter.increment()
    return "leaf"


@promising.function(use_thread_pool=True)
def _mid(counter: AtomicCounter) -> str:
    # Grandchild spawned from the pool thread and not awaited — the mid
    # promise finishes (and starts unregistering) while the grandchild is
    # still in flight or just registering.
    _leaf(counter)
    return "mid"


@promising.function
async def _top(counter: AtomicCounter, width: int) -> int:
    for _ in range(width):
        _mid(counter)
    await promising.await_children()
    return counter.value


async def test_mixed_tree_drains_completely() -> None:
    """
    A three-level tree (async top → pool-thread mids → async leaves) where
    mid promises finish while their leaf children are still settling.
    Everything must be caught by ``await_children()`` and the tree must be
    fully drained right after the top promise resolves.
    """
    for _ in range(30):
        counter = AtomicCounter()
        top_promise = _top(counter, 4)
        assert await top_promise == 4
        assert top_promise.collect_unsettled_children(awaitables_only=False) == set()


@promising.function(use_thread_pool=True)
def _barrier_leaf(barrier: threading.Barrier, counter: AtomicCounter) -> None:
    # All leaves block here and then finish as close to simultaneously as
    # the OS allows — maximizing collisions in the unregistration path on
    # their shared parent.
    barrier.wait(timeout=10)
    counter.increment()


async def test_simultaneous_finish_of_wide_tree_drains_root() -> None:
    """
    Eight pool-thread leaves under one root context finish at the same
    instant (synchronized on a barrier). ``await_children()`` must wait
    for all of them and the root must end up fully drained.
    """
    for _ in range(10):
        counter = AtomicCounter()
        barrier = threading.Barrier(8)

        with promising.context() as root_ctx:
            leaves = [_barrier_leaf(barrier, counter) for _ in range(8)]
            await root_ctx.await_children()

        assert counter.value == 8
        assert all(leaf.done() for leaf in leaves)
        assert root_ctx.collect_unsettled_children(awaitables_only=False) == set()


@promising.function(use_thread_pool=True)
def _chain(depth: int, barrier: threading.Barrier, counter: AtomicCounter) -> int:
    if depth > 0:
        # Child spawned and NOT awaited — the whole chain is in flight at
        # once, one pool thread per level.
        _chain(depth - 1, barrier, counter)
    # Every level of the chain finishes simultaneously, so the
    # unregistration must cascade through all the levels while they are
    # all settling at once.
    barrier.wait(timeout=10)
    counter.increment()
    return depth


async def test_simultaneous_finish_of_deep_chain_cascades_unregistration() -> None:
    """
    A six-level parent chain (one pool thread per level) finishes all at
    once. The settle-and-unregister cascade races itself across the
    levels; the root must still see every completion and drain fully.
    """
    for _ in range(10):
        counter = AtomicCounter()
        barrier = threading.Barrier(6)

        with promising.context() as root_ctx:
            _chain(5, barrier, counter)
            await root_ctx.await_children()

        assert counter.value == 6
        assert root_ctx.collect_unsettled_children(awaitables_only=False) == set()


async def test_grandchild_registration_racing_mid_context_drain() -> None:
    """
    Three-level version of the atomic-creation contract, aimed at the
    unlocked ``_unsettled_children`` read in
    ``_unregister_from_parent_if_time``:

    root context → mid context (already done, kept unsettled only while it
    has descendants) ← grandchild registering from a worker thread at the
    exact moment the mid context closes.

    If the grandchild is accepted, it must be reachable from the *root's*
    subtree (otherwise ``root.await_children()`` would return while the
    grandchild still runs — a silently lost branch). If it is rejected, it
    must never execute.
    """
    loop = asyncio.get_running_loop()

    for _ in range(RACE_ITERATIONS):
        with promising.context() as root_ctx:
            # Deliberately never entered as a `with` block — closing is
            # driven manually by the racer thread to stage the collision.
            mid_ctx = PromisingContext(parent=root_ctx)
            executions = AtomicCounter()
            box: dict = {}

            _, errors = await run_racers(
                make_child_creator(mid_ctx, loop, executions, box),
                mid_ctx.close_context_threadsafe,
            )
            assert_no_errors(errors)

            if "child" in box:
                grandchild = box["child"]
                # The root must be able to see the grandchild through the
                # (possibly already-done) mid context until it settles.
                assert grandchild.done() or grandchild in root_ctx.collect_unsettled_children(), (
                    "Accepted grandchild is invisible to the root's subtree (lost branch)"
                )
                await root_ctx.await_children()
                assert grandchild.done()

            await verify_atomic_creation_outcome(mid_ctx, executions, box)

        assert root_ctx.collect_unsettled_children(awaitables_only=False) == set()
