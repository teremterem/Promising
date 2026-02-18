# TODO Split into multiple files
"""
Tests for PromisingFunction and the function() decorator.
"""

import asyncio

import pytest

import promising
from promising.errors import PromisingFunctionNotCallableError
from promising.sentinels import GLOBAL_DEFAULT, INHERIT, NOT_SET, Sentinel

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


@pytest.mark.parametrize("everything_starts_soon_by_default", [True, False, INHERIT, GLOBAL_DEFAULT])
@pytest.mark.parametrize("start_soon", [True, False, INHERIT, NOT_SET])
@pytest.mark.parametrize("children_start_soon_by_default", [True, False, INHERIT, NOT_SET])
async def test_config_forwarding(
    *,
    start_soon: bool | Sentinel,
    children_start_soon_by_default: bool | Sentinel,
    everything_starts_soon_by_default: bool | Sentinel,
) -> None:
    """
    Parametrized over all three config parameters. At root
    level (no parent), INHERIT and GLOBAL_DEFAULT for
    everything_starts_soon_by_default both resolve to the
    global default (True). For start_soon, both INHERIT and
    NOT_SET fall back to everything_starts_soon_by_default.
    For children_start_soon_by_default, INHERIT resolves to
    everything_starts_soon_by_default, while NOT_SET stays
    as NOT_SET (no enforcement on children).
    """

    @promising.function(
        start_soon=start_soon,
        children_start_soon_by_default=children_start_soon_by_default,
        everything_starts_soon_by_default=everything_starts_soon_by_default,
    )
    async def noop() -> None:
        pass

    promise = noop()

    # At root level, INHERIT and GLOBAL_DEFAULT both read
    # the global default (True).
    expected_everything = (
        everything_starts_soon_by_default if isinstance(everything_starts_soon_by_default, bool) else True
    )
    # INHERIT and NOT_SET for start_soon fall back to
    # everything_starts_soon_by_default at root.
    expected_start_soon = start_soon if isinstance(start_soon, bool) else expected_everything
    # INHERIT resolves to everything_starts_soon_by_default;
    # NOT_SET stays as NOT_SET (no enforcement).
    expected_children = (
        expected_everything if children_start_soon_by_default is INHERIT else children_start_soon_by_default
    )

    assert promise._everything_starts_soon_by_default is expected_everything
    assert promise._start_soon is expected_start_soon
    assert promise._children_start_soon_by_default is expected_children

    await promise


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


@pytest.mark.parametrize("everything_starts_soon_by_default", [True, False])
@pytest.mark.parametrize("parent_start_soon", [True, False])
async def test_everything_starts_soon_by_default_inherits_from_parent(
    *,
    everything_starts_soon_by_default: bool,
    parent_start_soon: bool,
) -> None:
    """
    INHERIT (the default for everything_starts_soon_by_default)
    propagates the parent's value to child Promises. A parent
    with everything_starts_soon_by_default=False causes
    children (with INHERIT) to also resolve to False,
    overriding the global default (True).
    """
    child_promise = None

    @promising.function  # start_soon=NOT_SET, everything_starts_soon_by_default=INHERIT
    async def child_func() -> None:
        pass

    @promising.function(
        everything_starts_soon_by_default=everything_starts_soon_by_default,
        start_soon=parent_start_soon,
    )
    async def parent_func() -> None:
        nonlocal child_promise
        child_promise = child_func()

    await parent_func()
    assert child_promise._everything_starts_soon_by_default is everything_starts_soon_by_default
    # NOT_SET for start_soon falls back to the inherited value.
    assert child_promise._start_soon is everything_starts_soon_by_default
    await child_promise


@pytest.mark.parametrize("parent_starts_soon_by_default", [True, False])
@pytest.mark.parametrize("parent_start_soon", [True, False])
@pytest.mark.parametrize("child_start_soon", [True, False])
async def test_everything_starts_soon_by_default_global_default_ignores_parent(
    *,
    parent_starts_soon_by_default: bool,
    parent_start_soon: bool,
    child_start_soon: bool,
) -> None:
    """
    GLOBAL_DEFAULT always reads the live global setting,
    ignoring the parent's everything_starts_soon_by_default.
    """
    child_promise = None

    @promising.function(everything_starts_soon_by_default=GLOBAL_DEFAULT, start_soon=child_start_soon)
    async def child_func() -> None:
        pass

    @promising.function(everything_starts_soon_by_default=parent_starts_soon_by_default, start_soon=parent_start_soon)
    async def parent_func() -> None:
        nonlocal child_promise
        child_promise = child_func()

    await parent_func()
    # GLOBAL_DEFAULT always reads the live global (True).
    assert child_promise._everything_starts_soon_by_default is True
    await child_promise


@pytest.mark.parametrize("children_start_soon_by_default", [True, False, NOT_SET])
@pytest.mark.parametrize("parent_start_soon", [True, False])
async def test_children_start_soon_by_default_enforced_on_children(
    *,
    children_start_soon_by_default: bool | Sentinel,
    parent_start_soon: bool,
) -> None:
    """
    children_start_soon_by_default on the parent controls
    the start_soon resolution of child Promises that leave
    start_soon as NOT_SET. A concrete bool enforces that
    value; NOT_SET means no enforcement (child falls back
    to everything_starts_soon_by_default).
    """
    child_promise = None

    @promising.function  # start_soon=NOT_SET
    async def child_func() -> None:
        pass

    @promising.function(
        start_soon=parent_start_soon,
        children_start_soon_by_default=children_start_soon_by_default,
    )
    async def parent_func() -> None:
        nonlocal child_promise
        child_promise = child_func()

    await parent_func()

    # NOT_SET means no enforcement; child falls back to
    # everything_starts_soon_by_default (global default: True).
    expected_start_soon = True if children_start_soon_by_default is NOT_SET else children_start_soon_by_default
    assert child_promise._start_soon is expected_start_soon
    await child_promise


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


@pytest.mark.parametrize("await_remaining_children", [True, False])
async def test_promise_await_remaining_children(*, await_remaining_children: bool) -> None:
    """
    Parametrized over await_remaining_children={True, False}.
    With True: the parent coro body explicitly calls
    await_remaining_children(), so the child completes before
    the parent resolves. With False: the parent resolves
    without waiting for the child.
    """
    execution_order: list[str] = []
    child_promise = None

    @promising.function(start_soon=True)
    async def child_func() -> str:
        await asyncio.sleep(0.1)
        execution_order.append("child_done")
        return "child"

    @promising.function
    async def parent_func() -> str:
        nonlocal child_promise
        child_promise = child_func()
        execution_order.append("parent_coro_done")
        if await_remaining_children:
            await promising.get_current_promise().await_remaining_children()
        return "parent"

    await parent_func()

    if await_remaining_children:
        assert execution_order == ["parent_coro_done", "child_done"]
    else:
        assert execution_order == ["parent_coro_done"]

    # Let's await for the child promise to complete, so that we don't get any
    # asyncio warnings about the child promise being not awaited (or being
    # cancelled).
    await child_promise
