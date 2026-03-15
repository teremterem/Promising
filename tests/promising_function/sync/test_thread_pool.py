"""Tests for the thread_pool parameter of promising.function."""

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

import promising
from promising import ASYNCIO_DEFAULT, GLOBAL_DEFAULT

# ── GLOBAL_DEFAULT: uses Defaults.SYNC_THREAD_POOL ──────────────────


async def test_global_default_runs_off_main_thread() -> None:
    """
    thread_pool=GLOBAL_DEFAULT causes the sync function to run
    in a different thread than the main/event-loop thread.
    """
    main_thread = threading.current_thread()

    @promising.function(thread_pool=GLOBAL_DEFAULT)
    def get_thread() -> threading.Thread:
        return threading.current_thread()

    worker_thread = await get_thread()
    assert worker_thread is not main_thread


# ── ASYNCIO_DEFAULT: uses the event loop's default executor ─────────


async def test_asyncio_default_runs_off_main_thread() -> None:
    """
    thread_pool=ASYNCIO_DEFAULT causes the sync function to run
    in a different thread than the main/event-loop thread.
    """
    main_thread = threading.current_thread()

    @promising.function(thread_pool=ASYNCIO_DEFAULT)
    def get_thread() -> threading.Thread:
        return threading.current_thread()

    worker_thread = await get_thread()
    assert worker_thread is not main_thread


async def test_asyncio_default_returns_correct_result() -> None:
    """
    A sync function with thread_pool=ASYNCIO_DEFAULT returns
    the correct result.
    """

    @promising.function(thread_pool=ASYNCIO_DEFAULT)
    def greet(name: str) -> str:
        return f"hello, {name}"

    assert await greet("world") == "hello, world"


# ── Concrete ThreadPoolExecutor instance ────────────────────────────


async def test_custom_thread_pool_is_used() -> None:
    """
    A concrete ThreadPoolExecutor instance is used when provided.
    """
    custom_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="custom")

    @promising.function(thread_pool=custom_pool)
    def get_thread_name() -> str:
        return threading.current_thread().name

    thread_name = await get_thread_name()
    assert "custom" in thread_name
    custom_pool.shutdown(wait=False)


async def test_custom_thread_pool_returns_correct_result() -> None:
    """
    A sync function with a custom thread pool returns the correct result.
    """
    custom_pool = ThreadPoolExecutor(max_workers=2)

    @promising.function(thread_pool=custom_pool)
    def add(a: int, b: int) -> int:
        return a + b

    assert await add(3, 4) == 7
    custom_pool.shutdown(wait=False)


async def test_custom_thread_pool_exception_propagates() -> None:
    """
    Exceptions propagate correctly when using a custom thread pool.
    """
    custom_pool = ThreadPoolExecutor(max_workers=1)

    @promising.function(thread_pool=custom_pool)
    def failing() -> None:
        raise ValueError("custom pool error")

    with pytest.raises(ValueError, match="custom pool error"):
        await failing()
    custom_pool.shutdown(wait=False)


# ── INHERIT: inherits from parent context ───────────────────────────


async def test_inherit_from_context() -> None:
    """
    A promising function with thread_pool=INHERIT (default)
    inherits the thread pool from the enclosing promising.context.
    """
    custom_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="inherited")

    @promising.function
    def get_thread_name() -> str:
        return threading.current_thread().name

    with promising.context(thread_pool=custom_pool):
        thread_name = await get_thread_name()

    assert "inherited" in thread_name
    custom_pool.shutdown(wait=False)


async def test_inherit_from_parent_promise() -> None:
    """
    A child sync function inherits the thread pool from its parent
    promise.
    """
    custom_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="parent-pool")

    @promising.function
    def child_get_thread_name() -> str:
        with promising.context():  # Let's add one more level
            return threading.current_thread().name

    @promising.function(thread_pool=custom_pool)
    async def parent() -> str:
        with promising.context():  # Let's add one more level
            return await child_get_thread_name()

    thread_name = await parent()
    assert "parent-pool" in thread_name
    custom_pool.shutdown(wait=False)


async def test_inherit_falls_back_to_global_default() -> None:
    """
    When there is no parent context, INHERIT falls back to
    GLOBAL_DEFAULT (Defaults.SYNC_THREAD_POOL).
    """
    main_thread = threading.current_thread()

    @promising.function  # thread_pool defaults to INHERIT
    def get_thread() -> threading.Thread:
        return threading.current_thread()

    worker_thread = await get_thread()
    assert worker_thread is not main_thread


# ── Override at call site via kwargs ────────────────────────────────


async def test_thread_pool_override_at_call_site() -> None:
    """
    thread_pool can be overridden at the call site via kwargs,
    similar to start_soon.
    """
    custom_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="call-site")

    @promising.function
    def get_thread_name() -> str:
        return threading.current_thread().name

    thread_name = await get_thread_name(thread_pool=custom_pool)
    assert "call-site" in thread_name
    custom_pool.shutdown(wait=False)


async def test_call_site_override_takes_precedence_over_decorator() -> None:
    """
    thread_pool specified at the call site takes precedence over
    the value set at decoration time.
    """
    decorator_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="decorator")
    call_site_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="call-site")

    @promising.function(thread_pool=decorator_pool)
    def get_thread_name() -> str:
        return threading.current_thread().name

    thread_name = await get_thread_name(thread_pool=call_site_pool)
    assert "call-site" in thread_name
    assert "decorator" not in thread_name
    decorator_pool.shutdown(wait=False)
    call_site_pool.shutdown(wait=False)


# ── Context override takes precedence over GLOBAL_DEFAULT ───────────


async def test_context_thread_pool_overrides_global_default() -> None:
    """
    A thread pool set on a promising.context overrides the global
    default for sync functions called within that context.
    """
    custom_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ctx-pool")

    @promising.function
    def get_thread_name() -> str:
        return threading.current_thread().name

    with promising.context(thread_pool=custom_pool):
        thread_name = await get_thread_name()

    assert "ctx-pool" in thread_name
    custom_pool.shutdown(wait=False)


# ── Nested contexts: inner overrides outer ──────────────────────────


async def test_nested_context_inner_overrides_outer() -> None:
    """
    An inner promising.context with a different thread pool overrides
    the outer one.
    """
    outer_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="outer")
    inner_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="inner")

    @promising.function
    def get_thread_name() -> str:
        return threading.current_thread().name

    with promising.context(thread_pool=outer_pool):
        with promising.context(thread_pool=inner_pool):
            thread_name = await get_thread_name()

    assert "inner" in thread_name
    assert "outer" not in thread_name
    outer_pool.shutdown(wait=False)
    inner_pool.shutdown(wait=False)


async def test_nested_context_inner_inherits_outer() -> None:
    """
    An inner promising.context without a thread_pool setting inherits
    from the outer one.
    """
    outer_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="outer")

    @promising.function
    def get_thread_name() -> str:
        return threading.current_thread().name

    with promising.context(thread_pool=outer_pool):
        with promising.context():
            thread_name = await get_thread_name()

    assert "outer" in thread_name
    outer_pool.shutdown(wait=False)


# ── ASYNCIO_DEFAULT via context ─────────────────────────────────────


async def test_asyncio_default_via_context_runs_off_main_thread() -> None:
    """
    Setting thread_pool=ASYNCIO_DEFAULT on a context causes
    child sync functions to run in a different thread than the
    main/event-loop thread.
    """
    main_thread = threading.current_thread()

    @promising.function
    def get_thread() -> threading.Thread:
        return threading.current_thread()

    with promising.context(thread_pool=ASYNCIO_DEFAULT):
        worker_thread = await get_thread()

    assert worker_thread is not main_thread


# ── thread_pool has no effect on async functions ────────────────────


async def test_thread_pool_ignored_for_async_functions() -> None:
    """
    thread_pool has no effect on async functions — they always
    run on the event loop thread.
    """
    main_thread = threading.current_thread()
    custom_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ignored")

    @promising.function(thread_pool=custom_pool)
    async def get_thread() -> threading.Thread:
        return threading.current_thread()

    worker_thread = await get_thread()
    assert worker_thread is main_thread
    custom_pool.shutdown(wait=False)


# ── Inner thread_pool takes precedence over outer thread_pool ────────


async def test_inner_thread_pool_overrides_outer() -> None:
    """
    A thread_pool set closer to the function wins over one set
    further up in the hierarchy.
    """
    decorator_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="deco")
    context_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ctx")

    @promising.function(thread_pool=decorator_pool)
    def get_thread_name() -> str:
        return threading.current_thread().name

    with promising.context(thread_pool=context_pool):
        thread_name = await get_thread_name()

    assert "deco" in thread_name
    decorator_pool.shutdown(wait=False)
    context_pool.shutdown(wait=False)
