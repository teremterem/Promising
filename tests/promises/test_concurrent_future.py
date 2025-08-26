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
    Test Promise.as_concurrent_future() method's behavior under various timing and execution conditions.

    This test verifies that the concurrent.futures.Future returned by as_concurrent_future() correctly
    mirrors the Promise's state and results across different scenarios of Promise creation, execution,
    and awaiting patterns.

    Test Parameters:
        start_soon: Controls Promise execution timing:
            - True: Promise starts execution immediately upon creation
            - False: Promise delays execution until explicitly awaited
            - None: Creates a prefilled Promise with a result (no coroutine execution)

        await_promise: Controls whether and how the test awaits the Promise:
            - True: Explicitly awaits the Promise
            - False: Awaits for some time (0.2s) without directly awaiting the Promise
            - None: No awaiting at all (no task switching occurs)

        get_future_before_await: Controls when to obtain the concurrent.futures.Future:
            - True: Get the future before any await operations
            - False: Get the future after await operations

    Test Flow:
        1. Create a Promise based on start_soon parameter:
           - If None: Create a prefilled Promise with "Hello from Promise!" result
           - Otherwise: Create a Promise with a coroutine that sleeps for 0.1s and returns "Hello from Promise!"

        2. Optionally get the concurrent future (based on get_future_before_await)

        3. Handle awaiting based on await_promise parameter:
           - If True: Directly await the Promise
           - If False: Sleep for 0.2s (allowing started Promises to complete)
           - If None: Skip all awaiting (no task switching)

        4. Optionally get the concurrent future (if not already obtained)

        5. Verify the concurrent future's state:
           - Check it's a proper concurrent.futures.Future instance
           - Verify done() status matches expected state based on parameters
           - If done, verify the result is "Hello from Promise!"

        6. Ensure Promise is awaited if it wasn't already (to avoid asyncio warnings)

        7. Verify coroutine execution count:
           - 0 if Promise was prefilled (start_soon=None)
           - 1 if Promise had a coroutine

    Key Scenarios Tested:
        - Prefilled Promises are immediately done
        - Promises with start_soon=True begin execution immediately
        - Promises with start_soon=False only execute when awaited
        - The concurrent future correctly reflects Promise state at different points
        - No asyncio warnings are generated for unawaited Promises
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
    Test Promise.as_concurrent_future() method's exception handling across various timing conditions.

    This test verifies that the concurrent.futures.Future returned by as_concurrent_future() correctly
    propagates exceptions from the Promise and maintains proper exception state across different
    scenarios of Promise creation, execution, and awaiting patterns.

    Test Parameters:
        start_soon: Controls Promise execution timing:
            - True: Promise starts execution immediately upon creation
            - False: Promise delays execution until explicitly awaited
            - None: Creates a prefilled Promise with an exception (no coroutine execution)

        await_promise: Controls whether and how the test awaits the Promise:
            - True: Explicitly awaits the Promise (expecting ValueError to be raised)
            - False: Awaits for some time (0.2s) without directly awaiting the Promise
            - None: No awaiting at all (no task switching occurs)

        get_future_before_await: Controls when to obtain the concurrent.futures.Future:
            - True: Get the future before any await operations
            - False: Get the future after await operations

    Test Flow:
        1. Create a Promise based on start_soon parameter:
           - If None: Create a prefilled Promise with ValueError("Test error from Promise!")
           - Otherwise: Create a Promise with a coroutine that sleeps for 0.1s then raises ValueError

        2. Optionally get the concurrent future (based on get_future_before_await)

        3. Handle awaiting based on await_promise parameter:
           - If True: Await the Promise within pytest.raises(ValueError) context
           - If False: Sleep for 0.2s (allowing started Promises to complete with exception)
           - If None: Skip all awaiting (no task switching)

        4. Optionally get the concurrent future (if not already obtained)

        5. Verify the concurrent future's state:
           - Check it's a proper concurrent.futures.Future instance
           - Verify done() status matches expected state based on parameters
           - If done, verify calling result() raises ValueError with correct message

        6. Handle incomplete Promises:
           - If Promise isn't done, await it within pytest.raises context
           - This ensures proper exception retrieval and prevents asyncio warnings

        7. Verify coroutine execution count:
           - 0 if Promise was prefilled with exception (start_soon=None)
           - 1 if Promise had a coroutine that raised exception

    Key Scenarios Tested:
        - Prefilled exception Promises are immediately done with exception
        - Exceptions are properly propagated through concurrent.futures interface
        - Promises with start_soon=True raise exceptions after async execution
        - Promises with start_soon=False only raise when awaited
        - No asyncio warnings for unretrieved exceptions
        - Exception messages are preserved correctly
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
    Test thread-safe access to Promise results through concurrent.futures.Future interface.

    This test verifies that multiple threads can safely access a Promise's result through its
    concurrent.futures.Future interface, testing various timing scenarios and timeout behaviors.
    The test demonstrates the bridge between asyncio Promises and thread-based concurrent.futures.

    Test Parameters:
        start_soon: Controls Promise execution timing:
            - True: Promise starts execution immediately upon creation
            - False: Promise delays execution until explicitly awaited
            - None: Creates a prefilled Promise with immediate result availability

        await_promise: Controls whether and how the test awaits the Promise:
            - True: Explicitly awaits the Promise
            - False: Awaits for some time (0.3s) without directly awaiting the Promise
            - None: No awaiting at all (no task switching occurs)

    Test Flow:
        1. Create a Promise based on start_soon parameter:
           - If None: Create a prefilled Promise with "Result from thread test!" (immediate result)
           - Otherwise: Create a Promise with a coroutine that sleeps for 0.2s then returns result

        2. Get the concurrent.futures.Future interface for the Promise

        3. Create three threads that will attempt to get the result:
           - Thread 0: Waits up to 0.4s for result (generous timeout)
           - Thread 1: Waits up to 0.4s for result (generous timeout)
           - Thread 2: Waits up to 0.1s for result (tight timeout for testing timeout behavior)

        4. Start all threads concurrently

        5. Handle awaiting based on await_promise parameter:
           - If True: Directly await the Promise (ensures completion)
           - If False: Sleep for 0.3s (enough time for Promise to complete if started)
           - If None: No awaiting (tests thread behavior with incomplete Promise)

        6. Join all threads to ensure they complete

        7. Verify thread results based on Promise completion state:
           - If Promise not expected to be done (no start_soon and no await):
             * All threads should timeout (concurrent.futures.TimeoutError)
           - If Promise expected to be done:
             * Threads 0 and 1 should get "Result from thread test!"
             * Thread 2 behavior depends on timing:
               - Gets result if Promise was prefilled (immediate availability)
               - Times out if Promise needed 0.2s to complete (only had 0.1s timeout)

        8. Ensure Promise is awaited if not already done (prevent asyncio warnings)

        9. Verify coroutine execution count:
           - 0 if Promise was prefilled (start_soon=None)
           - 1 if Promise had a coroutine

    Key Scenarios Tested:
        - Thread-safe concurrent access to Promise results
        - Timeout behavior when Promise isn't ready
        - Multiple threads can successfully retrieve the same result
        - Prefilled Promises provide immediate results to all threads
        - Async Promise execution correctly synchronizes with thread access
        - Different timeout values properly control thread waiting behavior
        - No race conditions when multiple threads access the same Promise
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
