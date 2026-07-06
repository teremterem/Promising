"""
``PromisingContext`` lifecycle races: enter / exit / close.

``__enter__`` guards (``_previous_token``, ``_context_closed``) are read
and written without synchronization in the current implementation — the
class docstring even references GitHub issue #98 in a
"TODO [RACE CONDITIONS]" comment right inside ``__enter__``. The contract
pinned down here:

- the same context instance can never be successfully *inside* two
  threads at once: when two threads race to enter, at most one may
  succeed, the loser must get a clean ``ContextError``
  (``ContextAlreadyActiveError`` / ``ContextAlreadyClosedError``), and
  the winner's exit must work flawlessly;
- ``close_context_threadsafe()`` from another thread racing the owning
  thread's ``with``-block exit must never break the exit;
- N threads creating children racing one thread closing the context:
  every creation is atomic (accepted-and-tracked XOR cleanly-rejected-and
  -never-executed) and the context drains afterwards.
"""

import asyncio

import pytest

from promising import PromisingContext
from promising.errors import ContextError
from tests.race_conditions.utils_for_race_tests import (
    RACE_ITERATIONS,
    AtomicCounter,
    assert_no_errors,
    eventually,
    make_child_creator,
    run_racers,
)

pytestmark = pytest.mark.timeout(30)


async def test_concurrent_enter_of_same_context_has_at_most_one_winner() -> None:
    """
    Two threads race to ``__enter__`` the same context. At most one may
    win; the other must be cleanly rejected with a ``ContextError``. The
    winner exits from its own thread — that exit must never blow up with
    token/contextvar corruption (which is exactly what happens if both
    threads slip past the ``_previous_token is None`` check).
    """
    for _ in range(RACE_ITERATIONS):
        ctx = PromisingContext(parent=None)

        def _enterer(ctx: PromisingContext = ctx) -> str:
            try:
                ctx.__enter__()
            except ContextError:
                # Cleanly rejected: either the other thread is currently
                # inside (ContextAlreadyActiveError) or it already entered
                # and exited (ContextAlreadyClosedError).
                return "rejected"
            # Won the race — exiting must succeed from the entering thread.
            ctx.__exit__(None, None, None)
            return "entered"

        results, errors = await run_racers(_enterer, _enterer)
        assert_no_errors(errors)

        assert results.count("entered") <= 1, "Two threads entered the same context simultaneously"
        assert results.count("entered") + results.count("rejected") == 2


async def test_threadsafe_close_racing_with_block_exit() -> None:
    """
    A worker thread calls ``close_context_threadsafe()`` at the same
    moment the owning (loop) thread exits the ``with`` block (which also
    closes). Both operations are idempotent by contract; neither may
    raise, and the context must end up closed.
    """
    for _ in range(RACE_ITERATIONS):
        ctx = PromisingContext(parent=None)
        with ctx:
            closer_future = asyncio.ensure_future(run_racers(ctx.close_context_threadsafe))
            # Exit the with block while the closer thread runs — the two
            # close paths collide. (The with-block exit happens right
            # here, as this block ends.)

        _, errors = await closer_future
        assert_no_errors(errors)
        assert ctx.closed()


async def test_many_creators_racing_single_close() -> None:
    """
    Five threads create children of one open context while a sixth thread
    closes it — all released simultaneously. For every creator the
    creation must be atomic: the accepted children run exactly once and
    drain; the rejected children never run at all.

    NOTE: the "rejected children never run" half is expected to fail
    against the current implementation, because ``Promise.__init__``
    schedules execution before registering with the parent.
    """
    loop = asyncio.get_running_loop()

    for _ in range(20):
        ctx = PromisingContext(parent=None)
        ctx.__enter__()
        executions = AtomicCounter()
        boxes: list[dict] = [{} for _ in range(5)]

        creators = [make_child_creator(ctx, loop, executions, box) for box in boxes]
        _, errors = await run_racers(*creators, ctx.close_context_threadsafe)
        ctx.__exit__(None, None, None)
        assert_no_errors(errors)

        accepted = [box["child"] for box in boxes if "child" in box]
        rejected_boxes = [box for box in boxes if box.get("rejected")]
        assert len(accepted) + len(rejected_boxes) == 5, "A creator produced neither a child nor a clean rejection"

        for child in accepted:
            await eventually(child.done, message="Accepted child never reached a terminal state")

        # Let any (buggy) stray scheduling of rejected children surface
        # before comparing the execution count.
        await asyncio.sleep(0.005)
        assert executions.value == len(accepted), (
            f"Expected exactly the {len(accepted)} accepted children to execute, "
            f"but {executions.value} executions were observed "
            f"({len(rejected_boxes)} creations were rejected)"
        )

        await eventually(
            lambda ctx=ctx: not ctx.collect_unsettled_children(awaitables_only=False),
            message="Context never drained after the race",
        )
        for box in rejected_boxes:
            box["coro"].close()
