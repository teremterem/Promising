# Race-Condition Invariants for the `promising` Framework

A catalogue of properties that must hold even when multiple threads / tasks
hit the same `Promise` or `PromisingContext` concurrently. Each entry is
shaped so a test can target it: **invariant → why it can break → suggested
stressor**.

The framework intentionally exposes cross-thread access (sync functions in
a `ThreadPoolExecutor`, `.sync()` / `await_children_sync()` from arbitrary
threads, cross-thread cancellation, etc.), so most of these invariants are
*not* protected by the single-event-loop assumption — they need real
locking, atomic reads/writes, or careful state-machine design.

---

## 1. `Promise` state machine

The legal transitions are:

```
_PENDING ──► _UNPACKED_ONCE ──► _FINISHED
   │                │
   │                └──► _CANCELLED_AFTER_UNPACKED_ONCE
   └──► _CANCELLED_BEFORE_UNPACKED_ONCE
   └──► _FINISHED                            (exception before unpack)
```

### 1.1. Terminal states are absorbing
Once `_state` is `_FINISHED`, `_CANCELLED_BEFORE_UNPACKED_ONCE`, or
`_CANCELLED_AFTER_UNPACKED_ONCE`, no further transition is allowed.
- **Break vector:** `_set_result` / `_set_exception` /
  `_set_intermediate_promise` racing each other from the single-unpack
  task, the full-unpack task, `cancel()`'s synthesize path, and
  `_unpacking_task_done_callback`.
- **Stressor:** schedule `cancel()` from N threads at random points during
  `_unpack_once`/`_unpack_fully`; assert final state is one of the legal
  terminals and matches the first writer's intent.

### 1.2. No "spontaneous" transition out of `_PENDING`
`_state` only leaves `_PENDING` via a `_set_*` call that observed
`_state is _PENDING` (or `_UNPACKED_ONCE`) under the framework's own
serialisation. There must be no path where two writers both observe
`_PENDING`, both proceed, and both mutate state.
- **Break vector:** `_set_intermediate_promise` checks `is _PENDING` then
  writes `_intermediate_promise` then writes `_state`. A concurrent
  `_set_exception(CancelledError)` could interleave between the check and
  the writes.
- **Stressor:** monkey-patch `_set_state` to `await asyncio.sleep(0)`
  between assignment and `close_context()`; trigger cancellation in that
  window.

### 1.3. `done()`, `cancelled()`, `unpacked_once()` are monotonic
`done()` may only flip `False → True`. Same for `cancelled()` once True,
and for `unpacked_once()` once True.
- **Break vector:** an in-progress `_set_*` that fails midway through (the
  state-machine assertion raises) calls `_force_internal_error_finish`,
  which re-writes `_state = _FINISHED` and `_exception`. If
  `done()` was already True via a different path the second write must
  not regress any predicate.
- **Stressor:** poll `done()` / `cancelled()` from a hot loop on another
  thread while the Promise resolves; assert no observed regression.

### 1.4. Predicate coherence
At any single read, the *combination* of `done()` / `cancelled()` /
`unpacked_once()` must be consistent with one of the five legal
`_state` values. Equivalently: `done() implies unpacked_once_or_done()`;
`cancelled() implies done()`; if `_intermediate_promise is None` then
`unpacked_once() implies (exception is not None or _state is _FINISHED)`.
- **Break vector:** `_set_state` writes `_state` then calls
  `close_context()` (non-atomic with the surrounding `_result` /
  `_exception` / `_intermediate_promise` write).
- **Stressor:** read all five accessors back-to-back from another thread
  while resolution is in flight; check the snapshot maps to one valid
  state row in a truth table.

### 1.5. `_result` is set iff `_state is _FINISHED` and `_exception is None`
`result()` must never raise `RuntimeError("Promise result is UNCHANGED…")`
in a healthy run. The internal `_result == UNCHANGED` guard in `result()`
is a tripwire for a state/result write reordering.
- **Stressor:** call `.result()` on a hot loop while many concurrent
  consumers `await` the same Promise.

### 1.6. `_exception` and `_result` are mutually exclusive
After `done()`, exactly one of `_exception` / `_result` is the "real"
value. Specifically: `_exception is not None` ⇔ `_result is UNCHANGED` ⇔
`result()` raises. Holds even across the `_force_internal_error_finish`
path.

---

## 2. Unpacking-task lifecycle

### 2.1. At most one `_single_unpacking_task` ever exists per Promise
`_ensure_single_unpacking_scheduled` is the only place that creates one
and gates on `_single_unpacking_task is None and not unpacked_once_or_done()`.
Two callers must never both pass that gate.
- **Break vector:** `unpack_once()` is async (runs on the loop thread, no
  preemption between Python statements) — but it can also be triggered
  indirectly via `unpack_once_sync()` from another thread, which uses
  `run_coroutine_threadsafe` to dispatch back to the loop, and via
  `_unpack_fully` calling `_ensure_single_unpacking_scheduled` after an
  `await`.
- **Stressor:** N coroutines each `await promise.unpack_once()` on the
  same Promise concurrently; assert exactly one `_single_unpacking_task`
  object identity ever existed.

### 2.2. At most one `_full_unpacking_task` ever exists per Promise
Symmetric to 2.1; gated by `_full_unpacking_task is None and not done()`.
- **Stressor:** N consumers `await promise` + M threads call
  `.sync()` simultaneously on the same Promise; assert single full-task
  identity.

### 2.3. The two task slots, once written, are never overwritten
`_single_unpacking_task` / `_full_unpacking_task` are written exactly
once, in the `None → Task` direction.

### 2.4. A Task scheduled by `_ensure_*_scheduled` must run its done-callback
`_unpacking_task_done_callback` is the only thing that catches the
"cancelled between `create_task` and the first `__step`" race. It must
fire even if the loop is being torn down — otherwise the Promise stays
non-terminal.

### 2.5. `unpacked_once_or_done()` flips True before the
`_single_unpacking_task` becomes `done()`
The body of `_unpack_once` calls `_set_*` *before* returning. Any
consumer that observes `_single_unpacking_task.done()` must already see
`unpacked_once_or_done()`.

---

## 3. Cancellation

### 3.1. A single `cancel()` call drives the Promise terminal
After `cancel()` returns `True`, eventually `done()` becomes `True`. If
no underlying task is running, `cancel()` makes that transition happen
synchronously via `_synthesize_cancellation`. There must be no path
where `cancel()` returns `True` but the Promise stays `_PENDING`
forever.

### 3.2. Concurrent `cancel()` calls don't corrupt state
N threads call `.cancel()` simultaneously. Outcome:
- exactly one stored exception (the first one wins; later
  `CancelledError`s are silently dropped per `_set_exception`)
- `_state` is one of `_CANCELLED_BEFORE_UNPACKED_ONCE` /
  `_CANCELLED_AFTER_UNPACKED_ONCE`
- the Promise is unregistered from its parent exactly once.

### 3.3. `cancel()` racing with natural completion
If `cancel()` lands the same instant the body completes successfully,
the final state is *either* `_FINISHED` with a result *or* a cancelled
state — never both, never neither, and never `_FINISHED` with a stored
`CancelledError` masquerading as a real exception.
- **Break vector:** `_set_result` is called by the body, `cancel()` then
  synthesises a `CancelledError` after `done()` already flipped.
  `_set_exception` has an explicit branch for "already-terminal +
  CancelledError → drop". Verify that branch covers every interleaving.

### 3.4. `_synthesize_cancellation` always closes the context
The comment in `_synthesize_cancellation` is load-bearing: without
`close_context()` the child never unregisters. Invariant: every code
path that lands in `_CANCELLED_*` must have run `close_context()`
at least once.
- **Stressor:** cancel a `start_soon=False` Promise that was never
  awaited; assert it unregisters from its parent immediately.

### 3.5. Cancel of parent does NOT cancel nested ("returned") Promise
The TODO around `_unpack_fully` notes this intentional design. The
inner Promise's task keeps running independently. Test that cancelling
the outer leaves the inner's `_state` untouched.

---

## 4. Parent / child hierarchy (`_unsettled_children`)

### 4.1. A child is registered exactly once and unregistered exactly once
Independent of how many tasks/threads race through its construction and
resolution.
- **Break vector:** `_register_with_parent` runs at the end of
  `__init__` (after super init). For a sync `@promising.function`
  promise, that body runs on a worker thread while the parent's
  `_unsettled_children.update(...)` mutates a `set` from a non-loop
  thread.
- **Stressor:** spawn K sync child promises in parallel inside one
  parent's body; after parent finishes assert `len(_unsettled_children) == 0`
  and that the set never raised `RuntimeError: Set changed size during
  iteration` during a concurrent `collect_unsettled_children`.

### 4.2. `_unsettled_children` is never read inconsistently
`collect_unsettled_children` builds a `list[…](self._unsettled_children)`
from a `set`. On CPython this snapshot is safe only because the GIL
serializes `set.__iter__`'s C-level iteration with `set.add` / `set.discard`
*at most* — there is still a documented `RuntimeError: Set changed size
during iteration` window if the iteration is interleaved at the Python
level (i.e. across more than one bytecode boundary).
- **Stressor:** repeatedly call `collect_unsettled_children(whole_subtree=True)`
  while children are being registered/unregistered from worker threads;
  assert no exception escapes.

### 4.3. `closed()` parents reject new children
`_register_children` raises `ContextAlreadyClosedError` if `closed()` is
True. Invariant: there is no interleaving in which a child gets added to
a parent *after* the parent's `close_context()` ran.
- **Break vector:** `close_context()` sets `_context_closed = True` then
  unregisters. A child being constructed concurrently can read
  `_context_closed == False` between those statements? It runs
  before — but child registration happens *after* parent unregister
  attempt, so a worker thread mid-construction could miss the flag flip.
- **Stressor:** start a parent Promise that finishes very fast, fire off
  many sync grandchildren from a worker thread mid-finish, assert each
  either succeeds *or* gets a clean `ContextAlreadyClosedError`.

### 4.4. `await_children()` does terminate when all descendants settle
The outer `while children := …` loop terminates iff no descendant ever
escapes registration. Tests should provoke deeply nested cross-thread
spawns and confirm `await_children()` always returns in finite time.
- **Break vector:** a grandchild registers with its parent *after* the
  parent's set was last sampled by `collect_unsettled_children`, but
  *before* the parent finished `done()`. The outer loop should still
  pick it up on the next iteration. Verify with adversarial scheduling.

### 4.5. Parent's `_unregister_from_parent_if_time` is correct under races
The guard `done() and not _unsettled_children` is checked
non-atomically. If a child finishes (calls
`parent._unregister_children(self)` → `parent._unregister_from_parent_if_time`)
exactly as a new grandchild is added, the parent must not unregister
prematurely and orphan the grandchild.

### 4.6. Re-entry protection
`PromisingContext.__enter__` checks `_previous_token is not None` and
`_context_closed`. A context must never be successfully entered twice
concurrently from different tasks/threads (the framework comment at
`promising_context.py:749` flags this as a known race).

---

## 5. `__active_context` ContextVar

### 5.1. After every balanced `with ctx:` block, the active context is restored
Even if the block ran on a worker thread (with `contextvars.copy_context()`
propagation), or if multiple async tasks race over the same
`PromisingContext` instance.

### 5.2. No leak across thread-pool boundaries
A sync `@promising.function` body executes in a thread-pool thread with
the active-context ContextVar set via `ctx.run(...)`. The worker thread's
default contextvars must be unaffected when the next executor task uses
the same worker thread.
- **Stressor:** submit N sync functions to a 1-worker pool; between
  jobs, assert `PromisingContext.get_active_context(raise_if_none=False)`
  on that worker thread is `None`.

### 5.3. Concurrent enters on distinct contexts in the same task don't lose tokens
Stacked `with` blocks must restore in LIFO order even if intermediate
asynchronous suspensions happened.

---

## 6. Cross-thread sync APIs

### 6.1. `promise.sync()` from many threads on the same Promise returns the same value
Each caller drives `run_coroutine_threadsafe(awaitable_as_coroutine(self),
self.loop)` and blocks. Invariant: every caller observes the cached
result; the underlying function executes exactly once.
- **Stressor:** N threads `.sync()` the same not-yet-started
  (`start_soon=False`) Promise; assert the body ran exactly once and all
  returned the same value.

### 6.2. `.sync()` deadlock guard fires under every interleaving
`_assert_no_sync_usage_deadlock` raises `SyncUsageError` if called on
the loop thread. There must be no race where the check observes "not on
loop" but the actual `concurrent_future.result()` blocks the loop.

### 6.3. `unpack_once_sync()` fast-path is consistent
The fast-path returns directly when `unpacked_once_or_done()`. If two
threads call `unpack_once_sync()` and one takes the slow path, both must
end up observing the same `_intermediate_promise` (or final value /
exception).

### 6.4. `await_children_sync()` is a faithful sync mirror of `await_children()`
Driven via `run_coroutine_threadsafe` — must terminate iff the async
version would; must not deadlock when the loop is healthy.

---

## 7. Eager scheduling (`start_soon=True`)

### 7.1. `start_soon=True` schedules the full-unpack task before `__init__` returns
For `start_soon=True`, the call to `_ensure_full_unpacking_scheduled`
happens before `_register_with_parent`. Invariant: by the time the
parent sees the child in `_unsettled_children`, the child's task is
already on the loop.

### 7.2. Eager + deferred mix doesn't drop work
A parent with `children_start_soon=False` whose body spawns 100 children
and then exits without awaiting them must still see all children in its
`_unsettled_children`, and the parent's `await_children()` (called by
`protected_run`) must execute every one exactly once.

### 7.3. `_resolve_start_soon` snapshots are not torn
The decision tree in `_resolve_start_soon` reads
`parent_context._children_start_soon`. The parent's settings are
"frozen at creation time" per README §"Settings Are Frozen at Creation
Time". A child being constructed concurrently with the parent's
constructor finishing must still read fully-initialized parent settings.

---

## 8. Settings inheritance / global `Defaults`

### 8.1. A Promise's resolved settings are immutable after construction
After `__init__` returns, `_start_soon`, `_start_soon_default`,
`_children_start_soon`, `_collapse_tracebacks`, `_thread_pool`, `_loop`,
`_parent` never change. Tests should assert this under concurrent
mutation of `Defaults.*` and concurrent context entry.

### 8.2. Mutating `Defaults.START_SOON` mid-flight does not retroactively change behaviour
A test flips `Defaults.START_SOON` from `True` to `False` while a tree
of promises is being constructed and resolved; the already-created
promises continue with their captured value, while new ones reflect the
new default.

### 8.3. `Defaults.PROMISING_THREAD_POOL` swap is safe
Replacing the global pool while promises are running must not strand
any submitted callable.

---

## 9. Excepthook installation

### 9.1. `install_promising_tracebacks()` is idempotent
Called inside `_unpack_once` on every first run, often from many
promises in parallel. Must produce stable `sys.excepthook` /
`threading.excepthook` values regardless of interleaving.
- **Stressor:** create thousands of root-level promises in parallel;
  capture `sys.excepthook` at the end; assert it equals the installed
  promising excepthook (not the default and not double-wrapped).

---

## 10. Cross-event-loop guards

### 10.1. `_assert_awaiting_on_correct_event_loop` always sees the right loop
When a Promise's `loop` was inherited from its parent and the parent's
loop is no longer running (or a different loop is current), `await
promise` raises `EventLoopMismatchError` *deterministically* — not
"sometimes hangs, sometimes raises".

### 10.2. A Promise created on one loop, awaited on another, raises
Even when both loops are alive simultaneously on different threads.

---

## 11. Result-caching idempotence

### 11.1. The wrapped callable runs at most once per Promise
Even under N concurrent `await` + `.sync()` + `unpack_once()` consumers.
- **Stressor:** wrap a callable that increments a counter; saturate it
  with all four consumption APIs from multiple threads; assert
  counter == 1.

### 11.2. Identity invariant: `await p` and `p.sync()` and `p.result()`
return the *same* object (not just equal)
For non-Promise return values, the cached `_result` is returned by
identity. Concurrent consumers must all get `is`-equal results.

---

## 12. `intermediate_promise()` visibility

### 12.1. After `unpacked_once_or_done()` returns True, `intermediate_promise()`
either returns the stored intermediate Promise or raises the stored
exception
There must be no race where `unpacked_once_or_done()` is True but
`intermediate_promise()` raises `PromiseNotUnpackedError`.

### 12.2. The intermediate Promise's parent linkage is set before it is reachable
The intermediate Promise is created inside the outer Promise's
`with self:` block, so its parent is the outer. Concurrent
`get_trace()` on the inner must see the outer as ancestor immediately.

---

## 13. Tracing / observability

### 13.1. `get_trace()` is consistent
A concurrent reader walking parents via `get_parent_context()` always
sees an acyclic chain ending at a root. Even during mass
register/unregister churn, no cycle ever appears, and `get_trace()`
terminates.

### 13.2. `format_trace()` / `print_trace()` don't raise on a context being
unregistered concurrently
`__repr__` reads `self.namespace` and `id(self)` — both immutable —
so the only race surface is the parent chain walk in `get_trace`. Fuzz
test confirming.

---

## 14. Memory / leak invariants

### 14.1. After `await promise` returns, the awaitable is released
The promise holds `_awaitable`, which after consumption serves no
purpose. Verify (with `weakref`) that the awaitable's referents become
collectable promptly after settlement, including the `cancel()`-pre-start
path that calls `awaitable.close()` in `_synthesize_cancellation`.

### 14.2. After a parent fully resolves and `await_children()` returns,
`_unsettled_children` is empty
And the parent itself is unregistered from *its* parent. Otherwise the
tree leaks across runs.

---

## 15. Frame-summary capture race

### 15.1. `frame_summary_tuple` reflects the constructor's caller
`traceback.walk_stack` runs on the constructing thread before
`super().__init__` returns. If the constructor is called from a thread
pool worker, the captured stack must be that worker's stack (not the
loop's). Test by spawning from a sync function and inspecting frames.

---

## Practical guidance for tests

- Use `asyncio.sleep(0)` injected via monkey-patch into the framework's
  state-transition methods (`_set_state`, `_set_exception`,
  `_register_with_parent`, `close_context`) to widen race windows
  deterministically.
- Pair every "happy path" race test with an "exception path" twin: the
  most likely state-machine corruption sites are the `try/except
  BaseException` blocks that funnel into
  `_force_internal_error_finish`.
- For thread-pool stress, prefer a custom small pool (1–2 workers) and
  many submissions — that maximises contention on `_unsettled_children`
  and `__active_context`.
- For cancellation stress, alternate `cancel()` callers between the loop
  thread and a non-loop thread, and target the four phases (before
  schedule, after schedule but before first `__step`, mid-await, after
  unpack_once).
- For each invariant, assert both the *terminal* property (final state
  is legal) and the *transient* property (no intermediate observation
  violated a monotonicity / coherence rule).
