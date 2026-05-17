"""
Heavier load tests that stress thread-safety invariants the framework
must maintain regardless of CPython's GIL atomicity guarantees.

These tests do not target a single check-then-act window — they keep
many threads doing many operations until either:

- the framework raises something unexpected (``RuntimeError`` from a
  state-machine mismatch, ``ContextAlreadyClosedError`` on what should
  be a still-open context, etc.), or
- an invariant on the *final* state is violated (lost children,
  inconsistent ``done()``/``cancelled()``/``result()`` triplet, ...).

The intent: even when individual race windows are tiny on CPython, a
high-volume test eventually lands on the wrong interleaving.
"""

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor

import promising

# ── tree-shape invariants under heavy parallel construction ─────


async def test_deep_hierarchy_stress_keeps_tree_consistent() -> None:
    """
    Many sync-pool workers build a 2-level promise hierarchy in
    parallel. After all work completes the root must have awaited every
    leaf, and every leaf's parent must have unregistered cleanly.
    """

    N_PARENTS = 16
    N_CHILDREN_PER_PARENT = 32

    @promising.function
    async def leaf(idx: int) -> int:
        return idx

    @promising.function(use_thread_pool=True)
    def sync_parent(parent_idx: int) -> int:
        children = [leaf(parent_idx * 1000 + i) for i in range(N_CHILDREN_PER_PARENT)]
        total = 0
        for c in children:
            total += c.sync(timeout=5)
        return total

    @promising.function
    async def root() -> int:
        parents = [sync_parent(i) for i in range(N_PARENTS)]
        return sum(await asyncio.gather(*parents))

    expected = sum(p * 1000 * N_CHILDREN_PER_PARENT + sum(range(N_CHILDREN_PER_PARENT)) for p in range(N_PARENTS))
    for _ in range(30):
        actual = await root()
        assert actual == expected, (
            f"lost children or duplicated work in concurrent hierarchy build: {actual} vs {expected}"
        )


# ── many cancels racing with a fast natural completion ──────────


async def test_cancel_race_state_consistency_high_iterations() -> None:
    """
    For a Promise whose coroutine completes after one tick, fire a
    storm of ``cancel()`` calls from worker threads while the loop
    drives the task to completion. After settling, the *triplet*
    ``done()``/``cancelled()``/``exception()``/``result()`` must agree:

    - ``cancelled()`` True  → ``result()`` raises ``CancelledError``,
                              ``exception()`` raises ``CancelledError``
    - ``cancelled()`` False → ``result()`` returns the value,
                              ``exception()`` returns ``None``

    A torn state-machine update can put the Promise in a state where
    ``cancelled()`` is False but ``result()`` raises
    ``CancelledError`` (or vice-versa) — that's the bug we are hunting.
    """
    loop = asyncio.get_running_loop()

    for _ in range(2000):

        async def coro() -> int:
            for _ in range(3):
                await asyncio.sleep(0)
            return 42

        promise = promising.wrap_awaitable(coro(), parent=None, loop=loop, start_soon=True)

        N = 8
        ready = threading.Barrier(N + 1)

        def canceller() -> None:
            ready.wait()
            promise.cancel()

        threads = [threading.Thread(target=canceller, daemon=True) for _ in range(N)]
        for t in threads:
            t.start()

        ready.wait()

        try:
            value = await promise
            saw_value = True
        except BaseException:  # noqa: BLE001
            value = None
            saw_value = False

        for t in threads:
            t.join(timeout=5)
            assert not t.is_alive()

        assert promise.done(), f"promise did not reach a terminal state: {promise!r}"

        if saw_value:
            # We got the natural value back. The Promise's terminal
            # state must reflect that and ``result()``/``exception()``
            # must agree.
            assert not promise.cancelled(), f"await returned value={value} but promise.cancelled()=True: {promise!r}"
            assert promise.result() == value
            assert promise.exception() is None
        else:
            # We got an exception. It must be a CancelledError and
            # the Promise must be in the cancelled state.
            assert promise.cancelled(), f"await raised an exception but promise.cancelled()=False: {promise!r}"
            # result() / exception() must raise CancelledError, not
            # RuntimeError or anything else.
            raised_in_result: BaseException | None = None
            try:
                promise.result()
            except BaseException as exc:  # noqa: BLE001
                raised_in_result = exc
            assert raised_in_result is not None and type(raised_in_result).__name__ == "CancelledError", (
                f"promise.result() raised the wrong kind of exception: {raised_in_result!r}; promise={promise!r}"
            )


# ── concurrent threads doing many `await_children` cycles ───────


async def test_await_children_under_continuous_registration_load() -> None:
    """
    Heavy load: from inside a parent Promise, many worker threads
    register child Promises in tight loops. Concurrently the loop
    drains via ``await_children`` repeatedly. After settling, all
    children registered up to that point must be done and the parent
    must have no unsettled awaitable descendants.
    """

    N_WRITERS = 6
    WRITES = 100

    for _ in range(20):

        @promising.function
        async def root() -> int:
            active = promising.get_active_promise()
            loop = asyncio.get_running_loop()

            thread_errors: list[BaseException] = []
            thread_errors_lock = threading.Lock()
            all_promises: list[promising.Promise] = []
            all_promises_lock = threading.Lock()

            async def _quick() -> int:
                return 0

            start = threading.Barrier(N_WRITERS + 1)

            def writer() -> None:
                try:
                    start.wait()
                    local = []
                    for _ in range(WRITES):
                        local.append(
                            promising.wrap_awaitable(
                                _quick(),
                                parent=active,
                                loop=loop,
                                start_soon=False,
                            )
                        )
                    with all_promises_lock:
                        all_promises.extend(local)
                except BaseException as exc:  # noqa: BLE001
                    with thread_errors_lock:
                        thread_errors.append(exc)

            writers = [threading.Thread(target=writer, daemon=True) for _ in range(N_WRITERS)]
            for w in writers:
                w.start()

            start.wait()

            # Drain while workers register.
            for _ in range(30):
                await promising.await_children(whole_subtree=True)

            for w in writers:
                w.join(timeout=10)
                assert not w.is_alive()

            await promising.await_children(whole_subtree=True)

            assert not thread_errors, thread_errors

            with all_promises_lock:
                for p in all_promises:
                    assert p.done(), f"child promise not done after final drain: {p!r}"

            unsettled = active.collect_unsettled_children(whole_subtree=True, awaitables_only=True)
            assert unsettled == set(), f"{len(unsettled)} awaitable descendants left after draining"
            return 0

        await root()


# ── concurrent get_active_context across threads ────────────────


async def test_get_active_context_returns_correct_context_per_thread() -> None:
    """
    Each ``@promising.function(use_thread_pool=True)`` body runs on a
    worker thread; ``ctx.run(...)`` propagates the ``ContextVar`` so
    ``get_active_context()`` should return *that worker's* parent
    Promise inside the sync body. Many sync workers running
    concurrently must each see their own parent — never another
    worker's. A failure here points to ``ContextVar`` propagation
    being broken under contention.
    """

    @promising.function(use_thread_pool=True)
    def worker(label: str) -> tuple[str, str]:
        expected_namespace_substring = label
        active_promise = promising.get_active_promise()
        # The active promise's namespace was set explicitly to label.
        return (expected_namespace_substring, active_promise.namespace or "")

    @promising.function
    async def root() -> None:
        N = 32
        promises = [worker(f"label_{i}", namespace=f"label_{i}") for i in range(N)]
        results = await asyncio.gather(*promises)
        for expected, actual in results:
            assert expected in actual, (
                f"worker thread observed wrong active promise: expected namespace to "
                f"contain {expected!r}, got {actual!r}"
            )

    for _ in range(100):
        await root()


# ── massive concurrent close (cascading unregister) ─────────────


def test_massive_concurrent_close_grandparent_consistency() -> None:
    """
    Three-level tree: grandparent → middle (closed) → many children.
    Every child closes itself simultaneously. Cascading unregistration
    must converge on an empty grandparent, with the middle context
    unregistered exactly once. The race is around the read-then-act in
    ``_unregister_from_parent_if_time``.
    """
    loop = asyncio.new_event_loop()
    try:
        for _ in range(100):
            grandparent = promising.PromisingContext(loop=loop, parent=None)
            middle = promising.PromisingContext(loop=loop, parent=grandparent)

            N = 128
            children = [promising.PromisingContext(loop=loop, parent=middle) for _ in range(N)]
            middle.close_context()

            barrier = threading.Barrier(N)
            errors: list[BaseException] = []
            errors_lock = threading.Lock()

            def closer(c: promising.PromisingContext):
                def _go() -> None:
                    try:
                        barrier.wait()
                        c.close_context()
                    except BaseException as exc:  # noqa: BLE001
                        with errors_lock:
                            errors.append(exc)

                return _go

            threads = [threading.Thread(target=closer(c), daemon=True) for c in children]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=10)
                assert not t.is_alive()

            assert not errors, errors

            grand_unsettled = grandparent.collect_unsettled_children(
                whole_subtree=False,
                awaitables_only=False,
            )
            assert grand_unsettled == set(), (
                f"grandparent leaked {len(grand_unsettled)} entries after cascading unregister storm"
            )
    finally:
        loop.close()


# ── concurrent Promise.run from multiple threads ────────────────


def test_concurrent_independent_promise_run_invocations_isolate() -> None:
    """
    ``PromisingFunction.run()`` creates its own event loop. Multiple
    threads should be able to call ``.run()`` on the *same*
    ``@promising.function`` concurrently without leaking state across
    each other's hierarchies — the ``__active_context`` ContextVar
    must be properly per-thread/per-loop.

    NOTE [race-injection / 2026-05-17]: this test could not be made to
    fail by injecting the obvious race bugs into ``promising/``
    (non-atomic set writes, dropped ``copy_context``, dropped state
    guards, etc.). Each ``.run()`` allocates its own ``asyncio`` event
    loop in its own thread, and ``PromisingContext.__active_context``
    is a ``ContextVar`` whose value is per-thread / per-asyncio-task —
    so the threads never share an active-context slot in the first
    place. Breaking it would require an architectural change (e.g.
    replacing the ``ContextVar`` with a module-level global). Keep as
    regression guard against exactly that kind of refactor: someone
    "caching" the active promise in a global for perf would cause
    cross-thread leakage and this test would catch it.
    """

    @promising.function
    async def task(idx: int) -> int:
        return idx * 2

    N = 8

    for _ in range(50):
        results: list[int] = []
        errors: list[BaseException] = []
        lock = threading.Lock()
        barrier = threading.Barrier(N)

        def runner(idx: int) -> None:
            try:
                barrier.wait()
                value = task.run(idx)
                with lock:
                    results.append(value)
            except BaseException as exc:  # noqa: BLE001
                with lock:
                    errors.append(exc)

        threads = [threading.Thread(target=runner, args=(i,), daemon=True) for i in range(N)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
            assert not t.is_alive()

        assert not errors, errors
        assert sorted(results) == [i * 2 for i in range(N)], (
            f"results mismatch — possible cross-thread leakage of active context: {sorted(results)}"
        )


# ── sync() race with cancel — RuntimeError must not surface ─────


async def test_sync_consumers_never_observe_internal_runtime_error() -> None:
    """
    Consumers calling ``promise.sync()`` from threads must never see a
    ``RuntimeError`` originating from the framework's own state
    machine (``Cannot set result on a promise because of its current
    state ...``). Only acceptable outcomes are the value or a
    ``CancelledError``.
    """
    loop = asyncio.get_running_loop()

    for _ in range(500):

        async def coro() -> str:
            for _ in range(4):
                await asyncio.sleep(0)
            return "v"

        promise = promising.wrap_awaitable(coro(), parent=None, loop=loop, start_soon=True)

        N_CONSUMERS = 8
        N_CANCELLERS = 4

        outcomes: list[object] = []
        outcomes_lock = threading.Lock()

        start = threading.Barrier(N_CONSUMERS + N_CANCELLERS + 1)

        def consumer() -> None:
            start.wait()
            try:
                outcomes.append(("value", promise.sync(timeout=5)))
            except BaseException as exc:  # noqa: BLE001
                with outcomes_lock:
                    outcomes.append(("error", exc))

        def canceller() -> None:
            start.wait()
            promise.cancel()

        with ThreadPoolExecutor(max_workers=N_CONSUMERS + N_CANCELLERS) as ex:
            consumer_futs = [loop.run_in_executor(ex, consumer) for _ in range(N_CONSUMERS)]
            canceller_futs = [loop.run_in_executor(ex, canceller) for _ in range(N_CANCELLERS)]
            start.wait()
            await asyncio.gather(*consumer_futs, *canceller_futs)

        for kind, payload in outcomes:
            if kind == "value":
                assert payload == "v", f"unexpected value from sync(): {payload!r}"
            else:
                # Any exception must be a CancelledError — not RuntimeError,
                # PromiseNotDoneError, etc.
                assert type(payload).__name__ == "CancelledError", (
                    f"sync() raised internal/unexpected error during cancel race: "
                    f"{type(payload).__module__}.{type(payload).__qualname__}: {payload!r}"
                )
