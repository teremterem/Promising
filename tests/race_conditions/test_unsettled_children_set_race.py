"""
Race conditions around ``PromisingContext._unsettled_children``.

The set is mutated concurrently by:

- worker threads that create new child contexts/promises (each new
  child registers itself via ``parent._register_children(self)``)
- worker threads that close child contexts (which call
  ``parent._unregister_children(self)``)
- consumers iterating the set via ``collect_unsettled_children`` /
  ``await_children``

None of these paths take a lock, so concurrent access can:

- raise ``RuntimeError: Set changed size during iteration``
- silently lose children (registration overwritten by an unregistration
  that happened in a stale snapshot)
- register children onto a parent that has *just* been closed, breaking
  the ``closed() → no new children`` invariant
- corrupt the parent's idea of who its children are after a cascading
  ``_unregister_from_parent_if_time`` re-entrance

Every test below stresses one of these surfaces. While the framework is
unprotected, they are expected to fail; they exist so locks added later
can be verified end-to-end.
"""

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

import promising

# ── helpers ─────────────────────────────────────────────────────


def _make_dedicated_loop() -> asyncio.AbstractEventLoop:
    """Brand-new event loop owned by the test, never started."""
    return asyncio.new_event_loop()


def _run_workers(targets: list, *, join_timeout: float = 15.0) -> list[BaseException]:
    """
    Run a list of nullary callables in parallel threads behind a single
    ``threading.Barrier`` so they all fire as close to simultaneously as
    possible. Returns any exceptions raised.
    """
    errors: list[BaseException] = []
    errors_lock = threading.Lock()
    barrier = threading.Barrier(len(targets))

    def _wrap(fn):
        def _run():
            try:
                barrier.wait()
                fn()
            except BaseException as exc:  # noqa: BLE001
                with errors_lock:
                    errors.append(exc)

        return _run

    threads = [threading.Thread(target=_wrap(fn), daemon=True) for fn in targets]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=join_timeout)
        assert not t.is_alive(), "Worker thread did not finish in time"

    return errors


# ── concurrent registration ──────────────────────────────────────


def test_concurrent_child_registration_keeps_all_children() -> None:
    """
    Many worker threads simultaneously construct child ``PromisingContext``
    instances under one parent. After all workers finish, the parent's
    ``_unsettled_children`` must contain *every* child that was created.
    With unsynchronized ``set.update`` calls from many threads,
    children can be lost.
    """
    loop = _make_dedicated_loop()
    try:
        for _ in range(20):
            parent = promising.PromisingContext(loop=loop, parent=None)

            N_THREADS = 64
            CHILDREN_PER_THREAD = 50

            created: list[promising.PromisingContext] = []
            created_lock = threading.Lock()

            def worker() -> None:
                local: list[promising.PromisingContext] = []
                for _ in range(CHILDREN_PER_THREAD):
                    child = promising.PromisingContext(loop=loop, parent=parent)
                    local.append(child)
                with created_lock:
                    created.extend(local)

            errors = _run_workers([worker] * N_THREADS)
            assert not errors, errors

            expected = set(created)
            actual = parent.collect_unsettled_children(whole_subtree=False, awaitables_only=False)
            missing = expected - actual
            extra = actual - expected

            assert not missing, f"{len(missing)} children were lost from the parent's _unsettled_children set"
            assert not extra, f"unexpected children appeared in the parent's _unsettled_children set: {extra!r}"
    finally:
        loop.close()


def test_collect_unsettled_children_during_concurrent_registration_does_not_raise() -> None:
    """
    A reader thread iterates ``collect_unsettled_children`` in a tight
    loop while writer threads keep registering new child contexts. With
    no lock around the set, the reader's internal ``list(set)`` snapshot
    races with mutations and can raise
    ``RuntimeError: Set changed size during iteration``.

    NOTE [race-injection / 2026-05-17]: could not be made to fail
    simultaneously with the lost-children tests in this file. The two
    bug surfaces are mutually exclusive:

    - "lost children" requires non-atomic read-modify-write on
      ``_unsettled_children`` (i.e. rebinding to a fresh set), which
      means the reader's iteration target is a *different object* than
      the writer mutates — no in-place mutation, no
      ``RuntimeError: set changed size during iteration``.
    - "set changed size during iteration" requires in-place mutation
      (``.add`` / ``.discard``) on the live set, which is atomic per
      call in CPython and therefore would not lose children.

    Pick one bug pattern, surface the other. Keep this test as
    forward-compat for nogil Python (3.13t) where set-iteration
    atomicity weakens, and as a regression guard against refactors
    that swap the atomic ``set.update`` / ``list(set)`` C calls for
    Python-level loops over the live set.
    """
    loop = _make_dedicated_loop()
    try:
        parent = promising.PromisingContext(loop=loop, parent=None)

        N_WRITERS = 16
        WRITES_PER_WRITER = 200

        writers_done = threading.Event()
        writers_finished_count = 0
        writers_finished_lock = threading.Lock()

        def writer() -> None:
            nonlocal writers_finished_count
            try:
                for _ in range(WRITES_PER_WRITER):
                    promising.PromisingContext(loop=loop, parent=parent)
            finally:
                with writers_finished_lock:
                    writers_finished_count += 1
                    if writers_finished_count == N_WRITERS:
                        writers_done.set()

        def reader() -> None:
            while not writers_done.is_set():
                parent.collect_unsettled_children(whole_subtree=True, awaitables_only=False)

        targets = [reader] + [writer] * N_WRITERS
        errors = _run_workers(targets)
        assert not errors, errors
    finally:
        loop.close()


# ── concurrent unregistration ────────────────────────────────────


def test_concurrent_child_close_keeps_consistent_set() -> None:
    """
    Many children close themselves concurrently (each call invokes
    ``parent._unregister_children(self)``). After every worker has
    finished, the parent must have an *empty* ``_unsettled_children``
    set — no leaked entries from races on ``set.difference_update``.
    """
    loop = _make_dedicated_loop()
    try:
        parent = promising.PromisingContext(loop=loop, parent=None)

        N_CHILDREN = 256
        children = [promising.PromisingContext(loop=loop, parent=parent) for _ in range(N_CHILDREN)]
        # Sanity check before the race
        assert len(parent.collect_unsettled_children(whole_subtree=False, awaitables_only=False)) == N_CHILDREN

        def make_closer(child: promising.PromisingContext):
            def _close() -> None:
                child.close_context()

            return _close

        errors = _run_workers([make_closer(c) for c in children])
        assert not errors, errors

        remaining = parent.collect_unsettled_children(whole_subtree=False, awaitables_only=False)
        assert remaining == set(), f"parent still holds {len(remaining)} stale child references after concurrent close"
    finally:
        loop.close()


def test_concurrent_registration_and_unregistration_keeps_set_intact() -> None:
    """
    Two waves run simultaneously: half the threads register new
    contexts under a parent, the other half close pre-existing children.
    Reading the set with ``len()`` from a third thread must never blow
    up and the final state must equal (pre-existing - closed +
    newly-registered).
    """
    loop = _make_dedicated_loop()
    try:
        parent = promising.PromisingContext(loop=loop, parent=None)

        N_PRE_EXISTING = 200
        pre_existing = [promising.PromisingContext(loop=loop, parent=parent) for _ in range(N_PRE_EXISTING)]

        N_NEW = 200
        new_children: list[promising.PromisingContext] = []
        new_children_lock = threading.Lock()

        def closer(child: promising.PromisingContext):
            def _close() -> None:
                child.close_context()

            return _close

        def adder() -> None:
            local = [promising.PromisingContext(loop=loop, parent=parent) for _ in range(N_NEW // 50)]
            with new_children_lock:
                new_children.extend(local)

        targets = [closer(c) for c in pre_existing] + [adder] * 50
        errors = _run_workers(targets)
        assert not errors, errors

        remaining = parent.collect_unsettled_children(whole_subtree=False, awaitables_only=False)
        assert remaining == set(new_children), (
            f"after concurrent add/close, parent's set has "
            f"{len(remaining ^ set(new_children))} discrepancies "
            f"(expected={len(new_children)}, got={len(remaining)})"
        )
    finally:
        loop.close()


# ── register-vs-close race on the *parent* ───────────────────────


def test_register_child_after_parent_closed_must_be_rejected() -> None:
    """
    ``_register_children`` reads ``self.closed()`` *before* it
    ``self._unsettled_children.update(...)``. If another thread closes
    the parent in between, the check passes but the close already
    happened and the child is silently added to a closed parent —
    breaking the ``closed() → cannot accept children`` contract.

    The framework promises ``ContextAlreadyClosedError`` when adding to
    a closed context; in the post-close-but-update-still-happens window
    we expect *either* that error, or no leaked child in the closed
    parent's set — never both "no error" and "child present".
    """
    # TODO [TESTS] How is this test different from
    #  tests/race_conditions/test_context_lifecycle_race.py
    #  ::test_register_child_during_close_does_not_silently_succeed ?
    loop = _make_dedicated_loop()
    try:
        # Run many short races to widen the window.
        for _ in range(5000):
            parent = promising.PromisingContext(loop=loop, parent=None)

            start = threading.Barrier(2)
            outcome: dict[str, object] = {}

            def add_child() -> None:
                start.wait()
                try:
                    child = promising.PromisingContext(loop=loop, parent=parent)
                    outcome["child"] = child
                except promising.ContextAlreadyClosedError as exc:
                    outcome["error"] = exc

            def close_parent() -> None:
                start.wait()
                parent.close_context()

            t1 = threading.Thread(target=add_child, daemon=True)
            t2 = threading.Thread(target=close_parent, daemon=True)
            t1.start()
            t2.start()
            t1.join(timeout=5)
            t2.join(timeout=5)

            assert not t1.is_alive() and not t2.is_alive()

            if "child" in outcome:
                child = outcome["child"]
                # Invariant: a closed parent must not accept new children.
                # If registration silently succeeded against a parent that
                # is now closed, the framework's `closed() → no new
                # children` contract has been broken by the race.
                # TODO [TESTS] How do we know it happened AFTER the parent was
                #  closed ? I'm struggling to spot the part of test that
                #  insures things happened in that order and not the other way
                #  around
                assert not parent.closed(), (
                    "child registration silently succeeded after parent was closed — invariant violated"
                )
                in_parent = child in parent.collect_unsettled_children(
                    whole_subtree=False,
                    awaitables_only=False,
                )
                assert in_parent, (
                    "registration silently succeeded but the child is missing from "
                    "the closed parent's _unsettled_children — torn write"
                )
    finally:
        loop.close()


# ── await_children race ──────────────────────────────────────────


async def test_await_children_during_concurrent_thread_registration() -> None:
    """
    Inside an ``@promising.function``, a worker thread continuously
    constructs child Promises (each ``Promise.__init__`` calls
    ``parent._register_children(self)`` on the worker thread). The loop
    thread, meanwhile, repeatedly ``await``s ``await_children()`` —
    which iterates the same ``_unsettled_children`` set.

    With no lock, the loop-side iteration (``list(set)`` inside
    ``collect_unsettled_children``) can raise
    ``RuntimeError: Set changed size during iteration``, or
    ``await_children`` can return while previously registered children
    are still unsettled.
    """

    N_WRITERS = 4
    WRITES = 200

    @promising.function
    async def parent_func() -> None:
        active = promising.get_active_promise()
        loop = asyncio.get_running_loop()
        thread_errors: list[BaseException] = []
        thread_errors_lock = threading.Lock()

        async def _quick() -> int:
            return 42

        start_barrier = threading.Barrier(N_WRITERS + 1)

        def thread_writer() -> None:
            try:
                start_barrier.wait()
                for _ in range(WRITES):
                    promising.wrap_awaitable(
                        _quick(),
                        parent=active,
                        loop=loop,
                        start_soon=False,
                    )
            except BaseException as exc:  # noqa: BLE001
                with thread_errors_lock:
                    thread_errors.append(exc)

        writers = [threading.Thread(target=thread_writer, daemon=True) for _ in range(N_WRITERS)]
        for w in writers:
            w.start()

        # Release the writers and immediately race them with await_children.
        start_barrier.wait()

        # Drain children many times to keep the race window open.
        for _ in range(20):
            await promising.await_children(whole_subtree=True)

        for w in writers:
            w.join(timeout=10)
            assert not w.is_alive()

        # Final drain.
        await promising.await_children(whole_subtree=True)

        assert not thread_errors, thread_errors

        unsettled = active.collect_unsettled_children(whole_subtree=True, awaitables_only=True)
        assert unsettled == set(), (
            f"await_children returned with {len(unsettled)} unsettled awaitable children remaining"
        )

    await parent_func()


# ── cascading unregister race ────────────────────────────────────


def test_cascading_unregister_keeps_grandparent_set_consistent() -> None:
    """
    A grandparent owns a middle-tier parent which owns many children.
    All children close simultaneously: each unregistration triggers
    ``_unregister_from_parent_if_time`` on the middle context, which
    can cascade up to the grandparent.

    The cascading path reads ``_unsettled_children`` membership and
    calls ``_unregister_children`` on the grandparent — without locking,
    two children finishing in lockstep can both observe an empty middle
    set and both try to unregister the middle from the grandparent.
    """
    loop = _make_dedicated_loop()
    try:
        for _ in range(50):
            grandparent = promising.PromisingContext(loop=loop, parent=None)
            middle = promising.PromisingContext(loop=loop, parent=grandparent)

            N = 64
            children = [promising.PromisingContext(loop=loop, parent=middle) for _ in range(N)]
            # Close middle *after* attaching children, so it stays in
            # grandparent's set until all of its children drain.
            middle.close_context()

            def make_closer(c: promising.PromisingContext):
                def _close() -> None:
                    c.close_context()

                return _close

            errors = _run_workers([make_closer(c) for c in children])
            assert not errors, errors

            grand_children = grandparent.collect_unsettled_children(
                whole_subtree=False,
                awaitables_only=False,
            )
            # After every middle-child has closed, middle should have
            # cascaded out of grandparent's set exactly once.
            assert middle not in grand_children, (
                "middle context still appears in grandparent's set even though all of its children are closed"
            )
    finally:
        loop.close()


# ── load-bearing scenario: real Promises under a parent Promise ──


async def test_concurrent_promise_creation_from_threads_registers_all() -> None:
    """
    Many worker threads inside the same parent Promise create child
    Promises concurrently. Every newly-created child must end up in
    the parent's ``_unsettled_children`` set; none must be lost.
    """

    @promising.function
    async def parent_func() -> int:
        active = promising.get_active_promise()
        loop = asyncio.get_running_loop()

        N_THREADS = 32
        CHILDREN_PER_THREAD = 20

        created: list[promising.Promise] = []
        created_lock = threading.Lock()

        async def _quick() -> int:
            return 0

        def worker() -> None:
            local = []
            for _ in range(CHILDREN_PER_THREAD):
                child = promising.wrap_awaitable(
                    _quick(),
                    parent=active,
                    loop=loop,
                    start_soon=False,
                )
                local.append(child)
            with created_lock:
                created.extend(local)

        with ThreadPoolExecutor(max_workers=N_THREADS) as ex:
            await asyncio.gather(*[loop.run_in_executor(ex, worker) for _ in range(N_THREADS)])

        expected = set(created)
        actual = active.collect_unsettled_children(whole_subtree=False, awaitables_only=True)
        missing = expected - actual
        assert not missing, f"{len(missing)} child Promises lost from the parent's set"

        # Clean up the unused coroutines so asyncio doesn't warn.
        for child in created:
            child.cancel()

        return len(created)

    n = await parent_func()
    assert n == 32 * 20


# ── sanity (would-pass) test, included for self-verification ─────


@pytest.mark.skip(reason="Sanity reference; concurrency is fine when the set is touched from one thread.")
def test_single_thread_registration_keeps_all_children_sanity() -> None:
    loop = _make_dedicated_loop()
    try:
        parent = promising.PromisingContext(loop=loop, parent=None)
        children = [promising.PromisingContext(loop=loop, parent=parent) for _ in range(1000)]
        actual = parent.collect_unsettled_children(whole_subtree=False, awaitables_only=False)
        assert actual == set(children)
    finally:
        loop.close()
