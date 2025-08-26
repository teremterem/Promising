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
    Test Promise.as_concurrent_future() method functionality across various execution scenarios.

    This test validates that the concurrent.futures.Future wrapper returned by Promise.as_concurrent_future()
    correctly mirrors the Promise's state and result. It tests different combinations of:
    - Promise creation modes (immediate start, lazy start, prefilled)
    - Promise awaiting behaviors (direct await, indirect await, no await)
    - Future retrieval timing (before or after awaiting)

    Test Parameters:
        start_soon: Controls Promise execution timing:
            - True: Promise starts execution immediately upon creation
            - False: Promise starts only when awaited
            - None: Creates prefilled Promise with result (no coroutine execution)
        await_promise: Controls awaiting behavior:
            - True: Directly awaits the Promise
            - False: Performs general async sleep without awaiting Promise
            - None: No async operations (no task switching)
        get_future_before_await: Whether to retrieve concurrent future before or after awaiting

    Step-by-step test execution:
    1. Initialize call counter to track coroutine execution
    2. Create Promise based on start_soon parameter:
       - If None: Create prefilled Promise with "Hello from Promise!" result
       - Otherwise: Create Promise with sample_coro() that sleeps 0.1s and returns result
    3. Optionally get concurrent future before any awaiting (if get_future_before_await=True)
    4. Execute awaiting behavior based on await_promise parameter:
       - True: Await the Promise directly
       - False: Sleep 0.2s without awaiting Promise
       - None: No async operations
    5. Optionally get concurrent future after awaiting (if get_future_before_await=False)
    6. Verify concurrent future is instance of concurrent.futures.Future
    7. Check Promise completion status based on execution scenario:
       - Not done: When Promise doesn't start soon and isn't awaited directly, or no task switching occurs
       - Done: In all other scenarios, verify result equals "Hello from Promise!"
    8. Validate coroutine execution count:
       - 0 calls for prefilled Promises
       - 1 call for coroutine-based Promises
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
        # `start_soon=None` means that the promise was prefilled, so the coroutine should not have been called
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
    Test Promise.as_concurrent_future() exception handling across various execution scenarios.

    This test validates that the concurrent.futures.Future wrapper correctly propagates exceptions
    from the underlying Promise. It mirrors test_as_concurrent_future but focuses on exception
    scenarios, ensuring that exceptions are properly handled whether the Promise is prefilled
    with an exception or raises during coroutine execution.

    Test Parameters:
        start_soon: Controls Promise execution timing:
            - True: Promise starts execution immediately upon creation
            - False: Promise starts only when awaited
            - None: Creates prefilled Promise with ValueError exception
        await_promise: Controls awaiting behavior:
            - True: Directly awaits the Promise (expects ValueError)
            - False: Performs general async sleep without awaiting Promise
            - None: No async operations (no task switching)
        get_future_before_await: Whether to retrieve concurrent future before or after awaiting

    Step-by-step test execution:
    1. Initialize call counter to track coroutine execution
    2. Create Promise based on start_soon parameter:
       - If None: Create prefilled Promise with ValueError("Test error from Promise!")
       - Otherwise: Create Promise with failing_coro() that sleeps 0.1s then raises ValueError
    3. Optionally get concurrent future before any awaiting (if get_future_before_await=True)
    4. Execute awaiting behavior based on await_promise parameter:
       - True: Await the Promise directly, expecting ValueError to be raised
       - False: Sleep 0.2s without awaiting Promise
       - None: No async operations
    5. Optionally get concurrent future after awaiting (if get_future_before_await=False)
    6. Verify concurrent future is instance of concurrent.futures.Future
    7. Check Promise completion and exception status based on execution scenario:
       - Not done: When Promise doesn't start soon and isn't awaited directly, or no task switching occurs
         - Await Promise directly to consume exception and prevent asyncio warnings
       - Done: In all other scenarios, verify concurrent future raises ValueError with expected message
    8. Validate coroutine execution count:
       - 0 calls for prefilled Promises with exceptions
       - 1 call for coroutine-based Promises that raise exceptions
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
        # `start_soon=None` means that the promise was prefilled, so the coroutine should not have been called
        assert call_count == 0
    else:
        assert call_count == 1


@pytest.mark.parametrize("start_soon", [True, False, None])
@pytest.mark.parametrize("await_promise", [True, False, None])
async def test_from_threads(
    start_soon: Optional[bool],
    await_promise: Optional[bool],
):
    """
    Test concurrent access to Promise results from multiple threads using as_concurrent_future().

    This test validates the thread-safety of the concurrent.futures.Future wrapper by accessing
    the Promise result from multiple threads simultaneously. It ensures that the Promise's
    as_concurrent_future() method provides proper thread-safe access to results while respecting
    timeout constraints and Promise execution timing.

    Test Parameters:
        start_soon: Controls Promise execution timing:
            - True: Promise starts execution immediately upon creation
            - False: Promise starts only when awaited
            - None: Creates prefilled Promise with result (no coroutine execution)
        await_promise: Controls main thread awaiting behavior:
            - True: Main thread directly awaits the Promise
            - False: Main thread sleeps 0.3s without awaiting Promise
            - None: Main thread performs no async operations (no task switching)

    Step-by-step test execution:
    1. Initialize call counter to track coroutine execution
    2. Create Promise based on start_soon parameter:
       - If None: Create prefilled Promise with "Result from thread test!" result
       - Otherwise: Create Promise with sample_coro() that sleeps 0.2s and returns result
    3. Get concurrent future for thread access
    4. Initialize results list to store outcomes from 3 worker threads
    5. Define thread_function that attempts to get result with specified timeout:
       - Stores successful result or TimeoutError in results array
    6. Create and start 3 threads with different timeout values:
       - Thread 0: 0.4s timeout (should succeed if Promise completes)
       - Thread 1: 0.4s timeout (should succeed if Promise completes)
       - Thread 2: 0.1s timeout (may timeout for slow Promises)
    7. Execute main thread awaiting behavior based on await_promise parameter:
       - True: Await the Promise directly
       - False: Sleep 0.3s (allows Promise to complete if start_soon=True)
       - None: No async operations
    8. Wait for all threads to complete using join()
    9. Verify thread results based on execution scenario:
       - Promise not done: All threads should get TimeoutError
         - Await Promise directly to prevent asyncio warnings
       - Promise done: Threads with sufficient timeout get result, others may timeout
    10. Validate coroutine execution count:
        - 0 calls for prefilled Promises
        - 1 call for coroutine-based Promises

    Thread Safety Validation:
    - Multiple threads can safely access the same concurrent future
    - Timeouts work correctly across thread boundaries
    - Results are consistently available to all threads once Promise completes
    - No race conditions occur during concurrent access
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

    def thread_function(idx: int, timeout: float):
        try:
            results[idx] = concurrent_future.result(timeout=timeout)
        except concurrent.futures.TimeoutError as e:
            results[idx] = e

    threads = [
        threading.Thread(target=thread_function, args=(0, 0.4)),
        threading.Thread(target=thread_function, args=(1, 0.4)),
        threading.Thread(target=thread_function, args=(2, 0.1)),
    ]
    for t in threads:
        t.start()

    if await_promise is True:
        await promise
    elif await_promise is False:
        # Let's await in general, but not for the promise specifically
        await asyncio.sleep(0.3)
    # `await_promise=None` in our test means that we don't want to await for anything at all (no task switching)

    for t in threads:
        t.join()

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
            # The promise was prefilled, so the result should be available even for the thread that did not wait for
            # too long
            assert results[2] == "Result from thread test!"
        else:
            assert isinstance(results[2], concurrent.futures.TimeoutError)

    if start_soon is None:
        # `start_soon=None` means that the promise was prefilled, so the coroutine should not have been called
        assert call_count == 0
    else:
        assert call_count == 1
