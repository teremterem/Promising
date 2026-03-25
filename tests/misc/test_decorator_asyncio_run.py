import pytest

import promising
from tests.utils_for_tests import run_in_thread


@pytest.mark.parametrize("use_thread_pool", [True, False, None])
def test_async_function_decorator_with_run(use_thread_pool: bool | None) -> None:
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

    run_in_thread(_test)


@pytest.mark.parametrize("await_in_parent", [True, False])
@pytest.mark.parametrize("child_use_thread_pool", [True, False, None])
@pytest.mark.parametrize("parent_use_thread_pool", [True, False, None])
def test_async_function_decorator_with_run_and_child_promise(
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

    run_in_thread(_test)


async def test_async_context_decorator_resolves_parent_at_call_site() -> None:
    """
    The parent of a @promising.context-decorated async function's context
    is determined at call-site (when the coroutine object is created),
    not at await-site (when the coroutine body runs).

    Scenario: coroutine created inside `outer`, awaited outside it.
    func_ctx should still have `outer` as its parent.
    """
    func_ctx = None

    @promising.context
    async def work() -> str:
        nonlocal func_ctx
        func_ctx = promising.get_active_context()
        return "done"

    with promising.context() as outer:
        coro = work()
    await coro

    assert func_ctx is not None
    assert func_ctx.get_parent_context(raise_if_none=False) is outer


async def test_async_context_decorator_no_parent_when_called_outside_context() -> None:
    """
    Coroutine created outside any context, awaited inside one.
    func_ctx should have no parent — the context active at await-time
    is irrelevant.
    """
    func_ctx = None

    @promising.context
    async def work() -> str:
        nonlocal func_ctx
        func_ctx = promising.get_active_context()
        return "done"

    coro = work()
    with promising.context():
        await coro

    assert func_ctx is not None
    assert func_ctx.get_parent_context(raise_if_none=False) is None
