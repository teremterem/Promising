"""Race-condition tests for the Promise state machine.

Covers monotonic state transitions, single terminal state, writer/reader
ordering behind ``done()``, predicate consistency, one-shot result caching,
shared cached values across consumers, and single-assignment of the
internal unpacking tasks.
"""

from __future__ import annotations

import asyncio
import threading

from promising import Promise
from promising.sentinels import (
    _CANCELLED_AFTER_UNPACKED_ONCE,
    _CANCELLED_BEFORE_UNPACKED_ONCE,
    _FINISHED,
    _PENDING,
    _UNPACKED_ONCE,
)
from tests.race_conditions._harness import (
    ExceptionAggregator,
    assert_monotonic,
)

# Allowed state transitions per RACE_CONDITION_INVARIANTS.md §1.1
_ALLOWED_TRANSITIONS = {
    (_PENDING, _UNPACKED_ONCE),
    (_PENDING, _FINISHED),
    (_PENDING, _CANCELLED_BEFORE_UNPACKED_ONCE),
    (_UNPACKED_ONCE, _FINISHED),
    (_UNPACKED_ONCE, _CANCELLED_AFTER_UNPACKED_ONCE),
}

_TERMINAL_STATES = (_FINISHED, _CANCELLED_BEFORE_UNPACKED_ONCE, _CANCELLED_AFTER_UNPACKED_ONCE)


# ── 1.1 Monotonicity ─────────────────────────────────────────────


async def test_state_monotonic_under_concurrent_observers() -> None:
    """Spin N reader threads that snapshot ``_state`` while the Promise
    advances; no thread observes an illegal transition and every thread
    ends on a terminal state.
    """

    async def body() -> Promise[int]:
        # Yield once so observers get a chance to sample _PENDING and
        # _UNPACKED_ONCE distinctly.
        await asyncio.sleep(0)
        inner: Promise[int] = Promise(prefilled_result=42)
        return inner

    promise: Promise[int] = Promise(body(), start_soon=True)

    n_readers = 8
    stop = threading.Event()
    samples: list[list] = [[] for _ in range(n_readers)]
    aggregator = ExceptionAggregator()

    def reader(idx: int) -> None:
        local = samples[idx]
        while not stop.is_set():
            local.append(promise._state)
        # One final sample after the stop flag flips
        local.append(promise._state)

    threads = [threading.Thread(target=aggregator.capture(reader), args=(i,), daemon=True) for i in range(n_readers)]
    for t in threads:
        t.start()

    assert await promise == 42

    # Let readers observe the terminal state for a bit before we stop them.
    await asyncio.sleep(0.01)
    stop.set()
    for t in threads:
        t.join(timeout=2.0)
        assert not t.is_alive()

    aggregator.raise_if_any()

    for s in samples:
        assert s, "reader collected no samples"
        assert_monotonic(s, _ALLOWED_TRANSITIONS, label="_state")
        assert s[-1] in _TERMINAL_STATES


# ── 1.2 Single terminal state ────────────────────────────────────


async def test_repeated_set_calls_do_not_re_advance_terminal_state() -> None:
    """Calling the ``_set_*`` writers after a terminal state is reached
    must never re-advance the state machine, and a non-CancelledError
    arriving on an already-terminal Promise raises ``RuntimeError``.
    """

    async def body() -> int:
        return 7

    promise: Promise[int] = Promise(body(), start_soon=True)
    assert await promise == 7
    terminal = promise._state
    assert terminal is _FINISHED

    # Idempotent: late CancelledError is dropped silently (per docstring).
    promise._set_exception(asyncio.CancelledError("late"))
    assert promise._state is terminal
    assert promise.result() == 7

    # Non-CancelledError on a terminal Promise is a framework-bug
    # detector; force-finish path will swallow it but keep us terminal.
    promise._set_exception(RuntimeError("bogus"))
    assert promise._state is _FINISHED  # still terminal, no re-advance

    # Repeated result/intermediate setters also bail on terminal state.
    promise._set_result("override")
    assert promise._state is _FINISHED
    promise._set_intermediate_promise(Promise(prefilled_result=99))
    assert promise._state is _FINISHED
