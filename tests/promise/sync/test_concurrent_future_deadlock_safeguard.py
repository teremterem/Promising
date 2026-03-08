"""Tests for SyncUsageError safeguards on concurrent future blocking methods."""

import asyncio

import pytest

from promising import Promise
from promising.errors import SyncUsageError


async def test_result_raises_sync_usage_error_from_event_loop_thread() -> None:
    """
    Calling concurrent_future.result() from the event loop thread
    raises SyncUsageError because it would deadlock.
    """
    promise = Promise(prefill_result="hello")
    concurrent_future = promise.as_concurrent_future()

    with pytest.raises(SyncUsageError, match="deadlock"):
        concurrent_future.result()


async def test_exception_raises_sync_usage_error_from_event_loop_thread() -> None:
    """
    Calling concurrent_future.exception() from the event loop thread
    raises SyncUsageError because it would deadlock.
    """
    promise = Promise(prefill_result="hello")
    concurrent_future = promise.as_concurrent_future()

    with pytest.raises(SyncUsageError, match="deadlock"):
        concurrent_future.exception()


async def test_result_raises_sync_usage_error_even_when_done() -> None:
    """
    Calling concurrent_future.result() from the event loop thread
    raises SyncUsageError even when the future is already done.
    """

    async def sample_coro() -> str:
        return "done"

    promise = Promise(sample_coro(), start_soon=True)
    await promise

    concurrent_future = promise.as_concurrent_future()
    assert concurrent_future.done()

    with pytest.raises(SyncUsageError, match="deadlock"):
        concurrent_future.result()


async def test_exception_raises_sync_usage_error_even_when_done() -> None:
    """
    Calling concurrent_future.exception() from the event loop thread
    raises SyncUsageError even when the future is already done.
    """

    async def sample_coro() -> str:
        return "done"

    promise = Promise(sample_coro(), start_soon=True)
    await promise

    concurrent_future = promise.as_concurrent_future()
    assert concurrent_future.done()

    with pytest.raises(SyncUsageError, match="deadlock"):
        concurrent_future.exception()


async def test_result_raises_sync_usage_error_with_prefilled_exception() -> None:
    """
    Calling concurrent_future.result() from the event loop thread
    raises SyncUsageError, not the prefilled exception.
    """
    promise = Promise(prefill_exception=ValueError("test error"))
    concurrent_future = promise.as_concurrent_future()

    with pytest.raises(SyncUsageError, match="deadlock"):
        concurrent_future.result()


async def test_exception_raises_sync_usage_error_with_prefilled_exception() -> None:
    """
    Calling concurrent_future.exception() from the event loop thread
    raises SyncUsageError, not the prefilled exception.
    """
    promise = Promise(prefill_exception=ValueError("test error"))
    concurrent_future = promise.as_concurrent_future()

    with pytest.raises(SyncUsageError, match="deadlock"):
        concurrent_future.exception()


async def test_result_works_from_separate_thread() -> None:
    """
    Calling concurrent_future.result() from a separate thread works fine.
    """

    async def sample_coro() -> str:
        await asyncio.sleep(0.05)
        return "thread result"

    promise = Promise(sample_coro(), start_soon=True)
    concurrent_future = promise.as_concurrent_future()

    result = await asyncio.get_running_loop().run_in_executor(
        None,
        lambda: concurrent_future.result(timeout=1),
    )
    assert result == "thread result"


async def test_exception_works_from_separate_thread() -> None:
    """
    Calling concurrent_future.exception() from a separate thread works fine.
    """

    async def sample_coro() -> str:
        await asyncio.sleep(0.05)
        return "thread result"

    promise = Promise(sample_coro(), start_soon=True)
    concurrent_future = promise.as_concurrent_future()

    exception = await asyncio.get_running_loop().run_in_executor(
        None,
        lambda: concurrent_future.exception(timeout=1),
    )
    assert exception is None
