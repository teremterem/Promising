"""
Tests for the unregistration of a cancelled Promise from its parent
context. Cancellation is just another trigger for the same close →
unregister mechanism covered in ``test_unregister_from_parent.py``;
these tests verify it kicks in across the various cancellation paths
and interacts correctly with deferred unregistration when the
cancelled Promise still has unsettled children.
"""

import asyncio
import threading

import pytest

import promising
from promising import Promise


async def test_cancel_pending_promise_unregisters_from_parent() -> None:
    """
    Cancelling a never-started Promise (no underlying task — synthesize
    path in ``_cancel_unsafe``) must close its context so that the
    Promise unregisters from its parent. Without ``close_context_threadsafe()``
    on that path, ``_context_closed`` stays False and the child is leaked
    in the parent's ``_unsettled_children``.
    """
    with promising.context() as parent:

        async def coro() -> str:
            return "unreachable"

        promise = Promise(coro(), start_soon=False)
        assert promise._context_closed is False
        assert promise in parent._unsettled_children
        assert promise.cancelled() is False

        assert promise.cancel() is True

        assert promise.cancelled() is True
        assert promise not in parent._unsettled_children
        assert promise._context_closed is True


async def test_cancel_pending_promise_from_other_thread_unregisters_from_parent() -> None:
    """
    Synthesize path reached via the thread-safe dispatch: cancel() is
    called from a non-loop thread, which schedules ``_cancel_unsafe``
    on the loop. The unregistration must still happen, just on the loop
    thread.
    """
    with promising.context() as parent:

        async def coro() -> str:
            return "unreachable"

        promise = Promise(coro(), start_soon=False)
        assert promise._context_closed is False
        assert promise in parent._unsettled_children
        assert promise.cancelled() is False

        cancel_result: list[bool] = []

        def cancel_in_thread() -> None:
            cancel_result.append(promise.cancel("from thread"))

        thread = threading.Thread(target=cancel_in_thread)
        thread.start()
        # Yield so the threadsafe callback (and the thread blocked on its
        # future) can run on this loop. Don't await the promise itself
        # here — that would start an unpacking task and race with the
        # synthesize path we're trying to exercise.
        while not cancel_result:
            await asyncio.sleep(0.1)
        thread.join(timeout=2)

        assert cancel_result == [True]
        assert promise.cancelled() is True
        assert promise not in parent._unsettled_children
        assert promise._context_closed is True


async def test_coroutine_raising_cancelled_error_unregisters_from_parent() -> None:
    """
    When the coroutine itself raises ``CancelledError`` (no external
    cancel() call), the Promise still goes through the standard
    ``_unpack_once_from_loop`` path whose ``with self:`` closes the
    context. Verify the cancelled Promise unregisters from its parent.
    """
    with promising.context() as parent:

        async def coro() -> str:
            raise asyncio.CancelledError("from inside")

        promise = Promise(coro(), start_soon=True)
        assert promise._context_closed is False
        assert promise in parent._unsettled_children
        assert promise.cancelled() is False

        with pytest.raises(asyncio.CancelledError):
            await promise

        assert promise.cancelled() is True
        assert promise not in parent._unsettled_children
        assert promise._context_closed is True


async def test_cancel_full_unpacking_task_before_first_step_transitions_promise() -> None:
    """
    Cancelling the underlying ``_full_unpacking_task`` between
    ``create_task`` and its first ``__step`` throws ``CancelledError``
    into a not-yet-started coroutine — Python propagates that exception
    out without entering the body's ``try/except BaseException``, so the
    coroutine never calls ``_set_exception_from_loop`` itself. Without
    the done-callback bridge, the Task ends cancelled while the Promise
    stays ``_PENDING`` and leaks in its parent's ``_unsettled_children``.
    """
    with promising.context() as parent:

        async def coro() -> str:
            return "unreachable"

        promise = Promise(coro(), start_soon=True)
        # Let the threadsafe scheduling callback create the task without
        # giving the task itself a chance to take its first step.
        await asyncio.sleep(0)
        full_task = promise._full_unpacking_task
        assert full_task is not None
        assert full_task.done() is False

        full_task.cancel("preemptive")
        # Drain enough loop iterations for the cancel to land and for the
        # done-callback to run.
        for _ in range(3):
            await asyncio.sleep(0)

        # assert full_task.cancelled() is True
        assert promise.done() is True
        assert promise.cancelled() is True
        assert promise._context_closed is True
        assert promise not in parent._unsettled_children


async def test_cancel_single_unpacking_task_before_first_step_transitions_promise() -> None:
    """
    Same race as the full-unpacking variant, but for the
    ``_single_unpacking_task`` created via ``unpack_once()``. Verifies
    the done-callback is wired on both task creation sites.
    """
    with promising.context() as parent:

        async def coro() -> str:
            return "unreachable"

        promise = Promise(coro(), start_soon=False)

        async def trigger_unpack_once() -> None:
            try:
                await promise.unpack_once()
            except asyncio.CancelledError:
                pass

        unpack_driver = asyncio.create_task(trigger_unpack_once())
        # Let `unpack_once` schedule the single-unpacking task and start
        # awaiting it, but stop before the task itself runs its body.
        await asyncio.sleep(0)
        single_task = promise._single_unpacking_task
        assert single_task is not None
        assert single_task.done() is False

        single_task.cancel("preemptive")
        for _ in range(3):
            await asyncio.sleep(0)
        await unpack_driver

        assert single_task.cancelled() is True
        assert promise.done() is True
        assert promise.cancelled() is True
        assert promise._context_closed is True
        assert promise not in parent._unsettled_children


async def test_cancel_parent_promise_with_unsettled_child_defers_unregistration() -> None:
    """
    A cancelled Promise that still has unsettled child Promises must
    stay registered in its grandparent — same deferred-unregistration
    rule that applies to a normal context exit. Once the last child
    unregisters, the cancelled parent unregisters from the grandparent.
    """
    with promising.context() as grandparent:

        async def parent_coro() -> str:
            return "unreachable-parent"

        async def child_coro() -> str:
            return "unreachable-child"

        parent_promise = Promise(parent_coro(), start_soon=False)
        child_promise = Promise(child_coro(), parent=parent_promise, start_soon=False)

        assert parent_promise in grandparent._unsettled_children
        assert child_promise in parent_promise._unsettled_children

        # Cancel the parent — its context closes, but the child is still
        # unsettled, so the parent must NOT unregister from grandparent yet.
        assert parent_promise.cancel() is True
        assert parent_promise._context_closed is True
        assert parent_promise in grandparent._unsettled_children
        assert child_promise in parent_promise._unsettled_children

        # Now finish off the child — that should cascade unregistration
        # up to grandparent.
        assert child_promise.cancel() is True
        assert child_promise not in parent_promise._unsettled_children
        assert parent_promise not in grandparent._unsettled_children


async def test_cancel_one_sibling_only_unregisters_that_one() -> None:
    """
    Cancelling one Promise must not affect the registration of its
    siblings in the shared parent context.
    """
    with promising.context() as parent:

        async def coro() -> str:
            await asyncio.sleep(2)
            return "unreachable"

        sibling_a = Promise(coro(), start_soon=False)
        sibling_b = Promise(coro(), start_soon=False)
        sibling_c = Promise(coro(), start_soon=False)

        assert {sibling_a, sibling_b, sibling_c} <= parent._unsettled_children

        assert sibling_b.cancel() is True

        assert sibling_b not in parent._unsettled_children
        assert sibling_a in parent._unsettled_children
        assert sibling_c in parent._unsettled_children

        # Clean up the rest
        sibling_a.cancel()
        sibling_c.cancel()
