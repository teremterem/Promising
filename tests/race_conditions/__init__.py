"""
Race-condition test suite for the Promising framework.

Purpose
=======
Promising deliberately mixes asyncio with multi-threading: sync promising
functions run in a thread pool, ``sync()`` / ``unpack_once_sync()`` /
``await_children_sync()`` / ``cancel()`` may be called from arbitrary
threads, and Promises may even be *created* from worker threads. This suite
pins down the **concurrency contract** of the public API so that the
synchronization internals (currently a mix of a per-context
``threading.Lock``, ``call_soon_threadsafe`` dispatches, and a monotonic
state machine relying on GIL-atomic attribute reads) can be refactored with
confidence — see the ``TODO`` in ``PromisingContext.__init__``
(promising/promising_context.py) about funneling all mutations through the
event loop.

IMPORTANT: Some of these tests are EXPECTED TO FAIL against the current
implementation. They describe the *target* contract, not the status quo.
A failing test here marks a known (or suspected) synchronization gap that
the upcoming refactoring is meant to close; a test that used to pass and
starts failing marks a regression introduced by the refactoring.

Method
======
- **Barrier + herd**: racy operations are released simultaneously from
  multiple OS threads via ``threading.Barrier``
  (see ``utils_for_race_tests.run_racers``) to maximize the chance of
  landing inside the narrow racy window.
- **Repetition**: each racy window is re-created many times per test
  (races are probabilistic — a green run is evidence, not proof).
- **Behavioral assertions only**: tests assert on the public API
  (``done()``, ``result()``, ``sync()``, ``collect_unsettled_children()``,
  exception types, ...) — never on private synchronization primitives —
  so they remain valid no matter how the internals are reorganized.
- **Bounded waiting**: every blocking call carries a timeout and every
  module carries a generous ``pytest.mark.timeout``, so a broken invariant
  shows up as an assertion failure or an error, not as a hung test run.

Map of the suite
================
- ``test_state_visibility.py`` — cross-thread reads of the Promise state
  machine (``done``/``result``/``exception``/``intermediate_promise``
  consistency and monotonicity while the loop thread writes).
- ``test_exactly_once_execution.py`` — the wrapped awaitable must execute
  exactly once no matter how many threads race to consume/trigger it
  (including a mixed herd of every consumption entry point at once).
- ``test_sync_consumption_races.py`` — ``sync()`` / ``unpack_once_sync()``
  hammered at the exact moment of resolution/failure, including short
  timeouts and consumption from pool-based sync promising functions.
- ``test_cancellation_races.py`` — ``cancel()`` storms, cancellation racing
  natural completion / coroutine failure, racing lazy-start triggers,
  cancellation landing before the underlying task's first step, and
  cancellation isolation from nested (returned) Promises.
- ``test_child_registration_races.py`` — child Promise creation (from
  worker threads) racing the parent's closing/completion; creation must be
  atomic: either cleanly rejected (and never executed) or fully tracked.
  Also prefilled (born-terminal) promises: cross-thread visibility and
  registration-skipping semantics.
- ``test_hierarchy_drain_races.py`` — the unregistration cascade when many
  descendants across threads finish simultaneously; nothing may be lost
  and nothing may linger. Plus ``collect_unsettled_children`` hammered
  from threads during churn.
- ``test_await_children_races.py`` — ``await_children`` /
  ``await_children_sync`` completeness while children keep being spawned
  from worker threads and consumed from external threads; lazy children
  triggered by ``await_children`` racing external triggers; concurrent
  waiters; timeout-retry stacking; late registration never silently lost.
- ``test_context_lifecycle_races.py`` — ``PromisingContext`` enter/exit/
  close races (double-enter from two threads, close racing registration),
  the ``promising.context`` wrapper's shared CM state raced from two
  threads, and idempotency of concurrent ``close_context_threadsafe()``.
- ``test_multi_loop_races.py`` — several event loops in parallel threads
  sharing the global thread pool; contextvar isolation between trees and
  cross-loop consumption rules.
- ``test_loop_lifecycle_races.py`` — the promise's own loop shutting down
  while cross-thread consumers are blocked (fail fast, never hang) and
  the dead-loop ``NoRunningEventLoopError`` guards.
- ``test_global_state_races.py`` — concurrent first installation of the
  promising excepthooks (idempotency, no self-chained fallback hook).
"""
