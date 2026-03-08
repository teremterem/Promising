"""Tests for SyncUsageError safeguards on concurrent future blocking methods."""

import asyncio

import pytest

from promising import Promise
from promising.errors import SyncUsageError


@pytest.mark.parametrize("method", ["result", "exception"])
async def test_raises_sync_usage_error_from_event_loop_thread_with_prefilled_result(
    method: str,
) -> None:
    """
    Calling concurrent_future.result() or .exception() from the event loop
    thread raises SyncUsageError because it would deadlock.
    """
    promise = Promise(prefill_result="hello")
    concurrent_future = promise.as_concurrent_future()

    with pytest.raises(SyncUsageError, match="deadlock"):
        if method == "result":
            concurrent_future.result()
        else:
            concurrent_future.exception()


@pytest.mark.parametrize("method", ["result", "exception"])
async def test_raises_sync_usage_error_even_when_done(method: str) -> None:
    """
    Calling concurrent_future.result() or .exception() from the event loop
    thread raises SyncUsageError even when the future is already done.
    """

    async def sample_coro() -> str:
        return "done"

    promise = Promise(sample_coro(), start_soon=True)
    await promise

    concurrent_future = promise.as_concurrent_future()
    assert concurrent_future.done()

    with pytest.raises(SyncUsageError, match="deadlock"):
        if method == "result":
            concurrent_future.result()
        else:
            concurrent_future.exception()


@pytest.mark.parametrize("method", ["result", "exception"])
async def test_raises_sync_usage_error_with_prefilled_exception(
    method: str,
) -> None:
    """
    Calling concurrent_future.result() or .exception() from the event loop
    thread raises SyncUsageError, not the prefilled exception.
    """
    promise = Promise(prefill_exception=ValueError("test error"))
    concurrent_future = promise.as_concurrent_future()

    with pytest.raises(SyncUsageError, match="deadlock"):
        if method == "result":
            concurrent_future.result()
        else:
            concurrent_future.exception()

    # Now, let's retrieve the actual exception, so we don't get the asyncio
    # warning about the exception not having been retrieved.
    with pytest.raises(ValueError, match="test error"):
        await promise


@pytest.mark.parametrize("method", ["result", "exception"])
@pytest.mark.parametrize(
    ("sleep_duration", "timeout"),
    [(0.1, 0.2), (0.2, 0.1)],
    ids=["completes", "times_out"],
)
async def test_works_from_separate_thread(method: str, sleep_duration: float, timeout: float) -> None:
    """
    Calling concurrent_future.result() or .exception() from a separate
    thread works fine.
    """

    async def sample_coro() -> str:
        await asyncio.sleep(sleep_duration)
        return "thread result"

    promise = Promise(sample_coro(), start_soon=True)
    concurrent_future = promise.as_concurrent_future()

    if sleep_duration > timeout:
        with pytest.raises(TimeoutError):
            await asyncio.get_running_loop().run_in_executor(
                None,
                lambda: (
                    concurrent_future.result(timeout=timeout)
                    if method == "result"
                    else concurrent_future.exception(timeout=timeout)
                ),
            )
    else:
        value = await asyncio.get_running_loop().run_in_executor(
            None,
            lambda: (
                concurrent_future.result(timeout=timeout)
                if method == "result"
                else concurrent_future.exception(timeout=timeout)
            ),
        )

        if method == "result":
            assert value == "thread result"
        else:
            assert value is None
