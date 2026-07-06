"""
Cancellation racing everything else.

``Promise.cancel()`` is documented as thread-safe and mirrors
``asyncio.Task.cancel()`` semantics. The racy windows targeted here:

- many threads cancelling the same Promise simultaneously;
- cancellation racing natural completion (the terminal state must be
  exactly one of "finished with the result" / "cancelled" — consistent
  with what every consumer observes);
- cancellation racing the ``start_soon=True`` scheduling callback right
  after creation (including creation from a worker thread), which
  exercises the ``_unpacking_task_done_callback`` bridge and the
  synthesized-cancellation path;
- cancellation of a lazy, never-started Promise from threads (exactly one
  cancel call may "win");
- cancellation racing a ``sync()`` call that is itself about to trigger
  execution;
- a child being cancelled from a thread while the parent is inside
  ``await_children()`` (the parent must not hang and must not fail).
"""

import asyncio

import pytest

import promising
from promising import Promise
from tests.race_conditions.utils_for_race_tests import (
    RACE_ITERATIONS,
    RACER_THREADS,
    assert_no_errors,
    eventually,
    run_racers,
)

pytestmark = pytest.mark.timeout(30)


async def test_concurrent_cancel_storm_on_running_promise() -> None:
    """
    N threads cancel the same in-flight Promise simultaneously. None of
    the calls may raise, the Promise must reach the cancelled terminal
    state exactly once, every consumer must observe ``CancelledError``,
    and a post-terminal ``cancel()`` must report ``False``.
    """
    for _ in range(RACE_ITERATIONS):
        started = asyncio.Event()

        async def _coro(started: asyncio.Event = started) -> None:
            started.set()
            await asyncio.sleep(30)

        promise = Promise(_coro(), start_soon=True, parent=None)
        await started.wait()

        _, errors = await run_racers(*[promise.cancel] * RACER_THREADS)
        assert_no_errors(errors)

        with pytest.raises(asyncio.CancelledError):
            await promise
        assert promise.cancelled()
        assert promise.done()
        assert promise.cancel() is False, "cancel() on an already-terminal Promise must return False"


async def test_cancel_racing_natural_completion() -> None:
    """
    A fast-finishing Promise is cancelled from a thread at a random moment
    around its completion. The outcome must be exactly one of:

    - the Promise finished: consumers get the result, ``cancelled()`` is
      False;
    - the Promise was cancelled: consumers get ``CancelledError``,
      ``cancelled()`` is True.

    Never both, never neither, never a hang, and ``cancel()`` itself must
    never raise.
    """
    for iteration in range(RACE_ITERATIONS):

        async def _coro(iteration: int = iteration) -> list[str]:
            # Jitter the completion moment relative to the cancel call so
            # different iterations hit different interleavings.
            for _ in range(iteration % 5):
                await asyncio.sleep(0)
            return ["natural"]

        promise = Promise(_coro(), start_soon=True, parent=None)

        _, errors = await run_racers(promise.cancel)
        assert_no_errors(errors)

        try:
            value = await promise
        except asyncio.CancelledError:
            assert promise.cancelled()
            with pytest.raises(asyncio.CancelledError):
                promise.result()
        else:
            assert value == ["natural"]
            assert not promise.cancelled()
            assert promise.result() is value

        assert promise.done(), "Promise must reach a terminal state either way"


async def test_create_and_cancel_immediately_from_worker_threads() -> None:
    """
    Worker threads create ``start_soon=True`` Promises and cancel them
    immediately — the cancellation races the ``call_soon_threadsafe``
    callback that schedules the unpacking task, hitting both the
    "no task scheduled yet, synthesize the cancellation" path and the
    "task cancelled before its first step" bridge
    (``_unpacking_task_done_callback``).

    Every such Promise must reach a terminal cancelled state — a Promise
    stuck forever in a non-terminal state would wedge any parent's
    ``await_children()``.
    """
    loop = asyncio.get_running_loop()

    for _ in range(RACE_ITERATIONS):

        def _create_and_cancel() -> Promise[None]:
            async def _coro() -> None:
                await asyncio.sleep(30)

            created = Promise(_coro(), start_soon=True, parent=None, loop=loop)
            created.cancel()
            return created

        results, errors = await run_racers(*[_create_and_cancel] * 4)
        assert_no_errors(errors)

        for created_promise in results:
            await eventually(
                created_promise.done,
                message="Cancelled-at-birth Promise never reached a terminal state",
            )
            assert created_promise.cancelled()


async def test_concurrent_cancel_of_lazy_promise_has_exactly_one_winner() -> None:
    """
    N threads cancel a lazy (``start_soon=False``, never consumed) Promise
    simultaneously. The cancellation is synthesized without any task
    involvement; mirroring ``Future.cancel()``, exactly one call must
    report ``True`` and the rest ``False``.
    """
    for _ in range(RACE_ITERATIONS):

        async def _coro() -> None:
            pass  # pragma: no cover - must never run

        promise = Promise(_coro(), start_soon=False, parent=None)

        results, errors = await run_racers(*[promise.cancel] * RACER_THREADS)
        assert_no_errors(errors)

        assert promise.cancelled()
        assert results.count(True) == 1, f"Expected exactly one winning cancel(), got {results.count(True)}"


async def test_cancel_racing_sync_trigger() -> None:
    """
    One thread ``sync()``-s a lazy Promise (thereby triggering its
    execution) while another thread cancels it, released simultaneously.

    The consumer must observe an outcome consistent with the Promise's
    terminal state: either the value (not cancelled) or
    ``asyncio.CancelledError`` (cancelled) — the same exception type
    ``await`` would raise, since ``sync()`` is documented as its
    synchronous counterpart. ``cancel()`` itself must never raise.

    KNOWN DISCREPANCY (this test currently fails on it): ``sync()`` blocks
    on ``run_coroutine_threadsafe(...).result()``, and when the underlying
    coroutine is cancelled the ``concurrent.futures.Future`` re-raises
    ``concurrent.futures.CancelledError`` — which in Python ≥3.8 is a
    *separate* class inheriting from ``Exception``, NOT
    ``asyncio.CancelledError`` (which inherits from ``BaseException``).
    Callers who catch ``asyncio.CancelledError`` around ``sync()`` will
    miss it, and generic ``except Exception`` handlers will swallow it.
    The refactoring should translate the exception at the ``sync()``
    boundary (the same applies to ``unpack_once_sync()`` and
    ``await_children_sync()``).
    """
    for _ in range(RACE_ITERATIONS):

        async def _coro() -> list[str]:
            await asyncio.sleep(0.005)
            return ["late"]

        promise = Promise(_coro(), start_soon=False, parent=None)

        def _consumer(promise: Promise = promise) -> list[str]:
            return promise.sync(timeout=5)

        results, errors = await run_racers(_consumer, promise.cancel)
        assert errors[1] is None, f"cancel() raised: {errors[1]!r}"

        consumer_error = errors[0]
        if consumer_error is None:
            assert results[0] == ["late"]
            assert not promise.cancelled()
        else:
            assert isinstance(consumer_error, asyncio.CancelledError), (
                f"sync() must raise CancelledError on cancellation, got: {consumer_error!r}"
            )
            assert promise.cancelled()

        assert promise.done()


@promising.function
async def _stuck_child(started: asyncio.Event) -> None:
    started.set()
    await asyncio.sleep(30)


@promising.function
async def _parent_awaiting_children(child_box: dict, started: asyncio.Event) -> str:
    child_box["child"] = _stuck_child(started)
    # Must return even though the child gets cancelled midway —
    # await_children() waits for terminal states, tolerating failures.
    await promising.await_children()
    return "parent-done"


async def test_child_cancelled_from_thread_does_not_wedge_parent_await_children() -> None:
    """
    A parent sits in ``await_children()`` while its child is cancelled
    from a worker thread. The cancellation must count as the child
    settling: the parent must resolve normally, not hang and not fail.
    """
    for _ in range(10):
        child_box: dict = {}
        started = asyncio.Event()

        parent_promise = _parent_awaiting_children(child_box, started)
        await started.wait()

        _, errors = await run_racers(child_box["child"].cancel)
        assert_no_errors(errors)

        assert await parent_promise == "parent-done"
        assert child_box["child"].cancelled()
