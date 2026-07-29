"""
``sync()`` / ``unpack_once_sync()`` hammered at the exact moment of
resolution or failure.

Both methods take a fast path when the Promise is already settled and a
scheduling path (``run_coroutine_threadsafe``) otherwise; the check and
the action are not one atomic step, so these tests aim the herd exactly
at the settle moment. The contract:

- a consumer gets either the (identical, cached) result object or the
  stored exception — never a partial/incorrect value;
- a timed-out consumer may retry and must eventually get the result;
  timeouts must not corrupt the Promise or re-trigger execution;
- consumption from pool-based sync promising functions (the primary
  real-world usage) follows the same rules.
"""

import asyncio
import functools

import pytest

import promising
from promising import Promise
from tests.race_conditions.utils_for_race_tests import (
    RACE_ITERATIONS,
    AtomicCounter,
    assert_no_errors,
    run_racers,
)

pytestmark = pytest.mark.timeout(30)


async def test_sync_entry_racing_resolution() -> None:
    """
    Consumer threads enter ``sync()`` at the same instant another thread
    releases the Promise's result. Consumers that take the fast path
    (already done) and consumers that take the scheduling path must all
    get the correct value.
    """
    loop = asyncio.get_running_loop()

    for _ in range(RACE_ITERATIONS):
        release = asyncio.Event()

        async def _coro(release: asyncio.Event = release) -> list[str]:
            await release.wait()
            return ["ready"]

        promise = Promise(_coro(), start_soon=True, parent=None)

        def _resolver(release: asyncio.Event = release) -> None:
            loop.call_soon_threadsafe(release.set)

        consumers = [functools.partial(promise.sync, timeout=5) for _ in range(4)]
        results, errors = await run_racers(_resolver, *consumers)
        assert_no_errors(errors)

        for result in results[1:]:
            assert result == ["ready"]
        assert all(result is results[1] for result in results[1:])


async def test_sync_short_timeouts_racing_completion() -> None:
    """
    Impatient consumers call ``sync()`` with a timeout shorter than the
    Promise's runtime and retry in a loop. Each attempt races the
    resolution; the retries must eventually return the correct value,
    the timeouts must never corrupt the Promise, and the awaitable must
    still run exactly once despite the many re-entries.
    """
    for _ in range(20):
        calls = AtomicCounter()

        async def _coro(calls: AtomicCounter = calls) -> list[str]:
            calls.increment()
            await asyncio.sleep(0.002)
            return ["slow-value"]

        promise = Promise(_coro(), start_soon=True, parent=None)

        def _impatient_consumer(promise: Promise = promise) -> list[str]:
            while True:
                try:
                    return promise.sync(timeout=0.0005)
                except TimeoutError:
                    continue

        results, errors = await run_racers(*[_impatient_consumer] * 4)
        assert_no_errors(errors)

        assert all(result == ["slow-value"] for result in results)
        assert calls.value == 1, f"Awaitable executed {calls.value} times instead of exactly once"


async def test_unpack_once_sync_racing_failure() -> None:
    """
    Consumer threads call ``unpack_once_sync()`` at the same instant the
    Promise fails with an exception. Whichever path each consumer takes
    (fast path over the already-stored exception, or scheduling path that
    awaits the failing unpacking step), it must receive the stored
    ``ValueError`` — never a ``PromiseNotUnpackedError``, never ``None``.
    """
    loop = asyncio.get_running_loop()

    for _ in range(RACE_ITERATIONS):
        release = asyncio.Event()

        async def _failing(release: asyncio.Event = release) -> None:
            await release.wait()
            raise ValueError("unpack-once boom")

        promise = Promise(_failing(), start_soon=True, parent=None)

        def _resolver(release: asyncio.Event = release) -> None:
            loop.call_soon_threadsafe(release.set)

        def _unpacker(promise: Promise = promise) -> str:
            try:
                promise.unpack_once_sync(timeout=5)
            except ValueError as exc:
                assert str(exc) == "unpack-once boom"
                return "raised"
            return "did-not-raise"

        results, errors = await run_racers(_resolver, _unpacker, _unpacker, _unpacker)
        assert_no_errors(errors)
        assert results[1:] == ["raised"] * 3


@promising.function
async def _shared_source(calls: AtomicCounter) -> list[str]:
    calls.increment()
    await asyncio.sleep(0.001)
    return ["shared-value"]


@promising.function(use_thread_pool=True)
def _pool_consumer(source_promise: Promise[list[str]]) -> list[str]:
    # The primary real-world shape: a sync promising function running in
    # the thread pool blocks on another Promise via sync().
    return source_promise.sync(timeout=5)


async def test_pool_functions_consuming_one_shared_promise() -> None:
    """
    Many sync promising functions (each in its own pool thread) block on
    the same async Promise via ``sync()`` while it resolves. All of them
    must get the identical cached object and the source must run exactly
    once.
    """
    for _ in range(20):
        calls = AtomicCounter()
        source = _shared_source(calls)

        consumers = [_pool_consumer(source) for _ in range(6)]
        results = [await consumer for consumer in consumers]

        canonical = await source
        assert all(result is canonical for result in results), (
            "Pool consumers observed different result objects for the same Promise"
        )
        assert calls.value == 1, f"Shared source executed {calls.value} times instead of exactly once"
