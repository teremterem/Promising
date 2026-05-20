# Race-Condition Invariants for Promising

A catalogue of properties that must hold under arbitrary thread/event-loop
interleavings. Each invariant is phrased as a postcondition that a test can
assert after exercising a chosen race window. The list is intended as a
checklist for building a `tests/race_conditions/` suite that hammers each
invariant with many concurrent actors, repeats, and (where useful)
`hypothesis` schedules.

Scope notes:

- Promising explicitly targets the GIL-backed CPython interpreter (see the
  thread-safety contract on `Promise.done()`). Single-attribute reads/writes
  are assumed atomic; tests should still cover the *ordering* guarantees, not
  the per-attribute atomicity.
- All "from any thread" invariants must be checked from at least three
  vantage points: the Promise's own event-loop thread, a thread-pool worker
  belonging to the same loop, and an unrelated (foreign) thread.

---

## 1. Promise state machine

### 1.1 Monotonicity
Once `_state` advances past `_PENDING`, it never moves backwards. Allowed
transitions only:

- `_PENDING → _UNPACKED_ONCE`
- `_PENDING → _FINISHED`
- `_PENDING → _CANCELLED_BEFORE_UNPACKED_ONCE`
- `_UNPACKED_ONCE → _FINISHED`
- `_UNPACKED_ONCE → _CANCELLED_AFTER_UNPACKED_ONCE`

Test: spin N threads that repeatedly snapshot `_state`. Across the entire run
no thread observes a regression, and the recorded transition (sorted by wall
time) matches one of the allowed pairs.

### 1.2 Single terminal state
A Promise reaches exactly one terminal state (`_FINISHED`,
`_CANCELLED_BEFORE_UNPACKED_ONCE`, or `_CANCELLED_AFTER_UNPACKED_ONCE`) — and
reaches it at most once. Repeated calls to `_set_result_from_loop` /
`_set_exception_from_loop` / `_set_intermediate_promise_from_loop` after a
terminal state never re-advance it.

### 1.3 Writer/reader ordering (the contract behind `done()`)
For every state advance, the matching attribute is observable to readers
*before* the state flip:

- `_state == _UNPACKED_ONCE` ⇒ `_intermediate_promise is not None`.
- `_state == _FINISHED` and `_exception is None` ⇒ `_result is not UNCHANGED`.
- `_state in (_FINISHED, _CANCELLED_*)` and `_exception is not None` ⇒
  `_exception` is fully populated (not a partial assignment).

Test: thread A drives the Promise to completion; thread B busy-loops calling
`done()` and, the *instant* it sees `True`, calls `result()` /
`exception()` / `intermediate_promise()` without yielding. Those calls must
never raise `PromiseNotDoneError`, `PromiseNotUnpackedError`, nor the
`RuntimeError("Promise result is UNCHANGED…")` fallback in `result()`.

### 1.4 Predicate consistency under concurrent reads
At any instant, the predicate triple
`(done(), unpacked_once(), unpacked_once_or_done())` is consistent with one
single underlying `_state` value. No reader ever sees a combination such as
`done()==True and unpacked_once_or_done()==False`.

### 1.5 Result/exception caching is one-shot
For any awaitable handed to `Promise(...)`, the awaitable's `__await__` (or
equivalent) is driven exactly once across all concurrent consumers
(`await`, `sync`, `unpack_once`, `unpack_once_sync`, and any mix of them
fired in parallel). A counter inside the awaitable must read `1` after the
storm.

### 1.6 Consumers all observe the same cached value
N consumers from M threads — `await`, `sync()`, `unpack_once_sync()` — that
finish without exception receive `is`-identical results (when the result is
a non-primitive object). When the Promise finished with an exception, every
consumer sees the *same* exception instance (`is`-identical).

### 1.7 No "task created twice"
`_full_unpacking_task` is assigned exactly once; same for
`_single_unpacking_task`. Concurrent calls to
`_ensure_from_loop_full_unpacking_scheduled` /
`_ensure_from_loop_single_unpacking_scheduled` from rapid-fire await/sync
storms never produce two Tasks for the same role. (This invariant relies on
those methods only ever running on the Promise's own loop — that itself is
checked by invariant 4.1.)

---

## 2. Parent–child hierarchy (`_unsettled_children`)

### 2.1 No lost child
For every `Promise` / `PromisingContext` created with a parent, between
construction and the parent's eventual settling, the child appears in the
parent's `_unsettled_children` at least once. A test that spawns K children
concurrently while another thread snapshots
`parent._unsettled_children` must, in aggregate, witness every child id.

### 2.2 No stuck child
After the entire subtree is done, every ancestor's `_unsettled_children` is
empty. In particular,
`root.collect_unsettled_children(whole_subtree=True)` returns `set()` once
all leaves have settled, regardless of the order in which threads drove
them.

### 2.3 No double-register / double-unregister
The child appears in `parent._unsettled_children` at most once at any
moment. After unregister, it does not reappear. A concurrent stream of
`_register_children_threadsafe` / `_unregister_children_threadsafe` calls
must keep the set's element count consistent with a serial schedule
(check by counting `add`/`remove` operations against final size).

### 2.4 Iteration safety
Iterating `collect_unsettled_children` from one thread while another thread
register/unregisters children must never raise (`RuntimeError: Set changed
size during iteration`), and the returned snapshot must be a *consistent*
subset of `add`s up to some serializable point (no torn reads). The lock
inside `collect_unsettled_children` enforces this; the test is to flood the
set and assert no exception is raised in 1e5 iterations.

### 2.5 `closed()` after `close_context_threadsafe()` from another thread
After `close_context_threadsafe()` returns on thread A, any thread B's
subsequent call to `register_children_threadsafe` raises
`ContextAlreadyClosedError`. There must be no window in which `closed()`
returns `True` on one thread while another thread's `register` call slips
through and adds a child.

### 2.6 Late child cannot enter a closed context
A child whose `__init__` overlaps with the parent's
`close_context_threadsafe()` either (a) registers successfully and is later
properly drained, or (b) raises `ContextAlreadyClosedError`. There is no
third outcome — in particular the child must never be silently dropped while
its constructor still considered the parent alive.

### 2.7 Unregister ordering
`_unregister_from_parent_if_time` only unregisters when
`done() and not _unsettled_children`. Under concurrency, no parent ever sees
its child unregister while the child still has unsettled descendants. Test
by polling `parent._unsettled_children` and, for each child observed there,
asserting that either the child is not yet done, or it itself has unsettled
descendants. The set difference must always be empty.

### 2.8 No registration on a torn parent
A child's `_parent` pointer is set in `__init__` before the registration
call. Snapshotted in any reader thread, `child._parent` is always either
the originally captured value or `None` (when explicitly created as a root)
— never an unrelated context.

---

## 3. Cancellation

### 3.1 `cancel()` is thread-safe and never deadlocks
`Promise.cancel()` invoked simultaneously from K foreign threads against
the same Promise completes in bounded time, returns a deterministic result
(at most one `True`, rest `False` once the Promise is terminal), and never
deadlocks regardless of which thread the event loop runs on.

### 3.2 Cancellation always yields a terminal state
Every successful `cancel()` (`returned True` for at least one caller)
results in `done() == True and cancelled() == True` eventually (bounded by
a generous timeout). The Promise never lingers in a non-terminal state when
the loop is alive. This includes the corner case where
`task.cancel()` lands between `create_task` and the first `__step` — the
`_unpacking_task_done_callback` synthesize-path must drive the Promise to
terminal.

### 3.3 Result vs cancel race
If a Promise's underlying awaitable resolves in the same time window as a
foreign-thread `cancel()`, the outcome is *one of*:

- terminal `_FINISHED` with the produced result/exception, `cancel()` did
  not flip the state; or
- terminal `_CANCELLED_BEFORE_UNPACKED_ONCE` / `_CANCELLED_AFTER_UNPACKED_ONCE`,
  with a `CancelledError` stored as `_exception`.

The result must never be: torn state, two terminal states recorded, or a
mix of "result stored" + "exception stored".

### 3.4 Idempotent cancellation
Repeated `cancel()` calls on an already-cancelled Promise return `False`
and do not raise. A `CancelledError` arriving on an already-terminal
Promise via `_set_exception_from_loop` is silently dropped (per docstring).
A non-CancelledError arriving on a terminal Promise raises `RuntimeError`
(framework bug detector) — tests should assert this never happens under
normal user-driven races.

### 3.5 Wake-up of waiters
After `cancel()` from a foreign thread, every consumer blocked on `await`,
`.sync()`, or `unpack_once_sync()` is unblocked within a bounded time and
sees `CancelledError` (or its `__cause__` chain) — none hang indefinitely.

### 3.6 Cancellation propagates only as documented
Cancelling a *parent* Promise does **not** cancel a nested (returned-from)
Promise that the parent is currently awaiting (per the inline TODO in
`_fully_unpack_from_loop`). Tests should pin this current behaviour so any
future change is intentional.

### 3.7 Awaitable cleanup on synthesize-cancel
When `cancel()` synthesizes a `CancelledError` for a never-started Promise,
the wrapped coroutine is `close()`d exactly once (no "coroutine was never
awaited" warning across many runs).

---

## 4. Event-loop discipline

### 4.1 "From loop only" methods stay on the loop
Methods documented as "can only be used from the event loop of the Promise"
(`_ensure_from_loop_*`, `_unpack_once_from_loop`,
`_fully_unpack_from_loop`, `_set_*_from_loop`, `_cancel_from_loop`,
`_synthesize_cancellation_from_loop`) must never be invoked from a foreign
thread. Test: install a thread-id assertion at the top of each (a
test-only monkeypatch is fine) and run the full race suite — the assertion
must never trigger.

### 4.2 `SyncUsageError` is raised, not deadlock
Calling `promise.sync()`, `promise.unpack_once_sync()`, or
`await_children_sync()` from the Promise's own event-loop thread raises
`SyncUsageError` *immediately*, even when the call lands in the same
microsecond window as a foreign-thread `cancel()` or `await`. No deadlock,
no spurious success.

### 4.3 `start_soon=True` scheduling
A Promise created with `start_soon=True` from a non-loop thread eventually
schedules its full-unpacking task on the correct loop — even when the
constructing thread immediately drops its reference. Test: construct 10k
Promises in a thread pool, all targeting the same loop, then assert all
reach a terminal state.

### 4.4 No leaked task references on prefilled / never-awaited Promises
A prefilled Promise (`prefilled_result=…` or `prefilled_exception=…`) never
constructs `_full_unpacking_task` or `_single_unpacking_task`. A Promise
constructed with `start_soon=False` that is then cancelled before any
`await` also leaves both task attributes as `None`. Holds across concurrent
constructor/cancel races.

### 4.5 Loop-mismatch detection is race-free
`await promise` from a different running loop than `promise.loop` raises
`EventLoopMismatchError` synchronously. Holds even when the Promise's own
loop is concurrently mutating the Promise's state.

---

## 5. `await_children()` under churn

### 5.1 Eventual quiescence
`await_children(whole_subtree=True)` returns once all descendants are
done, even if children spawn new grand-children during the wait. Tests
should fan out a tree where leaves themselves spawn new leaves on
resolution, and assert the call still returns.

### 5.2 No surprise hang from non-awaitable contexts
A non-awaitable `PromisingContext` child does not stall its parent's
`await_children()` — they are filtered out by `awaitables_only=True`.
Tests should mix `promising.context` siblings with `Promise` siblings and
assert quiescence.

### 5.3 Exceptions in children do not interrupt the wait
`await_children` uses `return_exceptions=True`. If half of N concurrent
children fail and half succeed, the call still completes and the parent
sees its `_unsettled_children` drained.

### 5.4 Sync counterpart cannot deadlock
`await_children_sync()` from the event-loop thread raises
`SyncUsageError`. From a foreign thread it completes within a bounded
timeout for any subtree that would have completed under `await_children`.

### 5.5 `unpack_promises_fully=False` lets parents return early
With `unpack_promises_fully=False`, the call returns as soon as every
direct child has reached `unpacked_once_or_done()` — even if their full
unpacking is still in flight. Subsequent reads of those children must
still show monotonic state progression (invariant 1.1) without crashing.

---

## 6. `ContextVar` activation (`__active_context`)

### 6.1 Per-task isolation
Two coroutines running on the same loop, each inside their own
`with ctx:` block, see their own context as active when they call
`get_active_context()`. The `ContextVar` must not leak across tasks.

### 6.2 Activation is non-reentrant
Entering the same `PromisingContext` instance twice (concurrently or
sequentially) raises `ContextAlreadyActiveError`. Under concurrent
attempts, exactly one `__enter__` succeeds and the rest raise; the
successful one's `__exit__` correctly restores the previous token.

### 6.3 Cross-thread context inheritance
A sync promising function (with `use_thread_pool=True`) launched in a
worker thread sees its parent Promise as the active context (per the
`contextvars.copy_context()` call in `PromisingFunction._call_wrapped`).
Holds even when the parent Promise's own state is concurrently changing.

### 6.4 No active-context bleed across worker invocations
A thread-pool worker that finishes one sync promising function and is
reused for an unrelated callable observes no leftover `__active_context`
from the previous job.

---

## 7. Exception attachment (`try_to_link_exception`)

### 7.1 Deepest context wins, exactly once
`exception.__promising_context__` is set by the deepest context whose
`with` block sees the exception, and not overwritten by ancestors. Holds
under concurrent re-raise paths (e.g. multiple sibling Promises failing
simultaneously, each running on its own thread-pool worker).

### 7.2 No torn attribute writes
A reader thread that observes `__promising_context__` on an exception
also observes a matching `__promising_collapse_traceback__` boolean. The
two attributes never appear in a half-set state.

---

## 8. Settings frozen at creation

### 8.1 Defaults snapshot
A Promise's resolved settings (`_start_soon`, `_start_soon_default`,
`_children_start_soon`, `_collapse_tracebacks`, `_thread_pool`) are
captured during `__init__` and never change afterwards. Mutating
`promising.Defaults.*` from another thread during construction either
takes effect for that specific Promise (because `__init__` read the
default before the mutation) or does not — but the Promise's snapshot is
internally consistent: every getter on it returns the same value
throughout its lifetime.

### 8.2 No cross-promise leak via parent inheritance
When child Promise A inherits a setting from parent P at construction
time, and concurrently child Promise B is constructed from P, mutating
P's setting between the two (where API allows) does not retroactively
change A's resolved value.

---

## 9. Thread-pool dispatch

### 9.1 Correct executor used
A sync promising function with `use_thread_pool=True` runs on the
executor returned by `get_thread_pool_executor()` of its active Promise,
regardless of which thread called the wrapper. Test by tagging worker
threads per executor and asserting the function body ran on the
expected pool.

### 9.2 No starvation deadlock from sibling sync calls
Multiple sibling sync promising functions submitted to the same
bounded-size `ThreadPoolExecutor`, each performing `.sync()` on another
*non-overlapping* sibling, all complete. (Mutual `.sync()` between two
siblings that contends on the same pool is a user-side deadlock — that
is documented behaviour, not an invariant; tests should isolate it.)

---

## 10. `wrap_awaitable` / construction races

### 10.1 Bare-coroutine wrapping is concurrency-safe
`wrap_awaitable(coro)` invoked from K threads with K different coroutines
never produces a Promise that is associated with the wrong coroutine,
nor a Promise whose `_awaitable is None` despite an awaitable being
passed.

### 10.2 Validation runs before parent registration
`Promise.__init__` validates arguments before calling `super().__init__`.
Therefore, on validation failure, the parent's `_unsettled_children`
must not contain the would-be child. Test: feed bad arguments
concurrently with valid sibling construction; the parent's set never
contains a `Promise` instance that later raised in `__init__`.

---

## 11. `Defaults` mutation under load

### 11.1 No torn Promise from a flipping `START_SOON`
A test thread flips `Defaults.START_SOON` between `True` and `False` in a
tight loop while another thread constructs Promises. Every Promise either
has `_start_soon == True` (and was scheduled) or `_start_soon == False`
(and was not). No Promise is left in an in-between state where it was
scheduled but `_start_soon` reads `False`, or vice versa.

---

## 12. Sentinel safety

### 12.1 `Sentinel.__bool__` is unreachable from internal code
Under any of the races above, no internal code path produces a
`SentinelUsageError` (which would indicate the framework itself
truthiness-tested a sentinel). Tests should set up exception capture and
assert zero `SentinelUsageError` instances across the run.

---

## Suggested test harness primitives

Useful building blocks for the `tests/race_conditions/` suite:

- **`spin_until(predicate, timeout)`** — a tight `while not predicate()`
  loop with a generous timeout, used as the "observe the moment the flag
  flips" probe.
- **`run_on_many_threads(callable, n, *args)`** — fork N threads, all
  blocked on a `threading.Barrier`, then released simultaneously.
- **`assert_monotonic(samples, allowed_transitions)`** — given a list of
  observed states (with timestamps), assert that the sorted sequence is
  a valid walk through the documented state graph.
- **`exception_aggregator()`** — capture `SystemExit` /
  `BaseException` from all threads so a thread-only failure cannot be
  silently lost by the test driver.
- **stress repeats** — wrap each invariant in a loop of, say, 200
  iterations to surface low-probability windows. Combine with
  `pytest-repeat` or hypothesis stateful machines for schedule fuzzing.
- **dual-loop fixture** — one event loop in the main thread, another in
  a background thread, so cross-loop invariants (4.5, 6.3) get
  exercised.
