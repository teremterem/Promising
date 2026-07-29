"""
Cross-thread visibility of the Promise state machine.

Promise state (``_state``, ``_result``, ``_exception``,
``_intermediate_promise``) is written only from the event loop thread
(``_set_result_from_loop`` & co.), but read from arbitrary threads via
``done()``, ``result()``, ``exception()``, ``cancelled()``,
``unpacked_once()``, ``intermediate_promise()``. The documented contract
(see ``Promise.done()``) is:

1. The state machine is **monotonic** — once a reader observes an advanced
   state, no later read may observe an earlier one.
2. State attributes are written **before** the state advances, so a reader
   that observes an advanced state must also observe the matching
   attribute (never ``done() == True`` with ``result()`` still raising
   ``PromiseNotDoneError``).

These tests hammer reader threads against a resolving/failing/cancelling
Promise and assert both properties on every snapshot. They protect the
contract during the synchronization refactoring (e.g. if plain attribute
reads get replaced with something more elaborate, or writes get reordered).
"""

import asyncio
import time

import pytest

import promising
from promising import Promise
from tests.race_conditions.utils_for_race_tests import (
    AtomicCounter,
    PromiseStateMonotonicityTracker,
    assert_no_errors,
    assert_promise_snapshot_consistent,
    eventually,
    run_racers,
)

pytestmark = pytest.mark.timeout(30)

READERS = 4
ITERATIONS = 20


async def test_readers_never_observe_done_without_result() -> None:
    """
    Reader threads spin on the state flags while the Promise resolves with
    a value on the loop thread.

    Invariants (checked on every snapshot): monotonic flags, and once
    ``done()`` is observed, ``result()`` must immediately return the value
    — the window where the state has advanced but the result is not yet
    visible to other threads must not exist.
    """
    for _ in range(ITERATIONS):
        release = asyncio.Event()
        started_readers = AtomicCounter()

        async def _coro(release: asyncio.Event = release) -> list[str]:
            await release.wait()
            return ["payload"]

        promise = Promise(_coro(), start_soon=True, parent=None)

        def _reader(promise: Promise = promise, started_readers: AtomicCounter = started_readers) -> None:
            started_readers.increment()
            tracker = PromiseStateMonotonicityTracker(promise)
            while not promise.done():
                tracker.check()
                time.sleep(0)  # yield the GIL so the loop thread can run
            tracker.check()
            # done() was observed — the result must be readable right away
            assert promise.result() == ["payload"]

        racers_future = asyncio.ensure_future(run_racers(*[_reader] * READERS))
        # Only release the result once all the readers are actively spinning,
        # so the resolution lands in the middle of the read storm.
        await eventually(lambda counter=started_readers: counter.value == READERS)
        release.set()

        _, errors = await racers_future
        assert_no_errors(errors)


async def test_readers_never_observe_done_without_exception() -> None:
    """
    Same as above, but the Promise finishes with an exception: once a
    reader observes ``done()``, ``exception()`` must immediately return
    the stored exception and ``result()`` must immediately raise it.
    """
    for _ in range(ITERATIONS):
        release = asyncio.Event()
        started_readers = AtomicCounter()

        async def _failing(release: asyncio.Event = release) -> None:
            await release.wait()
            raise ValueError("state-visibility boom")

        promise = Promise(_failing(), start_soon=True, parent=None)

        def _reader(promise: Promise = promise, started_readers: AtomicCounter = started_readers) -> None:
            started_readers.increment()
            tracker = PromiseStateMonotonicityTracker(promise)
            while not promise.done():
                tracker.check()
                time.sleep(0)
            tracker.check()
            assert isinstance(promise.exception(), ValueError)
            with pytest.raises(ValueError, match="state-visibility boom"):
                promise.result()

        racers_future = asyncio.ensure_future(run_racers(*[_reader] * READERS))
        await eventually(lambda counter=started_readers: counter.value == READERS)
        release.set()

        _, errors = await racers_future
        assert_no_errors(errors)


async def test_readers_observe_consistent_cancellation() -> None:
    """
    The Promise is cancelled on the loop thread while readers spin.

    Once a reader observes ``done()``, it must also observe
    ``cancelled() == True``, and both ``result()`` and ``exception()``
    must raise ``CancelledError`` — never ``PromiseNotDoneError``, and
    never a stale successful result.
    """
    for _ in range(ITERATIONS):
        started_readers = AtomicCounter()

        async def _never_finishes() -> None:
            await asyncio.sleep(30)

        promise = Promise(_never_finishes(), start_soon=True, parent=None)

        def _reader(promise: Promise = promise, started_readers: AtomicCounter = started_readers) -> None:
            started_readers.increment()
            tracker = PromiseStateMonotonicityTracker(promise)
            while not promise.done():
                tracker.check()
                time.sleep(0)
            tracker.check()
            assert promise.cancelled()
            with pytest.raises(asyncio.CancelledError):
                promise.result()
            with pytest.raises(asyncio.CancelledError):
                promise.exception()

        racers_future = asyncio.ensure_future(run_racers(*[_reader] * READERS))
        await eventually(lambda counter=started_readers: counter.value == READERS)
        promise.cancel()

        _, errors = await racers_future
        assert_no_errors(errors)


@promising.function
async def _final_leg(gate: asyncio.Event) -> str:
    await gate.wait()
    return "final"


@promising.function
async def _first_leg(gate: asyncio.Event) -> Promise[str]:
    # Returns another Promise — the outer Promise transitions to the
    # "unpacked once" state while its full unpacking is still in flight.
    return _final_leg(gate, start_soon=True)


async def test_readers_never_observe_unpacked_once_without_intermediate_promise() -> None:
    """
    Reader threads spin while the outer Promise performs its first
    unpacking step (which yields an intermediate Promise, not a final
    value).

    Once a reader observes ``unpacked_once()``, ``intermediate_promise()``
    must immediately return the intermediate Promise — never raise
    ``PromiseNotUnpackedError``.
    """
    for _ in range(ITERATIONS):
        gate = asyncio.Event()
        promise = _first_leg(gate)

        def _reader(promise: Promise = promise) -> None:
            while not promise.unpacked_once():
                assert_promise_snapshot_consistent(promise)
                time.sleep(0)
            intermediate = promise.intermediate_promise()
            assert isinstance(intermediate, Promise)

        racers_future = asyncio.ensure_future(run_racers(*[_reader] * READERS))
        _, errors = await racers_future
        assert_no_errors(errors)

        gate.set()
        assert await promise == "final"
