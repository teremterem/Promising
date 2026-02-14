"""
Tests for PromisingFunction and the function() decorator.
"""

import asyncio

import pytest

from promising.errors import PromiseFunctionNotCallableError
from promising.promise import Promise
from promising.promising_function import PromisingFunction, function
from promising.sentinels import NOT_SET

# ── 1. Core: Async Function Wrapping & Argument Forwarding ──────────


async def test_calling_promising_function_returns_promise() -> None:
    async def greet() -> str:
        return "hello"

    pf = PromisingFunction(greet)
    result = pf()
    assert isinstance(result, Promise)
    assert await result == "hello"


async def test_forwards_positional_args() -> None:
    async def add(a: int, b: int) -> int:
        return a + b

    pf = PromisingFunction(add)
    assert await pf(1, 2) == 3


async def test_forwards_keyword_args() -> None:
    async def greet(*, greeting: str, name: str) -> str:
        return f"{greeting}, {name}"

    pf = PromisingFunction(greet)
    assert await pf(greeting="hi", name="world") == "hi, world"


async def test_forwards_mixed_args() -> None:
    async def mixed(a: int, b: int, *, suffix: str = "!") -> str:
        return f"{a + b}{suffix}"

    pf = PromisingFunction(mixed)
    assert await pf(3, 4, suffix="?") == "7?"


async def test_coroutine_executes_once() -> None:
    call_count = 0

    async def counted() -> str:
        nonlocal call_count
        call_count += 1
        return "done"

    pf = PromisingFunction(counted)
    assert await pf() == "done"
    assert call_count == 1
    assert await pf() == "done"
    assert call_count == 2


async def test_no_args_function() -> None:
    async def constant() -> int:
        return 42

    pf = PromisingFunction(constant)
    assert await pf() == 42


async def test_default_args() -> None:
    async def with_defaults(x: int = 10, y: int = 20) -> int:
        return x + y

    pf = PromisingFunction(with_defaults)
    assert await pf() == 30
    assert await pf(1, 2) == 3


async def test_star_args_and_kwargs() -> None:
    async def variadic(*args: int, **kwargs: str) -> tuple:
        return (args, kwargs)

    pf = PromisingFunction(variadic)
    result = await pf(1, 2, 3, key="value")
    assert result == ((1, 2, 3), {"key": "value"})


# ── 2. Callable Classes ─────────────────────────────────────────────


async def test_with_callable_class() -> None:
    class Greeter:
        def __init__(self, name: str) -> None:
            self.name = name

        async def __call__(self) -> str:
            return f"hello, {self.name}"

    pf = PromisingFunction(Greeter)
    assert await pf("world") == "hello, world"


async def test_with_callable_class_kwargs() -> None:
    class Greeter:
        def __init__(self, *, greeting: str, name: str) -> None:
            self.greeting = greeting
            self.name = name

        async def __call__(self) -> str:
            return f"{self.greeting}, {self.name}"

    pf = PromisingFunction(Greeter)
    assert await pf(greeting="hi", name="world") == "hi, world"


async def test_callable_class_execution_count() -> None:
    init_count = 0
    call_count = 0

    class Counter:
        def __init__(self) -> None:
            nonlocal init_count
            init_count += 1

        async def __call__(self) -> str:
            nonlocal call_count
            call_count += 1
            return "counted"

    pf = PromisingFunction(Counter)
    assert await pf() == "counted"
    assert init_count == 1
    assert call_count == 1
    assert await pf() == "counted"
    assert init_count == 2
    assert call_count == 2


# ── 3. Error Cases ──────────────────────────────────────────────────


async def test_none_raises_on_call() -> None:
    pf = PromisingFunction(None)
    with pytest.raises(PromiseFunctionNotCallableError):
        pf()


async def test_none_raises_on_call_with_args() -> None:
    pf = PromisingFunction(None)
    with pytest.raises(PromiseFunctionNotCallableError):
        pf(1, 2, key="v")


async def test_exception_propagates_through_promise() -> None:
    async def failing() -> None:
        raise ValueError("test error")

    pf = PromisingFunction(failing)
    with pytest.raises(ValueError, match="test error"):
        await pf()


async def test_exception_from_class_callable() -> None:
    class Failing:
        def __init__(self) -> None:
            pass

        async def __call__(self) -> None:
            raise RuntimeError("class call error")

    pf = PromisingFunction(Failing)
    with pytest.raises(RuntimeError, match="class call error"):
        await pf()


async def test_exception_in_class_init() -> None:
    class FailingInit:
        def __init__(self) -> None:
            raise TypeError("init error")

        async def __call__(self) -> None:
            pass

    pf = PromisingFunction(FailingInit)
    with pytest.raises(TypeError, match="init error"):
        pf()


@pytest.mark.parametrize(
    "exc_type",
    [ValueError, TypeError, RuntimeError, KeyError],
)
async def test_various_exception_types(*, exc_type: type) -> None:
    async def failing() -> None:
        raise exc_type("specific error")

    pf = PromisingFunction(failing)
    with pytest.raises(exc_type):
        await pf()


# ── 4. function() Decorator Modes ───────────────────────────────────


async def test_decorator_bare() -> None:
    @function
    async def greet() -> str:
        return "hello"

    assert isinstance(greet, PromisingFunction)
    result = greet()
    assert isinstance(result, Promise)
    assert await result == "hello"


async def test_decorator_with_empty_parens() -> None:
    @function()
    async def greet() -> str:
        return "hello"

    assert isinstance(greet, PromisingFunction)
    assert await greet() == "hello"


async def test_decorator_with_config() -> None:
    @function(start_soon=False, make_parent_wait=True)
    async def worker() -> str:
        return "done"

    assert isinstance(worker, PromisingFunction)
    promise = worker()
    config = promise.get_config()
    assert config.is_start_soon() is False
    assert config.is_make_parent_wait() is True
    await promise


async def test_decorator_with_class() -> None:
    @function
    class Greeter:
        def __init__(self, name: str) -> None:
            self.name = name

        async def __call__(self) -> str:
            return f"hello, {self.name}"

    assert isinstance(Greeter, PromisingFunction)
    assert await Greeter("world") == "hello, world"


async def test_used_as_direct_call() -> None:
    async def my_func() -> str:
        return "direct"

    pf = function(my_func)
    assert isinstance(pf, PromisingFunction)
    assert await pf() == "direct"


async def test_preserves_original_func() -> None:
    async def original() -> str:
        return "preserved"

    decorated = function(original)
    assert decorated.original is original


# ── 5. Config Forwarding (Parametrized) ─────────────────────────────


@pytest.mark.parametrize("start_soon", [True, False, NOT_SET])
@pytest.mark.parametrize("make_parent_wait", [True, False, NOT_SET])
@pytest.mark.parametrize(
    "config_inheritable",
    [True, NOT_SET],
    ids=["inheritable_true", "inheritable_not_set"],
)
async def test_config_forwarding(
    *,
    start_soon: bool,
    make_parent_wait: bool,
    config_inheritable: bool,
) -> None:
    """
    config_inheritable=False is excluded because root configs
    (Promises created outside a parent context) disallow it.
    See test_config_inheritable_false_on_root_raises for that
    case.
    """

    async def noop() -> None:
        pass

    pf = PromisingFunction(
        noop,
        start_soon=start_soon,
        make_parent_wait=make_parent_wait,
        config_inheritable=config_inheritable,
    )
    promise = pf()
    config = promise.get_config()

    # NOT_SET → defaults: start_soon=True,
    # make_parent_wait=False, config_inheritable=True
    expected_start_soon = True if start_soon is NOT_SET else start_soon
    expected_make_parent_wait = False if make_parent_wait is NOT_SET else make_parent_wait

    assert config.is_start_soon() is expected_start_soon
    assert config.is_make_parent_wait() is expected_make_parent_wait
    # Both True and NOT_SET resolve to True for root configs
    assert config.is_config_inheritable() is True

    await promise


async def test_config_inheritable_false_on_root_raises() -> None:
    """
    Root configs (no parent) cannot have config_inheritable=False.
    """

    async def noop() -> None:
        pass

    pf = PromisingFunction(noop, config_inheritable=False)
    with pytest.raises(ValueError, match="Cannot set config_inheritable to False"):
        pf()


@pytest.mark.parametrize("start_soon", [True, False])
async def test_start_soon_behavior(*, start_soon: bool) -> None:
    executed = False

    async def worker() -> str:
        nonlocal executed
        executed = True
        return "done"

    pf = PromisingFunction(worker, start_soon=start_soon)
    promise = pf()

    # Give the event loop a chance to run scheduled tasks
    await asyncio.sleep(0.05)

    if start_soon:
        assert executed is True
    else:
        assert executed is False

    await promise
    assert executed is True


# ── 6. Edge Cases & Integration ─────────────────────────────────────


async def test_call_delegates_to_call_method() -> None:
    async def add(a: int, b: int) -> int:
        return a + b

    pf = PromisingFunction(add)
    result_call = await pf(1, 2)
    result_method = await pf.call(3, 4)
    assert result_call == 3
    assert result_method == 7


async def test_multiple_calls_produce_independent_promises() -> None:
    async def identity(x: int) -> int:
        return x

    pf = PromisingFunction(identity)
    p1 = pf(1)
    p2 = pf(2)
    assert p1 is not p2
    assert await p1 == 1
    assert await p2 == 2


async def test_result_is_awaitable_promise() -> None:
    async def noop() -> None:
        pass

    pf = PromisingFunction(noop)
    result = pf()
    assert isinstance(result, Promise)
    assert isinstance(result, asyncio.Future)
    await result


async def test_promise_has_parent_when_created_in_context() -> None:
    child_promise = None

    async def child_func() -> str:
        return "child"

    async def parent_func() -> str:
        nonlocal child_promise
        child_pf = PromisingFunction(child_func)
        child_promise = child_pf()
        return "parent"

    parent_pf = PromisingFunction(parent_func)
    parent_promise = parent_pf()
    await parent_promise

    assert child_promise is not None
    await child_promise
    assert child_promise.get_parent(raise_if_none=False) is parent_promise


async def test_promise_has_no_parent_outside_context() -> None:
    async def noop() -> None:
        pass

    pf = PromisingFunction(noop)
    promise = pf()
    assert promise.get_parent(raise_if_none=False) is None
    await promise


async def test_make_parent_wait_integration() -> None:
    execution_order: list[str] = []

    async def child_func() -> str:
        await asyncio.sleep(0.05)
        execution_order.append("child_done")
        return "child"

    async def parent_func() -> str:
        child_pf = PromisingFunction(
            child_func,
            start_soon=True,
            make_parent_wait=True,
        )
        child_pf()
        execution_order.append("parent_coro_done")
        return "parent"

    parent_pf = PromisingFunction(parent_func)
    parent_promise = parent_pf()
    await parent_promise

    # Parent waits for child, so child_done comes before
    # the parent promise resolves. The parent coro body
    # finishes first, then _afinalize waits for children.
    assert execution_order == ["parent_coro_done", "child_done"]
