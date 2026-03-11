"""
Tests for Promise unpacking behavior: `await promise` (unpack_all)
vs `await promise.unpack_once()`.

`await promise` should recursively unpack the result until it's no longer
awaitable, while `unpack_once()` should only unpack a single level.
"""

import asyncio
from typing import Any

import pytest

import promising
from promising import Promise

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
# Promise returning a coroutine
# ---------------------------------------------------------------------------


async def test_custom_coroutine_await_unpacks() -> None:
    """`await` unpacks through a coroutine to the final value."""

    async def custom_coro() -> str:
        return "custom_value"

    async def coro() -> Any:
        return custom_coro()

    promise = Promise(coro())

    assert await promise == "custom_value"


async def test_custom_coroutine_unpack_once_stops() -> None:
    """`unpack_once()` returns the coroutine wrapped in a Promise."""

    async def custom_coro() -> str:
        return "custom_value"

    async def coro() -> Any:
        return custom_coro()

    promise = Promise(coro())

    result = await promise.unpack_once()
    assert isinstance(result, Promise)

    # Get rid of the asyncio warning
    assert await result == "custom_value"


# ---------------------------------------------------------------------------
# Promise → coroutine → Promise
# ---------------------------------------------------------------------------


async def test_mixed_chain_await_unpacks_all() -> None:
    """`await` unpacks through Promise → coroutine → scalar."""

    async def custom_coro() -> Promise[str]:
        return Promise(prefilled_result="final")

    async def coro() -> Any:
        return custom_coro()

    promise = Promise(coro())

    # coroutine wraps a Promise; `await promise` should unpack:
    # promise → coroutine → inner Promise → "final"
    assert await promise == "final"


async def test_mixed_chain_unpack_once() -> None:
    """`unpack_once()` on outer promise returns the coroutine wrapped in a Promise."""

    inner = None

    async def custom_coro() -> Promise[str]:
        return inner

    async def coro() -> Any:
        nonlocal inner
        inner = Promise(prefilled_result="final")
        return custom_coro()

    promise = Promise(coro())

    result = await promise.unpack_once()
    assert isinstance(result, Promise)

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
# Promise returning a coroutine that yields control
# ---------------------------------------------------------------------------


async def test_coroutine_with_sleep_await_unpacks() -> None:
    """`await` unpacks through a coroutine that yields control."""

    async def sleeping_coro() -> str:
        await asyncio.sleep(0.1)
        return "slept_value"

    async def coro() -> Any:
        return sleeping_coro()

    promise = Promise(coro())

    assert await promise == "slept_value"


async def test_coroutine_with_sleep_unpack_once_stops() -> None:
    """`unpack_once()` returns the coroutine wrapped in a Promise."""

    async def sleeping_coro() -> str:
        await asyncio.sleep(0.1)
        return "slept_value"

    async def coro() -> Any:
        return sleeping_coro()

    promise = Promise(coro())

    result = await promise.unpack_once()
    assert isinstance(result, Promise)

    # Get rid of the asyncio warning
    assert await result == "slept_value"


# ---------------------------------------------------------------------------
# Deeply nested – 5 levels of Promises
# ---------------------------------------------------------------------------


async def test_five_levels_await_unpacks_all() -> None:
    """`await` flattens 5 levels of promise nesting."""

    async def make_chain(depth: int) -> Any:
        if depth == 0:
            return "5 deep"
        return Promise(make_chain(depth - 1))

    p = Promise(make_chain(4))

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

    async def outer_coro() -> str:
        return Promise(prefilled_result="inner_val")

    outer = Promise(outer_coro(), start_soon=start_soon)

    assert await outer == "inner_val"

    # Also verify unpack_once on a fresh promise
    inner2 = None

    async def outer_coro2() -> str:
        nonlocal inner2
        inner2 = Promise(prefilled_result="inner_val2")
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

    async def outer_coro() -> str:
        return Promise(prefilled_exception=ValueError("inner error"))

    outer = Promise(outer_coro())

    with pytest.raises(ValueError, match="inner error"):
        await outer


async def test_exception_in_inner_promise_unpack_once() -> None:
    """`unpack_once()` on outer returns the inner promise (doesn't raise)."""
    inner = None

    async def outer_coro() -> str:
        nonlocal inner
        inner = Promise(prefilled_exception=ValueError("inner error"))
        return inner

    outer = Promise(outer_coro())

    result = await outer.unpack_once()
    assert isinstance(result, Promise)
    assert result is inner

    # The exception surfaces when we await the inner promise
    with pytest.raises(ValueError, match="inner error"):
        await result


async def test_coro_exception_at_depth_5_with_promising_context_and_functions() -> None:
    """
    Coroutine that raises in a PromisingContext is 5 levels deep in a mixed
    chain of sync and async PromisingFunctions.

    Chain: PromisingFunction → coroutine → PromisingFunction[sync] →
        → PromisingFunction → PromisingContext(coroutine[raises])
    """

    @promising.context
    async def coro5_failing_in_context() -> str:
        raise ValueError("coro error at the end")

    @promising.function
    async def func4() -> Any:
        return coro5_failing_in_context()

    @promising.function
    def func3() -> Any:
        return func4()

    async def coro2() -> Any:
        return func3()

    @promising.function
    async def func1() -> Any:
        return coro2()

    with pytest.raises(ValueError, match="coro error at the end"):
        await func1()
