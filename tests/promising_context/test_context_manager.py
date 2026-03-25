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


# ── Context manager inside a sync promising function (.run()) ────


@pytest.mark.parametrize("use_thread_pool", [True, False])
def test_context_manager_inside_sync_promising_function_run(use_thread_pool: bool) -> None:
    """
    `with promising.context()` works inside a sync @promising.function
    executed via .run(). The context is activated and deactivated correctly.

    Runs in a separate thread to avoid interfering with the pytest-asyncio
    event loop.
    """

    def _test() -> None:
        captured_ctx = None
        before_ctx = None
        after_ctx = None

        @promising.function(use_thread_pool=use_thread_pool)
        def work() -> str:
            nonlocal captured_ctx, before_ctx, after_ctx
            before_ctx = promising.get_active_context()

            with promising.context() as ctx:
                captured_ctx = ctx
                assert promising.get_active_context() is ctx
                assert isinstance(ctx, promising.PromisingContext)

            after_ctx = promising.get_active_context(raise_if_none=False)
            return "done"

        assert work.run() == "done"
        assert captured_ctx is not None
        # After the `with` block the active context should revert to the
        # promise itself, not None — because we're still inside the
        # promising function body.
        assert before_ctx is after_ctx

    run_in_thread(_test)


@pytest.mark.parametrize("use_thread_pool", [True, False])
def test_nested_context_managers_inside_sync_promising_function_run(use_thread_pool: bool) -> None:
    """
    Nested `with promising.context()` blocks inside a sync @promising.function
    executed via .run(). Each block sees its own context, and the outer one is
    restored after the inner block exits.

    Runs in a separate thread to avoid interfering with the pytest-asyncio
    event loop.
    """

    def _test() -> None:
        results: dict = {}

        @promising.function(use_thread_pool=use_thread_pool)
        def work() -> str:
            with promising.context() as outer:
                results["outer_active"] = promising.get_active_context() is outer

                with promising.context() as inner:
                    results["inner_active"] = promising.get_active_context() is inner
                    results["inner_is_not_outer"] = inner is not outer
                    results["inner_parent_is_outer"] = inner.get_parent_context() is outer

                results["outer_restored"] = promising.get_active_context() is outer

            return "done"

        assert work.run() == "done"
        assert results["outer_active"]
        assert results["inner_active"]
        assert results["inner_is_not_outer"]
        assert results["inner_parent_is_outer"]
        assert results["outer_restored"]

    run_in_thread(_test)


@pytest.mark.parametrize("use_thread_pool", [True, False])
def test_context_manager_parent_is_promise_inside_sync_promising_function_run(use_thread_pool: bool) -> None:
    """
    A `with promising.context()` opened inside a sync @promising.function
    should have the enclosing promise as its parent (via INHERIT).

    Runs in a separate thread to avoid interfering with the pytest-asyncio
    event loop.
    """

    def _test() -> None:
        ctx_parent = None

        @promising.function(use_thread_pool=use_thread_pool)
        def work() -> str:
            nonlocal ctx_parent
            promise_ctx = promising.get_active_context()

            with promising.context() as ctx:
                ctx_parent = ctx.get_parent_context(raise_if_none=False)

            assert ctx_parent is promise_ctx
            return "done"

        assert work.run() == "done"
        assert ctx_parent is not None

    run_in_thread(_test)


@pytest.mark.parametrize("use_thread_pool", [True, False])
def test_context_manager_deactivates_on_exception_inside_sync_promising_function_run(use_thread_pool: bool) -> None:
    """
    The context opened with `with promising.context()` is properly deactivated
    even when an exception is raised, inside a sync @promising.function
    executed via .run().

    Runs in a separate thread to avoid interfering with the pytest-asyncio
    event loop.
    """

    def _test() -> None:
        promise_ctx_after = None

        @promising.function(use_thread_pool=use_thread_pool)
        def work() -> str:
            nonlocal promise_ctx_after
            promise_ctx = promising.get_active_context()

            with pytest.raises(ValueError, match="boom"):
                with promising.context():
                    raise ValueError("boom")

            # After the exception the active context should revert to the
            # promise, not be stuck on the errored context.
            promise_ctx_after = promising.get_active_context(raise_if_none=False)
            assert promise_ctx_after is promise_ctx
            return "done"

        assert work.run() == "done"
        assert promise_ctx_after is not None

    run_in_thread(_test)
