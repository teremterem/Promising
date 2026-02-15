"""
Tests for PromisingFunction and the function() decorator.
"""

import asyncio

import pytest

import promising
from promising.errors import PromisingFunctionNotCallableError
from promising.sentinels import NOT_SET, Sentinel

# ── 1. Core: Async Function Wrapping & Argument Forwarding ──────────


async def test_calling_promising_function_returns_promise() -> None:
    """
    Calling a decorated function returns a Promise;
    awaiting it returns the expected value.
    """

    @promising.function
    async def greet() -> str:
        return "hello"

    result = greet()
    assert isinstance(result, promising.Promise)
    assert await result == "hello"


async def test_forwards_positional_args() -> None:
    """
    Positional args are correctly forwarded to the
    wrapped async function.
    """

    @promising.function
    async def add(a: int, b: int) -> int:
        return a + b

    assert await add(1, 2) == 3


async def test_forwards_keyword_args() -> None:
    """
    Keyword-only params are correctly forwarded to the
    wrapped async function.
    """

    @promising.function
    async def greet(*, greeting: str, name: str) -> str:
        return f"{greeting}, {name}"

    assert await greet(greeting="hi", name="world") == "hi, world"


async def test_forwards_mixed_args() -> None:
    """
    A mix of positional and keyword args is forwarded
    correctly.
    """

    @promising.function
    async def mixed(a: int, b: int, *, suffix: str = "!") -> str:
        return f"{a + b}{suffix}"

    assert await mixed(3, 4, suffix="?") == "7?"


async def test_coroutine_executes_once() -> None:
    """
    A nonlocal counter confirms the coroutine runs
    exactly once per call; second call increments to 2.
    """
    call_count = 0

    @promising.function
    async def counted() -> str:
        nonlocal call_count
        call_count += 1
        return "done"

    promise_one = counted()
    # Awaiting a promise multiple times should not result in the function being
    # called multiple times
    assert await promise_one == "done"
    assert await promise_one == "done"
    assert call_count == 1

    promise_two = counted()
    # Awaiting a promise multiple times should not result in the function being
    # called multiple times
    assert await promise_two == "done"
    assert await promise_two == "done"
    assert await promise_two == "done"
    assert call_count == 2


async def test_no_args_function() -> None:
    """
    Wrapping a zero-argument async function and calling
    it with no args works.
    """

    @promising.function
    async def constant() -> int:
        return 42

    assert await constant() == 42


async def test_default_args() -> None:
    """
    Calling with no args uses defaults; calling with
    explicit args overrides them.
    """

    @promising.function
    async def with_defaults(x: int = 10, y: int = 20) -> int:
        return x + y

    assert await with_defaults() == 30
    assert await with_defaults(1, 2) == 3


async def test_star_args_and_kwargs() -> None:
    """
    *args and **kwargs are forwarded to the wrapped
    async function correctly.
    """

    @promising.function
    async def variadic(*args: int, **kwargs: str) -> tuple:
        return (args, kwargs)

    result = await variadic(1, 2, 3, key="value")
    assert result == ((1, 2, 3), {"key": "value"})


# ── 2. Callable Classes ─────────────────────────────────────────────


async def test_with_callable_class() -> None:
    """
    A class with __init__(name) and async __call__()
    is instantiated with args and awaited for the result.
    """

    @promising.function
    class Greeter:
        def __init__(self, name: str) -> None:
            self.name = name

        async def __call__(self) -> str:
            return f"hello, {self.name}"

    assert await Greeter("world") == "hello, world"


async def test_with_callable_class_kwargs() -> None:
    """
    A class with keyword-only __init__ params works
    when decorated with @promising.function.
    """

    @promising.function
    class Greeter:
        def __init__(self, *, greeting: str, name: str) -> None:
            self.greeting = greeting
            self.name = name

        async def __call__(self) -> str:
            return f"{self.greeting}, {self.name}"

    assert await Greeter(greeting="hi", name="world") == "hi, world"


async def test_callable_class_execution_count() -> None:
    """
    Each call creates a new instance — tracked via
    nonlocal counters for __init__ and __call__.
    """
    init_count = 0
    call_count = 0

    @promising.function
    class Counter:
        def __init__(self) -> None:
            nonlocal init_count
            init_count += 1

        async def __call__(self) -> str:
            nonlocal call_count
            call_count += 1
            return "counted"

    assert await Counter() == "counted"
    assert init_count == 1
    assert call_count == 1
    assert await Counter() == "counted"
    assert init_count == 2
    assert call_count == 2


# ── 3. Error Cases ──────────────────────────────────────────────────


async def test_none_raises_on_call() -> None:
    """
    PromisingFunction(None) raises
    PromisingFunctionNotCallableError when called.
    """
    pf = promising.PromisingFunction(None)
    with pytest.raises(PromisingFunctionNotCallableError):
        pf()


async def test_none_raises_on_call_with_args() -> None:
    """
    Same error even when passing args to a
    PromisingFunction wrapping None.
    """
    pf = promising.PromisingFunction(None)
    with pytest.raises(PromisingFunctionNotCallableError):
        pf(1, 2, key="v")


async def test_exception_propagates_through_promise() -> None:
    """
    An exception raised inside the async function
    propagates through the Promise when awaited.
    """

    @promising.function
    async def failing() -> None:
        raise ValueError("test error")

    with pytest.raises(ValueError, match="test error"):
        await failing()


async def test_exception_from_class_callable() -> None:
    """
    An exception raised in a class's __call__ method
    propagates through the Promise when awaited.
    """

    @promising.function
    class Failing:
        def __init__(self) -> None:
            pass

        async def __call__(self) -> None:
            raise RuntimeError("class call error")

    with pytest.raises(RuntimeError, match="class call error"):
        await Failing()


async def test_exception_in_class_init() -> None:
    """
    An exception in __init__ raises synchronously
    (before Promise creation).

    TODO We might want to deviate from this later, though.
    """

    @promising.function
    class FailingInit:
        def __init__(self) -> None:
            raise TypeError("init error")

        async def __call__(self) -> None:
            pass

    with pytest.raises(TypeError, match="init error"):
        FailingInit()


@pytest.mark.parametrize(
    "exc_type",
    [ValueError, TypeError, RuntimeError, KeyError],
)
async def test_various_exception_types(*, exc_type: type) -> None:
    """
    Parametrized: each exception type propagates
    through the Promise correctly.
    """

    @promising.function
    async def failing() -> None:
        raise exc_type("specific error")

    with pytest.raises(exc_type):
        await failing()


# ── 4. function() Decorator Modes ───────────────────────────────────


async def test_decorator_bare() -> None:
    """
    @promising.function (no parens) produces a
    PromisingFunction; calling returns a Promise;
    awaiting yields the result.
    """

    @promising.function
    async def greet() -> str:
        return "hello"

    assert isinstance(greet, promising.PromisingFunction)
    result = greet()
    assert isinstance(result, promising.Promise)
    assert await result == "hello"


async def test_decorator_with_empty_parens() -> None:
    """
    @promising.function() (empty parens) behaves
    identically to bare @promising.function.
    """

    @promising.function()
    async def greet() -> str:
        return "hello"

    assert isinstance(greet, promising.PromisingFunction)
    assert await greet() == "hello"


async def test_decorator_with_config() -> None:
    """
    @promising.function(start_soon=False,
    make_parent_wait=True) forwards config to the
    resulting Promise.
    """

    @promising.function(start_soon=False, make_parent_wait=True)
    async def worker() -> str:
        return "done"

    assert isinstance(worker, promising.PromisingFunction)
    promise = worker()
    config = promise.get_config()
    assert config.is_start_soon() is False
    assert config.is_make_parent_wait() is True
    await promise


async def test_decorator_with_class() -> None:
    """
    @promising.function applied to a class works
    end-to-end.
    """

    @promising.function
    class Greeter:
        def __init__(self, name: str) -> None:
            self.name = name

        async def __call__(self) -> str:
            return f"hello, {self.name}"

    assert isinstance(Greeter, promising.PromisingFunction)
    assert await Greeter("world") == "hello, world"


async def test_used_as_direct_call() -> None:
    """
    promising.function(my_func) used as a direct call
    (non-decorator) works.
    """

    async def my_func() -> str:
        return "direct"

    pf = promising.function(my_func)
    assert isinstance(pf, promising.PromisingFunction)
    assert await pf() == "direct"


async def test_preserves_original_func() -> None:
    """
    decorated.original is the original function passed
    to the decorator.
    """

    async def original() -> str:
        return "preserved"

    decorated = promising.function(original)
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
    start_soon: bool | Sentinel,
    make_parent_wait: bool | Sentinel,
    config_inheritable: bool | Sentinel,
) -> None:
    """
    Parametrized over start_soon, make_parent_wait,
    and config_inheritable. Asserts resolved config
    values match expectations. NOT_SET falls back to
    defaults: start_soon=True, make_parent_wait=False,
    config_inheritable=True.

    config_inheritable=False is excluded because root
    configs (Promises created outside a parent context)
    disallow it. See
    test_config_inheritable_false_on_root_raises.
    """

    async def noop() -> None:
        pass

    pf = promising.function(
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
    Root configs (no parent) cannot have
    config_inheritable=False.
    """

    async def noop() -> None:
        pass

    pf = promising.function(noop, config_inheritable=False)
    with pytest.raises(ValueError, match="Cannot set config_inheritable to False"):
        pf()


@pytest.mark.parametrize("start_soon", [True, False])
async def test_start_soon_behavior(*, start_soon: bool) -> None:
    """
    With start_soon=True: after calling + sleeping,
    the coroutine has already executed. With False:
    it hasn't executed until explicitly awaited.
    """
    executed = False

    async def worker() -> str:
        nonlocal executed
        executed = True
        return "done"

    pf = promising.function(worker, start_soon=start_soon)
    promise = pf()

    # Give the event loop a chance to run scheduled tasks
    await asyncio.sleep(0.1)

    if start_soon:
        assert executed is True
    else:
        assert executed is False

    await promise
    assert executed is True


# ── 6. Edge Cases & Integration ─────────────────────────────────────


async def test_call_delegates_to_call_method() -> None:
    """
    Calling via __call__ and via .call() produce
    equivalent results.
    """

    @promising.function
    async def add(a: int, b: int) -> int:
        return a + b

    result_call = await add(1, 2)
    result_method = await add.call(3, 4)
    assert result_call == 3
    assert result_method == 7


async def test_multiple_calls_produce_independent_promises() -> None:
    """
    Each call produces a distinct Promise with an
    independent result.
    """

    @promising.function
    async def identity(x: int) -> int:
        return x

    p1 = identity(1)
    p2 = identity(2)
    assert p1 is not p2
    assert await p1 == 1
    assert await p2 == 2


async def test_result_is_awaitable_promise() -> None:
    """
    The return value is both an instance of Promise
    and an instance of asyncio.Future.
    """

    @promising.function
    async def noop() -> None:
        pass

    result = noop()
    assert isinstance(result, promising.Promise)
    assert isinstance(result, asyncio.Future)
    await result


async def test_promise_has_parent_when_created_in_context() -> None:
    """
    A child Promise created inside a parent Promise's
    execution has get_parent() pointing to the parent.
    """
    child_promise = None

    @promising.function
    async def child_func() -> str:
        return "child"

    @promising.function
    async def parent_func() -> str:
        nonlocal child_promise
        child_promise = child_func()
        return "parent"

    parent_promise = parent_func()
    await parent_promise

    assert child_promise is not None
    await child_promise
    assert child_promise.get_parent(raise_if_none=False) is parent_promise


async def test_promise_has_no_parent_outside_context() -> None:
    """
    A Promise created at top level (outside any parent
    context) has no parent.
    """

    @promising.function
    async def noop() -> None:
        pass

    promise = noop()
    assert promise.get_parent(raise_if_none=False) is None
    await promise


@pytest.mark.parametrize("make_parent_wait", [True, False])
async def test_make_parent_wait_integration(*, make_parent_wait: bool) -> None:
    """
    Parametrized over make_parent_wait={True, False}.
    With True: the child completes before the parent
    promise resolves (parent coro body finishes first,
    then _afinalize waits for the child). With False:
    the parent resolves without waiting for the child.
    """
    execution_order: list[str] = []
    child_promise = None

    @promising.function(start_soon=True, make_parent_wait=make_parent_wait)
    async def child_func() -> str:
        await asyncio.sleep(0.1)
        execution_order.append("child_done")
        return "child"

    @promising.function
    async def parent_func() -> str:
        nonlocal child_promise
        child_promise = child_func()
        execution_order.append("parent_coro_done")
        return "parent"

    parent_promise = parent_func()
    await parent_promise

    if make_parent_wait:
        assert execution_order == ["parent_coro_done", "child_done"]
    else:
        assert execution_order == ["parent_coro_done"]

    # Let's await for the child promise to complete, so that we don't get any
    # asyncio warnings about the child promise being not awaited (or being
    # cancelled).
    await child_promise
