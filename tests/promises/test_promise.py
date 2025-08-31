#!/usr/bin/env python3
# pylint: disable=duplicate-code
"""
Asyncio-native tests to verify Promise behavior directly.
"""
import asyncio
from typing import Optional
import pytest
from promising.promises import Promise


@pytest.mark.parametrize("start_soon", [True, False, None])
@pytest.mark.parametrize("await_promise", [True, False, None])
@pytest.mark.parametrize("get_before_await", [True, False])
async def test_promise_basic(
    start_soon: Optional[bool],
    await_promise: Optional[bool],
    get_before_await: bool,
):
    """
    Test Promise's behavior under various timing and execution conditions.

    This test validates that the Promise instance correctly reflects its state and result. It tests different
    combinations of:
    - Promise creation modes (immediate start, lazy start, prefilled)
    - Promise awaiting behaviors (direct await, indirect await, no await)
    - Retrieval timing (before or after awaiting)
    """

    coro_call_count = 0

    if start_soon is None:
        promise = Promise(prefill_result="Hello from Promise!")
    else:

        async def sample_coro():
            nonlocal coro_call_count
            coro_call_count += 1
            await asyncio.sleep(0.1)
            return "Hello from Promise!"

        promise = Promise(sample_coro(), start_soon=start_soon)

    if get_before_await:
        view = promise

    if await_promise is True:
        await promise
    elif await_promise is False:
        await asyncio.sleep(0.2)

    if not get_before_await:
        view = promise

    assert isinstance(view, Promise)  # pylint: disable=possibly-used-before-assignment

    if (start_soon is not None and await_promise is None) or (start_soon is False and await_promise is not True):
        assert not view.done()
        assert coro_call_count == 0
        await promise
    else:
        assert view.done()
        assert promise.result() == "Hello from Promise!"

    if start_soon is None:
        assert coro_call_count == 0
    else:
        assert coro_call_count == 1


@pytest.mark.parametrize("start_soon", [True, False, None])
@pytest.mark.parametrize("await_promise", [True, False, None])
@pytest.mark.parametrize("get_before_await", [True, False])
async def test_promise_with_exception(
    start_soon: Optional[bool],
    await_promise: Optional[bool],
    get_before_await: bool,
):
    """
    Test Promise's exception handling across various timing conditions.

    This test verifies that exceptions are correctly propagated by Promise.
    It mirrors test_promise_basic but focuses on
    exception scenarios, ensuring proper behavior whether the Promise is prefilled with an exception or raises during
    coroutine execution.
    """

    coro_call_count = 0

    if start_soon is None:
        promise = Promise(prefill_exception=ValueError("Test error from Promise!"))
    else:

        async def failing_coro():
            nonlocal coro_call_count
            coro_call_count += 1
            await asyncio.sleep(0.1)
            raise ValueError("Test error from Promise!")

        promise = Promise(failing_coro(), start_soon=start_soon)

    if get_before_await:
        view = promise

    if await_promise is True:
        with pytest.raises(ValueError):
            await promise
    elif await_promise is False:
        await asyncio.sleep(0.2)

    if not get_before_await:
        view = promise

    assert isinstance(view, Promise)  # pylint: disable=possibly-used-before-assignment

    if (start_soon is not None and await_promise is None) or (start_soon is False and await_promise is not True):
        assert not view.done()
        assert coro_call_count == 0

        with pytest.raises(ValueError) as exc_info:
            await promise
        assert str(exc_info.value) == "Test error from Promise!"

    else:
        assert view.done()
        with pytest.raises(ValueError) as exc_info:
            promise.result()
        assert str(exc_info.value) == "Test error from Promise!"

    if start_soon is None:
        assert coro_call_count == 0
    else:
        assert coro_call_count == 1


@pytest.mark.parametrize("start_soon", [True, False, None])
@pytest.mark.parametrize("await_promise", [True, False, None])
async def test_promise_from_tasks(
    start_soon: Optional[bool],
    await_promise: Optional[bool],
):
    """
    Test concurrent access to Promise results via asyncio tasks and timeouts.

    This test verifies that multiple asyncio tasks can safely access a Promise's result,
    testing various timing scenarios and timeout behaviors, replacing threads with asyncio tasks.
    """

    coro_call_count = 0

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

    async def task_function(idx: int, timeout: float):
        try:
            results[idx] = await asyncio.wait_for(promise, timeout=timeout)
        except asyncio.TimeoutError as e:
            results[idx] = e

    tasks = [
        asyncio.create_task(task_function(0, 0.4)),
        asyncio.create_task(task_function(1, 0.4)),
        asyncio.create_task(task_function(2, 0.1)),
    ]

    if await_promise is True:
        await promise
    elif await_promise is False:
        await asyncio.sleep(0.3)

    await asyncio.gather(*tasks)

    if (start_soon is not None and await_promise is None) or (start_soon is False and await_promise is not True):
        assert isinstance(results[0], asyncio.TimeoutError)
        assert isinstance(results[1], asyncio.TimeoutError)
        assert isinstance(results[2], asyncio.TimeoutError)
        assert coro_call_count == 0
        await promise

    else:
        assert results[0] == "Result from task test!"
        assert results[1] == "Result from task test!"
        if start_soon is None:
            assert results[2] == "Result from task test!"
        else:
            assert isinstance(results[2], asyncio.TimeoutError)

    if start_soon is None:
        assert coro_call_count == 0
    else:
        assert coro_call_count == 1
