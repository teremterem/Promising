"""
Tests for synchronous functions decorated with @promising.function.
Sync functions are executed in a thread pool executor and their results
are delivered through a Promise just like async functions.
"""

import threading

import pytest

import promising

# ── Core: Sync Function Wrapping & Argument Forwarding ──────────


async def test_calling_sync_promising_function_returns_promise() -> None:
    """
    Calling a decorated sync function returns a Promise;
    awaiting it returns the expected value.
    """

    @promising.function
    def greet() -> str:
        return "hello"

    assert isinstance(greet, promising.PromisingFunction)
    result = greet()
    assert isinstance(result, promising.Promise)
    assert await result == "hello"


async def test_forwards_positional_args() -> None:
    """
    Positional args are correctly forwarded to the
    wrapped sync function.
    """

    @promising.function
    def add(a: int, b: int) -> int:
        return a + b

    assert await add(1, 2) == 3


async def test_forwards_keyword_args() -> None:
    """
    Keyword-only params are correctly forwarded to the
    wrapped sync function.
    """

    @promising.function
    def greet(*, greeting: str, name: str) -> str:
        return f"{greeting}, {name}"

    assert await greet(greeting="hi", name="world") == "hi, world"


async def test_forwards_mixed_args() -> None:
    """
    A mix of positional and keyword args is forwarded
    correctly.
    """

    @promising.function
    def mixed(a: int, b: int, *, suffix: str = "!") -> str:
        return f"{a + b}{suffix}"

    assert await mixed(3, 4, suffix="?") == "7?"


async def test_default_args() -> None:
    """
    Calling with no args uses defaults; calling with
    explicit args overrides them.
    """

    @promising.function
    def with_defaults(x: int = 10, y: int = 20) -> int:
        return x + y

    assert await with_defaults() == 30
    assert await with_defaults(1, 2) == 3


async def test_star_args_and_kwargs() -> None:
    """
    *args and **kwargs are forwarded to the wrapped
    sync function correctly.
    """

    @promising.function
    def variadic(*args: int, **kwargs: str) -> tuple:
        return (args, kwargs)

    result = await variadic(1, 2, 3, key="value")
    assert result == ((1, 2, 3), {"key": "value"})


async def test_sync_function_executes_once() -> None:
    """
    A nonlocal counter confirms the sync function runs
    exactly once per call; second call increments to 2.
    """
    call_count = 0

    @promising.function
    def counted() -> str:
        nonlocal call_count
        call_count += 1
        return "done"

    promise_one = counted()
    assert await promise_one == "done"
    assert await promise_one == "done"
    assert call_count == 1

    promise_two = counted()
    assert await promise_two == "done"
    assert await promise_two == "done"
    assert call_count == 2


# ── Thread Verification ──────────────────────────────────────────


async def test_sync_function_runs_in_different_thread() -> None:
    """
    The sync function actually runs in a different thread
    than the event loop thread.
    """
    main_thread = threading.current_thread()

    @promising.function
    def get_thread() -> threading.Thread:
        return threading.current_thread()

    worker_thread = await get_thread()
    assert worker_thread is not main_thread


# ── Error Cases ──────────────────────────────────────────────────


async def test_exception_propagates_through_promise() -> None:
    """
    An exception raised inside the sync function
    propagates through the Promise when awaited.
    """

    @promising.function
    def failing() -> None:
        raise ValueError("test error")

    with pytest.raises(ValueError, match="test error"):
        await failing()


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
    def failing() -> None:
        raise exc_type("specific error")

    with pytest.raises(exc_type):
        await failing()


# ── function() Decorator Modes ───────────────────────────────────


async def test_decorator_with_empty_parens() -> None:
    """
    @promising.function() (empty parens) behaves
    identically to bare @promising.function for sync functions.
    """

    @promising.function()
    def greet() -> str:
        return "hello"

    assert isinstance(greet, promising.PromisingFunction)
    assert await greet() == "hello"


async def test_used_as_direct_call() -> None:
    """
    promising.function(my_func) used as a direct call
    (non-decorator) works for sync functions.
    """

    def my_func() -> str:
        return "direct"

    pf = promising.function(my_func)
    assert isinstance(pf, promising.PromisingFunction)
    assert await pf() == "direct"


async def test_preserves_original_func() -> None:
    """
    decorated.__wrapped__ is the original function passed
    to the decorator.
    """

    def original() -> str:
        return "preserved"

    decorated = promising.function(original)
    assert decorated.__wrapped__ is original


# ── Config Parameters ────────────────────────────────────────────


async def test_config_params_work_with_sync_functions() -> None:
    """
    start_soon, children_start_soon_by_default, and
    everything_starts_soon_by_default config params
    work with sync functions.
    """

    @promising.function(
        start_soon=False,
        children_start_soon_by_default=False,
        everything_starts_soon_by_default=False,
    )
    def noop() -> None:
        pass

    promise = noop()
    assert promise._start_soon is False
    assert promise._children_start_soon_by_default is False
    assert promise._everything_starts_soon_by_default is False
    await promise


async def test_call_time_config_overrides_work_with_sync_functions() -> None:
    """
    Config params passed at call time override the
    PromisingFunction-level defaults for sync functions.
    """

    @promising.function(
        start_soon=False,
        children_start_soon_by_default=False,
        everything_starts_soon_by_default=False,
    )
    def noop() -> None:
        pass

    promise = noop(
        start_soon=True,
        children_start_soon_by_default=True,
        everything_starts_soon_by_default=True,
    )
    assert promise._start_soon is True
    assert promise._children_start_soon_by_default is True
    assert promise._everything_starts_soon_by_default is True
    await promise


async def test_config_kwargs_do_not_leak_into_sync_function() -> None:
    """
    start_soon etc. passed at call time are consumed by
    call() and not forwarded to the wrapped sync function.
    """

    @promising.function
    def add(a: int, b: int) -> int:
        return a + b

    result = await add(
        3,
        4,
        start_soon=True,
        children_start_soon_by_default=True,
        everything_starts_soon_by_default=True,
    )
    assert result == 7
