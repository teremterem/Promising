import pytest

import promising


async def test_context_decorator_activates_context() -> None:
    """
    @promising.context on a function: the context is active inside the function
    body.
    """
    captured_ctx = None

    @promising.context
    def work() -> str:
        nonlocal captured_ctx
        captured_ctx = promising.get_active_context()
        return "done"

    assert work() == "done"
    assert captured_ctx is not None
    assert isinstance(captured_ctx, promising.PromisingContext)


async def test_context_decorator_deactivates_after() -> None:
    """
    After the decorated function returns, the context is no longer active.
    """

    @promising.context
    def work() -> str:
        return "done"

    assert promising.get_active_context(raise_if_none=False) is None
    work()
    assert promising.get_active_context(raise_if_none=False) is None


async def test_context_decorator_forwards_args() -> None:
    """
    Positional and keyword arguments are forwarded to the decorated function.
    """

    @promising.context
    def add(a: int, b: int, *, multiplier: int = 1) -> int:
        return (a + b) * multiplier

    assert add(3, 4) == 7
    assert add(3, 4, multiplier=2) == 14


async def test_context_decorator_exception_propagates() -> None:
    """
    An exception raised inside the decorated function propagates to the caller.
    """

    @promising.context
    def failing() -> None:
        raise ValueError("func error")

    with pytest.raises(ValueError, match="func error"):
        failing()


async def test_context_decorator_deactivates_on_exception() -> None:
    """
    The context is deactivated even if the decorated function raises.
    """

    @promising.context
    def failing() -> None:
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        failing()

    assert promising.get_active_context(raise_if_none=False) is None


async def test_context_decorator_with_parens() -> None:
    captured_ctx = None

    @promising.context()
    def work() -> str:
        nonlocal captured_ctx
        captured_ctx = promising.get_active_context()
        return "parens"

    assert promising.get_active_context(raise_if_none=False) is None
    assert work() == "parens"
    assert isinstance(captured_ctx, promising.PromisingContext)
    assert promising.get_active_context(raise_if_none=False) is None


async def test_context_decorator_each_call_gets_fresh_context() -> None:
    """
    Each call to the decorated function gets a fresh
    PromisingContext (not the same instance).
    """
    contexts: list[promising.PromisingContext] = []

    @promising.context
    def capture() -> None:
        contexts.append(promising.get_active_context())

    capture()
    capture()
    assert len(contexts) == 2
    assert contexts[0] is not contexts[1]


@pytest.mark.parametrize("parent", [None, promising.INHERIT])
async def test_context_decorator_with_explicit_parent(parent) -> None:
    """
    `@promising.context`(parent=...) with explicit parent parameter:
    - parent=None creates a root context (no parent) even when called inside
      another context.
    - parent=INHERIT (default) captures the outer context as parent.
    """

    @promising.context(parent=parent)
    def work() -> promising.PromisingContext | None:
        ctx = promising.get_active_context()
        return ctx.get_parent_context(raise_if_none=False)

    with promising.context() as parent_ctx:
        returned_parent_ctx = work()
        if parent is None:
            assert returned_parent_ctx is None
        else:
            assert returned_parent_ctx is parent_ctx
