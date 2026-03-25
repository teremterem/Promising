import promising
from tests.utils_for_tests import run_in_thread


def test_async_function_decorator_with_run() -> None:
    """
    @promising.function on an async function used with PromisingFunction.run().

    run() delegates to asyncio.run(), which creates a new event loop. The
    PromisingFunction must resolve the event loop lazily (when the coroutine
    body runs) rather than eagerly (when the Promise object is constructed),
    because no running loop exists yet at construction time.

    Runs in a separate thread to avoid interfering with the pytest-asyncio
    event loop.
    """

    def _test() -> None:
        captured_ctx = None

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


def test_async_function_decorator_with_run_and_child_promise() -> None:
    """
    Same as above but also creates a child Promise inside the function, which
    exercises _call_soon_threadsafe and verifies the event loop is correctly
    resolved at runtime.

    Runs in a separate thread to avoid interfering with the pytest-asyncio
    event loop.
    """

    def _test() -> None:

        @promising.function
        async def child_work(x: int) -> int:
            return x * 2

        @promising.function
        async def parent_work() -> int:
            result = await child_work(21)
            return result

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
