import asyncio
import concurrent.futures
import threading
from typing import NoReturn

import pytest

import promising
from promising import Promise


@pytest.mark.parametrize("start_soon", [True, False, None])
@pytest.mark.parametrize("await_promise", [True, False, None])
@pytest.mark.parametrize("get_future_before_await", [True, False])
async def test_promise_as_future(
    *,
    start_soon: bool | None,
    await_promise: bool | None,
    get_future_before_await: bool,
) -> None:
    """
    Test Promise.concurrent_future method's behavior under various timing
    and execution conditions.

    This test validates that the concurrent.futures.Future wrapper returned by
    Promise.concurrent_future correctly mirrors the Promise's state and
    result. It tests different combinations of:
    - Promise creation modes (immediate start, lazy start, prefilled)
    - Promise awaiting behaviors (direct await, indirect await, no await)
    - Future retrieval timing (before or after awaiting)

    Test Parameters:
        start_soon: Controls Promise execution timing:
            - True: Promise starts execution immediately upon creation
            - False: Promise delays execution until explicitly awaited
            - None: Creates a prefilled Promise with a result (no coroutine
              execution)

        await_promise: Controls whether and how the test awaits the Promise:
            - True: Explicitly awaits the Promise
            - False: Awaits for some time (0.2s) without directly awaiting the
              Promise (allows asyncio task switching to happen)
            - None: No awaiting at all (no task switching occurs)

        get_future_before_await: Controls when to obtain the
        concurrent.futures.Future:
            - True: Get the future before any await operations
            - False: Get the future after await operations

    Test Flow:
        1. Create a Promise based on start_soon parameter:
           - If None: Create a prefilled Promise with "Hello from Promise!"
             result
           - Otherwise: Create a Promise with a coroutine that sleeps for 0.1s
             and returns "Hello from Promise!" (start_soon, which is either
             True or False in this case, is passed to the Promise constructor)

        2. Get the concurrent future if get_future_before_await is True

        3. Handle awaiting based on await_promise parameter:
           - If True: Directly await the Promise
           - If False: Sleep for 0.2s (allowing the Promise to complete
             asynchronously if it was started)
           - If None: Skip all awaiting (no task switching)

        4. If get_future_before_await was False, get the concurrent future at
           this point

        5. Verify the concurrent future's state:
           - Check that it's a proper concurrent.futures.Future instance
           - Verify that done() status matches expected state based on
             parameters
              - Expected not to be done - if Promise doesn't "start soon" and
                isn't awaited directly, or it does "start soon" but no task
                switching occurs and, as a result, it does not have a chance
                to complete. In these cases, the coroutine was never scheduled,
                so coro_call_count must be 0.
              - Expected to be done - in all other scenarios
           - If done, verify that the result is "Hello from Promise!"

        6. Ensure Promise is awaited if it wasn't already (to avoid asyncio
           warnings)

        7. Verify coroutine execution count:
           - 0 if Promise was prefilled (start_soon=None)
           - 1 if Promise had a coroutine (even if it did not have a chance to
             complete before the assertions of the test it was still awaited
             after, as mentioned above, to avoid asyncio warnings)

    Key Scenarios Tested:
        - Prefilled Promises are immediately done
        - Promises with start_soon=True begin execution immediately (or, to be
          precise, at the nearest opportunity the async event loop gives them)
        - Promises with start_soon=False only execute when awaited for directly
        - The concurrent future correctly reflects Promise state at different points
    """

    coro_call_count = 0

    # Create a Promise
    if start_soon is None:
        # `start_soon=None` in our test means that we want to create a
        # prefilled promise
        promise = Promise(prefilled_result="Hello from Promise!")
    else:

        async def sample_coro() -> str:
            nonlocal coro_call_count
            coro_call_count += 1
            await asyncio.sleep(0.1)
            return "Hello from Promise!"

        promise = Promise(sample_coro(), start_soon=start_soon)

    if get_future_before_await:
        # Get the concurrent future before we await for anything
        concurrent_future = promise.concurrent_future

    if await_promise is True:
        await promise
    elif await_promise is False:
        # Let's await in general, but not for the promise specifically
        await asyncio.sleep(0.2)
    # `await_promise=None` in our test means that we don't want to await for
    # anything at all (no task switching)

    if not get_future_before_await:
        # Get the concurrent future after we await for anything
        concurrent_future = promise.concurrent_future

    assert isinstance(concurrent_future, concurrent.futures.Future)

    if _promise_not_expected_to_be_done(start_soon=start_soon, await_promise=await_promise):
        # Two scenarios when the promise is not expected to be done:
        # 1. The promise is not prefilled and we don't await for anything at
        #    all (no task switching happens)
        # 2. The promise does not start soon (and is not prefilled), but we
        #    don't await for it directly
        assert not concurrent_future.done()

        assert coro_call_count == 0

        # Now, that we ensured that concurrent_future is not done in these
        # scenarios, let's await for the promise directly, so we don't get the
        # asyncio warning about it never being awaited
        await promise
    else:
        # In all other scenarios the promise should be done

        @promising.function(use_thread_pool=True)
        def assert_concurrent_future_done() -> None:
            # To bypass deadlock safeguards, we need to do this in a separate
            # thread, hence the @promising.function decorator
            assert concurrent_future.done()
            assert concurrent_future.result() == "Hello from Promise!"

        await assert_concurrent_future_done()

    if start_soon is None:
        # `start_soon=None` means that the promise was prefilled, so the
        # coroutine should not have been called
        assert coro_call_count == 0
    else:
        assert coro_call_count == 1


@pytest.mark.parametrize("start_soon", [True, False, None])
@pytest.mark.parametrize("await_promise", [True, False, None])
@pytest.mark.parametrize("get_future_before_await", [True, False])
async def test_promise_as_future_with_exception(
    *,
    start_soon: bool | None,
    await_promise: bool | None,
    get_future_before_await: bool,
) -> None:
    """
    Test Promise.concurrent_future method's exception handling across
    various timing conditions.

    This test verifies that the concurrent.futures.Future returned by
    concurrent_future correctly propagates exceptions from the underlying
    Promise. It mirrors test_promise_as_future but focuses on exception
    scenarios, ensuring that exceptions are properly handled whether the
    Promise is prefilled with an exception or raises during coroutine
    execution.

    Test Parameters:
        start_soon: Controls Promise execution timing:
            - True: Promise starts execution immediately upon creation
            - False: Promise delays execution until explicitly awaited
            - None: Creates a prefilled Promise with an exception (no coroutine
              execution)

        await_promise: Controls whether and how the test awaits the Promise:
            - True: Explicitly awaits the Promise (expecting ValueError to be
              raised)
            - False: Awaits for some time (0.2s) without directly awaiting the
              Promise (allows asyncio task switching to happen)
            - None: No awaiting at all (no task switching occurs)

        get_future_before_await: Controls when to obtain the
            concurrent.futures.Future:
            - True: Get the future before any await operations
            - False: Get the future after await operations

    Test Flow:
        1. Create a Promise based on start_soon parameter:
           - If None: Create a prefilled Promise with
             ValueError("Test error from Promise!")
           - Otherwise: Create a Promise with a coroutine that sleeps for 0.1s
             then raises ValueError (start_soon, which is either True or False
             in this case, is passed to the Promise constructor)

        2. Get the concurrent future if get_future_before_await is True

        3. Handle awaiting based on await_promise parameter:
           - If True: Await the Promise within pytest.raises(ValueError) context
           - If False: Sleep for 0.2s  (allowing the Promise to run
             asynchronously if it was started)
           - If None: Skip all awaiting (no task switching)

        4. If get_future_before_await was False, get the concurrent future at
           this point

        5. Verify the concurrent future's state:
           - Check that it's a proper concurrent.futures.Future instance
           - Verify that done() status matches expected state based on
             parameters
              - Expected not to be done - if Promise doesn't "start soon" and
                isn't awaited directly, or it does "start soon" but no task
                switching occurs and, as a result, it does not have a chance to
                complete. In these cases, the coroutine was never scheduled,
                so coro_call_count must be 0.
              - Expected to be done - in all other scenarios
           - If done, verify that calling result() raises ValueError with
             the correct message

        6. Handle incomplete Promises:
           - If Promise isn't done, await it within pytest.raises context
           - This ensures proper exception retrieval and prevents asyncio
             warnings

        7. Verify coroutine execution count:
           - 0 if Promise was prefilled with exception (start_soon=None)
           - 1 if Promise had a coroutine that raised exception (even if it did
             not have a chance to run before the assertions of the test it was
             still awaited after, as mentioned above, to avoid asyncio warnings)

    Key Scenarios Tested:
        - Prefilled exception Promises are immediately done with exception
        - Exceptions are properly propagated through concurrent.futures
          interface
        - Promises with start_soon=True get to the point where they raise
          exceptions as long as there is task switching (either by being
          awaited for directly, or because of asyncio task switching for other
          reasons)
        - Promises with start_soon=False only raise when awaited for directly
    """

    coro_call_count = 0

    # Create a Promise
    if start_soon is None:
        # `start_soon=None` in our test means that we want to create a
        # prefilled promise with exception
        promise = Promise(prefilled_exception=ValueError("Test error from Promise!"))
    else:

        async def failing_coro() -> NoReturn:
            nonlocal coro_call_count
            coro_call_count += 1
            await asyncio.sleep(0.1)
            raise ValueError("Test error from Promise!")

        promise = Promise(failing_coro(), start_soon=start_soon)

    if get_future_before_await:
        # Get the concurrent future before we await for anything
        concurrent_future = promise.concurrent_future

    if await_promise is True:
        with pytest.raises(ValueError, match="Test error from Promise!"):
            await promise
    elif await_promise is False:
        # Let's await in general, but not for the promise specifically
        await asyncio.sleep(0.2)
    # `await_promise=None` in our test means that we don't want to await for
    # anything at all (no task switching)

    if not get_future_before_await:
        # Get the concurrent future after we await for anything
        concurrent_future = promise.concurrent_future

    assert isinstance(concurrent_future, concurrent.futures.Future)

    if _promise_not_expected_to_be_done(start_soon=start_soon, await_promise=await_promise):
        # Two scenarios when the promise is not expected to be done:
        # 1. The promise is not prefilled and we don't await for anything at
        #    all (no task switching happens)
        # 2. The promise does not start soon (and is not prefilled), but we
        #    don't await for it directly
        assert not concurrent_future.done()

        assert coro_call_count == 0

        with pytest.raises(ValueError, match="Test error from Promise!"):
            # Now, that we ensured that concurrent_future is not done in these
            # scenarios, let's await for the promise directly, so we don't get
            # the asyncio warning about the exception not ever being retrieved
            await promise

    else:
        # In all other scenarios the promise should be done (with exception)

        @promising.function(use_thread_pool=True)
        def assert_concurrent_future_exception() -> None:
            # To bypass deadlock safeguards, we need to do this in a separate
            # thread, hence the @promising.function decorator
            assert concurrent_future.done()
            with pytest.raises(ValueError, match="Test error from Promise!"):
                concurrent_future.result()

        await assert_concurrent_future_exception()

    if start_soon is None:
        # `start_soon=None` means that the promise was prefilled, so the
        # coroutine should not have been called
        assert coro_call_count == 0
    else:
        assert coro_call_count == 1


@pytest.mark.parametrize("start_soon", [True, False, None])
@pytest.mark.parametrize("await_promise", [True, False, None])
async def test_concurrent_consumers_with_timeout(*, start_soon: bool | None, await_promise: bool | None) -> None:
    """
    Test thread-safe access to Promise results through the
    concurrent.futures.Future interface.

    This test verifies that multiple threads can safely access a Promise's
    result through its concurrent.futures.Future interface, testing various
    timing scenarios and timeout behaviors. The test demonstrates the bridge
    between asyncio Promises and thread-based concurrent.futures.

    Test Parameters:
        start_soon: Controls Promise execution timing:
            - True: Promise starts execution immediately upon creation
            - False: Promise delays execution until explicitly awaited
            - None: Creates a prefilled Promise with immediate result
              availability

        await_promise: Controls whether and how the test awaits the Promise:
            - True: Explicitly awaits the Promise
            - False: Awaits for some time (0.3s) without directly awaiting the
              Promise (allows asyncio task switching to happen)
            - None: No awaiting at all (no task switching occurs)

    Test Flow:
        1. Create a Promise based on start_soon parameter:
           - If None: Create a prefilled Promise with
             "Result from thread test!" (immediate result)
           - Otherwise: Create a Promise with a coroutine that sleeps for 0.2s
             then returns result

        2. Get the concurrent.futures.Future interface for the Promise

        3. Create three threads that will attempt to get the result:
           - Thread 0: Waits up to 0.4s for result (generous timeout)
           - Thread 1: Waits up to 0.4s for result (generous timeout)
           - Thread 2: Waits up to 0.1s for result (tight timeout for testing
             timeout behavior)

        4. Start all threads concurrently

        5. Handle awaiting based on await_promise parameter:
           - If True: Directly await the Promise (ensures completion)
           - If False: Sleep for 0.3s (enough time for Promise to complete if
             started)
           - If None: No awaiting (tests thread behavior with incomplete
             Promise)

        6. Join all threads to ensure they finish their work

        7. Verify thread results based on Promise completion state:
           - Promise is NOT expected to be done - if Promise doesn't
             "start soon" and isn't awaited directly, or it does "start soon"
             but no task switching occurs and, as a result, it does not have a
             chance to complete. In these cases, the coroutine was never
             scheduled, so coro_call_count must be 0.
              - All threads should timeout (TimeoutError)
           - Promise IS expected to be done - in all other scenarios
              - Threads 0 and 1 should get "Result from thread test!"
              - Thread 2 behavior depends on timing:
                 - Gets result if Promise was prefilled (immediate
                   availability)
                 - Times out if Promise needed 0.2s to complete (only had 0.1s
                   timeout)

        8. Ensure Promise is awaited if not already done (to avoid asyncio
           warnings)

        9. Verify coroutine execution count:
           - 0 if Promise was prefilled (start_soon=None)
           - 1 if Promise had a coroutine (even if it did not have a chance to
             complete before the assertions of the test it was still awaited
             after, as mentioned above, to avoid asyncio warnings)

    Key Scenarios Tested:
        - Thread-safe concurrent access to Promise results
        - Timeout behavior when Promise isn't ready
        - Multiple threads can successfully retrieve the same result
        - Prefilled Promises provide immediate results to all threads
        - Promises with start_soon=True begin execution immediately (or, at the
          nearest opportunity the async event loop gives them, to be precise)
        - Promises with start_soon=False only execute when awaited for directly
        - Different timeout values properly control thread waiting behavior
    """

    coro_call_count = 0

    # Create a Promise
    if start_soon is None:
        # `start_soon=None` in our test means that we want to create a
        # prefilled promise
        promise = Promise(prefilled_result="Result from thread test!")
    else:

        async def sample_coro() -> str:
            nonlocal coro_call_count
            coro_call_count += 1
            await asyncio.sleep(0.2)
            return "Result from thread test!"

        promise = Promise(sample_coro(), start_soon=start_soon)

    concurrent_future = promise.concurrent_future

    results = [None, None, None]

    def thread_function(idx: int, timeout: float) -> None:
        try:
            results[idx] = concurrent_future.result(timeout=timeout)  # TODO ensure_task_scheduled=False ?
        except TimeoutError as e:
            results[idx] = e

    threads = [
        threading.Thread(target=thread_function, args=(0, 0.4), daemon=True),
        threading.Thread(target=thread_function, args=(1, 0.4), daemon=True),
        threading.Thread(target=thread_function, args=(2, 0.1), daemon=True),
    ]
    for t in threads:
        t.start()

    if await_promise is True:
        await promise
    elif await_promise is False:
        # Let's await in general, but not for the promise specifically
        await asyncio.sleep(0.3)
    # `await_promise=None` in our test means that we don't want to await for
    # anything at all (no task switching)

    for t in threads:
        t.join(timeout=2)
        assert not t.is_alive(), "Thread did not finish in time"

    if _promise_not_expected_to_be_done(start_soon=start_soon, await_promise=await_promise):
        # Two scenarios when the promise is not expected to be done:
        # 1. The promise is not prefilled and we don't await for anything at
        #    all (no task switching happens)
        # 2. The promise does not start soon (and is not prefilled), but we
        #    don't await for it directly
        assert isinstance(results[0], TimeoutError)
        assert isinstance(results[1], TimeoutError)
        assert isinstance(results[2], TimeoutError)

        assert coro_call_count == 0

        # Now, that we ensured that concurrent_future is not done no matter the
        # waiting time out, let's await for the promise directly, so we don't
        # get the asyncio warning about it never being awaited
        await promise

    else:
        assert results[0] == "Result from thread test!"
        assert results[1] == "Result from thread test!"
        if start_soon is None:
            # The promise was prefilled, so the result should be available
            # even in the thread that did not wait long enough
            assert results[2] == "Result from thread test!"
        else:
            assert isinstance(results[2], TimeoutError)

    if start_soon is None:
        # `start_soon=None` means that the promise was prefilled, so the
        # coroutine should not have been called
        assert coro_call_count == 0
    else:
        assert coro_call_count == 1


def _promise_not_expected_to_be_done(*, start_soon: bool | None, await_promise: bool | None) -> bool:
    """
    Return True when the promise is NOT expected to be done:
    1. Not prefilled and no task switching occurs (await_promise is None)
    2. Does not start soon, not prefilled, and not awaited directly
    """
    return (start_soon is not None and await_promise is None) or (start_soon is False and await_promise is not True)
