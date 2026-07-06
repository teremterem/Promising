"""
Event loop shutdown racing cross-thread consumption.

A Promise is bound to one event loop for life, but its cross-thread entry
points (``sync()``, ``unpack_once_sync()``, ``await_children_sync()``,
``cancel()``) can be invoked while that loop is shutting down — or after
it is already gone. Two contracts pinned here:

1. **Fail fast, never hang.** A consumer blocked inside ``sync()`` when
   the promise's loop shuts down must be released promptly with an
   exception (``asyncio.run()`` cancels pending tasks at teardown, which
   must propagate out to the blocked ``concurrent.futures.Future``). The
   dangerous window is a loop that has *stopped* but not yet run the
   consumer's scheduled callback: the callback then never runs and the
   consumer waits for its full timeout (or forever, for ``cancel()``,
   which blocks on ``future.result()`` with NO timeout — see the second
   test's docstring).

2. **Dead-loop guard.** Once the loop is gone, every cross-thread entry
   point must be rejected immediately with ``NoRunningEventLoopError``
   (currently protected by ``_assert_event_loop_running_for_sync``) —
   a refactoring that funnels everything through the loop must keep
   rejecting instead of scheduling onto a loop that will never run again.
"""

import asyncio
import threading

import pytest

from promising import Promise
from promising.errors import NoRunningEventLoopError
from tests.race_conditions.utils_for_race_tests import run_racers_sync

pytestmark = pytest.mark.timeout(30)


def test_sync_blocked_when_promise_loop_shuts_down_fails_fast() -> None:
    """
    A consumer thread is blocked inside ``sync()`` on a never-finishing
    Promise when the promise's loop (owned by another thread via
    ``asyncio.run()``) shuts down. The teardown cancels pending tasks —
    including the consumer's dispatched wrapper — so the consumer must be
    released with a ``CancelledError``-flavored exception promptly.

    Reaching the consumer's own ``sync(timeout=5)`` instead means the
    shutdown did NOT propagate to the blocked thread — the "waits out its
    full timeout against a dead loop" failure mode this test forbids.
    """
    for _ in range(10):
        box: dict = {}
        created = threading.Event()
        consumer_entered = threading.Event()

        def _loop_owner(
            box: dict = box,
            created: threading.Event = created,
            consumer_entered: threading.Event = consumer_entered,
        ) -> None:
            async def _main() -> None:
                async def _never() -> None:
                    await asyncio.sleep(30)

                box["promise"] = Promise(_never(), start_soon=True, parent=None)
                created.set()
                # Hold the loop until the consumer is about to block, plus a
                # beat for its dispatched wrapper to get scheduled — then
                # return, letting asyncio.run() tear the loop down and
                # cancel all pending tasks.
                await asyncio.to_thread(consumer_entered.wait, 2)
                await asyncio.sleep(0.01)

            asyncio.run(_main())

        def _consumer(
            box: dict = box,
            created: threading.Event = created,
            consumer_entered: threading.Event = consumer_entered,
        ) -> object:
            assert created.wait(timeout=5), "Loop owner never published the Promise"
            consumer_entered.set()
            return box["promise"].sync(timeout=5)

        results, errors = run_racers_sync(_loop_owner, _consumer)
        assert errors[0] is None, f"Loop owner failed: {errors[0]!r}"

        consumer_error = errors[1]
        assert consumer_error is not None, f"sync() returned {results[1]!r} from a promise that could never resolve"
        assert not isinstance(consumer_error, TimeoutError), (
            "sync() sat out its own full timeout instead of being released by the loop shutdown"
        )


def test_cross_thread_ops_on_dead_loop_raise_clean_errors() -> None:
    """
    All cross-thread entry points invoked on a Promise whose loop has
    already finished and closed must raise ``NoRunningEventLoopError``
    immediately (currently protected — regression net).

    This guard matters most for ``cancel()``: past the check it blocks on
    ``concurrent.futures.Future.result()`` with NO timeout, so scheduling
    onto a loop that will never run its callbacks would hang the calling
    thread forever.
    """
    box: dict = {}

    def _loop_owner() -> None:
        async def _main() -> None:
            async def _never() -> None:
                await asyncio.sleep(30)  # pragma: no cover - never driven

            coro = _never()
            box["coro"] = coro
            # Lazy: no task is ever scheduled, so nothing is pending at
            # loop teardown — the Promise simply outlives its dead loop.
            box["promise"] = Promise(coro, start_soon=False, parent=None)

        asyncio.run(_main())

    owner = threading.Thread(target=_loop_owner, daemon=True)
    owner.start()
    owner.join(timeout=10)
    assert not owner.is_alive()

    promise = box["promise"]
    try:
        with pytest.raises(NoRunningEventLoopError):
            promise.sync(timeout=1)
        with pytest.raises(NoRunningEventLoopError):
            promise.unpack_once_sync(timeout=1)
        with pytest.raises(NoRunningEventLoopError):
            promise.await_children_sync(timeout=1)
        with pytest.raises(NoRunningEventLoopError):
            promise.cancel()
        assert not promise.done()
    finally:
        # The lazy coroutine was never scheduled — close it so it doesn't
        # emit a "coroutine was never awaited" warning at GC time.
        box["coro"].close()
