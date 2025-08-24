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


def _get_future_result(container, index, future, timeout):
    try:
        container[index] = future.result(timeout=timeout)
    except concurrent.futures.TimeoutError as e:
        container[index] = e


async def _run_thread_test(start_soon: Optional[bool], await_promise: Optional[bool]) -> None:
    calls = 0
    if start_soon is None:
        promise = Promise(prefill_result="Result from thread test!")
    else:

        async def sample_coro():
            nonlocal calls
            calls += 1
            await asyncio.sleep(0.2)
            return "Result from thread test!"

        promise = Promise(sample_coro(), start_soon=start_soon)

    concurrent_future = promise.as_concurrent_future()

    results = [None, None, None]
    thread1 = threading.Thread(target=_get_future_result, args=(results, 0, concurrent_future, 0.4))
    thread2 = threading.Thread(target=_get_future_result, args=(results, 1, concurrent_future, 0.4))
    thread3 = threading.Thread(target=_get_future_result, args=(results, 2, concurrent_future, 0.1))

    thread1.start()
    thread2.start()
    thread3.start()

    if await_promise is True:
        await promise
    elif await_promise is False:
        await asyncio.sleep(0.3)

    thread1.join()
    thread2.join()
    thread3.join()

    if (start_soon is not None and await_promise is None) or (start_soon is False and await_promise is not True):
        assert isinstance(results[0], concurrent.futures.TimeoutError)
        assert isinstance(results[1], concurrent.futures.TimeoutError)
        assert isinstance(results[2], concurrent.futures.TimeoutError)
        await promise
    else:
        assert results[0] == "Result from thread test!"
        assert results[1] == "Result from thread test!"
        if start_soon is None:
            assert results[2] == "Result from thread test!"
        else:
            assert isinstance(results[2], concurrent.futures.TimeoutError)

    if start_soon is not None:
        assert calls == 1


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

    # Create a Promise
    if start_soon is None:
        # `start_soon=None` in our test means that we want to create a prefilled promise
        promise = Promise(prefill_result="Hello from Promise!")
    else:

        async def sample_coro():
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

    # Create a Promise
    if start_soon is None:
        # `start_soon=None` in our test means that we want to create a prefilled promise with exception
        promise = Promise(prefill_exception=ValueError("Test error from Promise!"))
    else:

        async def failing_coro():
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


@pytest.mark.parametrize("start_soon", [True, False, None])
@pytest.mark.parametrize("await_promise", [True, False, None])
async def test_from_threads(
    start_soon: Optional[bool],
    await_promise: Optional[bool],
):
    await _run_thread_test(start_soon, await_promise)
