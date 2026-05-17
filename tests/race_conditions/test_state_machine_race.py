"""
Race conditions around ``Promise``'s state machine.

``Promise._state`` is read and written by:

- ``_unpack_once`` / ``_unpack_fully`` on the loop thread, via
  ``_set_intermediate_promise`` / ``_set_result`` / ``_set_exception``
- ``Promise.cancel()`` and ``_synthesize_cancellation`` from *any*
  thread — public API mirrors ``Future.cancel()`` which is invokable
  off-loop
- ``done()`` / ``cancelled()`` / ``result()`` consumers from any thread

There is no lock guarding the transitions. ``_set_exception`` and
``_set_result`` perform a multi-step (read state → decide terminal
state → write state) sequence, so two threads can both observe a
``_PENDING`` state and both race to write a terminal state. The framework
either:

- raises an internal ``RuntimeError`` ("Cannot set result on a
  promise because of its current state ...") which is then swallowed
  into the Promise via ``_force_internal_error_finish``
- or silently transitions to a wrong terminal state (e.g. ``cancelled``
  after a successful ``_set_result``).

These tests aim to surface those races.
"""

import asyncio
import threading
from typing import Any

import pytest

import promising

# ── helpers ─────────────────────────────────────────────────────


def _run_threads_with_barrier(targets: list, *, join_timeout: float = 10.0) -> list[BaseException]:
    errors: list[BaseException] = []
    errors_lock = threading.Lock()
    barrier = threading.Barrier(len(targets))

    def _wrap(fn):
        def _run() -> None:
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


# ── concurrent cancel ──────────────────────────────────────────


async def test_many_threads_cancelling_same_pending_promise_yield_consistent_state() -> None:
    """
    Many worker threads race to cancel the same ``start_soon=False``
    Promise (no task scheduled yet → cancel goes through
    ``_synthesize_cancellation`` which writes ``_state``). All workers
    should agree on a single cancelled terminal state.
    """
    for _ in range(50):

        async def coro() -> int:
            return 1

        promise = promising.wrap_awaitable(coro(), parent=None, start_soon=False)

        N = 32

        def _cancel() -> None:
            promise.cancel("from worker")

        errors = _run_threads_with_barrier([_cancel] * N)
        assert not errors, errors

        assert promise.done(), "Promise must be done after concurrent cancellation"
        assert promise.cancelled(), "Promise must be in the cancelled state"

        # exception() on a cancelled Promise re-raises the stored
        # CancelledError — it must not raise RuntimeError or any other
        # internal error.
        with pytest.raises(asyncio.CancelledError):
            promise.exception()


async def test_cancel_racing_with_natural_completion_keeps_state_consistent() -> None:
    """
    Spawn a Promise that completes after a quick ``asyncio.sleep(0)``.
    Right as the loop tries to call ``_set_result``, fire many cancels
    from worker threads. The Promise must end up in *exactly one*
    terminal state — either successfully ``finished`` with the value,
    or ``cancelled``. It must never end up with a hybrid internal-error
    state or surface ``RuntimeError`` to the caller.
    """
    for _ in range(80):
        loop = asyncio.get_running_loop()

        async def coro() -> int:
            await asyncio.sleep(0)
            return 7

        promise = promising.wrap_awaitable(coro(), parent=None, loop=loop, start_soon=True)

        N = 16
        started = threading.Barrier(N + 1)

        def _cancel() -> None:
            started.wait()
            try:
                promise.cancel()
            except BaseException:  # noqa: BLE001
                # Some race losers can raise — that itself is a bug
                # worth surfacing.
                raise

        threads = [threading.Thread(target=_cancel, daemon=True) for _ in range(N)]
        for t in threads:
            t.start()

        # Race the workers against the loop step that resolves the task.
        started.wait()
        try:
            value = await promise
            outcome: dict[str, Any] = {"finished": value}
        except asyncio.CancelledError:
            outcome = {"cancelled": True}

        for t in threads:
            t.join(timeout=5)
            assert not t.is_alive()

        assert promise.done(), "Promise must reach a terminal state"
        if "finished" in outcome:
            assert not promise.cancelled()
            assert promise.result() == 7
            assert promise.exception() is None
        else:
            assert promise.cancelled()
            with pytest.raises(asyncio.CancelledError):
                promise.result()


async def test_concurrent_cancel_with_full_unpacking_promise_chain() -> None:
    """
    When a Promise has both a single-unpacking and a full-unpacking
    task scheduled, ``cancel()`` calls ``cancel`` on both. Done callbacks
    on those tasks then invoke ``_synthesize_cancellation`` via
    ``_unpacking_task_done_callback``. Multiple worker threads cancelling
    the same Promise simultaneously can cause both done-callbacks to
    fire ``_synthesize_cancellation`` against an already-transitioning
    state, triggering an internal ``RuntimeError``.
    """
    for _ in range(40):
        loop = asyncio.get_running_loop()

        async def inner_coro() -> str:
            await asyncio.sleep(0.01)
            return "ok"

        @promising.function
        async def outer_func() -> promising.Promise[str]:
            return promising.wrap_awaitable(inner_coro(), loop=loop, start_soon=True)

        promise = outer_func()

        # Schedule both unpacking paths
        async def _kick() -> None:
            await promise.unpack_once()  # schedules single-unpacking

        kick_task = loop.create_task(_kick())
        try:
            # Brief yield so the single unpacking task is in flight
            await asyncio.sleep(0)

            def _cancel() -> None:
                promise.cancel()

            errors = _run_threads_with_barrier([_cancel] * 8)
            assert not errors, errors

            try:
                await promise
            except asyncio.CancelledError:
                pass
            except BaseException:
                # The promise might also have completed before the
                # cancel landed.
                pass
        finally:
            kick_task.cancel()
            try:
                await kick_task
            except (asyncio.CancelledError, BaseException):
                pass

        assert promise.done(), f"Promise not done after cancel race: {promise!r}"

        # exception() must not raise a non-CancelledError exception.
        if promise.cancelled():
            with pytest.raises(asyncio.CancelledError):
                promise.exception()
        else:
            exc = promise.exception()
            # Any *internal* error from racing _set_* paths would show
            # up here.
            assert exc is None or isinstance(exc, asyncio.CancelledError), (
                f"unexpected exception from racing state machine: {exc!r}"
            )


async def test_concurrent_set_state_does_not_double_unregister_from_parent() -> None:
    """
    ``_set_state`` calls ``close_context()`` which calls
    ``_unregister_from_parent_if_time`` which checks ``self.done()``
    and ``not self._unsettled_children`` and then calls
    ``parent._unregister_children(self)``. Two threads transitioning
    state in lockstep can both call into parent's unregister path,
    triggering ``set.difference_update`` twice and (if cascading) racing
    further up.
    """
    loop = asyncio.get_running_loop()

    parent = promising.PromisingContext(loop=loop, parent=None)

    for _ in range(50):

        async def coro() -> int:
            return 5

        promise = promising.wrap_awaitable(coro(), parent=parent, start_soon=False)

        # Two threads call cancel — only one can actually set the
        # terminal state, but with the race both think they can.
        N = 4

        def _cancel() -> None:
            promise.cancel()

        errors = _run_threads_with_barrier([_cancel] * N)
        assert not errors, errors

        assert promise.done()
        assert promise.cancelled()

    # After all the promises cancelled, none should remain in parent.
    remaining = parent.collect_unsettled_children(whole_subtree=False, awaitables_only=False)
    assert remaining == set(), f"parent leaked {len(remaining)} children after racing cancellations"
