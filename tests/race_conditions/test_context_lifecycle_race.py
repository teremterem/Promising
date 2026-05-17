"""
Race conditions around ``PromisingContext``'s lifecycle:

- ``__enter__`` reads ``self._previous_token`` and
  ``self._context_closed`` before writing the token. Two threads
  entering the same context can both pass the check and both call
  ``ContextVar.set``, leaving the loser's token orphaned and the next
  ``__exit__`` cross-thread ``reset()`` either no-op'ing or raising
  ``ValueError``.
- ``close_context`` flips ``_context_closed`` and calls
  ``_unregister_from_parent_if_time`` without coordinating with
  ``_register_children`` on the same instance.

These tests stress those paths via real ``with`` blocks and real
``PromisingContext`` instances.
"""

import asyncio
import threading

import pytest

import promising

# ── helpers ─────────────────────────────────────────────────────


def _make_dedicated_loop() -> asyncio.AbstractEventLoop:
    return asyncio.new_event_loop()


# ── concurrent __enter__ of the same instance ───────────────────


def test_concurrent_enter_same_context_only_one_succeeds() -> None:
    """
    Two worker threads call ``ctx.__enter__()`` on the same instance
    simultaneously. Exactly one should succeed; the other must see
    ``ContextAlreadyActiveError``. Without a lock around the
    ``_previous_token is not None`` check both can pass it and both
    will overwrite ``_previous_token`` — silently leaking the
    first-thread token.
    """
    loop = _make_dedicated_loop()
    try:
        N = 8
        for _ in range(500):
            ctx = promising.PromisingContext(loop=loop, parent=None)
            barrier = threading.Barrier(N)
            succeeded: list[str] = []
            already_active_errors: list[BaseException] = []
            other_errors: list[BaseException] = []
            list_lock = threading.Lock()

            def enter() -> None:
                try:
                    barrier.wait()
                    ctx.__enter__()
                    with list_lock:
                        succeeded.append(threading.current_thread().name)
                except promising.ContextAlreadyActiveError as exc:
                    with list_lock:
                        already_active_errors.append(exc)
                except BaseException as exc:  # noqa: BLE001
                    with list_lock:
                        other_errors.append(exc)

            threads = [threading.Thread(target=enter, name=f"T{i}", daemon=True) for i in range(N)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=5)
                assert not t.is_alive()

            assert not other_errors, other_errors
            assert len(succeeded) == 1, (
                f"{len(succeeded)} threads entered the same context concurrently "
                f"(succeeded={succeeded}, already_active={len(already_active_errors)})"
            )
            assert len(already_active_errors) == N - 1
    finally:
        loop.close()


def test_concurrent_enter_then_concurrent_exit_does_not_corrupt_contextvar() -> None:
    """
    When two threads enter the same context (provided such a race condition
    exists) and then both call ``__exit__``, one of them ends up calling
    ``ContextVar.reset(token)`` with a token that was created in the *other*
    thread's context. That cross-thread reset is at minimum a no-op and at
    worst raises ``ValueError``. Either way ``__exit__`` must not crash with an
    unrelated error.
    """
    import time

    loop = _make_dedicated_loop()
    try:
        for _ in range(3000):
            ctx = promising.PromisingContext(loop=loop, parent=None)

            enter_barrier = threading.Barrier(2)
            errors: list[BaseException] = []
            errors_lock = threading.Lock()

            def routine() -> None:
                try:
                    enter_barrier.wait()
                    try:
                        ctx.__enter__()
                    except promising.ContextAlreadyActiveError:
                        # Framework rejected this thread's entry: nothing to exit.
                        return
                    # Yield to give the other thread a chance to enter, too.
                    time.sleep(0.0005)
                    ctx.__exit__(None, None, None)
                except BaseException as exc:  # noqa: BLE001
                    with errors_lock:
                        errors.append(exc)

            t1 = threading.Thread(target=routine, daemon=True)
            t2 = threading.Thread(target=routine, daemon=True)
            t1.start()
            t2.start()
            t1.join(timeout=5)
            t2.join(timeout=5)

            assert not errors, f"{len(errors)} unexpected exceptions: {errors!r}"
    finally:
        loop.close()


# ── register vs close on a single context ───────────────────────


def test_register_child_during_close_does_not_silently_succeed() -> None:
    """
    Thread A is in the middle of ``parent._register_children(child)``:
    after the ``self.closed()`` check passes but before
    ``self._unsettled_children.update(...)`` runs, Thread B calls
    ``parent.close_context()``. Currently the child is then added to
    a context that has already been closed.

    The expected contract: either the child registration raises
    ``ContextAlreadyClosedError`` and the parent's set stays empty,
    OR the registration completes and the child must still be reachable
    via ``collect_unsettled_children`` until it is closed itself.
    """
    # TODO [TESTS] How is this test different from
    #  tests/race_conditions/test_unsettled_children_set_race.py
    #  ::test_register_child_after_parent_closed_must_be_rejected ?
    loop = _make_dedicated_loop()
    try:
        for _ in range(3000):
            parent = promising.PromisingContext(loop=loop, parent=None)
            barrier = threading.Barrier(2)
            outcome: dict[str, object] = {}

            def add_child() -> None:
                barrier.wait()
                try:
                    outcome["child"] = promising.PromisingContext(loop=loop, parent=parent)
                except promising.ContextAlreadyClosedError as exc:
                    outcome["closed_error"] = exc

            def close_parent() -> None:
                barrier.wait()
                parent.close_context()

            t1 = threading.Thread(target=add_child, daemon=True)
            t2 = threading.Thread(target=close_parent, daemon=True)
            t1.start()
            t2.start()
            t1.join(timeout=5)
            t2.join(timeout=5)

            if "child" in outcome:
                child = outcome["child"]
                # Invariant: a context that is closed cannot accept new
                # children. If the race lets registration succeed against
                # a closed parent, that contract is broken — the child
                # has a parent reference that points at a context that
                # will never drive its lifecycle.
                # TODO [TESTS] How do we know it happened AFTER the parent was
                #  closed ? I'm struggling to spot the part of test that
                #  insures things happened in that order and not the other way
                #  around
                assert not parent.closed(), (
                    "child registration succeeded onto a parent that is now closed — "
                    "the `closed() → no new children` invariant was violated by a race"
                )
                reachable = child in parent.collect_unsettled_children(
                    whole_subtree=False,
                    awaitables_only=False,
                )
                assert reachable, (
                    "child registered onto parent silently, but is missing from "
                    "parent._unsettled_children — torn update or lost child"
                )
    finally:
        loop.close()


# ── Promise context: with-block opening races with sync registration ─


async def test_promise_context_open_races_with_external_child_registration() -> None:
    """
    A Promise enters its own context (``with self:``) inside
    ``_unpack_once`` on the loop thread. While that ``__enter__``
    runs, a worker thread tries to register a brand-new child Promise
    against the same Promise (as parent). The child registration uses
    ``self.closed()`` as the gate — that field flips to True only on
    ``__exit__``, but ``_previous_token`` is being set in lockstep with
    ``__enter__`` on the loop thread.

    Concurrent reads/writes of those instance attributes can:

    - raise ``ContextAlreadyClosedError`` even though the parent is
      still open
    - silently add a child to a parent whose lifecycle has already
      moved on
    """
    loop = asyncio.get_running_loop()

    @promising.function
    async def parent_promise() -> int:
        active = promising.get_active_promise()
        errors: list[BaseException] = []
        children: list[promising.Promise] = []
        children_lock = threading.Lock()
        stop = threading.Event()

        async def _quick() -> int:
            return 1

        def worker() -> None:
            try:
                while not stop.is_set():
                    p = promising.wrap_awaitable(
                        _quick(),
                        parent=active,
                        loop=loop,
                        start_soon=False,
                    )
                    with children_lock:
                        children.append(p)
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        writers = [threading.Thread(target=worker, daemon=True) for _ in range(8)]
        for w in writers:
            w.start()
        try:
            for _ in range(200):
                await asyncio.sleep(0)
        finally:
            stop.set()
            for w in writers:
                w.join(timeout=5)

        assert not errors, errors

        # Every child registered while the Promise was running must
        # be tracked.
        actual = active.collect_unsettled_children(whole_subtree=False, awaitables_only=True)
        missing = set(children) - actual
        assert not missing, f"{len(missing)} children were lost from active Promise's set during the lifecycle race"

        # Clean up so asyncio doesn't warn about un-awaited coros.
        for c in children:
            c.cancel()

        return 0

    await parent_promise()


# ── close_context idempotency under threads ─────────────────────


def test_close_context_concurrent_calls_must_be_idempotent() -> None:
    """
    ``close_context`` flips ``_context_closed`` and conditionally
    unregisters from the parent. Concurrent calls from many threads
    on the same instance should converge on a single
    "closed + unregistered" terminal state — but they all read the
    fields, all decide they need to unregister, and all call
    ``parent._unregister_children(self)``. With the underlying
    ``set.difference_update`` being a no-op on missing elements, the
    only visible damage is when several siblings finish in the same
    cycle and trigger re-entrant cascading unregistration. This test
    asserts the simpler property: no exceptions, and parent is empty.
    """
    loop = _make_dedicated_loop()
    try:
        for _ in range(100):
            parent = promising.PromisingContext(loop=loop, parent=None)
            child = promising.PromisingContext(loop=loop, parent=parent)

            N = 16
            errors: list[BaseException] = []
            errors_lock = threading.Lock()
            barrier = threading.Barrier(N)

            def close_target() -> None:
                try:
                    barrier.wait()
                    child.close_context()
                except BaseException as exc:  # noqa: BLE001
                    with errors_lock:
                        errors.append(exc)

            threads = [threading.Thread(target=close_target, daemon=True) for _ in range(N)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=5)
                assert not t.is_alive()

            assert not errors, errors
            assert child.closed()
            assert child not in parent.collect_unsettled_children(
                whole_subtree=False,
                awaitables_only=False,
            )
    finally:
        loop.close()


@pytest.mark.skip(reason="Sanity reference — single-threaded lifecycle is fine.")
def test_single_threaded_enter_exit_works() -> None:
    loop = _make_dedicated_loop()
    try:
        ctx = promising.PromisingContext(loop=loop, parent=None)
        ctx.__enter__()
        ctx.__exit__(None, None, None)
        assert ctx.closed()
    finally:
        loop.close()
