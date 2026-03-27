import pytest

import promising

# ── Core: Async Function Wrapping & Argument Forwarding ──────────


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
