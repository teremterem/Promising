"""
Tests for Promise.cancel() — modeled on asyncio.Future / asyncio.Task
semantics. Cancellation flows through ``_set_exception_from_loop``: the
``CancelledError`` is stored first, the ``_CANCELLED_*`` state transition
is its effect.
"""

import asyncio
import threading

import pytest

from promising import Promise, PromiseNotDoneError

# ── Cancel before any task is scheduled ──────────────────────────


async def test_cancel_pending_promise_with_no_task() -> None:
    """
    A Promise with start_soon=False that has never been awaited has no
    underlying task; cancel() should still synthesize CancelledError and
    move the Promise into the cancelled state immediately.
    """

    async def coro() -> str:
        return "never reached"

    promise = Promise(coro(), start_soon=False)

    assert promise.cancel() is True
    assert promise.cancelled() is True
    assert promise.done() is True

    with pytest.raises(asyncio.CancelledError):
        promise.result()

    with pytest.raises(asyncio.CancelledError):
        promise.exception()

    # Awaiting an already-cancelled Promise also surfaces CancelledError
    with pytest.raises(asyncio.CancelledError):
        await promise


async def test_cancel_pending_promise_with_message() -> None:
    """The cancel message is preserved on the stored CancelledError."""

    async def coro() -> str:
        return "x"

    promise = Promise(coro(), start_soon=False)
    promise.cancel("custom reason")

    with pytest.raises(asyncio.CancelledError) as exc_info:
        promise.result()
    assert exc_info.value.args == ("custom reason",)


# ── Cancel while task is running ─────────────────────────────────


async def test_cancel_running_promise() -> None:
    """
    Cancelling a started Promise interrupts the running coroutine; the
    propagated CancelledError is stored and the Promise transitions to a
    cancelled terminal state.
    """

    started = asyncio.Event()

    async def coro() -> str:
        started.set()
        await asyncio.sleep(10)
        return "unreachable"

    promise = Promise(coro(), start_soon=True)
    await started.wait()

    assert promise.cancel() is True

    with pytest.raises(asyncio.CancelledError):
        await promise

    assert promise.cancelled() is True
    assert promise.done() is True


async def test_cancel_already_done_promise_returns_false() -> None:
    """A Promise that already finished cannot be cancelled."""

    promise = Promise(prefilled_result=42)
    assert promise.cancel() is False
    assert promise.cancelled() is False
    assert promise.result() == 42


async def test_cancel_twice_idempotent() -> None:
    """Second cancel() returns False because the Promise is already done."""

    async def coro() -> str:
        return "x"

    promise = Promise(coro(), start_soon=False)
    assert promise.cancel() is True
    assert promise.cancel() is False


# ── Coroutine raising CancelledError counts as cancellation ──────


async def test_coroutine_raising_cancellederror_marks_promise_cancelled() -> None:
    """
    A coroutine that raises ``CancelledError`` itself transitions the
    Promise to a cancelled state — same as how ``asyncio.Task`` treats
    a coroutine that raises ``CancelledError``.
    """

    async def coro() -> str:
        raise asyncio.CancelledError("from inside")

    promise = Promise(coro(), start_soon=True)
    with pytest.raises(asyncio.CancelledError):
        await promise

    assert promise.cancelled() is True


# ── CancelledError stays BaseException-derived ───────────────────


async def test_cancellederror_not_caught_by_except_exception() -> None:
    """
    The CancelledError stored on the Promise is the asyncio one (which
    deliberately inherits from BaseException, not Exception), so a plain
    ``except Exception`` does not swallow it.
    """

    async def coro() -> str:
        return "x"

    promise = Promise(coro(), start_soon=False)
    promise.cancel()

    caught_as_exception = False
    try:
        promise.result()
    except Exception:  # noqa: BLE001
        caught_as_exception = True
    except asyncio.CancelledError:
        caught_as_exception = False

    assert caught_as_exception is False


# ── Querying state before done() ─────────────────────────────────


async def test_result_raises_not_done_before_cancel_propagates() -> None:
    """
    ``cancel()`` on a running task only *requests* cancellation; until the
    CancelledError lands and is stored via ``_set_exception_from_loop``, ``done()``
    stays False and ``result()`` raises ``PromiseNotDoneError``.
    """

    started = asyncio.Event()

    async def coro() -> str:
        started.set()
        await asyncio.sleep(10)
        return "unreachable"

    promise = Promise(coro(), start_soon=True)
    await started.wait()

    promise.cancel()
    # Cancellation hasn't been observed by the task yet
    assert promise.done() is False

    with pytest.raises(PromiseNotDoneError):
        promise.result()

    # Drain to keep asyncio happy
    with pytest.raises(asyncio.CancelledError):
        await promise


# ── Thread-safe cancel() ─────────────────────────────────────────


async def test_cancel_from_another_thread() -> None:
    """
    cancel() called from a thread other than the event loop's thread
    dispatches via call_soon_threadsafe and reports True once the
    cancellation request was scheduled.
    """

    started = asyncio.Event()

    async def coro() -> str:
        started.set()
        await asyncio.sleep(10)
        return "unreachable"

    promise = Promise(coro(), start_soon=True)
    await started.wait()

    cancel_result: list[bool] = []

    def cancel_in_thread() -> None:
        cancel_result.append(promise.cancel("from thread"))

    thread = threading.Thread(target=cancel_in_thread)
    thread.start()
    # Drive the event loop while the other thread hops onto it
    with pytest.raises(asyncio.CancelledError):
        await promise
    thread.join(timeout=2)

    assert cancel_result == [True]
    assert promise.cancelled() is True


# ── intermediate_promise() behavior under cancellation ───────────


async def test_intermediate_promise_raises_when_cancelled_before_unpack() -> None:
    """
    A Promise cancelled before its first unpacking step has no intermediate
    Promise to expose, so ``intermediate_promise()`` re-raises the stored
    CancelledError.
    """

    async def coro() -> str:
        await asyncio.sleep(10)
        return "unreachable"

    promise = Promise(coro(), start_soon=False)
    promise.cancel()

    with pytest.raises(asyncio.CancelledError):
        promise.intermediate_promise()
