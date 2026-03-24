import asyncio
import threading

from promising import Promise


def test_prefilled_promise_created_outside_async_context() -> None:
    """
    Reproduces the issue where a prefilled Promise created outside an async
    context cannot be awaited inside asyncio.run(), because the event loop
    check in __await__ rejects it before checking if the Promise is already
    done.

    Runs in a separate thread to avoid interfering with the pytest-asyncio
    event loop.
    """
    error = None

    def _run_in_thread() -> None:
        nonlocal error
        try:
            # Create a prefilled Promise outside any running event loop
            promise = Promise(prefilled_result=42)

            async def await_the_promise() -> int:
                return await promise

            # This should work because the promise is already done and no
            # event loop interaction is needed, but currently fails with
            # RuntimeError due to the loop identity check happening before
            # the done() check.
            result = asyncio.run(await_the_promise())
            assert result == 42
        except BaseException as exc:
            error = exc

    t = threading.Thread(target=_run_in_thread)
    t.start()
    t.join()
    if error is not None:
        raise error


async def test_done_promise_awaited_from_different_loop() -> None:
    """
    A Promise is created and fulfilled via a coroutine in the test (on the
    pytest-asyncio event loop), then awaited in a separate thread with a
    different event loop. Since the Promise is already done, no event loop
    interaction should be needed and the await should succeed.
    """

    async def compute() -> int:
        await asyncio.sleep(0.1)
        return 42

    promise = Promise(compute(), start_soon=True)
    result = await promise
    assert result == 42
    assert promise.done()

    error = None

    def _read_in_thread() -> None:
        nonlocal error
        try:

            async def await_the_promise() -> int:
                return await promise

            # This runs on a *different* event loop than the one the promise
            # was created on. It should work because the promise is already
            # done.
            read_result = asyncio.run(await_the_promise())
            assert read_result == 42
        except BaseException as exc:
            error = exc

    t = threading.Thread(target=_read_in_thread)
    t.start()
    t.join()
    if error is not None:
        raise error
