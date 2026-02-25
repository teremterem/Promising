import threading

import pytest

import promising
from promising import get_active_promise

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


# ── Context Propagation ─────────────────────────────────────────


async def test_active_promise_accessible_inside_sync_function() -> None:
    """
    get_active_promise() inside a sync promising function
    (running in a thread pool) returns the wrapping Promise.
    """

    @promising.function
    def sync_func() -> promising.Promise:
        return get_active_promise(raise_if_none=False)

    promise = sync_func()
    current_from_inside = await promise
    assert current_from_inside is promise


async def test_sync_parent_child_relationship() -> None:
    """
    A child Promise created inside a sync promising
    function has the sync function's Promise as its parent.
    """
    child_promise = None

    @promising.function
    async def child_func() -> str:
        return "child"

    @promising.function
    def sync_parent() -> None:
        nonlocal child_promise
        child_promise = child_func(start_soon=False)

    parent_promise = sync_parent()
    await parent_promise

    assert child_promise is not None
    assert child_promise.get_parent(raise_if_none=False) is parent_promise
    await child_promise
