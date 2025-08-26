#!/usr/bin/env python3
"""
Simple test script to verify the as_concurrent_future() method works.
"""
import asyncio
import concurrent.futures
import threading
from typing import Optional
import pytest
from promising.promises import Promise


@pytest.mark.parametrize("start_soon", [True, False, None])
@pytest.mark.parametrize("await_promise", [True, False, None])
@pytest.mark.parametrize("get_future_before_await", [True, False])
async def test_as_concurrent_future(
    start_soon: Optional[bool],
    await_promise: Optional[bool],
    get_future_before_await: bool,
):
    """
    Test Promise.as_concurrent_future().
    """

    call_count = 0

    # Create a Promise
    if start_soon is None:
        # `start_soon=None` in our test means that we want to create a prefilled promise
        promise = Promise(prefill_result="Hello from Promise!")
    else:

        async def sample_coro():
            nonlocal call_count
            call_count += 1
            await asyncio.sleep(0.1)
            return "Hello from Promise!"

        promise = Promise(sample_coro(), start_soon=start_soon)

    if get_future_before_await:
        # Get the concurrent future before we await for anything
        concurrent_future = promise.as_concurrent_future()

    if await_promise is True:
        await promise
    elif await_promise is False:
        # Let's await in general, but not for the promise specifically
        await asyncio.sleep(0.2)
    # `await_promise=None` in our test means that we don't want to await for anything at all (no task switching)

    if not get_future_before_await:
        # Get the concurrent future after we await for anything
        concurrent_future = promise.as_concurrent_future()

    assert isinstance(concurrent_future, concurrent.futures.Future)  # pylint: disable=possibly-used-before-assignment

    if (start_soon is not None and await_promise is None) or (start_soon is False and await_promise is not True):
        # Two scenarios when the promise is not expected to be done:
        # 1. The promise is not prefilled and we don't await for anything at all (no task switching happens)
        # 2. The promise does not start soon (and is not prefilled), but we don't await for it directly
        assert not concurrent_future.done()

        # Now, that we ensured that concurrent_future is not done in these scenarios, let's await for the promise
        #  directly, so we don't get the asyncio warning about it never being awaited
        await promise
    else:
        # In all other scenarios the promise should be done
        assert concurrent_future.done()
        assert concurrent_future.result() == "Hello from Promise!"

    if start_soon is None:
        assert call_count == 0
    else:
        assert call_count == 1


@pytest.mark.parametrize("start_soon", [True, False, None])
@pytest.mark.parametrize("await_promise", [True, False, None])
@pytest.mark.parametrize("get_future_before_await", [True, False])
async def test_with_exception(
    start_soon: Optional[bool],
    await_promise: Optional[bool],
    get_future_before_await: bool,
):
    """
    Test Promise.as_concurrent_future() with exceptions.
    """

    call_count = 0

    # Create a Promise
    if start_soon is None:
        # `start_soon=None` in our test means that we want to create a prefilled promise with exception
        promise = Promise(prefill_exception=ValueError("Test error from Promise!"))
    else:

        async def failing_coro():
            nonlocal call_count
            call_count += 1
            await asyncio.sleep(0.1)
            raise ValueError("Test error from Promise!")

        promise = Promise(failing_coro(), start_soon=start_soon)

    if get_future_before_await:
        # Get the concurrent future before we await for anything
        concurrent_future = promise.as_concurrent_future()

    if await_promise is True:
        with pytest.raises(ValueError):
            await promise
    elif await_promise is False:
        # Let's await in general, but not for the promise specifically
        await asyncio.sleep(0.2)
    # `await_promise=None` in our test means that we don't want to await for anything at all (no task switching)

    if not get_future_before_await:
        # Get the concurrent future after we await for anything
        concurrent_future = promise.as_concurrent_future()

    assert isinstance(concurrent_future, concurrent.futures.Future)  # pylint: disable=possibly-used-before-assignment

    if (start_soon is not None and await_promise is None) or (start_soon is False and await_promise is not True):
        # Two scenarios when the promise is not expected to be done:
        # 1. The promise is not prefilled and we don't await for anything at all (no task switching happens)
        # 2. The promise does not start soon (and is not prefilled), but we don't await for it directly
        assert not concurrent_future.done()

        with pytest.raises(ValueError) as exc_info:
            # Now, that we ensured that concurrent_future is not done in these scenarios, let's await for the promise
            # directly, so we don't get the asyncio warning about the exception not ever being retrieved
            await promise
        assert str(exc_info.value) == "Test error from Promise!"

    else:
        # In all other scenarios the promise should be done (with exception)
        assert concurrent_future.done()
        with pytest.raises(ValueError) as exc_info:
            concurrent_future.result()
        assert str(exc_info.value) == "Test error from Promise!"

    if start_soon is None:
        assert call_count == 0
    else:
        assert call_count == 1


@pytest.mark.parametrize("start_soon", [True, False, None])
@pytest.mark.parametrize("await_promise", [True, False, None])
# pylint: disable=too-many-statements
async def test_from_threads(
    start_soon: Optional[bool],
    await_promise: Optional[bool],
):
    """
    Test accessing Promise result from different threads.
    """

    call_count = 0

    # Create a Promise
    if start_soon is None:
        # `start_soon=None` in our test means that we want to create a prefilled promise
        promise = Promise(prefill_result="Result from thread test!")
    else:

        async def sample_coro():
            nonlocal call_count
            call_count += 1
            await asyncio.sleep(0.2)
            return "Result from thread test!"

        promise = Promise(sample_coro(), start_soon=start_soon)

    concurrent_future = promise.as_concurrent_future()

    results = [None, None, None]
    timeouts = [0.4, 0.4, 0.1]  # Time out earlier than the promise is completed for the third thread

    def thread_function(index: int, timeout: float):
        try:
            results[index] = concurrent_future.result(timeout=timeout)
        except concurrent.futures.TimeoutError as e:
            results[index] = e

    threads = []
    for i, timeout in enumerate(timeouts):
        thread = threading.Thread(target=thread_function, args=(i, timeout))
        threads.append(thread)
        thread.start()

    if await_promise is True:
        await promise
    elif await_promise is False:
        # Let's await in general, but not for the promise specifically
        await asyncio.sleep(0.3)
    # `await_promise=None` in our test means that we don't want to await for anything at all (no task switching)

    for thread in threads:
        thread.join()

    if (start_soon is not None and await_promise is None) or (start_soon is False and await_promise is not True):
        # Two scenarios when the promise is not expected to be done:
        # 1. The promise is not prefilled and we don't await for anything at all (no task switching happens)
        # 2. The promise does not start soon (and is not prefilled), but we don't await for it directly
        assert isinstance(results[0], concurrent.futures.TimeoutError)
        assert isinstance(results[1], concurrent.futures.TimeoutError)
        assert isinstance(results[2], concurrent.futures.TimeoutError)

        # Now, that we ensured that concurrent_future is not done no matter the waiting time out, let's await for the
        # promise directly, so we don't get the asyncio warning about it never being awaited
        await promise

    else:
        assert results[0] == "Result from thread test!"
        assert results[1] == "Result from thread test!"
        if start_soon is None:
            # The promise was prefilled, so the result should be available even for the thread that did not wait long
            # enough
            assert results[2] == "Result from thread test!"
        else:
            assert isinstance(results[2], concurrent.futures.TimeoutError)

    if start_soon is None:
        assert call_count == 0
    else:
        assert call_count == 1
