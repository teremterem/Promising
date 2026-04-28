import asyncio
from typing import Any

import pytest

import promising
from promising import Promise


@pytest.mark.parametrize("unpack_once", [True, False])
async def test_single_promise_no_nesting(*, unpack_once: bool) -> None:
    """A plain promise with a scalar result behaves the same
    for both `sync` and `unpack_once_sync`."""

    async def coro() -> str:
        return "hello"

    promise: Promise[str] = Promise(coro())
    loop = asyncio.get_running_loop()

    if unpack_once:
        result = await loop.run_in_executor(None, promise.unpack_once_sync)
    else:
        result = await loop.run_in_executor(None, promise.sync)

    assert result == "hello"


async def test_prefilled_promise_no_nesting() -> None:
    """Prefilled promise works the same for both modes."""
    promise = Promise(prefilled_result=42)
    loop = asyncio.get_running_loop()

    assert await loop.run_in_executor(None, promise.sync) == 42
    assert await loop.run_in_executor(None, promise.unpack_once_sync) == 42


async def test_two_levels_unpack_all() -> None:
    """`sync()` should unpack both levels and return the
    final value."""

    async def inner_coro() -> str:
        return "deep value"

    async def outer_coro() -> str:
        return Promise(inner_coro())

    outer: Promise[str] = Promise(outer_coro())
    loop = asyncio.get_running_loop()

    result = await loop.run_in_executor(None, outer.sync)
    assert result == "deep value"


async def test_two_levels_unpack_once_stop_at_inner() -> None:
    """`unpack_once_sync()` on the outer promise should
    return the inner promise, not the final scalar."""

    async def inner_coro() -> str:
        return "deep value"

    inner = None

    async def outer_coro() -> str:
        nonlocal inner
        inner = Promise(inner_coro())
        return inner

    outer: Promise[str] = Promise(outer_coro())
    loop = asyncio.get_running_loop()

    result = await loop.run_in_executor(None, outer.unpack_once_sync)
    assert isinstance(result, Promise)
    assert result is inner

    # Awaiting the inner promise should give the scalar
    assert await result == "deep value"


async def test_three_levels_unpack_all() -> None:
    """`sync()` on a triply-nested promise returns the
    deepest value."""

    async def mid_coro() -> str:
        return Promise(prefilled_result="bottom")

    async def top_coro() -> str:
        return Promise(mid_coro())

    p1 = Promise(top_coro())
    loop = asyncio.get_running_loop()

    assert await loop.run_in_executor(None, p1.sync) == "bottom"


async def test_three_levels_unpack_once_return_second_level() -> None:
    """`unpack_once_sync()` on a triply-nested promise
    returns the second-level promise."""
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
    loop = asyncio.get_running_loop()

    level2 = await loop.run_in_executor(None, p1.unpack_once_sync)
    assert isinstance(level2, Promise)
    assert level2 is p2

    level3 = await loop.run_in_executor(None, level2.unpack_once_sync)
    assert isinstance(level3, Promise)
    assert level3 is p3

    assert await loop.run_in_executor(None, level3.unpack_once_sync) == "bottom"


@pytest.mark.xfail_feature_possibly_obsolete
async def test_custom_coroutine_unpack_all() -> None:
    """`sync()` unpacks through a coroutine to the final
    value."""

    async def custom_coro() -> str:
        return "custom_value"

    async def coro() -> Any:
        return custom_coro()

    promise = Promise(coro())
    loop = asyncio.get_running_loop()

    assert await loop.run_in_executor(None, promise.sync) == "custom_value"


@pytest.mark.xfail_feature_possibly_obsolete
async def test_custom_coroutine_unpack_once() -> None:
    """`unpack_once_sync()` returns the coroutine wrapped in a Promise."""

    async def custom_coro() -> str:
        return "custom_value"

    async def coro() -> Any:
        return custom_coro()

    promise = Promise(coro())
    loop = asyncio.get_running_loop()

    result = await loop.run_in_executor(None, promise.unpack_once_sync)
    assert isinstance(result, Promise)

    # Get rid of the asyncio warning
    assert await result == "custom_value"


@pytest.mark.xfail_feature_possibly_obsolete
async def test_mixed_chain_unpack_all() -> None:
    """`sync()` unpacks through
    Promise → coroutine → scalar."""

    async def custom_coro() -> Promise[str]:
        return Promise(prefilled_result="final")

    async def coro() -> Any:
        return custom_coro()

    promise = Promise(coro())
    loop = asyncio.get_running_loop()

    # coroutine wraps a Promise; `sync()` should unpack:
    # promise → coroutine → inner Promise → "final"
    assert await loop.run_in_executor(None, promise.sync) == "final"


@pytest.mark.xfail_feature_possibly_obsolete
async def test_mixed_chain_unpack_once() -> None:
    """`unpack_once_sync()` on outer promise returns the
    coroutine wrapped in a Promise."""

    inner = None

    async def custom_coro() -> Promise[str]:
        return inner

    async def coro() -> Any:
        nonlocal inner
        inner = Promise(prefilled_result="final")
        return custom_coro()

    promise = Promise(coro())
    loop = asyncio.get_running_loop()

    result = await loop.run_in_executor(None, promise.unpack_once_sync)
    assert isinstance(result, Promise)

    # Awaiting the inner promise separately should work
    assert await inner == "final"


@pytest.mark.xfail_feature_possibly_obsolete
async def test_asyncio_future_unpack_all() -> None:
    """`sync()` unpacks through an asyncio.Future to the
    final value."""
    loop = asyncio.get_running_loop()
    fut: asyncio.Future[str] = loop.create_future()
    fut.set_result("from_future")

    async def coro() -> asyncio.Future[str]:
        return fut

    promise = Promise(coro())

    assert await loop.run_in_executor(None, promise.sync) == "from_future"


@pytest.mark.xfail_feature_possibly_obsolete
async def test_asyncio_future_unpack_once() -> None:
    """`unpack_once_sync()` wraps the returned asyncio.Future in a Promise."""
    loop = asyncio.get_running_loop()
    fut: asyncio.Future[str] = loop.create_future()
    fut.set_result("from_future")

    async def coro() -> asyncio.Future[str]:
        return fut

    promise = Promise(coro())

    result = await loop.run_in_executor(None, promise.unpack_once_sync)
    assert isinstance(result, Promise)
    assert result.get_parent_context() is promise
    assert await result == "from_future"


@pytest.mark.xfail_feature_possibly_obsolete
async def test_coroutine_with_sleep_unpack_all() -> None:
    """`sync()` unpacks through a coroutine that yields
    control."""

    async def sleeping_coro() -> str:
        await asyncio.sleep(0.1)
        return "slept_value"

    async def coro() -> Any:
        return sleeping_coro()

    promise = Promise(coro())
    loop = asyncio.get_running_loop()

    assert await loop.run_in_executor(None, promise.sync) == "slept_value"


@pytest.mark.xfail_feature_possibly_obsolete
async def test_coroutine_with_sleep_unpack_once() -> None:
    """`unpack_once_sync()` returns the coroutine wrapped in a Promise."""

    async def sleeping_coro() -> str:
        await asyncio.sleep(0.1)
        return "slept_value"

    async def coro() -> Any:
        return sleeping_coro()

    promise = Promise(coro())
    loop = asyncio.get_running_loop()

    result = await loop.run_in_executor(None, promise.unpack_once_sync)
    assert isinstance(result, Promise)

    # Get rid of the asyncio warning
    assert await result == "slept_value"


async def test_five_levels_unpack_all() -> None:
    """`sync()` flattens 5 levels of promise nesting."""

    async def make_chain(depth: int) -> Any:
        if depth == 0:
            return "5 deep"
        return Promise(make_chain(depth - 1))

    p = Promise(make_chain(4))
    loop = asyncio.get_running_loop()

    assert await loop.run_in_executor(None, p.sync) == "5 deep"


async def test_five_levels_sequential_unpack_once() -> None:
    """Sequentially calling `unpack_once_sync()` 5 times
    peels off all layers."""
    p5 = Promise(prefilled_result="5 deep")

    promises = [p5]
    for _ in range(4):
        inner = promises[-1]

        async def wrap(inner_ref=inner):
            return inner_ref

        promises.append(Promise(wrap()))

    # promises[-1] is the outermost;
    # promises[0] is the innermost (p5)
    loop = asyncio.get_running_loop()
    current = promises[-1]
    for i in range(4, 0, -1):
        result = await loop.run_in_executor(None, current.unpack_once_sync)
        assert isinstance(result, Promise)
        assert result is promises[i - 1]
        current = result

    # Final unpack gives the scalar
    assert await loop.run_in_executor(None, current.unpack_once_sync) == "5 deep"


@pytest.mark.parametrize("start_soon", [True, False])
async def test_nested_with_start_soon(*, start_soon: bool) -> None:
    """Unpacking works regardless of start_soon setting."""

    async def outer_coro() -> str:
        return Promise(prefilled_result="inner_val")

    outer = Promise(outer_coro(), start_soon=start_soon)
    loop = asyncio.get_running_loop()

    assert await loop.run_in_executor(None, outer.sync) == "inner_val"

    # Also verify unpack_once_sync on a fresh promise
    inner2 = None

    async def outer_coro2() -> str:
        nonlocal inner2
        inner2 = Promise(prefilled_result="inner_val2")
        return inner2

    outer2 = Promise(outer_coro2(), start_soon=start_soon)
    result = await loop.run_in_executor(None, outer2.unpack_once_sync)
    assert isinstance(result, Promise)
    assert result is inner2


@pytest.mark.parametrize(
    "value",
    [42, "string", [1, 2, 3], {"key": "val"}, None, True, 3.14],
    ids=["int", "str", "list", "dict", "None", "bool", "float"],
)
async def test_non_awaitable_returned_as_is(*, value: Any) -> None:
    """Both `sync()` and `unpack_once_sync()` return
    non-awaitable values as-is."""
    promise = Promise(prefilled_result=value)
    loop = asyncio.get_running_loop()

    assert await loop.run_in_executor(None, promise.sync) == value
    assert await loop.run_in_executor(None, promise.unpack_once_sync) == value


async def test_exception_in_inner_promise_unpack_all() -> None:
    """`sync()` on outer propagates exception from inner
    promise."""

    async def outer_coro() -> str:
        return Promise(prefilled_exception=ValueError("inner error"))

    outer = Promise(outer_coro())
    loop = asyncio.get_running_loop()

    with pytest.raises(ValueError, match="inner error"):
        await loop.run_in_executor(None, outer.sync)


async def test_exception_in_inner_promise_unpack_once() -> None:
    """`unpack_once_sync()` on outer returns the inner
    promise (doesn't raise)."""
    inner = None

    async def outer_coro() -> str:
        nonlocal inner
        inner = Promise(prefilled_exception=ValueError("inner error"))
        return inner

    outer = Promise(outer_coro())
    loop = asyncio.get_running_loop()

    result = await loop.run_in_executor(None, outer.unpack_once_sync)
    assert isinstance(result, Promise)
    assert result is inner

    # The exception surfaces when we await the inner promise
    with pytest.raises(ValueError, match="inner error"):
        await result


@pytest.mark.xfail_feature_possibly_obsolete
async def test_coro_exception_at_depth_5_with_promising_context_and_functions() -> None:
    """
    Coroutine that raises in a PromisingContext is 5 levels
    deep in a mixed chain of sync and async
    PromisingFunctions.

    Chain: PromisingFunction → coroutine →
        PromisingFunction[sync] →
        → PromisingFunction → PromisingContext(coro[raises])
    """

    @promising.context
    async def coro5_failing_in_context() -> str:
        raise ValueError("coro error at the end")

    @promising.function
    async def func4() -> Any:
        return coro5_failing_in_context()

    @promising.function(use_thread_pool=True)
    def func3() -> Any:
        return func4()

    async def coro2() -> Any:
        return func3()

    @promising.function
    async def func1() -> Any:
        return coro2()

    promise = func1()
    loop = asyncio.get_running_loop()

    with pytest.raises(ValueError, match="coro error at the end"):
        await loop.run_in_executor(None, promise.sync)
