"""
Test script to verify Promise behavior directly using asyncio — checking
done(), result(), and await behavior under different creation modes and
timing conditions.
"""

import asyncio
from typing import NoReturn

import pytest

from promising import Promise


@pytest.mark.parametrize("start_soon", [True, False, None])
@pytest.mark.parametrize("await_promise", [True, False, None])
async def test_promise_as_future(
    *,
    start_soon: bool | None,
    await_promise: bool | None,
) -> None:
    """
    Test Promise's done() and result() behavior under various
    timing and execution conditions.

    This test validates that Promise correctly reports its state
    and result. It tests different combinations of:
    - Promise creation modes (immediate start, lazy start,
      prefilled)
    - Promise awaiting behaviors (direct await, indirect await,
      no await)

    Test Parameters:
        start_soon: Controls Promise execution timing:
            - True: Promise starts execution immediately upon
              creation
            - False: Promise delays execution until explicitly
              awaited
            - None: Creates a prefilled Promise with a result
              (no coroutine execution)

        await_promise: Controls whether and how the test awaits
            the Promise:
            - True: Explicitly awaits the Promise
            - False: Awaits for some time (0.2s) without directly
              awaiting the Promise (allows asyncio task switching
              to happen)
            - None: No awaiting at all (no task switching occurs)

    Test Flow:
        1. Create a Promise based on start_soon parameter:
           - If None: Create a prefilled Promise with
             "Hello from Promise!" result
           - Otherwise: Create a Promise with a coroutine that
             sleeps for 0.1s and returns "Hello from Promise!"

        2. Handle awaiting based on await_promise parameter:
           - If True: Directly await the Promise
           - If False: Sleep for 0.2s (allowing the Promise to
             complete asynchronously if it was started)
           - If None: Skip all awaiting (no task switching)

        3. Verify the Promise's state:
           - Check that it's a proper asyncio.Future instance
           - Verify that done() status matches expected state
             based on parameters
              - Expected not to be done: Promise doesn't
                "start soon" and isn't awaited directly, or it
                does "start soon" but no task switching occurs
              - Expected to be done: all other scenarios
           - If done, verify that result() returns
             "Hello from Promise!"

        4. Ensure Promise is awaited if it wasn't already (to
           avoid asyncio warnings)

        5. Verify coroutine execution count:
           - 0 if Promise was prefilled (start_soon=None)
           - 1 if Promise had a coroutine
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

    if await_promise is True:
        await promise
    elif await_promise is False:
        # Let's await in general, but not for the promise specifically
        await asyncio.sleep(0.2)
    # `await_promise=None` in our test means that we don't want to await for
    # anything at all (no task switching)

    assert isinstance(promise, asyncio.Future)

    if _promise_not_expected_to_be_done(start_soon=start_soon, await_promise=await_promise):
        # Two scenarios when the promise is not expected to be done:
        # 1. The promise is not prefilled and we don't await for anything at
        #    all (no task switching happens)
        # 2. The promise does not start soon (and is not prefilled), but we
        #    don't await for it directly
        assert not promise.done()

        assert coro_call_count == 0

        # Now, that we ensured that the promise is not done in these
        # scenarios, let's await it directly, so we don't get the asyncio
        # warning about it never being awaited
        await promise
    else:
        # In all other scenarios the promise should be done
        assert promise.done()
        assert promise.result() == "Hello from Promise!"

    if start_soon is None:
        # `start_soon=None` means that the promise was prefilled, so the
        # coroutine should not have been called
        assert coro_call_count == 0
    else:
        assert coro_call_count == 1


@pytest.mark.parametrize("start_soon", [True, False, None])
@pytest.mark.parametrize("await_promise", [True, False, None])
async def test_promise_as_future_with_exception(
    *,
    start_soon: bool | None,
    await_promise: bool | None,
) -> None:
    """
    Test Promise's exception handling across various timing
    conditions.

    This test verifies that Promise correctly propagates
    exceptions. It mirrors test_promise but focuses on exception
    scenarios, ensuring that exceptions are properly handled
    whether the Promise is prefilled with an exception or raises
    during coroutine execution.

    Test Parameters:
        start_soon: Controls Promise execution timing:
            - True: Promise starts execution immediately upon
              creation
            - False: Promise delays execution until explicitly
              awaited
            - None: Creates a prefilled Promise with an exception
              (no coroutine execution)

        await_promise: Controls whether and how the test awaits
            the Promise:
            - True: Explicitly awaits the Promise (expecting
              ValueError to be raised)
            - False: Awaits for some time (0.2s) without directly
              awaiting the Promise (allows asyncio task switching
              to happen)
            - None: No awaiting at all (no task switching occurs)

    Test Flow:
        1. Create a Promise based on start_soon parameter:
           - If None: Create a prefilled Promise with
             ValueError("Test error from Promise!")
           - Otherwise: Create a Promise with a coroutine that
             sleeps for 0.1s then raises ValueError

        2. Handle awaiting based on await_promise parameter:
           - If True: Await the Promise within
             pytest.raises(ValueError) context
           - If False: Sleep for 0.2s (allowing the Promise to
             run asynchronously if it was started)
           - If None: Skip all awaiting (no task switching)

        3. Verify the Promise's state:
           - Verify that done() status matches expected state
             based on parameters
           - If done, verify that calling result() raises
             ValueError with the correct message

        4. Handle incomplete Promises:
           - If Promise isn't done, await it within
             pytest.raises context
           - This ensures proper exception retrieval and prevents
             asyncio warnings

        5. Verify coroutine execution count:
           - 0 if Promise was prefilled with exception
             (start_soon=None)
           - 1 if Promise had a coroutine that raised exception
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

    if await_promise is True:
        with pytest.raises(ValueError, match="Test error from Promise!"):
            await promise
    elif await_promise is False:
        # Let's await in general, but not for the promise specifically
        await asyncio.sleep(0.2)
    # `await_promise=None` in our test means that we don't want to await for
    # anything at all (no task switching)

    if _promise_not_expected_to_be_done(start_soon=start_soon, await_promise=await_promise):
        # Two scenarios when the promise is not expected to be done:
        # 1. The promise is not prefilled and we don't await for anything at
        #    all (no task switching happens)
        # 2. The promise does not start soon (and is not prefilled), but we
        #    don't await for it directly
        assert not promise.done()

        assert coro_call_count == 0

        with pytest.raises(ValueError, match="Test error from Promise!"):
            # Now, that we ensured that the promise is not done in these
            # scenarios, let's await it directly, so we don't get the asyncio
            # warning about the exception not ever being retrieved
            await promise

    else:
        # In all other scenarios the promise should be done (with exception)
        assert promise.done()
        with pytest.raises(ValueError, match="Test error from Promise!"):
            promise.result()

    if start_soon is None:
        # `start_soon=None` means that the promise was prefilled, so the
        # coroutine should not have been called
        assert coro_call_count == 0
    else:
        assert coro_call_count == 1


@pytest.mark.parametrize("start_soon", [True, False, None])
async def test_concurrent_consumers(*, start_soon: bool | None) -> None:
    """
    Test that multiple concurrent tasks awaiting the same Promise
    all receive the correct result while the underlying coroutine
    executes exactly once.

    Test Parameters:
        start_soon: Controls Promise execution timing:
            - True: Promise starts execution immediately upon
              creation
            - False: Promise delays execution until explicitly
              awaited
            - None: Creates a prefilled Promise (no coroutine
              execution)

    Test Flow:
        1. Create a Promise based on start_soon parameter:
           - If None: Create a prefilled Promise with
             "Hello from Promise!"
           - Otherwise: Create a Promise with a coroutine that
             sleeps for 0.1s and returns "Hello from Promise!"

        2. Launch 5 concurrent tasks, each directly awaiting the
           same Promise

        3. Gather all task results

        4. Verify:
           - All 5 tasks received the correct result
           - The coroutine was called exactly once (or 0 times
             if prefilled)

    Key Scenario Tested:
        - Multiple concurrent awaits of the same Promise do not
          cause the coroutine to execute more than once
    """

    coro_call_count = 0

    if start_soon is None:
        promise = Promise(prefilled_result="Hello from Promise!")
    else:

        async def sample_coro() -> str:
            nonlocal coro_call_count
            coro_call_count += 1
            await asyncio.sleep(0.1)
            return "Hello from Promise!"

        promise = Promise(sample_coro(), start_soon=start_soon)

    async def await_promise_task() -> str:
        return await promise

    tasks = [asyncio.create_task(await_promise_task()) for _ in range(5)]
    results = await asyncio.gather(*tasks)

    assert promise.result() == "Hello from Promise!"

    # A couple of additional, consecutive awaits of the same promise
    assert await promise == "Hello from Promise!"
    assert await promise == "Hello from Promise!"

    # Check the results of the concurrent tasks
    assert all(r == "Hello from Promise!" for r in results)

    if start_soon is None:
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
