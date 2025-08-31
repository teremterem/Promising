#!/usr/bin/env python3
"""
Tests for the Promise class directly using asyncio instead of concurrent.futures.

This module mirrors the concurrent.futures tests in test_concurrent_future.py but tests
the Promise class directly using asyncio primitives and tasks instead of threads.
"""
import asyncio
from typing import Optional
import pytest
from promising.promises import Promise


@pytest.mark.parametrize("start_soon", [True, False, None])
@pytest.mark.parametrize("await_promise", [True, False, None])
@pytest.mark.parametrize("get_result_before_await", [True, False])
async def test_promise_direct(
    start_soon: Optional[bool],
    await_promise: Optional[bool],
    get_result_before_await: bool,
):  # pylint: disable=too-many-branches,too-many-statements
    """
    Test Promise behavior directly using asyncio under various timing and execution conditions.

    This test validates that the Promise correctly manages its state and result. It tests different combinations of:
    - Promise creation modes (immediate start, lazy start, prefilled)
    - Promise awaiting behaviors (direct await, indirect await, no await)
    - Result checking timing (before or after awaiting)

    Test Parameters:
        start_soon: Controls Promise execution timing:
            - True: Promise starts execution immediately upon creation
            - False: Promise delays execution until explicitly awaited
            - None: Creates a prefilled Promise with a result (no coroutine execution)

        await_promise: Controls whether and how the test awaits the Promise:
            - True: Explicitly awaits the Promise
            - False: Awaits for some time (0.2s) without directly awaiting the Promise (allows asyncio task switching
              to happen)
            - None: No awaiting at all (no task switching occurs)

        get_result_before_await: Controls when to check the Promise's done status:
            - True: Check the Promise before any await operations
            - False: Check the Promise after await operations

    Test Flow:
        1. Create a Promise based on start_soon parameter:
           - If None: Create a prefilled Promise with "Hello from Promise!" result
           - Otherwise: Create a Promise with a coroutine that sleeps for 0.1s and returns "Hello from Promise!"
             (start_soon, which is either True or False in this case, is passed to the Promise constructor)

        2. Check the Promise state if get_result_before_await is True

        3. Handle awaiting based on await_promise parameter:
           - If True: Directly await the Promise
           - If False: Sleep for 0.2s (allowing the Promise to complete asynchronously if it was started)
           - If None: Skip all awaiting (no task switching)

        4. If get_result_before_await was False, check the Promise state at this point

        5. Verify the Promise's state:
           - Check it's a proper Promise instance
           - Verify done() status matches expected state based on parameters
              - Not done: When Promise doesn't "start soon" and isn't awaited directly, or it does "start soon" but no
                task switching occurs and, as a result, it does not have a chance to complete
              - Done: In all other scenarios, verify result equals "Hello from Promise!"
           - If done, verify the result is "Hello from Promise!"

        6. Ensure Promise is awaited if it wasn't already (to avoid asyncio warnings)

        7. Verify coroutine execution count:
           - 0 if Promise was prefilled (start_soon=None)
           - 1 if Promise had a coroutine (even if it did not have a chance to complete before the assertions of the
             test it was still awaited after, as mentioned above, to avoid asyncio warnings)

    Key Scenarios Tested:
        - Prefilled Promises are immediately done
        - Promises with start_soon=True begin execution immediately (or, at the nearest opportunity the async event
          loop gives them, to be precise)
        - Promises with start_soon=False only execute when awaited for directly
        - The Promise correctly reflects its state at different points
    """

    coro_call_count = 0

    # Create a Promise
    if start_soon is None:
        # `start_soon=None` in our test means that we want to create a prefilled promise
        promise = Promise(prefill_result="Hello from Promise!")
    else:

        async def sample_coro():
            nonlocal coro_call_count
            coro_call_count += 1
            await asyncio.sleep(0.1)
            return "Hello from Promise!"

        promise = Promise(sample_coro(), start_soon=start_soon)

    promise_done_before = False
    promise_result_before = None
    promise_done_after = False
    promise_result_after = None

    if get_result_before_await:
        # Check the Promise state before we await for anything
        promise_done_before = promise.done()
        if promise_done_before:
            promise_result_before = promise.result()

    if await_promise is True:
        await promise
    elif await_promise is False:
        # Let's await in general, but not for the promise specifically
        await asyncio.sleep(0.2)
    # `await_promise=None` in our test means that we don't want to await for anything at all (no task switching)

    if not get_result_before_await:
        # Check the Promise state after we await for anything
        promise_done_after = promise.done()
        if promise_done_after:
            promise_result_after = promise.result()

    assert isinstance(promise, Promise)

    if (start_soon is not None and await_promise is None) or (start_soon is False and await_promise is not True):
        # Two scenarios when the promise is not expected to be done:
        # 1. The promise is not prefilled and we don't await for anything at all (no task switching happens)
        # 2. The promise does not start soon (and is not prefilled), but we don't await for it directly
        if get_result_before_await:
            assert not promise_done_before
        else:
            assert not promise_done_after
        assert not promise.done()
        assert coro_call_count == 0

        # Now, that we ensured that Promise is not done in these scenarios, let's await for the promise
        # directly, so we don't get the asyncio warning about it never being awaited
        await promise
    else:
        # In all other scenarios the promise should be done
        if get_result_before_await:
            if start_soon is None:
                # Prefilled promises are immediately done
                assert promise_done_before
                assert promise_result_before == "Hello from Promise!"
            elif await_promise is not None:
                # For non-prefilled promises, they should be done after some await operation
                assert promise.done()
                assert promise.result() == "Hello from Promise!"
        else:
            assert promise_done_after
            assert promise_result_after == "Hello from Promise!"

        assert promise.done()
        assert promise.result() == "Hello from Promise!"

    if start_soon is None:
        # `start_soon=None` means that the promise was prefilled, so the coroutine should not have been called
        assert coro_call_count == 0
    else:
        assert coro_call_count == 1


@pytest.mark.parametrize("start_soon", [True, False, None])
@pytest.mark.parametrize("await_promise", [True, False, None])
@pytest.mark.parametrize("get_result_before_await", [True, False])
async def test_promise_with_exception(
    start_soon: Optional[bool],
    await_promise: Optional[bool],
    get_result_before_await: bool,
):  # pylint: disable=too-many-branches,too-many-statements
    """
    Test Promise exception handling directly across various timing conditions.

    This test verifies that the Promise correctly propagates exceptions. It mirrors test_promise_direct but focuses
    on exception scenarios, ensuring that exceptions are properly handled whether the Promise is prefilled with an
    exception or raises during coroutine execution.

    Test Parameters:
        start_soon: Controls Promise execution timing:
            - True: Promise starts execution immediately upon creation
            - False: Promise delays execution until explicitly awaited
            - None: Creates a prefilled Promise with an exception (no coroutine execution)

        await_promise: Controls whether and how the test awaits the Promise:
            - True: Explicitly awaits the Promise (expecting ValueError to be raised)
            - False: Awaits for some time (0.2s) without directly awaiting the Promise (allows asyncio task switching
              to happen)
            - None: No awaiting at all (no task switching occurs)

        get_result_before_await: Controls when to check the Promise's state:
            - True: Check the Promise before any await operations
            - False: Check the Promise after await operations

    Test Flow:
        1. Create a Promise based on start_soon parameter:
           - If None: Create a prefilled Promise with ValueError("Test error from Promise!")
           - Otherwise: Create a Promise with a coroutine that sleeps for 0.1s then raises ValueError (start_soon,
             which is either True or False in this case, is passed to the Promise constructor)

        2. Check the Promise state if get_result_before_await is True

        3. Handle awaiting based on await_promise parameter:
           - If True: Await the Promise within pytest.raises(ValueError) context
           - If False: Sleep for 0.2s (allowing the Promise to run asynchronously if it was started)
           - If None: Skip all awaiting (no task switching)

        4. If get_result_before_await was False, check the Promise state at this point

        5. Verify the Promise's state:
           - Check it's a proper Promise instance
           - Verify done() status matches expected state based on parameters
              - Not done: When Promise doesn't "start soon" and isn't awaited directly, or it does "start soon" but no
                task switching occurs and, as a result, it does not have a chance to complete
              - Done: In all other scenarios, verify calling result() raises ValueError with correct message

        6. Handle incomplete Promises:
           - If Promise isn't done, await it within pytest.raises context
           - This ensures proper exception retrieval and prevents asyncio warnings

        7. Verify coroutine execution count:
           - 0 if Promise was prefilled with exception (start_soon=None)
           - 1 if Promise had a coroutine that raised exception (even if it did not have a chance to run before
             the assertions of the test it was still awaited after, as mentioned above, to avoid asyncio warnings)

    Key Scenarios Tested:
        - Prefilled exception Promises are immediately done with exception
        - Exceptions are properly propagated through Promise interface
        - Promises with start_soon=True get to the point where they raise exceptions as long as there is task switching
          (either by being awaited for directly, or because of asyncio task switching for other reasons)
        - Promises with start_soon=False only raise when awaited for directly
    """

    coro_call_count = 0

    # Create a Promise
    if start_soon is None:
        # `start_soon=None` in our test means that we want to create a prefilled promise with exception
        promise = Promise(prefill_exception=ValueError("Test error from Promise!"))
    else:

        async def failing_coro():
            nonlocal coro_call_count
            coro_call_count += 1
            await asyncio.sleep(0.1)
            raise ValueError("Test error from Promise!")

        promise = Promise(failing_coro(), start_soon=start_soon)

    promise_done_before = False
    promise_exception_before = None
    promise_done_after = False
    promise_exception_after = None

    if get_result_before_await:
        # Check the Promise state before we await for anything
        promise_done_before = promise.done()
        if promise_done_before:
            promise_exception_before = promise.exception()

    if await_promise is True:
        with pytest.raises(ValueError):
            await promise
    elif await_promise is False:
        # Let's await in general, but not for the promise specifically
        await asyncio.sleep(0.2)
    # `await_promise=None` in our test means that we don't want to await for anything at all (no task switching)

    if not get_result_before_await:
        # Check the Promise state after we await for anything
        promise_done_after = promise.done()
        if promise_done_after:
            promise_exception_after = promise.exception()

    assert isinstance(promise, Promise)

    if (start_soon is not None and await_promise is None) or (start_soon is False and await_promise is not True):
        # Two scenarios when the promise is not expected to be done:
        # 1. The promise is not prefilled and we don't await for anything at all (no task switching happens)
        # 2. The promise does not start soon (and is not prefilled), but we don't await for it directly
        if get_result_before_await:
            assert not promise_done_before
        else:
            assert not promise_done_after
        assert not promise.done()
        assert coro_call_count == 0

        with pytest.raises(ValueError) as exc_info:
            # Now, that we ensured that Promise is not done in these scenarios, let's await for the promise
            # directly, so we don't get the asyncio warning about the exception not ever being retrieved
            await promise
        assert str(exc_info.value) == "Test error from Promise!"

    else:
        # In all other scenarios the promise should be done (with exception)
        if get_result_before_await:
            if start_soon is None:
                # Prefilled promises are immediately done with exception
                assert promise_done_before
                assert isinstance(promise_exception_before, ValueError)
                assert str(promise_exception_before) == "Test error from Promise!"
            elif await_promise is not None:
                # For non-prefilled promises, they should be done after some await operation
                assert promise.done()
                assert isinstance(promise.exception(), ValueError)
                assert str(promise.exception()) == "Test error from Promise!"
        else:
            assert promise_done_after
            assert isinstance(promise_exception_after, ValueError)
            assert str(promise_exception_after) == "Test error from Promise!"

        assert promise.done()
        with pytest.raises(ValueError) as exc_info:
            promise.result()
        assert str(exc_info.value) == "Test error from Promise!"

    if start_soon is None:
        # `start_soon=None` means that the promise was prefilled, so the coroutine should not have been called
        assert coro_call_count == 0
    else:
        assert coro_call_count == 1


@pytest.mark.parametrize("start_soon", [True, False, None])
@pytest.mark.parametrize("await_promise", [True, False, None])
async def test_promise_from_tasks(
    start_soon: Optional[bool],
    await_promise: Optional[bool],
):
    """
    Test concurrent access to Promise results through asyncio tasks interface.

    This test verifies that multiple asyncio tasks can safely access a Promise's result, testing various timing
    scenarios and timeout behaviors. The test demonstrates concurrent access patterns within the asyncio event loop.

    Test Parameters:
        start_soon: Controls Promise execution timing:
            - True: Promise starts execution immediately upon creation
            - False: Promise delays execution until explicitly awaited
            - None: Creates a prefilled Promise with immediate result availability

        await_promise: Controls whether and how the test awaits the Promise:
            - True: Explicitly awaits the Promise
            - False: Awaits for some time (0.3s) without directly awaiting the Promise (allows asyncio task switching
              to happen)
            - None: No awaiting at all (no task switching occurs)

    Test Flow:
        1. Create a Promise based on start_soon parameter:
           - If None: Create a prefilled Promise with "Result from task test!" (immediate result)
           - Otherwise: Create a Promise with a coroutine that sleeps for 0.2s then returns result

        2. Create three asyncio tasks that will attempt to get the result:
           - Task 0: Waits up to 0.4s for result (generous timeout via asyncio.wait_for)
           - Task 1: Waits up to 0.4s for result (generous timeout via asyncio.wait_for)
           - Task 2: Waits up to 0.1s for result (tight timeout for testing timeout behavior)

        3. Start all tasks concurrently

        4. Handle awaiting based on await_promise parameter:
           - If True: Directly await the Promise (ensures completion)
           - If False: Sleep for 0.3s (enough time for Promise to complete if started)
           - If None: No awaiting (tests task behavior with incomplete Promise)

        5. Gather all task results

        6. Verify task results based on Promise completion state:
           - If Promise not expected to be done:
              - When Promise doesn't "start soon" and isn't awaited directly, or it does "start soon" but no task
                switching occurs and, as a result, it does not have a chance to complete
              - All tasks should timeout (asyncio.TimeoutError)
           - If Promise expected to be done:
              - Tasks 0 and 1 should get "Result from task test!"
              - Task 2 behavior depends on timing:
                 - Gets result if Promise was prefilled (immediate availability)
                 - Times out if Promise needed 0.2s to complete (only had 0.1s timeout)

        7. Ensure Promise is awaited if not already done (to avoid asyncio warnings)

        8. Verify coroutine execution count:
           - 0 if Promise was prefilled (start_soon=None)
           - 1 if Promise had a coroutine (even if it did not have a chance to complete before the assertions of the
             test it was still awaited after, as mentioned above, to avoid asyncio warnings)

    Key Scenarios Tested:
        - Concurrent access to Promise results via asyncio tasks
        - Timeout behavior when Promise isn't ready
        - Multiple tasks can successfully retrieve the same result
        - Prefilled Promises provide immediate results to all tasks
        - Promises with start_soon=True begin execution immediately (or, at the nearest opportunity the async event
          loop gives them, to be precise)
        - Promises with start_soon=False only execute when awaited for directly
        - Different timeout values properly control task waiting behavior
    """

    coro_call_count = 0

    # Create a Promise
    if start_soon is None:
        # `start_soon=None` in our test means that we want to create a prefilled promise
        promise = Promise(prefill_result="Result from task test!")
    else:

        async def sample_coro():
            nonlocal coro_call_count
            coro_call_count += 1
            await asyncio.sleep(0.2)
            return "Result from task test!"

        promise = Promise(sample_coro(), start_soon=start_soon)

    results = [None, None, None]

    async def task_function(idx: int, timeout: float):
        try:
            results[idx] = await asyncio.wait_for(promise, timeout=timeout)
        except asyncio.TimeoutError as e:
            results[idx] = e

    tasks = [
        asyncio.create_task(task_function(0, 0.4)),
        asyncio.create_task(task_function(1, 0.4)),
        asyncio.create_task(task_function(2, 0.1)),
    ]

    if await_promise is True:
        await promise
    elif await_promise is False:
        # Let's await in general, but not for the promise specifically
        await asyncio.sleep(0.3)
    # `await_promise=None` in our test means that we don't want to await for anything at all (no task switching)

    # Wait for all tasks to complete
    await asyncio.gather(*tasks, return_exceptions=True)

    if (start_soon is not None and await_promise is None) or (start_soon is False and await_promise is not True):
        # Two scenarios when the promise is not expected to be done:
        # 1. The promise is not prefilled and we don't await for anything at all (no task switching happens)
        # 2. The promise does not start soon (and is not prefilled), but we don't await for it directly
        assert isinstance(results[0], asyncio.TimeoutError)
        assert isinstance(results[1], asyncio.TimeoutError)
        assert isinstance(results[2], asyncio.TimeoutError)
        assert coro_call_count == 0

        # Now, that we ensured that Promise is not done no matter the waiting timeout, let's await for the
        # promise directly, so we don't get the asyncio warning about it never being awaited
        await promise

    else:
        assert results[0] == "Result from task test!"
        assert results[1] == "Result from task test!"
        if start_soon is None:
            # The promise was prefilled, so the result should be available even for the task that did not wait for
            # too long
            assert results[2] == "Result from task test!"
        else:
            assert isinstance(results[2], asyncio.TimeoutError)

    if start_soon is None:
        # `start_soon=None` means that the promise was prefilled, so the coroutine should not have been called
        assert coro_call_count == 0
    else:
        assert coro_call_count == 1
