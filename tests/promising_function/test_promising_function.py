import asyncio
import threading

import pytest

import promising

# ── Core: Async Function Wrapping & Argument Forwarding ──────────


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


# ── Error Cases ──────────────────────────────────────────────────


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


# ── function() Decorator Modes ───────────────────────────────────


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
    decorated.__wrapped__ is the original function passed
    to the decorator.
    """

    async def original() -> str:
        return "preserved"

    decorated = promising.function(original)
    assert decorated.__wrapped__ is original


# ── Edge Cases & Integration ─────────────────────────────────────


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


async def test_promise_has_parent_when_created_in_context() -> None:
    """
    A child Promise created inside a parent Promise's
    execution has get_parent_context() and get_parent_promise() pointing to
    the parent.
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
    assert child_promise.get_parent_context(raise_if_none=False) is parent_promise
    assert child_promise.get_parent_promise(raise_if_none=False) is parent_promise


async def test_promise_has_no_parent_outside_context() -> None:
    """
    A Promise created at top level (outside any parent
    context) has no parent.
    """

    @promising.function
    async def noop() -> None:
        pass

    promise = noop()
    assert promise.get_parent_context(raise_if_none=False) is None
    assert promise.get_parent_promise(raise_if_none=False) is None
    await promise


# ── asyncio.run() Compatibility ─────────────────────────────────


def test_async_function_decorator_with_asyncio_run() -> None:
    """
    @promising.function on an async function used with asyncio.run().

    asyncio.run() evaluates f() — and therefore the decorator's
    __call__ — *before* asyncio.run creates and starts its own event
    loop.  The PromisingFunction must resolve the event loop lazily
    (when the coroutine body runs) rather than eagerly (when the
    Promise object is constructed), otherwise it captures a stale
    loop and fails.

    Runs in a separate thread to avoid interfering with the
    pytest-asyncio event loop.
    """
    error = None

    def _run_in_thread() -> None:
        nonlocal error
        try:

            @promising.function
            async def work() -> str:
                return "done"

            result = asyncio.run(work())
            assert result == "done"
        except BaseException as exc:
            error = exc

    t = threading.Thread(target=_run_in_thread)
    t.start()
    t.join()
    if error is not None:
        raise error


def test_async_function_decorator_with_asyncio_run_and_child_promise() -> None:
    """
    Same as above but also creates a child Promise inside the function,
    which exercises _call_soon_threadsafe and verifies the event loop
    is correctly resolved at runtime.

    Runs in a separate thread to avoid interfering with the
    pytest-asyncio event loop.
    """
    error = None

    def _run_in_thread() -> None:
        nonlocal error
        try:

            @promising.function
            async def child_work(x: int) -> int:
                return x * 2

            @promising.function
            async def parent_work() -> int:
                result = await child_work(21)
                return result

            assert asyncio.run(parent_work()) == 42
        except BaseException as exc:
            error = exc

    t = threading.Thread(target=_run_in_thread)
    t.start()
    t.join()
    if error is not None:
        raise error
