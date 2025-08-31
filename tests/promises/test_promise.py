#!/usr/bin/env python3
"""
Tests verifying Promise behavior directly (asyncio-based), mirroring
tests/promises/test_concurrent_future.py which validates the
as_concurrent_future() bridge.

Notes:
- Where the original tests used threads to access results via
  concurrent.futures.Future, these tests use asyncio tasks awaiting
  the Promise directly with asyncio.wait_for.
- Param shapes and timing scenarios are preserved where meaningful;
  when a parameter only influenced the concurrent-future wrapper
  creation timing, we keep it for parity, but it has no effect for
  direct-Promise assertions.
"""
import asyncio
from typing import Optional

import pytest

from promising.promises import Promise


@pytest.mark.parametrize("start_soon", [True, False, None])
@pytest.mark.parametrize("await_promise", [True, False, None])
@pytest.mark.parametrize("get_future_before_await", [True, False])
async def test_promise(
    start_soon: Optional[bool],
    await_promise: Optional[bool],
    get_future_before_await: bool,
):
    """
    Test Promise's behavior under various timing and execution conditions.

    This mirrors test_as_concurrent_future but validates the Promise directly.

    Parameters:
        start_soon:
            - True: start execution immediately
            - False: execute only when awaited directly
            - None: prefilled Promise with result
        await_promise:
            - True: await the Promise directly
            - False: await asyncio.sleep(0.2) to allow task switching
            - None: no awaiting at all
        get_future_before_await:
            Retained for parity with the concurrent-future test to vary the
            moment when the wrapper was obtained; here it is a no-op beyond
            choosing when we bind a local variable to the Promise.
    """

    coro_call_count = 0

    # Create a Promise
    if start_soon is None:
        promise = Promise(prefill_result="Hello from Promise!")
    else:

        async def sample_coro():
            nonlocal coro_call_count
            coro_call_count += 1
            await asyncio.sleep(0.1)
            return "Hello from Promise!"

        promise = Promise(sample_coro(), start_soon=start_soon)

    if get_future_before_await:
        # For parity with the other test; not functionally significant here
        promise_ref = promise

    if await_promise is True:
        await promise
    elif await_promise is False:
        await asyncio.sleep(0.2)
    # await_promise is None -> do not await anything (no task switching)

    if not get_future_before_await:
        promise_ref = promise

    assert isinstance(promise_ref, Promise)  # pylint: disable=possibly-used-before-assignment

    if (start_soon is not None and await_promise is None) or (start_soon is False and await_promise is not True):
        # Not expected to be done yet:
        # 1) Not prefilled and no task switching
        # 2) start_soon=False and not awaited directly
        assert not promise_ref.done()
        assert coro_call_count == 0

        # Avoid asyncio warnings about not awaiting
        await promise
    else:
        # In all other scenarios the Promise should be done
        assert promise_ref.done()
        assert promise_ref.result() == "Hello from Promise!"

    if start_soon is None:
        assert coro_call_count == 0
    else:
        assert coro_call_count == 1


@pytest.mark.parametrize("start_soon", [True, False, None])
@pytest.mark.parametrize("await_promise", [True, False, None])
@pytest.mark.parametrize("get_future_before_await", [True, False])
async def test_promise_with_exception(
    start_soon: Optional[bool],
    await_promise: Optional[bool],
    get_future_before_await: bool,
):
    """
    Test Promise's exception behavior under various timing conditions.

    Mirrors test_with_exception but validates the Promise directly.
    """

    coro_call_count = 0

    # Create a Promise
    if start_soon is None:
        promise = Promise(prefill_exception=ValueError("Test error from Promise!"))
    else:

        async def failing_coro():
            nonlocal coro_call_count
            coro_call_count += 1
            await asyncio.sleep(0.1)
            raise ValueError("Test error from Promise!")

        promise = Promise(failing_coro(), start_soon=start_soon)

    if get_future_before_await:
        promise_ref = promise

    if await_promise is True:
        with pytest.raises(ValueError):
            await promise
    elif await_promise is False:
        await asyncio.sleep(0.2)
    # await_promise is None -> do not await anything (no task switching)

    if not get_future_before_await:
        promise_ref = promise

    assert isinstance(promise_ref, Promise)  # pylint: disable=possibly-used-before-assignment

    if (start_soon is not None and await_promise is None) or (start_soon is False and await_promise is not True):
        # Not expected to be done yet:
        # 1) Not prefilled and no task switching
        # 2) start_soon=False and not awaited directly
        assert not promise_ref.done()
        assert coro_call_count == 0

        with pytest.raises(ValueError) as exc_info:
            await promise  # avoid warning and validate exception
        assert str(exc_info.value) == "Test error from Promise!"
    else:
        # In all other scenarios the Promise should be done (with exception)
        assert promise_ref.done()
        with pytest.raises(ValueError) as exc_info:
            promise_ref.result()
        assert str(exc_info.value) == "Test error from Promise!"

    if start_soon is None:
        assert coro_call_count == 0
    else:
        assert coro_call_count == 1


@pytest.mark.parametrize("start_soon", [True, False, None])
@pytest.mark.parametrize("await_promise", [True, False, None])
async def test_from_tasks(
    start_soon: Optional[bool],
    await_promise: Optional[bool],
):
    """
    Test concurrent access to Promise results via asyncio tasks.

    This adapts test_from_threads to asyncio by spawning multiple tasks
    that await the same Promise with different timeouts using
    asyncio.wait_for.

    Semantics differ slightly from thread-based waiting:
    - Awaiting the Promise in any task (even when start_soon=False)
      triggers its execution.
    - Therefore completion depends on the Promise's internal delay vs
      each task's timeout rather than on whether the main test awaited
      the Promise.
    """

    coro_call_count = 0

    # Create a Promise
    if start_soon is None:
        promise = Promise(prefill_result="Result from task test!")
    else:

        async def sample_coro():
            nonlocal coro_call_count
            coro_call_count += 1
            await asyncio.sleep(0.2)
            return "Result from task test!"

        promise = Promise(sample_coro(), start_soon=start_soon)

    results: list[object] = [None, None, None]

    async def task_fn(idx: int, timeout: float) -> None:
        # Polling approach to avoid multiple concurrent awaits on the Promise
        # when start_soon is False (which would otherwise race on _afulfill()).
        deadline = asyncio.get_running_loop().time() + timeout
        while True:
            if promise.done():
                try:
                    results[idx] = promise.result()
                except BaseException as exc:  # pylint: disable=broad-except
                    results[idx] = exc
                return
            if asyncio.get_running_loop().time() >= deadline:
                results[idx] = asyncio.TimeoutError()
                return
            await asyncio.sleep(0.01)

    tasks = [
        asyncio.create_task(task_fn(0, 0.4)),
        asyncio.create_task(task_fn(1, 0.4)),
        asyncio.create_task(task_fn(2, 0.1)),
    ]

    # If not starting soon, ensure at least one background awaiter actually starts the Promise
    starter_task = None
    if start_soon is False and await_promise is not True:

        async def _starter() -> None:
            try:
                await promise
            except BaseException:  # pylint: disable=broad-except
                # Let timed-out waiters surface exceptions via their own await
                pass

        starter_task = asyncio.create_task(_starter())

    if await_promise is True:
        await promise
    elif await_promise is False:
        await asyncio.sleep(0.3)
    # await_promise is None -> do not await the Promise explicitly

    # Ensure tasks finish according to their individual timeouts/completion
    await asyncio.gather(*tasks, return_exceptions=True)
    if starter_task is not None:
        # Make sure the starter finished too
        await starter_task

    if start_soon is None:
        # Prefilled: immediate availability for all
        assert results[0] == "Result from task test!"
        assert results[1] == "Result from task test!"
        assert results[2] == "Result from task test!"
    else:
        # Coroutine has 0.2s delay: tasks with 0.4s should succeed, 0.1s should timeout
        assert results[0] == "Result from task test!"
        assert results[1] == "Result from task test!"
        assert isinstance(results[2], asyncio.TimeoutError)  # type: ignore[attr-defined]

    if start_soon is None:
        assert coro_call_count == 0
    else:
        assert coro_call_count == 1
