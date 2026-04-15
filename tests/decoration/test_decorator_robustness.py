"""
Tests for decorator stacking edge cases: call-time error semantics and
attribute independence under unusual decorator combinations.

Many of the scenarios here (double-decoration, unconventional stacking order,
etc.) are **not realistic usage patterns** — they exist solely to stress-test
the robustness of the framework under extreme edge cases.

**Part 1 — Call-time errors**

Errors from incorrect call-time arguments (missing args, wrong types, invalid
``use_thread_pool`` on async functions) must be raised immediately at call-time
rather than being deferred to await-time.

*Why this matters:* an error surfaced at the call site points the developer
straight to the offending line.  If the same error is deferred to await-time,
the traceback originates from wherever the coroutine happens to be awaited —
potentially far from the actual mistake — making debugging significantly harder,
even despite the availability of the ``exc.__promising_context__.print_trace()``
feature.

Covers three categories:

1. **Baselines** — plain functions, ``@promising.context``-only, and
   ``@promising.function``-only decorations (both sync and async) to confirm
   standard Python call-time TypeError behavior is preserved.
2. **Unusual decorator stacking** — unconventional combinations like
   ``@promising.context`` on top of ``@promising.function``, double
   ``@promising.function``, ``@promising.function`` on top of
   ``@promising.context``, and double ``@promising.context``.
3. **Sync counterparts** — the same stacking scenarios applied to sync functions.
   Unlike async functions, a decorated sync function has no separation between
   coroutine creation and awaiting — everything runs in the thread pool at once,
   so some errors that surface at call-time for async functions only surface at
   await-time for sync functions.

**Part 2 — Attribute independence under double-decoration**

Stacking two identical decorators (``@promising.function`` on top of
``@promising.function``, or ``@promising.context`` on top of
``@promising.context``) must preserve each layer's attributes independently,
while still propagating standard ``functools.update_wrapper`` attributes
(``__name__``, ``__qualname__``, ``__doc__``, ``__module__``, etc.) from the
original function through both layers.
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import get_type_hints

import pytest

import promising
from promising import INHERIT

# ── Baselines (no decorator stacking) ────────────────────────────


async def test_plain_async_raises_arg_error_at_call_time() -> None:
    """
    Baseline 1 for test_context_on_top_of_function_raises_arg_error_at_call_time:
    a plain async function with required arguments raises TypeError immediately
    at call-time when called with wrong arguments. This is standard Python
    behavior — no decorators involved. This test exists purely for
    demonstration purposes.
    """

    async def add(a: int, b: int) -> int:
        return a + b

    assert await add(1, 2) == 3

    with pytest.raises(TypeError, match="required positional argument"):
        add()  # no await — the error happens at call-time


@pytest.mark.parametrize("with_parens", [False, True], ids=["no-parens", "with-parens"])
async def test_context_alone_raises_arg_error_at_call_time(*, with_parens: bool) -> None:
    """
    Baseline 2 for test_context_on_top_of_function_raises_arg_error_at_call_time:
    @promising.context alone on an async function that requires arguments
    should raise TypeError immediately at call-time when called with
    wrong arguments (not defer it to await-time).
    """
    context_decorator = promising.context() if with_parens else promising.context

    @context_decorator
    async def add(a: int, b: int) -> int:
        return a + b

    assert await add(1, 2) == 3

    with pytest.raises(TypeError, match="required positional argument"):
        add()  # no await — the error should happen at call-time


@pytest.mark.parametrize("with_parens", [False, True], ids=["no-parens", "with-parens"])
async def test_context_alone_on_sync_function_raises_arg_error_at_call_time(*, with_parens: bool) -> None:
    """
    Baseline for test_context_on_top_of_sync_function_raises_arg_error_at_await_time:
    @promising.context alone on a sync function that requires arguments should
    raise TypeError immediately at call-time when called with wrong arguments.

    Unlike test_context_on_top_of_sync_function_raises_arg_error_at_await_time,
    there is no @promising.function here, so the function remains truly
    synchronous — no deferral concern.
    """
    context_decorator = promising.context() if with_parens else promising.context

    @context_decorator
    def add(a: int, b: int) -> int:
        return a + b

    # Unlike `@promising.function`, `@promising.context` does not convert
    # functions (either sync or async) into Promising Functions, it only wraps
    # the code in a PromisingContext manager, which in this case means the
    # function remains synchronous
    assert add(1, 2) == 3

    with pytest.raises(TypeError, match="required positional argument"):
        add()


@pytest.mark.parametrize("use_thread_pool", [True, False])
@pytest.mark.parametrize("with_parens", [False, True], ids=["no-parens", "with-parens"])
async def test_function_alone_raises_use_thread_pool_error_at_call_time(
    *,
    with_parens: bool,
    use_thread_pool: bool,
) -> None:
    """
    Baseline: @promising.function alone on an async function should raise
    DecorationError immediately at call-time when use_thread_pool is passed.
    """
    function_decorator = promising.function() if with_parens else promising.function

    @function_decorator
    async def add(a: int, b: int) -> int:
        return a + b

    ground_truth = add(1, 2)
    assert isinstance(ground_truth, promising.Promise)
    assert await ground_truth == 3

    with pytest.raises(promising.DecorationError, match="cannot be set for async function"):
        # no await — `promising.DecorationError` should happen at call-time
        add(1, 2, use_thread_pool=use_thread_pool)


@pytest.mark.parametrize("with_parens", [False, True], ids=["no-parens", "with-parens"])
async def test_function_alone_raises_arg_error_at_call_time(*, with_parens: bool) -> None:
    """
    Baseline: @promising.function alone on an async function should raise
    TypeError immediately at call-time when called with wrong arguments.
    """
    function_decorator = promising.function() if with_parens else promising.function

    @function_decorator
    async def add(a: int, b: int) -> int:
        return a + b

    ground_truth = add(1, 2)
    assert isinstance(ground_truth, promising.Promise)
    assert await ground_truth == 3

    with pytest.raises(TypeError, match="required positional argument"):
        add()  # no await — the error should happen at call-time


@pytest.mark.parametrize("decorator_use_thread_pool", [True, False])
async def test_function_alone_on_sync_raises_use_thread_pool_error_at_call_time(
    *,
    decorator_use_thread_pool: bool,
) -> None:
    """
    Baseline: @promising.function on a sync function — passing
    use_thread_pool=None at call-time should raise DecorationError immediately
    because it attempts to unset the required thread-pool setting.
    """

    @promising.function(use_thread_pool=decorator_use_thread_pool)
    def add(a: int, b: int) -> int:
        return a + b

    ground_truth = add(1, 2)
    assert isinstance(ground_truth, promising.Promise)
    assert await ground_truth == 3

    with pytest.raises(promising.DecorationError, match="requires an explicit `use_thread_pool` setting"):
        # no await — `promising.DecorationError` should happen at call-time
        add(1, 2, use_thread_pool=None)


@pytest.mark.parametrize("decorator_use_thread_pool", [True, False])
async def test_function_alone_on_sync_raises_arg_error_at_await_time(*, decorator_use_thread_pool: bool) -> None:
    """
    Baseline: @promising.function on a sync function. Unlike async functions,
    a decorated sync function has no separation between coroutine creation and
    awaiting — everything runs in the thread pool at once, so argument errors
    surface only at await-time.
    """

    @promising.function(use_thread_pool=decorator_use_thread_pool)
    def add(a: int, b: int) -> int:
        return a + b

    ground_truth = add(1, 2)
    assert isinstance(ground_truth, promising.Promise)
    assert await ground_truth == 3

    add_promise = add()
    with pytest.raises(TypeError, match="required positional argument"):
        # Argument errors of the underlying sync function only surface at
        # await-time
        await add_promise


# ── Unusual Decorator Stacking ──────────────────────────────────


@pytest.mark.parametrize("use_thread_pool", [True, False])
@pytest.mark.parametrize("context_with_parens", [False, True], ids=["ctx-no-parens", "ctx-with-parens"])
@pytest.mark.parametrize("function_with_parens", [False, True], ids=["func-no-parens", "func-with-parens"])
async def test_context_on_top_of_function_raises_use_thread_pool_error_at_call_time(
    *,
    function_with_parens: bool,
    context_with_parens: bool,
    use_thread_pool: bool,
) -> None:
    """
    When @promising.context is stacked on top of @promising.function —
    an unusual combination that is not a realistic usage pattern —
    passing use_thread_pool at call time on an async function should
    raise DecorationError immediately at call-time, not defer it to
    await-time.
    """
    context_decorator = promising.context() if context_with_parens else promising.context
    function_decorator = promising.function() if function_with_parens else promising.function

    @context_decorator
    @function_decorator
    async def add(a: int, b: int) -> int:
        return a + b

    ground_truth = add(1, 2)
    # `@promising.context` decorator obscures the underlying Promise away from
    # us in this stacking scenario
    assert not isinstance(ground_truth, promising.Promise)
    assert asyncio.iscoroutine(ground_truth)
    assert await ground_truth == 3

    with pytest.raises(promising.DecorationError, match="cannot be set for async function"):
        # no await — `promising.DecorationError` should happen at call-time
        add(1, 2, use_thread_pool=use_thread_pool)


@pytest.mark.parametrize("context_with_parens", [False, True], ids=["ctx-no-parens", "ctx-with-parens"])
@pytest.mark.parametrize("function_with_parens", [False, True], ids=["func-no-parens", "func-with-parens"])
async def test_context_on_top_of_function_raises_arg_error_at_call_time(
    *,
    function_with_parens: bool,
    context_with_parens: bool,
) -> None:
    """
    When @promising.context is stacked on top of @promising.function —
    an unusual combination that is not a realistic usage pattern —
    calling the decorated function with wrong arguments should raise
    TypeError immediately at call-time, not defer it to await-time.
    """
    context_decorator = promising.context() if context_with_parens else promising.context
    function_decorator = promising.function() if function_with_parens else promising.function

    @context_decorator
    @function_decorator
    async def add(a: int, b: int) -> int:
        return a + b

    ground_truth = add(1, 2)
    # `@promising.context` decorator obscures the underlying Promise away from
    # us in this stacking scenario
    assert not isinstance(ground_truth, promising.Promise)
    assert asyncio.iscoroutine(ground_truth)
    assert await ground_truth == 3

    with pytest.raises(TypeError, match="required positional argument"):
        add()  # no await — the error should happen at call-time


@pytest.mark.parametrize("use_thread_pool", [True, False])
@pytest.mark.parametrize("outer_with_parens", [False, True], ids=["outer-no-parens", "outer-with-parens"])
@pytest.mark.parametrize("inner_with_parens", [False, True], ids=["inner-no-parens", "inner-with-parens"])
async def test_function_on_top_of_function_raises_use_thread_pool_error_at_call_time(
    *,
    inner_with_parens: bool,
    outer_with_parens: bool,
    use_thread_pool: bool,
) -> None:
    """
    When @promising.function is stacked directly on top of another
    @promising.function — an unusual combination that is not a realistic
    usage pattern — passing use_thread_pool at call time on an async
    function should still raise DecorationError immediately at call-time.
    """
    outer_decorator = promising.function() if outer_with_parens else promising.function
    inner_decorator = promising.function() if inner_with_parens else promising.function

    @outer_decorator
    @inner_decorator
    async def add(a: int, b: int) -> int:
        return a + b

    ground_truth = add(1, 2)
    assert isinstance(ground_truth, promising.Promise)
    assert await ground_truth == 3

    with pytest.raises(promising.DecorationError, match="cannot be set for async function"):
        # no await — `promising.DecorationError` should happen at call-time
        add(1, 2, use_thread_pool=use_thread_pool)


@pytest.mark.parametrize("outer_with_parens", [False, True], ids=["outer-no-parens", "outer-with-parens"])
@pytest.mark.parametrize("inner_with_parens", [False, True], ids=["inner-no-parens", "inner-with-parens"])
async def test_function_on_top_of_function_raises_arg_error_at_call_time(
    *,
    inner_with_parens: bool,
    outer_with_parens: bool,
) -> None:
    """
    When @promising.function is stacked directly on top of another
    @promising.function — an unusual combination that is not a realistic
    usage pattern — calling with wrong arguments should still raise
    TypeError immediately at call-time.
    """
    outer_decorator = promising.function() if outer_with_parens else promising.function
    inner_decorator = promising.function() if inner_with_parens else promising.function

    @outer_decorator
    @inner_decorator
    async def add(a: int, b: int) -> int:
        return a + b

    ground_truth = add(1, 2)
    assert isinstance(ground_truth, promising.Promise)
    assert await ground_truth == 3

    with pytest.raises(TypeError, match="required positional argument"):
        add()  # no await — the error should happen at call-time


@pytest.mark.parametrize("use_thread_pool", [True, False])
@pytest.mark.parametrize("func_with_parens", [False, True], ids=["func-no-parens", "func-with-parens"])
@pytest.mark.parametrize("ctx_with_parens", [False, True], ids=["ctx-no-parens", "ctx-with-parens"])
async def test_function_on_top_of_context_raises_use_thread_pool_error_at_call_time(
    *,
    ctx_with_parens: bool,
    func_with_parens: bool,
    use_thread_pool: bool,
) -> None:
    """
    When @promising.function is stacked on top of @promising.context —
    an unusual combination that is not a realistic usage pattern —
    passing use_thread_pool at call time on an async function should
    still raise DecorationError immediately at call-time.
    """
    func_decorator = promising.function() if func_with_parens else promising.function
    ctx_decorator = promising.context() if ctx_with_parens else promising.context

    @func_decorator
    @ctx_decorator
    async def add(a: int, b: int) -> int:
        return a + b

    ground_truth = add(1, 2)
    assert isinstance(ground_truth, promising.Promise)
    assert await ground_truth == 3

    with pytest.raises(promising.DecorationError, match="cannot be set for async function"):
        # no await — `promising.DecorationError` should happen at call-time
        add(1, 2, use_thread_pool=use_thread_pool)


@pytest.mark.parametrize("func_with_parens", [False, True], ids=["func-no-parens", "func-with-parens"])
@pytest.mark.parametrize("ctx_with_parens", [False, True], ids=["ctx-no-parens", "ctx-with-parens"])
async def test_function_on_top_of_context_raises_arg_error_at_call_time(
    *,
    ctx_with_parens: bool,
    func_with_parens: bool,
) -> None:
    """
    When @promising.function is stacked on top of @promising.context —
    an unusual combination that is not a realistic usage pattern —
    calling with wrong arguments should still raise TypeError immediately
    at call-time.
    """
    func_decorator = promising.function() if func_with_parens else promising.function
    ctx_decorator = promising.context() if ctx_with_parens else promising.context

    @func_decorator
    @ctx_decorator
    async def add(a: int, b: int) -> int:
        return a + b

    ground_truth = add(1, 2)
    assert isinstance(ground_truth, promising.Promise)
    assert await ground_truth == 3

    with pytest.raises(TypeError, match="required positional argument"):
        add()  # no await — the error should happen at call-time


@pytest.mark.parametrize("outer_with_parens", [False, True], ids=["outer-no-parens", "outer-with-parens"])
@pytest.mark.parametrize("inner_with_parens", [False, True], ids=["inner-no-parens", "inner-with-parens"])
async def test_context_on_top_of_context_raises_arg_error_at_call_time(
    *,
    inner_with_parens: bool,
    outer_with_parens: bool,
) -> None:
    """
    When @promising.context is stacked on top of another @promising.context —
    an unusual combination that is not a realistic usage pattern —
    calling with wrong arguments should raise TypeError immediately at call-time.
    """
    outer_decorator = promising.context() if outer_with_parens else promising.context
    inner_decorator = promising.context() if inner_with_parens else promising.context

    @outer_decorator
    @inner_decorator
    async def add(a: int, b: int) -> int:
        return a + b

    assert await add(1, 2) == 3

    with pytest.raises(TypeError, match="required positional argument"):
        add()  # no await — the error should happen at call-time


@pytest.mark.parametrize("outer_with_parens", [False, True], ids=["outer-no-parens", "outer-with-parens"])
@pytest.mark.parametrize("inner_with_parens", [False, True], ids=["inner-no-parens", "inner-with-parens"])
async def test_context_on_top_of_context_on_sync_raises_arg_error_at_call_time(
    *,
    inner_with_parens: bool,
    outer_with_parens: bool,
) -> None:
    """
    When @promising.context is stacked on top of another @promising.context
    on a sync function — an unusual combination that is not a realistic
    usage pattern — calling with wrong arguments should raise TypeError
    immediately at call-time.
    """
    outer_decorator = promising.context() if outer_with_parens else promising.context
    inner_decorator = promising.context() if inner_with_parens else promising.context

    @outer_decorator
    @inner_decorator
    def add(a: int, b: int) -> int:
        return a + b

    assert add(1, 2) == 3

    with pytest.raises(TypeError, match="required positional argument"):
        add()


# ── Sync Counterparts for Argument-Error-at-Call-Time Tests ──────


@pytest.mark.parametrize("decorator_use_thread_pool", [True, False])
@pytest.mark.parametrize("context_with_parens", [False, True], ids=["ctx-no-parens", "ctx-with-parens"])
async def test_context_on_top_of_sync_function_rejects_use_thread_pool_none_at_call_time(
    *,
    context_with_parens: bool,
    decorator_use_thread_pool: bool,
) -> None:
    """
    Sync counterpart of test_context_on_top_of_function_raises_use_thread_pool_error_at_call_time.

    Passing ``use_thread_pool=None`` at call-time tries to unset the required
    thread-pool setting, which is not allowed. Even though the inner
    @promising.function turns the sync function into a thread-pool-executed one,
    ``use_thread_pool`` validation happens before execution begins, so the
    DecorationError is raised immediately at call-time.
    """
    context_decorator = promising.context() if context_with_parens else promising.context

    @context_decorator
    @promising.function(use_thread_pool=decorator_use_thread_pool)
    def add(a: int, b: int) -> int:
        return a + b

    ground_truth = add(1, 2)
    # `@promising.context` decorator obscures the underlying Promise away from
    # us in this stacking scenario
    assert not isinstance(ground_truth, promising.Promise)
    assert asyncio.iscoroutine(ground_truth)
    assert await ground_truth == 3

    with pytest.raises(promising.DecorationError, match="requires an explicit `use_thread_pool` setting"):
        # no await — `promising.DecorationError` should happen at call-time
        add(1, 2, use_thread_pool=None)


@pytest.mark.parametrize("decorator_use_thread_pool", [True, False])
@pytest.mark.parametrize("context_with_parens", [False, True], ids=["ctx-no-parens", "ctx-with-parens"])
async def test_context_on_top_of_sync_function_raises_arg_error_at_await_time(
    *,
    context_with_parens: bool,
    decorator_use_thread_pool: bool,
) -> None:
    """
    Sync counterpart of test_context_on_top_of_function_raises_arg_error_at_call_time.

    The inner @promising.function turns the sync function into a
    thread-pool-executed one, where there is no separation between coroutine
    creation and awaiting — everything runs at once. The outer @promising.context
    does not change this, so argument errors surface only at await-time.
    """
    context_decorator = promising.context() if context_with_parens else promising.context

    @context_decorator
    @promising.function(use_thread_pool=decorator_use_thread_pool)
    def add(a: int, b: int) -> int:
        return a + b

    ground_truth = add(1, 2)
    # `@promising.context` decorator obscures the underlying Promise away from
    # us in this stacking scenario
    assert not isinstance(ground_truth, promising.Promise)
    assert asyncio.iscoroutine(ground_truth)
    assert await ground_truth == 3

    add_promise = add()
    with pytest.raises(TypeError, match="required positional argument"):
        # Argument errors of the underlying sync function only surface at
        # await-time
        await add_promise


@pytest.mark.parametrize("decorator_use_thread_pool", [True, False])
@pytest.mark.parametrize("outer_with_parens", [False, True], ids=["outer-no-parens", "outer-with-parens"])
async def test_function_on_top_of_function_on_sync_accepts_use_thread_pool_none(
    *,
    outer_with_parens: bool,
    decorator_use_thread_pool: bool,
) -> None:
    """
    Sync counterpart of test_function_on_top_of_function_raises_use_thread_pool_error_at_call_time.

    Passing ``use_thread_pool=None`` does NOT raise an error here. The inner
    @promising.function turns the sync function into an async one, so the outer
    @promising.function sees an async function and consumes the
    ``use_thread_pool=None`` override itself — no validation error occurs.
    """
    outer_decorator = promising.function() if outer_with_parens else promising.function

    @outer_decorator
    @promising.function(use_thread_pool=decorator_use_thread_pool)
    def add(a: int, b: int) -> int:
        return a + b

    ground_truth = add(1, 2)
    assert isinstance(ground_truth, promising.Promise)
    assert await ground_truth == 3

    # This will not raise DecorationError at all because `use_thread_pool=None`
    # is consumed at call-time by the outer `@promising.function` decorator. As
    # far as the outer decorator is concerned, the function being wrapped is
    # async - the inner promising function decorator turns the sync function
    # into an async function.
    await add(1, 2, use_thread_pool=None)


@pytest.mark.parametrize("decorator_use_thread_pool", [True, False])
@pytest.mark.parametrize("outer_with_parens", [False, True], ids=["outer-no-parens", "outer-with-parens"])
async def test_function_on_top_of_function_on_sync_raises_arg_error_at_await_time(
    *,
    outer_with_parens: bool,
    decorator_use_thread_pool: bool,
) -> None:
    """
    Sync counterpart of test_function_on_top_of_function_raises_arg_error_at_call_time.

    The inner @promising.function turns the sync function into a
    thread-pool-executed one, where there is no separation between coroutine
    creation and awaiting — everything runs at once. The outer @promising.function
    does not change this, so argument errors surface only at await-time.
    """
    outer_decorator = promising.function() if outer_with_parens else promising.function

    @outer_decorator
    @promising.function(use_thread_pool=decorator_use_thread_pool)
    def add(a: int, b: int) -> int:
        return a + b

    ground_truth = add(1, 2)
    assert isinstance(ground_truth, promising.Promise)
    assert await ground_truth == 3

    add_promise = add()
    with pytest.raises(TypeError, match="required positional argument"):
        # Argument errors of the underlying sync function only surface at
        # await-time
        await add_promise


@pytest.mark.parametrize("decorator_use_thread_pool", [True, False])
@pytest.mark.parametrize("ctx_with_parens", [False, True], ids=["ctx-no-parens", "ctx-with-parens"])
async def test_function_on_top_of_context_on_sync_raises_use_thread_pool_error_at_call_time(
    *,
    ctx_with_parens: bool,
    decorator_use_thread_pool: bool,
) -> None:
    """
    Sync counterpart of test_function_on_top_of_context_raises_use_thread_pool_error_at_call_time.

    Passing ``use_thread_pool=None`` at call-time tries to unset the required
    thread-pool setting, which is not allowed. Here @promising.function is the
    outermost decorator and validates ``use_thread_pool`` before execution begins,
    so the DecorationError is raised immediately at call-time.
    """
    ctx_decorator = promising.context() if ctx_with_parens else promising.context

    @promising.function(use_thread_pool=decorator_use_thread_pool)
    @ctx_decorator
    def add(a: int, b: int) -> int:
        return a + b

    ground_truth = add(1, 2)
    assert isinstance(ground_truth, promising.Promise)
    assert await ground_truth == 3

    with pytest.raises(promising.DecorationError, match="requires an explicit `use_thread_pool` setting"):
        # no await — DecorationError happens at call-time
        add(1, 2, use_thread_pool=None)


@pytest.mark.parametrize("decorator_use_thread_pool", [True, False])
@pytest.mark.parametrize("ctx_with_parens", [False, True], ids=["ctx-no-parens", "ctx-with-parens"])
async def test_function_on_top_of_context_on_sync_raises_arg_error_at_await_time(
    *,
    ctx_with_parens: bool,
    decorator_use_thread_pool: bool,
) -> None:
    """
    Sync counterpart of test_function_on_top_of_context_raises_arg_error_at_call_time.

    @promising.function turns the sync function into a thread-pool-executed one,
    where there is no separation between coroutine creation and awaiting —
    everything runs at once. The inner @promising.context does not change this,
    so argument errors surface only at await-time.
    """
    ctx_decorator = promising.context() if ctx_with_parens else promising.context

    @promising.function(use_thread_pool=decorator_use_thread_pool)
    @ctx_decorator
    def add(a: int, b: int) -> int:
        return a + b

    ground_truth = add(1, 2)
    assert isinstance(ground_truth, promising.Promise)
    assert await ground_truth == 3

    add_promise = add()
    with pytest.raises(TypeError, match="required positional argument"):
        # Argument errors of the underlying sync function only surface at
        # await-time
        await add_promise


# ── Attribute Independence Under Double-Decoration ─────────────


async def test_double_function_decorator_attrs_stay_independent() -> None:
    """Outer @promising.function attributes must not be clobbered by inner."""
    outer_pool = ThreadPoolExecutor(max_workers=1)
    inner_pool = ThreadPoolExecutor(max_workers=2)

    @promising.function(
        namespace="outer",
        start_soon=True,
        children_start_soon=True,
        start_soon_default=True,
        thread_pool=outer_pool,
    )
    @promising.function(
        namespace="inner",
        start_soon=False,
        children_start_soon=False,
        start_soon_default=False,
        thread_pool=inner_pool,
    )
    async def add(a: int, b: int) -> int:
        """Add two numbers."""
        return a + b

    # -- Promising-specific attrs must reflect each layer's own values ------

    assert add.namespace == "outer"
    assert add.start_soon is True
    assert add.children_start_soon is True
    assert add.start_soon_default is True
    assert add.thread_pool is outer_pool

    inner = add.__wrapped__
    assert inner.namespace == "inner"
    assert inner.start_soon is False
    assert inner.children_start_soon is False
    assert inner.start_soon_default is False
    assert inner.thread_pool is inner_pool

    # -- Standard functools.update_wrapper attrs must propagate from the
    #    original function through both layers --------------------------------

    assert add.__name__ == "add"
    assert add.__qualname__ == "test_double_function_decorator_attrs_stay_independent.<locals>.add"
    assert add.__doc__ == "Add two numbers."
    assert add.__module__ == __name__
    assert get_type_hints(add) == {"a": int, "b": int, "return": int}

    assert inner.__name__ == "add"
    assert inner.__qualname__ == "test_double_function_decorator_attrs_stay_independent.<locals>.add"
    assert inner.__doc__ == "Add two numbers."
    assert inner.__module__ == __name__
    assert get_type_hints(inner) == {"a": int, "b": int, "return": int}

    # -- Sanity-check: the decorated function still works --------------------

    result = add(1, 2)
    assert isinstance(result, promising.Promise)
    assert await result == 3


async def test_double_context_decorator_attrs_stay_independent() -> None:
    """Outer @promising.context attributes must not be clobbered by inner."""
    outer_pool = ThreadPoolExecutor(max_workers=1)
    inner_pool = ThreadPoolExecutor(max_workers=2)

    @promising.context(
        namespace="outer",
        children_start_soon=True,
        start_soon_default=True,
        thread_pool=outer_pool,
        parent=None,
    )
    @promising.context(
        namespace="inner",
        children_start_soon=False,
        start_soon_default=False,
        thread_pool=inner_pool,
    )
    async def add(a: int, b: int) -> int:
        """Add two numbers."""
        return a + b

    # -- Promising-specific attrs must reflect each layer's own values ------

    assert add.namespace == "outer"
    assert add.children_start_soon is True
    assert add.start_soon_default is True
    assert add.thread_pool is outer_pool
    assert add.parent is None

    inner = add.__wrapped__
    assert inner.namespace == "inner"
    assert inner.children_start_soon is False
    assert inner.start_soon_default is False
    assert inner.thread_pool is inner_pool
    assert inner.parent is INHERIT

    # -- Standard functools.update_wrapper attrs must propagate from the
    #    original function through both layers --------------------------------

    assert add.__name__ == "add"
    assert add.__qualname__ == "test_double_context_decorator_attrs_stay_independent.<locals>.add"
    assert add.__doc__ == "Add two numbers."
    assert add.__module__ == __name__
    assert get_type_hints(add) == {"a": int, "b": int, "return": int}

    assert inner.__name__ == "add"
    assert inner.__qualname__ == "test_double_context_decorator_attrs_stay_independent.<locals>.add"
    assert inner.__doc__ == "Add two numbers."
    assert inner.__module__ == __name__
    assert get_type_hints(inner) == {"a": int, "b": int, "return": int}

    # -- Sanity-check: the decorated function still works --------------------

    result = await add(1, 2)
    assert result == 3
