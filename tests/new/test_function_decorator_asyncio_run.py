import asyncio
import threading

import promising


def test_async_function_decorator_with_asyncio_run() -> None:
    """
    @promising.function on an async function used with asyncio.run().

    asyncio.run() evaluates f() — and therefore the decorator's
    __call__ — *before* asyncio.run creates and starts its own event
    loop.  The PromisingFunction must resolve the event loop lazily
    (when the coroutine body runs) rather than eagerly (when the
    Promise object is constructed), otherwise it captures a stale
    loop and fails.

    Runs in a separate thread to avoid interfering with the
    pytest-asyncio event loop.
    """
    error = None

    def _run_in_thread() -> None:
        nonlocal error
        try:

            @promising.function
            async def work() -> str:
                return "done"

            result = asyncio.run(work())
            assert result == "done"
        except BaseException as exc:
            error = exc

    t = threading.Thread(target=_run_in_thread)
    t.start()
    t.join()
    if error is not None:
        raise error


def test_async_function_decorator_with_asyncio_run_and_child_promise() -> None:
    """
    Same as above but also creates a child Promise inside the function,
    which exercises _call_soon_threadsafe and verifies the event loop
    is correctly resolved at runtime.

    Runs in a separate thread to avoid interfering with the
    pytest-asyncio event loop.
    """
    error = None

    def _run_in_thread() -> None:
        nonlocal error
        try:

            @promising.function
            async def child_work(x: int) -> int:
                return x * 2

            @promising.function
            async def parent_work() -> int:
                result = await child_work(21)
                return result

            assert asyncio.run(parent_work()) == 42
        except BaseException as exc:
            error = exc

    t = threading.Thread(target=_run_in_thread)
    t.start()
    t.join()
    if error is not None:
        raise error
