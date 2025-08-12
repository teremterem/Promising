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
    else:
        # In all other scenarios the promise should be done (with exception)
        assert concurrent_future.done()
        with pytest.raises(ValueError) as exc_info:
            concurrent_future.result()
        assert str(exc_info.value) == "Test error from Promise!"


async def test_from_thread():
    """
    Test accessing Promise result from different threads.
    """

    async def sample_coro():
        await asyncio.sleep(0.2)
        return "Result from thread test!"

    promise = Promise(sample_coro())
    concurrent_future = promise.as_concurrent_future()

    result1 = None
    result2 = None
    result3 = None

    def thread_function1():
        nonlocal result1
        result1 = concurrent_future.result(timeout=0.3)

    def thread_function2():
        nonlocal result2
        result2 = concurrent_future.result(timeout=0.3)

    def thread_function3():
        nonlocal result3
        try:
            # Time out earlier than the promise is completed
            concurrent_future.result(timeout=0.1)
        except concurrent.futures.TimeoutError as e:
            result3 = e

    thread1 = threading.Thread(target=thread_function1)
    thread2 = threading.Thread(target=thread_function2)
    thread3 = threading.Thread(target=thread_function3)
    thread1.start()
    thread2.start()
    thread3.start()

    # Let the promise complete
    await promise

    thread1.join()
    thread2.join()
    thread3.join()

    assert result1 == "Result from thread test!"
    assert result2 == "Result from thread test!"
    assert isinstance(result3, concurrent.futures.TimeoutError)
