import pytest

import promising

# ── Context Manager: Basic Usage ─────────────────────────────────


async def test_context_manager_activates_context() -> None:
    """
    `with promising.context():` activates a PromisingContext that
    is visible via `promising.get_active_context()`.
    """
    assert promising.get_active_context(raise_if_none=False) is None

    with promising.context() as ctx:
        assert promising.get_active_context() is ctx

    assert promising.get_active_context(raise_if_none=False) is None


async def test_context_manager_returns_promising_context() -> None:
    """
    The value yielded by `with promising.context() as ctx` is a
    PromisingContext instance.
    """
    with promising.context() as ctx:
        assert isinstance(ctx, promising.PromisingContext)


async def test_context_manager_deactivates_on_exit() -> None:
    """
    After exiting the `with` block the PromisingContext is no
    longer the active context.
    """
    with promising.context():
        pass

    assert promising.get_active_context(raise_if_none=False) is None


async def test_context_manager_deactivates_on_exception() -> None:
    """
    The context is properly deactivated even when an exception
    is raised inside the `with` block.
    """
    with pytest.raises(ValueError, match="boom"):
        with promising.context():
            raise ValueError("boom")

    assert promising.get_active_context(raise_if_none=False) is None


async def test_nested_context_managers() -> None:
    """
    Nested `with promising.context():` blocks each see their own
    PromisingContext as active, and the outer one is restored
    after the inner block exits.
    """
    with promising.context() as outer:
        assert promising.get_active_context() is outer

        with promising.context() as inner:
            assert promising.get_active_context() is inner
            assert inner is not outer

        assert promising.get_active_context() is outer

    assert promising.get_active_context(raise_if_none=False) is None


async def test_nested_context_parent_relationship() -> None:
    """
    When nesting contexts, the inner context's parent is the
    outer context (because parent defaults to INHERIT).
    """
    with promising.context() as outer:
        with promising.context() as inner:
            assert inner.get_parent_context() is outer


async def test_context_manager_reuse_raises() -> None:
    """
    Entering the same PromisingContext twice without exiting raises
    ContextAlreadyActiveError.
    """
    ctx = promising.context()
    with ctx:
        with pytest.raises(promising.ContextAlreadyActiveError):
            ctx.__enter__()


async def test_context_manager_with_explicit_parent_none() -> None:
    """
    `promising.context(parent=None)` creates a root context with no
    parent, even when called inside another context.
    """
    with promising.context() as outer:
        with promising.context(parent=None) as inner:
            assert inner.get_parent_context(raise_if_none=False) is None
            assert promising.get_active_context() is inner

        assert promising.get_active_context() is outer
