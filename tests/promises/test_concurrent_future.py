#!/usr/bin/env python3
"""
Simple test script to verify the as_concurrent_future() method works.
"""
import asyncio
import concurrent.futures
import threading
from promising.promises import Promise


# TODO Review this AI generated test script


async def test_as_concurrent_future():
    """Test the as_concurrent_future method."""

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

    print("✓ as_concurrent_future() method works correctly!")


async def test_with_exception():
    """Test as_concurrent_future with exceptions."""

    async def failing_coro():
        await asyncio.sleep(0.1)
        raise ValueError("Test error")

    promise = Promise(failing_coro())
    concurrent_future = promise.as_concurrent_future()

    try:
        await promise
    except ValueError:
        pass  # Expected

    assert concurrent_future.done()
    try:
        concurrent_future.result()
        assert False, "Should have raised an exception"
    except ValueError as e:
        assert str(e) == "Test error"

    print("✓ Exception handling works correctly!")


async def test_from_thread():
    """Test accessing from a different thread."""

    async def sample_coro():
        await asyncio.sleep(0.2)
        return "Result from thread test!"

    promise = Promise(sample_coro())
    concurrent_future = promise.as_concurrent_future()

    result_container = {}

    def thread_function():
        # This runs in a separate thread
        result = concurrent_future.result(timeout=1.0)
        result_container["result"] = result

    thread = threading.Thread(target=thread_function)
    thread.start()

    # Let the promise complete
    await promise
    thread.join()

    assert result_container["result"] == "Result from thread test!"
    print("✓ Thread access works correctly!")


async def main():
    """Run all tests."""
    print("Testing as_concurrent_future() method...")

    await test_as_concurrent_future()
    await test_with_exception()
    await test_from_thread()

    print("All tests passed! 🎉")


if __name__ == "__main__":
    asyncio.run(main())
