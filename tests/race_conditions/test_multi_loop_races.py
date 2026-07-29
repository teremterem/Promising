"""
Multiple event loops in parallel threads sharing global framework state.

Every ``PromisingFunction.run()`` call spins up its own event loop, but
all the loops share ``Defaults.PROMISING_THREAD_POOL`` — one pool's worker
threads serve promise trees living on different loops at the same time.
The contextvars copied into pool threads are the only thing keeping the
trees apart.

Contract pinned down here:

- concurrent ``run()`` invocations are fully isolated: a pool worker
  always observes *its own* tree's root as its ancestry, never a foreign
  tree's (contextvar leakage between pool tasks would break parenting and
  configuration inheritance);
- ``run()``'s default subtree-awaiting works under parallelism — no tree
  returns before its own fire-and-forget children finished;
- a Promise bound to loop A, hit concurrently from a thread running loop
  B (must raise ``EventLoopMismatchError``) and from plain threads via
  ``sync()`` (must work) — the guard and the legitimate path race safely.
"""

import asyncio
import functools

import pytest

import promising
from promising import Promise
from promising.errors import EventLoopMismatchError
from tests.race_conditions.utils_for_race_tests import (
    AtomicCounter,
    assert_no_errors,
    run_racers,
    run_racers_sync,
)

pytestmark = pytest.mark.timeout(60)


@promising.function(use_thread_pool=True)
def _report_root_identity(tree_id: int) -> tuple[int, int]:
    # Runs in a shared-pool worker thread. The root of the trace must be
    # this worker's own tree — a foreign root means contextvars leaked
    # across pool tasks belonging to different loops.
    root_context = promising.get_active_promise().get_trace()[0]
    return (tree_id, id(root_context))


@promising.function
async def _tree_root(tree_id: int, width: int) -> int:
    my_promise = promising.get_active_promise()

    workers = [_report_root_identity(tree_id) for _ in range(width)]
    observed = [await worker for worker in workers]

    assert all(observed_tree_id == tree_id for observed_tree_id, _ in observed)
    root_ids = {root_id for _, root_id in observed}
    assert root_ids == {id(my_promise)}, (
        f"Pool workers of tree {tree_id} observed foreign root context(s): {root_ids} instead of {{{id(my_promise)}}}"
    )
    return tree_id


def _run_tree(tree_id: int) -> int:
    return _tree_root.run(tree_id, 4)


def test_parallel_run_trees_share_pool_without_context_leakage() -> None:
    """
    Four independent promise trees run simultaneously, each on its own
    event loop (via ``run()`` from four plain threads), all dispatching
    sync functions into the shared global thread pool. Every pool worker
    must see its own tree's root as its ancestor.
    """
    for _ in range(5):
        results, errors = run_racers_sync(*[functools.partial(_run_tree, tree_id) for tree_id in range(4)])
        assert_no_errors(errors)
        assert results == [0, 1, 2, 3]


@promising.function
async def _increment_soon(counter: AtomicCounter) -> None:
    await asyncio.sleep(0.001)
    counter.increment()


@promising.function
async def _spawning_root(counter: AtomicCounter, width: int) -> str:
    for _ in range(width):
        _increment_soon(counter)  # fire-and-forget
    return "ok"


def _run_and_count() -> int:
    counter = AtomicCounter()
    # run() awaits the WHOLE_SUBTREE by default — when it returns, every
    # fire-and-forget child must have completed.
    assert _spawning_root.run(counter, 5) == "ok"
    return counter.value


def test_parallel_run_awaits_whole_subtree_of_each_tree() -> None:
    """
    Several ``run()`` invocations in parallel threads, each leaving
    fire-and-forget children behind. Each ``run()`` must not return until
    its own subtree drained — under cross-loop parallelism, a lost child
    registration would let ``run()`` return early (counter below the
    expected total).
    """
    for _ in range(5):
        results, errors = run_racers_sync(*[_run_and_count] * 4)
        assert_no_errors(errors)
        assert results == [5, 5, 5, 5]


async def test_foreign_loop_await_rejected_while_sync_consumers_proceed() -> None:
    """
    A Promise lives on the test's loop. Simultaneously:

    - a thread running its OWN event loop tries to ``await`` it — must be
      rejected with ``EventLoopMismatchError`` (before corrupting any
      state);
    - two plain threads consume it via ``sync()`` — must both receive the
      identical result object.
    """
    for _ in range(20):

        async def _coro() -> list[str]:
            await asyncio.sleep(0.002)
            return ["cross-loop"]

        promise = Promise(_coro(), start_soon=True, parent=None)

        def _foreign_awaiter(promise: Promise = promise) -> str:
            async def _attempt() -> None:
                with pytest.raises(EventLoopMismatchError):
                    await promise

            asyncio.run(_attempt())
            return "rejected-as-expected"

        def _sync_consumer(promise: Promise = promise) -> list[str]:
            return promise.sync(timeout=5)

        results, errors = await run_racers(_foreign_awaiter, _sync_consumer, _sync_consumer)
        assert_no_errors(errors)

        assert results[0] == "rejected-as-expected"
        assert results[1] == ["cross-loop"]
        assert results[1] is results[2]
