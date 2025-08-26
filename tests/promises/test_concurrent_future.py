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
    Step-by-step outline:
    1) Parametrize over:
       - start_soon ∈ {True, False, None}
       - await_promise ∈ {True, False, None}
       - get_future_before_await ∈ {True, False}
    2) If start_soon is None, construct a prefilled Promise with a result.
       Else define a coroutine that increments call_count, sleeps briefly, and
       returns a string. Create a Promise with start_soon.
    3) Optionally obtain the concurrent.futures.Future via as_concurrent_future()
       before any awaits when get_future_before_await is True.
    4) Depending on await_promise:
       - await the Promise
       - or await a short sleep
       - or perform no awaiting (no task switching) when await_promise is None
    5) If the Future was not obtained earlier, obtain it now after the awaits.
    6) Assert the returned object is an instance of concurrent.futures.Future.
    7) For scenarios where the Promise is expected not to be done yet — when
       (start_soon is not None and await_promise is None) or
       (start_soon is False and await_promise is not True) — assert
       concurrent_future.done() is False, then explicitly await the Promise to
       avoid un-awaited warnings.
    8) For all other scenarios, assert the Future is done and its result equals
       the expected string.
    9) Finally, assert call_count is 0 for prefilled Promises (start_soon is
       None) and 1 otherwise, verifying the coroutine ran exactly once when
       applicable.
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
    Step-by-step outline:
    1) Parametrize over:
       - start_soon ∈ {True, False, None}
       - await_promise ∈ {True, False, None}
       - get_future_before_await ∈ {True, False}
    2) If start_soon is None, construct a prefilled Promise with a ValueError.
       Else define a coroutine that increments call_count, sleeps briefly, and
       raises ValueError, then create a Promise with start_soon.
    3) Optionally obtain the concurrent.futures.Future before any awaits when
       get_future_before_await is True.
    4) Depending on await_promise: await the Promise expecting ValueError; or
       await a short sleep; or perform no awaiting (no task switching) when
       await_promise is None.
    5) If the Future was not obtained earlier, obtain it now after the awaits.
    6) Assert the returned object is an instance of concurrent.futures.Future.
    7) For scenarios where the Promise is expected not to be done yet — when
       (start_soon is not None and await_promise is None) or
       (start_soon is False and await_promise is not True) — assert the Future
       is not done, then await the Promise expecting ValueError and verify the
       message.
    8) For all other scenarios, assert the Future is done; calling result()
       raises ValueError and the message matches the expected text.
    9) Finally, assert call_count is 0 for prefilled Promises (start_soon is
       None) and 1 otherwise, verifying the failing coroutine executed exactly
       once when applicable.
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
    Step-by-step outline:
    1) Parametrize over start_soon ∈ {True, False, None} and await_promise ∈
       {True, False, None}.
    2) If start_soon is None, construct a prefilled Promise with a result.
       Else define a coroutine that increments call_count, sleeps briefly, and
       returns a string, then create a Promise with start_soon.
    3) Convert the Promise to a concurrent.futures.Future via
       as_concurrent_future().
    4) Prepare a results array and a thread function that calls
       concurrent_future.result(timeout=...) capturing either the value or a
       TimeoutError.
    5) Start three threads with two longer timeouts and one short timeout; begin
       their execution.
    6) Depending on await_promise: await the Promise; or await a short sleep; or
       perform no awaiting (no task switching) when await_promise is None.
    7) Join all threads to collect their outcomes.
    8) For scenarios where the Promise is expected not to be done yet — when
       (start_soon is not None and await_promise is None) or (start_soon is
       False and await_promise is not True) — assert all three threads observed
       TimeoutError, then explicitly await the Promise to avoid un-awaited
       warnings.
    9) For all other scenarios, assert the two long-timeout threads received the
       expected result; the short-timeout thread receives the result immediately
       only for prefilled Promises, otherwise it times out.
    10) Finally, assert call_count is 0 for prefilled Promises (start_soon is
        None) and 1 otherwise, verifying the coroutine ran exactly once when
        applicable.
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
