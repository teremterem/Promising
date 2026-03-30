import pytest

import promising
from tests.utils_for_tests import run_in_thread


@pytest.mark.parametrize("use_thread_pool", [True, False, None])
def test_promising_function_run(use_thread_pool: bool | None) -> None:
    """
    @promising.function used with PromisingFunction.run().

    run() delegates to asyncio.run(), which creates a new event loop. The
    PromisingFunction must resolve the event loop lazily (when the coroutine
    body runs) rather than eagerly (when the Promise object is constructed),
    because no running loop exists yet at construction time.

    Runs in a separate thread to avoid interfering with the pytest-asyncio
    event loop.
    """

    def _test() -> None:
        captured_ctx = None

        if use_thread_pool is not None:

            @promising.function(use_thread_pool=use_thread_pool)
            def work() -> str:
                nonlocal captured_ctx
                captured_ctx = promising.get_active_context()
                return "done"

        else:

            @promising.function
            async def work() -> str:
                nonlocal captured_ctx
                captured_ctx = promising.get_active_context()
                return "done"

        result = work.run()
        assert result == "done"
        assert captured_ctx is not None
        assert isinstance(captured_ctx, promising.Promise)

    run_in_thread(_test, timeout=2)


@pytest.mark.parametrize("await_in_parent", [True, False])
@pytest.mark.parametrize("child_use_thread_pool", [True, False, None])
@pytest.mark.parametrize("parent_use_thread_pool", [True, False, None])
def test_promising_function_run_with_child_promise(
    parent_use_thread_pool: bool | None,
    child_use_thread_pool: bool | None,
    await_in_parent: bool,
) -> None:
    """
    Same as above but also creates a child Promise inside the function, which
    exercises _call_soon_threadsafe and verifies the event loop is correctly
    resolved at runtime.

    Runs in a separate thread to avoid interfering with the pytest-asyncio
    event loop.
    """

    def _test() -> None:
        if child_use_thread_pool is not None:

            @promising.function(use_thread_pool=child_use_thread_pool)
            def child_work(x: int) -> int:
                return x * 2

        else:

            @promising.function
            async def child_work(x: int) -> int:
                return x * 2

        if parent_use_thread_pool is not None:

            @promising.function(use_thread_pool=parent_use_thread_pool)
            def parent_work() -> int:
                if await_in_parent:
                    if parent_use_thread_pool:
                        return child_work(21).sync()
                    else:
                        # When synchronous promising function runs in the same
                        # thread as the event loop, calling `.sync()` should
                        # not be allowed (otherwise it would deadlock)
                        with pytest.raises(promising.SyncUsageError):
                            return child_work(21).sync()
                        return 42  # "Appease" the outer scope's assertion

                else:
                    return child_work(21)

        else:

            @promising.function
            async def parent_work() -> int:
                return await child_work(21)

        assert parent_work.run() == 42

    run_in_thread(_test, timeout=2)
