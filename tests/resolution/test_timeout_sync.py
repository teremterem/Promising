"""
Tests for timeout behavior of ``Promise.sync()`` and
``Promise.unpack_once_sync()``.
"""

import asyncio
import functools
import time
from typing import Any

import pytest

from promising import Promise

# TODO Generate test_timeout_async.py using asyncio.wait_for() ?

# ---------------------------------------------------------------------------
# unpack_once_sync timeout
# ---------------------------------------------------------------------------


async def test_unpack_once_sync_times_out_on_slow_promise() -> None:
    """unpack_once_sync() raises TimeoutError when the
    promise doesn't resolve in time."""

    async def slow_coro() -> str:
        await asyncio.sleep(0.2)
        return "too late"

    promise = Promise(slow_coro())
    loop = asyncio.get_running_loop()

    with pytest.raises(TimeoutError):
        await loop.run_in_executor(
            None,
            functools.partial(promise.unpack_once_sync, timeout=0.1),
        )

    # Get rid of the asyncio warning
    assert await promise == "too late"


async def test_unpack_once_sync_succeeds_within_timeout() -> None:
    """unpack_once_sync() returns the result when the promise
    resolves before the timeout."""

    async def fast_coro() -> str:
        await asyncio.sleep(0.1)
        return "fast"

    promise = Promise(fast_coro())
    loop = asyncio.get_running_loop()

    result = await loop.run_in_executor(
        None,
        functools.partial(promise.unpack_once_sync, timeout=1),
    )
    assert result == "fast"


# ---------------------------------------------------------------------------
# sync timeout – single level
# ---------------------------------------------------------------------------


async def test_sync_times_out_on_slow_promise() -> None:
    """sync() raises TimeoutError when the promise doesn't
    resolve in time."""

    async def slow_coro() -> str:
        await asyncio.sleep(0.2)
        return "too late"

    promise = Promise(slow_coro())
    loop = asyncio.get_running_loop()

    with pytest.raises(TimeoutError):
        await loop.run_in_executor(
            None,
            functools.partial(promise.sync, timeout=0.1),
        )

    # Get rid of the asyncio warning
    assert await promise == "too late"


async def test_sync_succeeds_within_timeout() -> None:
    """sync() returns the result when the promise resolves
    before the timeout."""

    async def fast_coro() -> str:
        await asyncio.sleep(0.1)
        return "fast"

    promise = Promise(fast_coro())
    loop = asyncio.get_running_loop()

    result = await loop.run_in_executor(
        None,
        functools.partial(promise.sync, timeout=1),
    )
    assert result == "fast"


# ---------------------------------------------------------------------------
# sync timeout – nested promises
# ---------------------------------------------------------------------------


async def test_sync_times_out_on_slow_inner_promise() -> None:
    """sync() raises TimeoutError when an inner (nested)
    promise doesn't resolve in time — the timeout covers
    the entire unpacking chain."""

    async def slow_inner() -> str:
        await asyncio.sleep(0.2)
        return "too late"

    async def outer_coro() -> Promise[str]:
        return Promise(slow_inner())

    promise = Promise(outer_coro())
    loop = asyncio.get_running_loop()

    with pytest.raises(TimeoutError):
        await loop.run_in_executor(
            None,
            functools.partial(promise.sync, timeout=0.1),
        )

    # Get rid of the asyncio warning
    assert await promise == "too late"


async def test_sync_nested_succeeds_within_timeout() -> None:
    """sync() fully unpacks nested promises when they all
    resolve within the timeout."""

    async def inner_coro() -> str:
        await asyncio.sleep(0.1)
        return "nested fast"

    async def outer_coro() -> Promise[str]:
        return Promise(inner_coro())

    promise = Promise(outer_coro())
    loop = asyncio.get_running_loop()

    result = await loop.run_in_executor(
        None,
        functools.partial(promise.sync, timeout=1),
    )
    assert result == "nested fast"


async def test_sync_timeout_spans_multiple_levels() -> None:
    """The timeout budget is shared across all levels of
    unpacking — a chain of small delays that together exceed
    the timeout should raise TimeoutError."""

    async def make_chain(depth: int) -> Any:
        await asyncio.sleep(0.1)
        if depth == 0:
            return "done"
        return Promise(make_chain(depth - 1))

    # 5 levels × 0.1s each = 0.5s total; 0.3s timeout
    # should fail
    promise = Promise(make_chain(4))
    loop = asyncio.get_running_loop()

    with pytest.raises(TimeoutError):
        await loop.run_in_executor(
            None,
            functools.partial(promise.sync, timeout=0.3),
        )

    # Get rid of the asyncio warning
    assert await promise == "done"


async def test_sync_timeout_spans_multiple_levels_elapsed_time() -> None:
    """The total elapsed time until TimeoutError should be roughly
    equal to the timeout value — the deadline must carry across
    all unpacking levels, not restart per level."""

    async def make_chain(depth: int) -> Any:
        await asyncio.sleep(0.15)
        if depth == 0:
            return "done"
        return Promise(make_chain(depth - 1))

    # 5 levels × 0.15s = 0.75s total work; 0.4s timeout
    # should fail after ~0.4s (not immediately, not after 0.75s)
    timeout = 0.4
    promise = Promise(make_chain(4))
    loop = asyncio.get_running_loop()

    start = time.monotonic()
    with pytest.raises(TimeoutError):
        await loop.run_in_executor(
            None,
            functools.partial(promise.sync, timeout=timeout),
        )
    elapsed = time.monotonic() - start

    assert elapsed >= timeout * 0.9, f"Timed out too early: {elapsed:.3f}s < {timeout * 0.9:.3f}s"
    assert elapsed < timeout * 1.1, f"Timed out too late: {elapsed:.3f}s > {timeout * 1.1:.3f}s"

    # Get rid of the asyncio warning
    assert await promise == "done"


async def test_sync_timeout_spans_multiple_levels_succeeds() -> None:
    """A chain of small delays that fits within the timeout
    should succeed."""

    async def make_chain(depth: int) -> Any:
        await asyncio.sleep(0.1)
        if depth == 0:
            return "done"
        return Promise(make_chain(depth - 1))

    # 3 levels × 0.1s each = ~0.3s total; 1s timeout
    promise = Promise(make_chain(2))
    loop = asyncio.get_running_loop()

    result = await loop.run_in_executor(
        None,
        functools.partial(promise.sync, timeout=1),
    )
    assert result == "done"


# ---------------------------------------------------------------------------
# sync timeout – non-Promise awaitables (coroutines)
# ---------------------------------------------------------------------------


@pytest.mark.xfail_feature_possibly_obsolete(skip_entirely=True, skip_reason="suppress_asyncio_warning")
@pytest.mark.parametrize("longer_timeout", [False, True])
async def test_sync_times_out_on_slow_coroutine_result(*, longer_timeout: bool) -> None:
    """
    sync() raises TimeoutError when the promise returns a coroutine
    (not a Promise) that takes too long.

    When the timeout is shorter than the outer coroutine's sleep time,
    slow_coro is never called.
    """

    call_count = 0

    async def slow_coro() -> str:
        nonlocal call_count
        call_count += 1
        await asyncio.sleep(0.2)
        return "too late"

    async def outer() -> Any:
        await asyncio.sleep(0.2)
        return slow_coro()

    promise = Promise(outer())
    loop = asyncio.get_running_loop()

    with pytest.raises(TimeoutError):
        await loop.run_in_executor(
            None,
            functools.partial(promise.sync, timeout=0.3 if longer_timeout else 0.1),
        )

    if longer_timeout:
        assert call_count == 1
    else:
        assert call_count == 0

    # Get rid of the asyncio warning
    assert await promise == "too late"


@pytest.mark.xfail_feature_possibly_obsolete(skip_entirely=True, skip_reason="suppress_asyncio_warning")
async def test_sync_coroutine_result_succeeds_within_timeout() -> None:
    """sync() unpacks a coroutine result when it resolves
    within the timeout."""

    async def fast_coro() -> str:
        await asyncio.sleep(0.1)
        return "fast coro"

    async def outer() -> Any:
        return fast_coro()

    promise = Promise(outer())
    loop = asyncio.get_running_loop()

    result = await loop.run_in_executor(
        None,
        functools.partial(promise.sync, timeout=1),
    )
    assert result == "fast coro"


# ---------------------------------------------------------------------------
# No timeout (None) – never times out
# ---------------------------------------------------------------------------


async def test_sync_no_timeout_waits_indefinitely() -> None:
    """sync() with timeout=None waits as long as needed."""

    async def slow_ish() -> str:
        await asyncio.sleep(0.1)
        return "waited"

    async def outer() -> Promise[str]:
        return Promise(slow_ish())

    promise = Promise(outer())
    loop = asyncio.get_running_loop()

    result = await loop.run_in_executor(None, promise.sync)
    assert result == "waited"


async def test_unpack_once_sync_no_timeout_waits_indefinitely() -> None:
    """unpack_once_sync() with timeout=None waits as long
    as needed."""

    async def slow_ish() -> str:
        await asyncio.sleep(0.1)
        return "waited"

    promise = Promise(slow_ish())
    loop = asyncio.get_running_loop()

    result = await loop.run_in_executor(None, promise.unpack_once_sync)
    assert result == "waited"


# ---------------------------------------------------------------------------
# Zero timeout
# ---------------------------------------------------------------------------


async def test_sync_zero_timeout_on_prefilled_promise() -> None:
    """sync() with timeout=0 returns immediately for a
    prefilled promise."""
    promise = Promise(prefilled_result="instant")
    loop = asyncio.get_running_loop()

    result = await loop.run_in_executor(
        None,
        functools.partial(promise.sync, timeout=0),
    )
    assert result == "instant"


async def test_unpack_once_sync_zero_timeout_on_prefilled_promise() -> None:
    """unpack_once_sync() with timeout=0 returns immediately
    for a prefilled promise."""
    promise = Promise(prefilled_result="instant")
    loop = asyncio.get_running_loop()

    result = await loop.run_in_executor(
        None,
        functools.partial(promise.unpack_once_sync, timeout=0),
    )
    assert result == "instant"


async def test_sync_zero_timeout_on_slow_promise() -> None:
    """sync() with timeout=0 raises TimeoutError for an
    unresolved promise."""

    async def slow_coro() -> str:
        await asyncio.sleep(0.1)
        return "too late"

    promise = Promise(slow_coro())
    loop = asyncio.get_running_loop()

    with pytest.raises(TimeoutError):
        await loop.run_in_executor(
            None,
            functools.partial(promise.sync, timeout=0),
        )

    # Get rid of the asyncio warning
    assert await promise == "too late"


async def test_unpack_once_sync_zero_timeout_on_slow_promise() -> None:
    """unpack_once_sync() with timeout=0 raises TimeoutError
    for an unresolved promise."""

    async def slow_coro() -> str:
        await asyncio.sleep(0.1)
        return "too late"

    promise = Promise(slow_coro())
    loop = asyncio.get_running_loop()

    with pytest.raises(TimeoutError):
        await loop.run_in_executor(
            None,
            functools.partial(promise.unpack_once_sync, timeout=0),
        )

    # Get rid of the asyncio warning
    assert await promise == "too late"


async def test_sync_zero_timeout_nested_prefilled() -> None:
    """sync() with timeout=0 fully unpacks nested prefilled
    promises (no waiting needed)."""

    async def outer_coro() -> Promise[str]:
        return Promise(prefilled_result="deep instant")

    promise = Promise(outer_coro())
    loop = asyncio.get_running_loop()

    # Give the outer coroutine a moment to resolve so both
    # levels are ready before we call sync(timeout=0)
    await asyncio.sleep(0.1)

    result = await loop.run_in_executor(
        None,
        functools.partial(promise.sync, timeout=0),
    )
    assert result == "deep instant"


async def test_sync_zero_timeout_nested_slow_inner() -> None:
    """sync() with timeout=0 raises TimeoutError when the
    outer promise resolves but the inner is slow."""

    async def slow_inner() -> str:
        await asyncio.sleep(0.2)
        return "too late"

    async def outer_coro() -> Promise[str]:
        return Promise(slow_inner())

    promise = Promise(outer_coro())
    loop = asyncio.get_running_loop()

    # Let the outer promise resolve so we enter the unpacking
    # loop, but the inner promise is still pending.
    await asyncio.sleep(0.1)

    with pytest.raises(TimeoutError):
        await loop.run_in_executor(
            None,
            functools.partial(promise.sync, timeout=0),
        )

    # Get rid of the asyncio warning
    assert await promise == "too late"
