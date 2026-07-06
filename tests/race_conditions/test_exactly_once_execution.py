"""
Exactly-once execution of the wrapped awaitable under concurrent triggers.

A Promise caches its result and its awaitable must run **exactly once**,
no matter how many consumers race to trigger it and from which threads:

- ``sync()`` from multiple threads on a lazy (``start_soon=False``) Promise;
- ``await`` on the loop racing ``sync()`` from threads;
- ``unpack_once_sync()`` from multiple threads (the single-unpacking task
  must be created exactly once, and every consumer must receive the *same*
  intermediate Promise instance);
- creation with ``start_soon=True`` in a worker thread (which schedules
  execution via ``call_soon_threadsafe``) racing immediate ``sync()``
  consumption from other threads.

Duplicate scheduling would either re-run side effects (counter > 1) or
crash with "cannot reuse already awaited coroutine" — both are caught
here. Result *identity* (``is``) is asserted, not just equality: every
consumer must see the exact same cached object.
"""

import asyncio
import functools
import threading

import pytest

import promising
from promising import Promise
from tests.race_conditions.utils_for_race_tests import (
    RACE_ITERATIONS,
    RACER_THREADS,
    AtomicCounter,
    assert_no_errors,
    run_racers,
)

pytestmark = pytest.mark.timeout(30)


async def test_concurrent_sync_consumers_trigger_execution_exactly_once() -> None:
    """
    N threads call ``sync()`` simultaneously on a lazy Promise. All of them
    race through the ``done()``-check → ``run_coroutine_threadsafe`` path
    at once; the underlying coroutine must still run exactly once and all
    the callers must get the identical result object.
    """
    for _ in range(RACE_ITERATIONS):
        calls = AtomicCounter()

        async def _coro(calls: AtomicCounter = calls) -> list[str]:
            calls.increment()
            await asyncio.sleep(0)
            return ["value"]

        promise = Promise(_coro(), start_soon=False, parent=None)

        consumers = [functools.partial(promise.sync, timeout=5) for _ in range(RACER_THREADS)]
        results, errors = await run_racers(*consumers)
        assert_no_errors(errors)

        assert results[0] == ["value"]
        assert all(result is results[0] for result in results), "Consumers observed different result objects"
        assert calls.value == 1, f"Awaitable executed {calls.value} times instead of exactly once"


async def test_loop_await_racing_thread_sync_consumers() -> None:
    """
    The event loop ``await``-s a lazy Promise while worker threads
    concurrently ``sync()`` it. Both paths race to schedule the full
    unpacking; only one of them may actually create it.
    """
    for _ in range(RACE_ITERATIONS):
        calls = AtomicCounter()

        async def _coro(calls: AtomicCounter = calls) -> list[str]:
            calls.increment()
            await asyncio.sleep(0)
            return ["value"]

        promise = Promise(_coro(), start_soon=False, parent=None)

        racers_future = asyncio.ensure_future(
            run_racers(*[functools.partial(promise.sync, timeout=5) for _ in range(4)])
        )
        value = await promise
        results, errors = await racers_future
        assert_no_errors(errors)

        assert value == ["value"]
        assert all(result is value for result in results), "sync() consumers observed a different result object"
        assert calls.value == 1, f"Awaitable executed {calls.value} times instead of exactly once"


@promising.function
async def _inner_fn(inner_calls: AtomicCounter) -> list[str]:
    inner_calls.increment()
    return ["final-value"]


@promising.function
async def _outer_fn(inner_calls: AtomicCounter, outer_calls: AtomicCounter) -> Promise[list[str]]:
    outer_calls.increment()
    # Return a lazy inner Promise: single unpacking of the outer promise
    # must NOT start it, only full unpacking (or direct consumption) may.
    return _inner_fn(inner_calls, start_soon=False)


async def test_concurrent_unpack_once_sync_share_one_unpacking_step() -> None:
    """
    N threads call ``unpack_once_sync()`` simultaneously on a lazy Promise
    whose function returns another (lazy) Promise.

    Contract: the outer function body runs exactly once, every thread
    receives the *same* intermediate Promise instance, the single
    unpacking alone does not finish the outer Promise and does not start
    the lazy inner Promise. The inner Promise, hammered afterwards, also
    runs exactly once.
    """
    for _ in range(20):
        inner_calls = AtomicCounter()
        outer_calls = AtomicCounter()
        promise = _outer_fn(inner_calls, outer_calls, start_soon=False)

        unpackers = [functools.partial(promise.unpack_once_sync, timeout=5) for _ in range(RACER_THREADS)]
        results, errors = await run_racers(*unpackers)
        assert_no_errors(errors)

        intermediate = results[0]
        assert isinstance(intermediate, Promise)
        assert all(result is intermediate for result in results), (
            "unpack_once_sync consumers received different intermediate Promises"
        )
        assert outer_calls.value == 1, f"Outer function executed {outer_calls.value} times instead of exactly once"

        # A single unpacking step must not go further than one level.
        assert promise.unpacked_once()
        assert not promise.done()
        assert inner_calls.value == 0, "Single unpacking started the lazy inner Promise"

        # Now hammer the inner Promise from threads — exactly-once as well.
        inner_consumers = [functools.partial(intermediate.sync, timeout=5) for _ in range(4)]
        inner_results, inner_errors = await run_racers(*inner_consumers)
        assert_no_errors(inner_errors)
        assert inner_results[0] == ["final-value"]
        assert all(result is inner_results[0] for result in inner_results)
        assert inner_calls.value == 1

        # Full unpacking of the outer promise completes it with the same value.
        assert await promise == ["final-value"]


async def test_creation_in_worker_thread_racing_sync_consumers() -> None:
    """
    A Promise is *created* in a worker thread with ``start_soon=True``
    (its execution is dispatched onto the loop via
    ``call_soon_threadsafe``) while other threads pounce on it with
    ``sync()`` the moment the reference becomes visible.

    The scheduling-at-creation path and the scheduling-at-consumption path
    race with each other; the awaitable must still run exactly once.
    """
    loop = asyncio.get_running_loop()

    for _ in range(RACE_ITERATIONS):
        calls = AtomicCounter()
        box: dict[str, Promise] = {}
        created = threading.Event()

        def _creator(
            calls: AtomicCounter = calls,
            box: dict[str, Promise] = box,
            created: threading.Event = created,
        ) -> None:
            async def _coro() -> list[str]:
                calls.increment()
                return ["worker-made"]

            box["promise"] = Promise(_coro(), start_soon=True, parent=None, loop=loop)
            created.set()

        def _consumer(box: dict[str, Promise] = box, created: threading.Event = created) -> list[str]:
            assert created.wait(timeout=5), "Creator thread never published the Promise"
            return box["promise"].sync(timeout=5)

        results, errors = await run_racers(_creator, _consumer, _consumer, _consumer)
        assert_no_errors(errors)

        consumer_results = results[1:]
        assert consumer_results[0] == ["worker-made"]
        assert all(result is consumer_results[0] for result in consumer_results)
        assert calls.value == 1, f"Awaitable executed {calls.value} times instead of exactly once"


@promising.function(use_thread_pool=True)
def _pool_bound_work(calls: AtomicCounter) -> list[str]:
    calls.increment()
    return ["pool-made"]


async def test_sync_function_promise_executes_once_under_mixed_consumption() -> None:
    """
    A lazy sync promising function (running in the thread pool once
    triggered) is consumed simultaneously by the event loop (``await``)
    and by worker threads (``sync()``). The pool-bound body must run
    exactly once.
    """
    for _ in range(RACE_ITERATIONS):
        calls = AtomicCounter()
        promise = _pool_bound_work(calls, start_soon=False)

        racers_future = asyncio.ensure_future(
            run_racers(*[functools.partial(promise.sync, timeout=5) for _ in range(4)])
        )
        value = await promise
        results, errors = await racers_future
        assert_no_errors(errors)

        assert value == ["pool-made"]
        assert all(result is value for result in results)
        assert calls.value == 1, f"Pool-bound body executed {calls.value} times instead of exactly once"
