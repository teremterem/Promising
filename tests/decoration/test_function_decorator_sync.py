import threading

import pytest

import promising


async def test_calling_promising_function_returns_promise() -> None:
    """
    Calling a decorated sync function returns a Promise;
    awaiting it returns the expected value.
    """

    @promising.function(use_thread_pool=True)
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

    @promising.function(use_thread_pool=True)
    def add(a: int, b: int) -> int:
        return a + b

    assert await add(1, 2) == 3


async def test_forwards_keyword_args() -> None:
    """
    Keyword-only params are correctly forwarded to the
    wrapped sync function.
    """

    @promising.function(use_thread_pool=True)
    def greet(*, greeting: str, name: str) -> str:
        return f"{greeting}, {name}"

    assert await greet(greeting="hi", name="world") == "hi, world"


async def test_forwards_mixed_args() -> None:
    """
    A mix of positional and keyword args is forwarded
    correctly.
    """

    @promising.function(use_thread_pool=True)
    def mixed(a: int, b: int, *, suffix: str = "!") -> str:
        return f"{a + b}{suffix}"

    assert await mixed(3, 4, suffix="?") == "7?"


async def test_executes_once() -> None:
    """
    A nonlocal counter confirms the sync function runs
    exactly once per call; second call increments to 2.
    """
    call_count = 0

    @promising.function(use_thread_pool=True)
    def double(value: int) -> int:
        nonlocal call_count
        call_count += 1
        return value * 2

    promise_one = double(2)
    assert await promise_one == 4
    assert await promise_one == 4
    assert call_count == 1

    promise_two = double(3)
    assert await promise_two == 6
    assert await promise_two == 6
    assert await promise_two == 6
    assert call_count == 2

    assert promise_one is not promise_two


async def test_default_args() -> None:
    """
    Calling with no args uses defaults; calling with
    explicit args overrides them.
    """

    @promising.function(use_thread_pool=True)
    def with_defaults(x: int = 10, y: int = 20) -> int:
        return x + y

    assert await with_defaults() == 30
    assert await with_defaults(1, 2) == 3


async def test_star_args_and_kwargs() -> None:
    """
    *args and **kwargs are forwarded to the wrapped
    sync function correctly.
    """

    @promising.function(use_thread_pool=True)
    def variadic(*args: int, **kwargs: str) -> tuple:
        return (args, kwargs)

    result = await variadic(1, 2, 3, key="value")
    assert result == ((1, 2, 3), {"key": "value"})


async def test_exception_propagates_through_promise() -> None:
    """
    An exception raised inside the sync function
    propagates through the Promise when awaited.
    """
    call_count = 0

    @promising.function(use_thread_pool=True)
    def failing() -> None:
        nonlocal call_count
        call_count += 1
        raise ValueError("test error")

    failing_promise = failing()
    with pytest.raises(ValueError, match="test error"):
        await failing_promise
    with pytest.raises(ValueError, match="test error"):
        await failing_promise
    with pytest.raises(ValueError, match="test error"):
        await failing_promise

    assert type(failing_promise.exception()) is ValueError
    assert str(failing_promise.exception()) == "test error"
    assert call_count == 1


@pytest.mark.parametrize(
    "exception_type",
    [ValueError, TypeError, RuntimeError, KeyError],
)
async def test_various_exception_types(*, exception_type: type) -> None:
    """
    Parametrized: each exception type propagates
    through the Promise correctly.
    """

    @promising.function(use_thread_pool=True)
    def failing() -> None:
        raise exception_type("specific error")

    with pytest.raises(exception_type):
        await failing()


async def test_used_as_direct_call() -> None:
    """
    promising.function(my_func) used as a direct call
    (non-decorator) works for sync functions.
    """

    def my_func() -> str:
        return "direct"

    pf = promising.function(my_func, start_soon=False, use_thread_pool=True)
    assert isinstance(pf, promising.PromisingFunction)

    promise = pf()
    assert isinstance(promise, promising.Promise)
    assert await promise == "direct"


async def test_preserves_original_func() -> None:
    """
    decorated.__wrapped__ is the original function passed
    to the decorator.
    """

    def original() -> str:
        return "preserved"

    decorated = promising.function(original, use_thread_pool=True)
    assert decorated.__wrapped__ is original

    decorated = promising.function(use_thread_pool=True)(original)
    assert decorated.__wrapped__ is original


async def test_sync_function_runs_in_different_thread() -> None:
    """
    The sync function actually runs in a different thread
    than the event loop thread.
    """
    main_thread = threading.current_thread()

    @promising.function(use_thread_pool=True)
    def get_thread() -> threading.Thread:
        return threading.current_thread()

    worker_thread = await get_thread()
    assert worker_thread is not main_thread
