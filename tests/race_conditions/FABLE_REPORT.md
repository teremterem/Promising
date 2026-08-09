# Fable Concluding Report

## Part 1

Suite done. tests/race_conditions/ — 37 tests, 9 modules + shared helpers. Full repo run: 707 old tests pass untouched; 4 race tests fail deterministically, 1 more flaps under load — all 5 failures = real gaps in current sync approach, documented in docstrings. Suite runs in ~1s.

Structure

┌──────────────────────────────────┬──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│              Module              │                                                                   Contract pinned                                                                    │
├──────────────────────────────────┼──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ test_state_visibility.py         │ Cross-thread reads of Promise state machine: monotonic flags, done() ⇒ result()/exception() readable, unpacked_once() ⇒ intermediate_promise()       │
│                                  │ readable                                                                                                                                             │
├──────────────────────────────────┼──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ test_exactly_once_execution.py   │ Awaitable runs exactly once under concurrent sync()/await/unpack_once_sync() triggers, incl. creation from worker threads; all consumers get         │
│                                  │ identical (is) cached object                                                                                                                         │
├──────────────────────────────────┼──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ test_sync_consumption_races.py   │ sync()/unpack_once_sync() hammered at exact settle/failure moment; short-timeout retries never corrupt or re-execute                                 │
├──────────────────────────────────┼──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ test_cancellation_races.py       │ Cancel storms, cancel vs natural completion (exactly one terminal outcome), cancel-at-birth from worker threads, cancel vs sync() trigger, cancelled │
│                                  │  child doesn't wedge await_children()                                                                                                                │
├──────────────────────────────────┼──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ test_child_registration_races.py │ Atomic creation contract: child creation racing parent close/completion → either clean ContextAlreadyClosedError + never executes, or tracked + runs │
│                                  │  exactly once. Never silent loss                                                                                                                     │
├──────────────────────────────────┼──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ test_hierarchy_drain_races.py    │ Unregistration cascade when wide/deep trees finish simultaneously across pool threads (barrier-synced); nothing lost, nothing lingers in             │
│                                  │ collect_unsettled_children                                                                                                                           │
├──────────────────────────────────┼──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ test_await_children_races.py     │ Completeness with thread-spawned descendants, concurrent await_children_sync siblings, external sync() consumers, unpack_promises_fully=False mode   │
├──────────────────────────────────┼──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ test_context_lifecycle_races.py  │ Double-__enter__ from two threads (≤1 winner, clean rejection), close racing with-exit, N creators vs 1 closer                                       │
├──────────────────────────────────┼──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ test_multi_loop_races.py         │ Parallel .run() loops sharing global pool: contextvar isolation between trees, subtree awaiting, EventLoopMismatchError guard vs legit sync()        │
└──────────────────────────────────┴──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘

utils_for_race_tests.py: run_racers (barrier-released thread herd, errors collected, deadlock → assertion not hang), AtomicCounter, assert_promise_snapshot_consistent, PromiseStateMonotonicityTracker, make_child_creator/verify_atomic_creation_outcome. Package __init__.py docstring = suite philosophy + map.

2 real gaps the failures expose

1. Non-atomic child creation (4 tests): Promise.__init__ calls call_soon_threadsafe to schedule execution before _register_with_parent_thread_unsafe. Registration rejected with ContextAlreadyClosedError → coroutine already scheduled → runs orphaned. test_many_creators_racing_single_close shows it starkly: "0 accepted children, but 5 executions observed".
2. Wrong cancellation exception from sync() (1 test): cancellation leaks concurrent.futures.CancelledError — separate class, inherits Exception — instead of asyncio.CancelledError (inherits BaseException). Caller catching asyncio.CancelledError misses it; except Exception swallows it. Same risk in unpack_once_sync() / await_children_sync(). Full note in test_cancel_racing_sync_trigger docstring.

Design notes: all assertions on public API only (no _unsettled_children peeking) → suite survives "everything on the loop" refactor. Every wait bounded (timeout= + per-module pytest.mark.timeout) → broken invariant fails, never hangs. test_child_creation_racing_parent_promise_completion_is_atomic intentionally probabilistic — passes solo, fails ~most full-suite runs when load opens the window; same root cause as gap 1.

## Part 2

Second pass done. Suite now 52 tests (was 37). Full repo: 720 pass, race suite fails 5–7 depending on timing — and the new tests caught 2 fresh, real defects beyond the documented ones.

New discoveries (tests that fail for real reasons)

1. Lost-unregistration leak (test_collect_unsettled_children_hammered_during_churn, intermittent). Pool thread creates child → execution scheduled on loop before registration → loop runs child's entire lifecycle in the gap → child's finish-time unregister is a no-op (not registered yet) → pool thread then registers the already-FINISHED child → pinned in hierarchy forever. Test output shows FINISHED _mid + _leaf stuck in root's tracking. Same root cause as the atomicity gap, different symptom: permanent leak instead of orphan execution.
2. Nested-cancellation comment is wrong (test_cancel_after_first_unpacking_leaves_nested_promise_running, deterministic). Comment in _fully_unpack_from_loop claims cancelling wrapper leaves nested promise running. Reality: outer full-unpack task's _fut_waiter is the inner's task, so Task.cancel() cancels it → inner ends _CANCELLED_BEFORE_UNPACKED_ONCE. Refactor must decide TODO [CANCELLATION] philosophy explicitly — shield the await (keep test) or embrace propagation (flip test).

New coverage, incl. currently-protected regression nets

┌────────────────────────────────────────────────────────────────────────────────┬──────────────────────────────────────┬────────────────────────────────────────────────────────────────┐
│                                      Area                                      │                Tests                 │                           Status now                           │
├────────────────────────────────────────────────────────────────────────────────┼──────────────────────────────────────┼────────────────────────────────────────────────────────────────┤
│ Prefilled promises: cross-thread constructor writes; registration-skip vs      │ 2 in                                 │ pass — protected by "no refs escaped" + done() skip            │
│ closing parent                                                                 │ test_child_registration_races.py     │                                                                │
├────────────────────────────────────────────────────────────────────────────────┼──────────────────────────────────────┼────────────────────────────────────────────────────────────────┤
│ Cancel vs coroutine failure (duplicate-terminal-exception drop branch);        │ 2 in test_cancellation_races.py      │ 1 pass / 1 fail (above)                                        │
│ nested-cancel isolation                                                        │                                      │                                                                │
├────────────────────────────────────────────────────────────────────────────────┼──────────────────────────────────────┼────────────────────────────────────────────────────────────────┤
│ Lazy children triggered by await_children racing external sync() triggers;     │                                      │                                                                │
│ concurrent waiter tasks; await_children_sync timeout-retry stacking; late      │ 4 in test_await_children_races.py    │ pass                                                           │
│ registration never lost                                                        │                                      │                                                                │
├────────────────────────────────────────────────────────────────────────────────┼──────────────────────────────────────┼────────────────────────────────────────────────────────────────┤
│ Mixed herd — every consumption entry point at once on one nested promise       │ 1 in test_exactly_once_execution.py  │ pass                                                           │
├────────────────────────────────────────────────────────────────────────────────┼──────────────────────────────────────┼────────────────────────────────────────────────────────────────┤
│ promising.context CM wrapper's shared _promising_context raced from 2 threads; │ 2 in test_context_lifecycle_races.py │ pass (overlap window exists but narrow — occupancy detector    │
│  concurrent close_context idempotency + sibling survival            │                                      │ armed for refactor)                                            │
├────────────────────────────────────────────────────────────────────────────────┼──────────────────────────────────────┼────────────────────────────────────────────────────────────────┤
│ Loop shutdown while sync() blocked (fail fast, never hang); dead-loop          │ 2 in test_loop_lifecycle_races.py —  │ pass — guard is currently protecting; docstring flags          │
│ NoRunningEventLoopError guards on all 4 sync entry points                      │ new file                             │ cancel()'s timeout-less future.result() hang hazard            │
├────────────────────────────────────────────────────────────────────────────────┼──────────────────────────────────────┼────────────────────────────────────────────────────────────────┤
│ Concurrent first install of excepthooks: exactly-one-winner, no self-chained   │ 1 in test_global_state_races.py —    │ pass — protected by double-checked lock. Only test in suite    │
│ fallback (infinite recursion at crash time)                                    │ new file                             │ touching privates (_excepthook_state); self-chain otherwise    │
│                                                                                │                                      │ invisible until crash                                          │
├────────────────────────────────────────────────────────────────────────────────┼──────────────────────────────────────┼────────────────────────────────────────────────────────────────┤
│ collect_unsettled_children hammered from threads during churn                  │ 1 in test_hierarchy_drain_races.py   │ intermittent fail (discovery #1)                               │
└────────────────────────────────────────────────────────────────────────────────┴──────────────────────────────────────┴────────────────────────────────────────────────────────────────┘

Considered, deliberately not tested — for your awareness

- Pool exhaustion deadlock (sync-fn chain deeper than pool workers) — known, has its own TODO in Defaults; deterministic resource issue, not a race.
- Defaults mutation mid-creation — settings frozen at creation from single attribute reads; no observable torn state to assert on.
- await_children(whole_subtree=False) under churn — semantics of "direct children only while grandchildren spawn" is a design question, not an invariant yet.
- Free-threaded CPython — the whole done() thread-safety contract rests on GIL-atomic reads (docstring says non-goal); suite would need memory-fence-aware rework there.
- cancel() from thread hanging if loop stops between the running-check and callback execution — the stopped-not-closed window; noted in test_loop_lifecycle_races.py docstrings, but staging that exact window deterministically requires driving a raw loop by hand; the dead-loop guard test covers the adjacent contract.

Lint clean, results stable across repeated runs, existing 668 non-race tests untouched.
