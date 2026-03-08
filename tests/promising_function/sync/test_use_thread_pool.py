"""Tests for the use_thread_pool parameter of promising.function."""

import threading

import pytest

import promising
from promising import await_children_sync, get_active_promise
from promising.errors import SyncUsageError

# ── use_thread_pool=True (default): sync function runs in a thread pool ──


async def test_default_use_thread_pool_runs_in_different_thread() -> None:
    """
    With the default use_thread_pool=True, a sync function
    runs in a different thread than the event loop.
    """
    main_thread = threading.current_thread()

    @promising.function
    def get_thread() -> threading.Thread:
        return threading.current_thread()

    worker_thread = await get_thread()
    assert worker_thread is not main_thread


# ── use_thread_pool=False: sync function runs on the event loop thread ──


async def test_use_thread_pool_false_runs_on_event_loop_thread() -> None:
    """
    With use_thread_pool=False, a sync function runs on the
    same thread as the event loop.
    """
    main_thread = threading.current_thread()

    @promising.function(use_thread_pool=False)
    def get_thread() -> threading.Thread:
        return threading.current_thread()

    worker_thread = await get_thread()
    assert worker_thread is main_thread


async def test_use_thread_pool_false_returns_correct_result() -> None:
    """
    A sync function with use_thread_pool=False still returns
    the correct result.
    """

    @promising.function(use_thread_pool=False)
    def greet(name: str) -> str:
        return f"hello, {name}"

    assert await greet("world") == "hello, world"


async def test_use_thread_pool_false_exception_propagates() -> None:
    """
    Exceptions from a sync function with use_thread_pool=False
    propagate through the Promise.
    """

    @promising.function(use_thread_pool=False)
    def failing() -> None:
        raise ValueError("inline error")

    with pytest.raises(ValueError, match="inline error"):
        await failing()


async def test_use_thread_pool_false_context_propagation() -> None:
    """
    get_active_promise() works inside a sync function with
    use_thread_pool=False.
    """

    @promising.function(use_thread_pool=False)
    def sync_func() -> promising.Promise:
        return get_active_promise(raise_if_none=False)

    promise = sync_func()
    current_from_inside = await promise
    assert current_from_inside is promise


# ── SyncUsageError when calling sync() from use_thread_pool=False ──


async def test_sync_raises_sync_usage_error_with_no_thread_pool() -> None:
    """
    Calling promise.sync() inside a use_thread_pool=False
    function raises SyncUsageError because it would deadlock.
    """
    child_promise = None

    @promising.function
    async def child() -> str:
        return "child result"

    @promising.function(use_thread_pool=False)
    def parent() -> str:
        nonlocal child_promise
        child_promise = child(start_soon=False)
        return child_promise.sync()

    with pytest.raises(SyncUsageError, match="deadlock"):
        await parent()

    assert child_promise is not None
    assert not child_promise.done()

    # Prevent the warning about the unawaited coroutine
    await child_promise


async def test_await_children_sync_raises_sync_usage_error_with_no_thread_pool() -> None:
    """
    Calling await_children_sync() inside a use_thread_pool=False
    function raises SyncUsageError because it would deadlock.
    """

    @promising.function
    async def child() -> str:
        return "child result"

    @promising.function(use_thread_pool=False)
    def parent() -> None:
        child()
        await_children_sync()

    with pytest.raises(SyncUsageError, match="deadlock"):
        await parent()


async def test_concurrent_future_result_raises_sync_usage_error_with_no_thread_pool() -> None:
    """
    Calling concurrent_future.result() inside a use_thread_pool=False
    function raises SyncUsageError because it would deadlock.
    """
    child_promise = None

    @promising.function
    async def child() -> str:
        return "child result"

    @promising.function(use_thread_pool=False)
    def parent() -> str:
        nonlocal child_promise
        child_promise = child(start_soon=False)
        return child_promise.as_concurrent_future().result()

    with pytest.raises(SyncUsageError, match="deadlock"):
        await parent()

    assert child_promise is not None
    assert not child_promise.done()

    # Prevent the warning about the unawaited coroutine
    await child_promise


async def test_concurrent_future_exception_raises_sync_usage_error_with_no_thread_pool() -> None:
    """
    Calling concurrent_future.exception() inside a use_thread_pool=False
    function raises SyncUsageError because it would deadlock.
    """
    child_promise = None

    @promising.function
    async def child() -> str:
        return "child result"

    @promising.function(use_thread_pool=False)
    def parent() -> None:
        nonlocal child_promise
        child_promise = child(start_soon=False)
        child_promise.as_concurrent_future().exception()

    with pytest.raises(SyncUsageError, match="deadlock"):
        await parent()

    assert child_promise is not None
    assert not child_promise.done()

    # Prevent the warning about the unawaited coroutine
    await child_promise


# ── Verify that sync() works fine with use_thread_pool=True ──


async def test_sync_works_with_thread_pool() -> None:
    """
    Calling promise.sync() inside a use_thread_pool=True (default)
    function works fine because the function runs in a separate thread.
    """

    @promising.function
    async def child() -> str:
        return "child result"

    @promising.function
    def parent() -> str:
        return child(start_soon=False).sync()

    assert await parent() == "child result"


async def test_await_children_sync_works_with_thread_pool() -> None:
    """
    Calling await_children_sync() inside a use_thread_pool=True
    (default) function works fine.
    """
    child_result = None

    @promising.function
    async def child() -> str:
        return "child result"

    @promising.function
    def parent() -> None:
        nonlocal child_result
        p = child()
        await_children_sync()
        child_result = p.sync()

    await parent()
    assert child_result == "child result"


@pytest.mark.parametrize("start_soon", [True, False])
async def test_concurrent_future_result_works_with_thread_pool(start_soon: bool) -> None:
    """
    Calling concurrent_future.result() inside a use_thread_pool=True
    (default) function works fine because the function runs in a
    separate thread.
    """

    @promising.function
    async def child() -> str:
        return "child result"

    @promising.function
    def parent() -> str:
        return child(start_soon=start_soon).as_concurrent_future().result()

    assert await parent() == "child result"


@pytest.mark.parametrize("start_soon", [True, False])
async def test_concurrent_future_exception_works_with_thread_pool(start_soon: bool) -> None:
    """
    Calling concurrent_future.exception() inside a use_thread_pool=True
    (default) function works fine because the function runs in a
    separate thread.
    """
    child_exception = None

    @promising.function
    async def child() -> str:
        return "child result"

    @promising.function
    def parent() -> None:
        nonlocal child_exception
        p = child(start_soon=start_soon)
        child_exception = p.as_concurrent_future().exception()

    await parent()
    assert child_exception is None


# ── use_thread_pool has no effect on async functions ──


@pytest.mark.parametrize("use_thread_pool", [True, False])
async def test_use_thread_pool_ignored_for_async_functions(use_thread_pool: bool) -> None:
    """
    use_thread_pool has no effect on async functions — they
    always run on the event loop thread regardless.
    """
    main_thread = threading.current_thread()

    @promising.function(use_thread_pool=use_thread_pool)
    async def get_thread() -> threading.Thread:
        return threading.current_thread()

    worker_thread = await get_thread()
    assert worker_thread is main_thread


# ── Override at call site via kwargs ─────────────────────────────────


async def test_use_thread_pool_override_at_call_site() -> None:
    """
    use_thread_pool can be overridden at the call site via kwargs,
    switching a decorator-level True to False at call time.
    """
    main_thread = threading.current_thread()

    @promising.function  # use_thread_pool defaults to True
    def get_thread() -> threading.Thread:
        return threading.current_thread()

    worker_thread = await get_thread(use_thread_pool=False)
    assert worker_thread is main_thread


async def test_use_thread_pool_call_site_false_to_true() -> None:
    """
    use_thread_pool=False at decoration time can be overridden
    to True at call time, causing the sync function to run in
    a thread pool.
    """
    main_thread = threading.current_thread()

    @promising.function(use_thread_pool=False)
    def get_thread() -> threading.Thread:
        return threading.current_thread()

    worker_thread = await get_thread(use_thread_pool=True)
    assert worker_thread is not main_thread


async def test_use_thread_pool_call_site_not_forwarded() -> None:
    """
    use_thread_pool passed at the call site is consumed by call()
    and not forwarded to the wrapped function as a regular kwarg.
    """

    @promising.function
    def add(a: int, b: int) -> int:
        return a + b

    result = await add(3, 4, use_thread_pool=True)
    assert result == 7
