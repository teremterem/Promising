import promising


async def test_calling_promising_function_returns_promise() -> None:
    """
    Calling a decorated function returns a Promise;
    awaiting it returns the expected value.
    """

    @promising.function
    async def greet() -> str:
        return "hello"

    assert isinstance(greet, promising.PromisingFunction)
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


async def test_executes_once() -> None:
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

    assert promise_one is not promise_two


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
