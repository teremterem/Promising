"""
Tests for Promise unpacking behavior: `await promise` (unpack_all)
vs `await promise.unpack_once()`.

`await promise` should recursively unpack the result until it's no longer
awaitable, while `unpack_once()` should only unpack a single level.
"""

import asyncio
from typing import Any

import pytest

from promising import Promise

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class CustomAwaitable:
    """A minimal custom awaitable (not a Promise) that resolves to a value."""

    def __init__(self, value: Any) -> None:
        self._value = value

    def __await__(self):
        return self._value
        yield  # make it a generator  # noqa: RET503


class CustomAwaitableWithSleep:
    """A custom awaitable that yields control before returning."""

    def __init__(self, value: Any) -> None:
        self._value = value

    def __await__(self):
        yield from asyncio.sleep(0.1).__await__()
        return self._value


# ---------------------------------------------------------------------------
# 1 level – no nesting (baseline)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("use_unpack_once", [True, False])
async def test_single_promise_no_nesting(*, use_unpack_once: bool) -> None:
    """A plain promise with a scalar result behaves the same for both
    `await` and `unpack_once`."""

    async def coro() -> str:
        return "hello"

    promise: Promise[str] = Promise(coro())

    if use_unpack_once:
        result = await promise.unpack_once()
    else:
        result = await promise

    assert result == "hello"


async def test_prefilled_promise_no_nesting() -> None:
    """Prefilled promise works the same for both modes."""
    promise = Promise(prefilled_result=42)

    assert await promise == 42
    assert await promise.unpack_once() == 42


# ---------------------------------------------------------------------------
# 2 levels – Promise returning a Promise
# ---------------------------------------------------------------------------


async def test_two_levels_await_unpacks_all() -> None:
    """`await outer` should unpack both levels and return the final value."""

    async def inner_coro() -> str:
        return "deep value"

    async def outer_coro() -> str:
        return Promise(inner_coro())

    outer: Promise[str] = Promise(outer_coro())

    result = await outer
    assert result == "deep value"


async def test_two_levels_unpack_once_stops_at_inner() -> None:
    """`unpack_once()` on the outer promise should return the inner promise,
    not the final scalar."""

    async def inner_coro() -> str:
        return "deep value"

    inner = None

    async def outer_coro() -> str:
        nonlocal inner
        inner = Promise(inner_coro())
        return inner

    outer: Promise[str] = Promise(outer_coro())

    result = await outer.unpack_once()
    assert isinstance(result, Promise)
    assert result is inner

    # Awaiting the inner promise should give the scalar
    assert await result == "deep value"


# ---------------------------------------------------------------------------
# 3 levels – Promise → Promise → Promise
# ---------------------------------------------------------------------------


async def test_three_levels_await_unpacks_all() -> None:
    """`await` on a triply-nested promise returns the deepest value."""

    async def mid_coro() -> str:
        return Promise(prefilled_result="bottom")

    async def top_coro() -> str:
        return Promise(mid_coro())

    p1 = Promise(top_coro())

    assert await p1 == "bottom"


async def test_three_levels_unpack_once_returns_second_level() -> None:
    """`unpack_once()` on a triply-nested promise returns the
    second-level promise."""
    p2 = None
    p3 = None

    async def mid_coro() -> str:
        nonlocal p3
        p3 = Promise(prefilled_result="bottom")
        return p3

    async def top_coro() -> str:
        nonlocal p2
        p2 = Promise(mid_coro())
        return p2

    p1 = Promise(top_coro())

    level2 = await p1.unpack_once()
    assert isinstance(level2, Promise)
    assert level2 is p2

    level3 = await level2.unpack_once()
    assert isinstance(level3, Promise)
    assert level3 is p3

    assert await level3.unpack_once() == "bottom"


# ---------------------------------------------------------------------------
# Promise returning a custom awaitable
# ---------------------------------------------------------------------------


async def test_custom_awaitable_await_unpacks() -> None:
    """`await` unpacks through a custom awaitable to the final value."""

    async def coro() -> CustomAwaitable:
        return CustomAwaitable("custom_value")

    promise: Promise[CustomAwaitable] = Promise(coro())

    assert await promise == "custom_value"


async def test_custom_awaitable_unpack_once_stops() -> None:
    """`unpack_once()` returns the custom awaitable itself."""

    async def coro() -> CustomAwaitable:
        return CustomAwaitable("custom_value")

    promise: Promise[CustomAwaitable] = Promise(coro())

    result = await promise.unpack_once()
    assert isinstance(result, CustomAwaitable)


# ---------------------------------------------------------------------------
# Promise → custom awaitable → Promise
# ---------------------------------------------------------------------------


async def test_mixed_chain_await_unpacks_all() -> None:
    """`await` unpacks through Promise → CustomAwaitable → scalar."""
    inner = Promise(prefilled_result="final")

    async def coro() -> CustomAwaitable:
        return CustomAwaitable(inner)

    promise = Promise(coro())

    # CustomAwaitable wraps a Promise; `await promise` should unpack:
    # promise → CustomAwaitable → inner Promise → "final"
    assert await promise == "final"


async def test_mixed_chain_unpack_once() -> None:
    """`unpack_once()` on outer promise returns the CustomAwaitable."""
    inner = Promise(prefilled_result="final")

    async def coro() -> CustomAwaitable:
        return CustomAwaitable(inner)

    promise = Promise(coro())

    result = await promise.unpack_once()
    assert isinstance(result, CustomAwaitable)

    # Awaiting the inner promise separately should work
    assert await inner == "final"


# ---------------------------------------------------------------------------
# Promise returning an asyncio.Future
# ---------------------------------------------------------------------------


async def test_asyncio_future_await_unpacks() -> None:
    """`await` unpacks through an asyncio.Future to the final value."""
    loop = asyncio.get_running_loop()
    fut: asyncio.Future[str] = loop.create_future()
    fut.set_result("from_future")

    async def coro() -> asyncio.Future[str]:
        return fut

    promise = Promise(coro())

    assert await promise == "from_future"


async def test_asyncio_future_unpack_once_stops() -> None:
    """`unpack_once()` returns the asyncio.Future."""
    loop = asyncio.get_running_loop()
    fut: asyncio.Future[str] = loop.create_future()
    fut.set_result("from_future")

    async def coro() -> asyncio.Future[str]:
        return fut

    promise = Promise(coro())

    result = await promise.unpack_once()
    assert isinstance(result, asyncio.Future)
    assert result is fut


# ---------------------------------------------------------------------------
# Promise returning a coroutine object (also awaitable)
# ---------------------------------------------------------------------------


async def test_coroutine_object_await_unpacks() -> None:
    """`await` should unpack a coroutine object returned as a result."""

    async def inner() -> str:
        return "from_coro"

    async def outer() -> Any:
        return inner()  # returns the coroutine object, doesn't await it

    promise = Promise(outer())

    assert await promise == "from_coro"


async def test_coroutine_object_unpack_once_stops() -> None:
    """`unpack_once()` returns the coroutine object without running it."""

    async def inner() -> str:
        return "from_coro"

    async def outer() -> Any:
        return inner()

    promise = Promise(outer())

    result = await promise.unpack_once()
    # result should be the coroutine object itself
    assert asyncio.iscoroutine(result)

    # Clean up: await the coroutine so it doesn't trigger a warning
    assert await result == "from_coro"


# ---------------------------------------------------------------------------
# Promise returning a CustomAwaitableWithSleep (yields control)
# ---------------------------------------------------------------------------


async def test_awaitable_with_sleep_await_unpacks() -> None:
    """`await` unpacks through an awaitable that yields control."""

    async def coro() -> CustomAwaitableWithSleep:
        return CustomAwaitableWithSleep("slept_value")

    promise = Promise(coro())

    assert await promise == "slept_value"


async def test_awaitable_with_sleep_unpack_once_stops() -> None:
    """`unpack_once()` returns the awaitable."""

    async def coro() -> CustomAwaitableWithSleep:
        return CustomAwaitableWithSleep("slept_value")

    promise = Promise(coro())

    result = await promise.unpack_once()
    assert isinstance(result, CustomAwaitableWithSleep)


# ---------------------------------------------------------------------------
# Deeply nested – 5 levels of Promises
# ---------------------------------------------------------------------------


async def test_five_levels_await_unpacks_all() -> None:
    """`await` flattens 5 levels of promise nesting."""
    p = Promise(prefilled_result="5 deep")
    for _ in range(4):
        inner = p

        async def wrap(inner_ref=inner):
            return inner_ref

        p = Promise(wrap())

    assert await p == "5 deep"


async def test_five_levels_sequential_unpack_once() -> None:
    """Sequentially calling `unpack_once()` 5 times peels off all layers."""
    p5 = Promise(prefilled_result="5 deep")

    promises = [p5]
    for _ in range(4):
        inner = promises[-1]

        async def wrap(inner_ref=inner):
            return inner_ref

        promises.append(Promise(wrap()))

    # promises[-1] is the outermost; promises[0] is the innermost (p5)
    current = promises[-1]
    for i in range(4, 0, -1):
        result = await current.unpack_once()
        assert isinstance(result, Promise)
        assert result is promises[i - 1]
        current = result

    # Final unpack gives the scalar
    assert await current.unpack_once() == "5 deep"


# ---------------------------------------------------------------------------
# start_soon variations with nested promises
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("start_soon", [True, False])
async def test_nested_with_start_soon(*, start_soon: bool) -> None:
    """Unpacking works regardless of start_soon setting."""
    inner = Promise(prefilled_result="inner_val")

    async def outer_coro() -> Promise[str]:
        return inner

    outer = Promise(outer_coro(), start_soon=start_soon)

    assert await outer == "inner_val"

    # Also verify unpack_once on a fresh promise
    outer2 = Promise(outer_coro(), start_soon=start_soon)
    # We need a new coro for the new promise
    inner2 = Promise(prefilled_result="inner_val2")

    # Get rid of the asyncio warning
    await outer2

    async def outer_coro2() -> Promise[str]:
        return inner2

    outer2 = Promise(outer_coro2(), start_soon=start_soon)
    result = await outer2.unpack_once()
    assert isinstance(result, Promise)
    assert result is inner2


# ---------------------------------------------------------------------------
# Non-awaitable results are returned as-is
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [42, "string", [1, 2, 3], {"key": "val"}, None, True, 3.14],
    ids=["int", "str", "list", "dict", "None", "bool", "float"],
)
async def test_non_awaitable_returned_as_is(*, value: Any) -> None:
    """Both `await` and `unpack_once()` return non-awaitable values as-is."""
    promise = Promise(prefilled_result=value)

    assert await promise == value
    assert await promise.unpack_once() == value


# ---------------------------------------------------------------------------
# Exception propagation through nesting
# ---------------------------------------------------------------------------


async def test_exception_in_inner_promise_await() -> None:
    """`await` on outer propagates exception from inner promise."""
    inner = Promise(prefilled_exception=ValueError("inner error"))

    async def outer_coro() -> Promise:
        return inner

    outer = Promise(outer_coro())

    with pytest.raises(ValueError, match="inner error"):
        await outer


async def test_exception_in_inner_promise_unpack_once() -> None:
    """`unpack_once()` on outer returns the inner promise (doesn't raise)."""
    inner = Promise(prefilled_exception=ValueError("inner error"))

    async def outer_coro() -> Promise:
        return inner

    outer = Promise(outer_coro())

    result = await outer.unpack_once()
    assert isinstance(result, Promise)
    assert result is inner

    # The exception surfaces when we await the inner promise
    with pytest.raises(ValueError, match="inner error"):
        await result
