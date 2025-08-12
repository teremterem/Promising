#!/usr/bin/env python3
"""
Simple test script to verify the as_concurrent_future() method works.
"""
import asyncio
import concurrent.futures
import threading
import pytest
from promising.promises import Promise


async def test_as_concurrent_future():
    """
    Test Promise.as_concurrent_future().
    """

    async def sample_coro():
        await asyncio.sleep(0.1)
        return "Hello from Promise!"

    # Create a Promise
    promise = Promise(sample_coro())

    # Convert to concurrent.futures.Future
    concurrent_future = promise.as_concurrent_future()

    # Test that it's the right type
    assert isinstance(concurrent_future, concurrent.futures.Future)

    # Wait for completion
    await promise

    # Check that the concurrent future also completed
    assert concurrent_future.done()
    assert concurrent_future.result() == "Hello from Promise!"


async def test_with_exception():
    """
    Test Promise.as_concurrent_future() with exceptions.
    """

    async def failing_coro():
        await asyncio.sleep(0.1)
        raise ValueError("Test error")

    promise = Promise(failing_coro())
    concurrent_future = promise.as_concurrent_future()

    with pytest.raises(ValueError):
        await promise

    assert concurrent_future.done()
    with pytest.raises(ValueError) as exc_info:
        concurrent_future.result()
    assert str(exc_info.value) == "Test error"


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
