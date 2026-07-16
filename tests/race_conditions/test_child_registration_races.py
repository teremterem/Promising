"""
Child registration racing the parent's closing/completion.

A child registers with its parent at construction time — possibly from a
worker thread — while the parent may simultaneously be closing (its
``with`` block exiting on the loop thread, or its own completion
triggering ``close_context_threadsafe()``). The target windows in the
current implementation:

- ``Promise.__init__`` schedules execution (``call_soon_threadsafe``)
  *before* registering with the parent, and registration itself carries a
  "TODO Activate the threading lock ?" — so a child rejected by
  registration has already been scheduled and runs anyway, orphaned;
- ``_register_children_threadsafe`` (child side, any thread) vs
  ``close_context_threadsafe`` + ``_unregister_from_parent_if_time``
  (parent side, which reads ``_unsettled_children`` without the lock).

The contract these tests pin down — **creation must be atomic**:

- EITHER the constructor raises ``ContextAlreadyClosedError`` and the
  child's awaitable never executes,
- OR the constructor succeeds, the awaitable executes exactly once, and
  the child stays visible to the parent (and is therefore reachable by
  ``await_children()``) until it settles.

Silently-lost children and rejected-but-still-running children are both
contract violations. The "rejected must not execute" half is EXPECTED TO
FAIL against the current implementation (see above).
"""

import asyncio

import pytest

import promising
from promising import Promise, PromisingContext
from tests.race_conditions.utils_for_race_tests import (
    RACE_ITERATIONS,
    AtomicCounter,
    assert_no_errors,
    eventually,
    make_child_creator,
    run_racers,
    verify_atomic_creation_outcome,
)

pytestmark = pytest.mark.timeout(30)


async def test_child_creation_racing_parent_context_close_is_atomic() -> None:
    """
    A worker thread creates a child Promise (explicit ``parent=``) at the
    same moment another thread closes the parent context. Verifies the
    atomic-creation contract (see the module docstring) and that the
    parent context fully drains afterwards.
    """
    loop = asyncio.get_running_loop()

    for _ in range(RACE_ITERATIONS):
        ctx = PromisingContext(parent=None)
        ctx.__enter__()
        executions = AtomicCounter()
        box: dict = {}

        _, errors = await run_racers(
            make_child_creator(ctx, loop, executions, box),
            ctx.close_context_threadsafe,
        )
        # Unwind the contextvar on the thread that entered the context
        # (close_context_threadsafe above does not touch the contextvar).
        ctx.__exit__(None, None, None)
        assert_no_errors(errors)

        await verify_atomic_creation_outcome(ctx, executions, box)
        await eventually(
            lambda ctx=ctx: not ctx.collect_unsettled_children(awaitables_only=False),
            message="Parent context never drained after the race",
        )


async def test_child_creation_racing_parent_promise_completion_is_atomic() -> None:
    """
    Same atomicity contract, but the parent is a *Promise* whose own
    completion (triggered via ``sync()`` from a second racer thread)
    closes its context — the natural way a parent closes in real usage.
    """
    # TODO [RACE CONDITIONS] Any way to make this test fail more reliably when
    #  the respective bug exists ?
    loop = asyncio.get_running_loop()

    for _ in range(RACE_ITERATIONS):

        async def _parent_coro() -> str:
            return "parent-done"

        parent = Promise(_parent_coro(), start_soon=False, parent=None)
        executions = AtomicCounter()
        box: dict = {}

        def _finish_parent(parent: Promise = parent) -> str:
            return parent.sync(timeout=5)

        _, errors = await run_racers(
            make_child_creator(parent, loop, executions, box),
            _finish_parent,
        )
        assert_no_errors(errors)

        await verify_atomic_creation_outcome(parent, executions, box)
        await eventually(
            lambda parent=parent: not parent.collect_unsettled_children(awaitables_only=False),
            message="Parent promise never drained after the race",
        )


@promising.function
async def _tick(counter: AtomicCounter) -> None:
    counter.increment()


@promising.function(use_thread_pool=True)
def _sync_spawner(counter: AtomicCounter) -> str:
    # Fire-and-forget: the child Promise is created from the pool thread
    # and nobody awaits it here — only the root's await_children() may.
    _tick(counter)
    return "sync-done"


@promising.function
async def _root_awaits_all(counter: AtomicCounter, width: int) -> int:
    for _ in range(width):
        _sync_spawner(counter)
    await promising.await_children()
    # Captured before returning: every fire-and-forget grandchild must
    # have completed by the time await_children() released us.
    return counter.value


async def test_thread_spawned_grandchildren_complete_before_await_children_returns() -> None:
    """
    Sync promising functions running in pool threads spawn fire-and-forget
    async grandchildren (created from worker threads, registered with
    parents whose bodies are about to finish). The root's
    ``await_children()`` must catch every one of them — a lost
    registration shows up as a completion count below the expected total.
    """
    for _ in range(30):
        counter = AtomicCounter()
        assert await _root_awaits_all(counter, 5) == 5


@promising.function
async def _hub(counter: AtomicCounter, n_threads: int) -> int:
    me = promising.get_active_promise()

    def _spawn_child(me: Promise = me, counter: AtomicCounter = counter) -> None:
        async def _child(counter: AtomicCounter = counter) -> None:
            counter.increment()

        Promise(_child(), parent=me, loop=me.loop, start_soon=True)

    # N raw threads register children on this (still running) Promise
    # simultaneously — hammering the registration path itself.
    _, errors = await run_racers(*[_spawn_child] * n_threads)
    assert_no_errors(errors)

    await promising.await_children()
    return counter.value


async def test_concurrent_registration_from_many_raw_threads() -> None:
    """
    Many raw threads create children of the same live Promise at the same
    instant. Every registration must land: ``await_children()`` inside the
    parent must wait for all of them, so the completion counter observed
    right after it must equal the number of spawned children.
    """
    for _ in range(20):
        assert await _hub(AtomicCounter(), 8) == 8


async def test_prefilled_promises_created_and_read_across_threads() -> None:
    """
    Prefilled Promises are born already-terminal: the constructor stores
    the result/exception directly, on whatever thread it runs in —
    currently justified by "no outside code has a reference to this
    Promise yet". After the refactoring this cross-thread write must stay
    immediately visible: a prefilled Promise must read as ``done()`` with
    the correct value/exception both on the creating thread and on any
    other thread, with no "not done yet" window ever observable.
    """
    loop = asyncio.get_running_loop()

    for _ in range(20):

        def _create_with_result() -> Promise:
            prefilled = Promise(prefilled_result=["prefilled-value"], parent=None, loop=loop)
            assert prefilled.done()
            assert prefilled.result() == ["prefilled-value"]
            return prefilled

        def _create_with_exception() -> Promise:
            prefilled = Promise(prefilled_exception=ValueError("prefilled-boom"), parent=None, loop=loop)
            assert prefilled.done()
            assert isinstance(prefilled.exception(), ValueError)
            return prefilled

        results, errors = await run_racers(
            _create_with_result,
            _create_with_exception,
            _create_with_result,
            _create_with_exception,
        )
        assert_no_errors(errors)

        # Cross-thread visibility: promises created in worker threads must
        # read as terminal from the loop thread too, immediately.
        for prefilled in results:
            assert prefilled.done()


async def test_prefilled_child_creation_racing_parent_close_never_rejected() -> None:
    """
    Prefilled children are born done and skip parent registration
    entirely, so — unlike regular children — they can never collide with
    the parent's closing: creation must never raise
    ``ContextAlreadyClosedError`` and must never leave anything tracked on
    the parent.

    Currently protected (registration is skipped when the child is already
    ``done()``) — this is a regression net for the refactoring, where a
    naive "register everything, always" rule would start rejecting (or
    leaking) prefilled children created against a closing parent.
    """
    loop = asyncio.get_running_loop()

    for _ in range(RACE_ITERATIONS):
        ctx = PromisingContext(parent=None)
        ctx.__enter__()

        def _create_prefilled(ctx: PromisingContext = ctx) -> Promise:
            return Promise(prefilled_result="prefilled", parent=ctx, loop=loop)

        _, errors = await run_racers(_create_prefilled, ctx.close_context_threadsafe)
        ctx.__exit__(None, None, None)
        # ContextAlreadyClosedError (or anything else) here is a contract
        # violation — prefilled creation must always succeed.
        assert_no_errors(errors)
        assert ctx.collect_unsettled_children(awaitables_only=False) == set()
