import pytest

import promising
from tests.utils_for_tests import run_in_thread


async def test_context_manager_activates_context() -> None:
    """
    `with promising.context():` activates a PromisingContext that
    is visible via `promising.get_active_context()`.
    """
    assert promising.get_active_context(raise_if_none=False) is None

    with promising.context() as ctx:
        assert promising.get_active_context() is ctx
        assert isinstance(ctx, promising.PromisingContext)

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
            with ctx:
                pass


async def test_context_manager_reuse_after_exit_raises() -> None:
    """
    Re-entering a PromisingContext that has already been used and exited
    raises ContextAlreadyClosedError.

    This is tested on PromisingContext directly rather than on
    promising.context(), because promising.context() creates a fresh
    PromisingContext on each entry — the concrete object doesn't exist
    until the context is entered, so re-entry is not a concern there.
    The guard exists on PromisingContext to simplify hierarchy tracking:
    a context that has already participated in a parent-child tree
    should not be re-activated.
    """
    ctx = promising.PromisingContext(parent=None)
    with ctx:
        pass

    with pytest.raises(promising.ContextAlreadyClosedError):
        with ctx:
            pass


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


@pytest.mark.parametrize("use_thread_pool", [True, False, None])
def test_context_manager_inside_promising_function_run(*, use_thread_pool: bool | None) -> None:
    """
    `with promising.context()` works inside a @promising.function
    executed via .run(). The context is activated and deactivated correctly.

    Runs in a separate thread to avoid interfering with the pytest-asyncio
    event loop.
    """

    def _test() -> None:
        captured_ctx = None
        before_ctx = None
        after_ctx = None

        def actual_work() -> str:
            nonlocal captured_ctx, before_ctx, after_ctx
            before_ctx = promising.get_active_context()

            with promising.context() as ctx:
                captured_ctx = ctx
                assert promising.get_active_context() is ctx
                assert isinstance(ctx, promising.PromisingContext)

            after_ctx = promising.get_active_context()
            return "done"

        if use_thread_pool is not None:

            @promising.function(use_thread_pool=use_thread_pool)
            def work() -> str:
                return actual_work()

        else:

            @promising.function
            async def work() -> str:
                return actual_work()

        assert work.run() == "done"

        assert isinstance(captured_ctx, promising.PromisingContext)
        assert not isinstance(captured_ctx, promising.Promise)
        assert isinstance(before_ctx, promising.Promise)

        assert captured_ctx is not before_ctx
        assert captured_ctx.get_parent_context() is before_ctx
        assert before_ctx is after_ctx

    run_in_thread(_test, timeout=2)
