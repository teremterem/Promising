"""
Tests that errors from incorrect call-time arguments (missing args, wrong types,
invalid ``use_thread_pool`` on async functions) are raised immediately at call-time
rather than being deferred to await-time.

**Why this matters:** an error surfaced at the call site points the developer
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
   ``@promising.context``, and double ``@promising.context``. These stress-test
   that call-time error semantics survive even under non-standard stacking.
3. **Sync counterparts** — the same stacking scenarios applied to sync functions,
   verifying that ``use_thread_pool`` validation and argument errors surface at
   call-time.
"""

import pytest

import promising

# ── Baselines (no decorator stacking) ────────────────────────────


async def test_plain_async_raises_arg_error_at_call_time() -> None:
    """
    Baseline 1 for test_context_on_top_of_function_raises_arg_error_at_call_time:
    a plain async function with required arguments raises TypeError
    immediately at call-time when called with wrong arguments.
    This is standard Python behavior — no decorators involved.
    """

    async def add(a: int, b: int) -> int:
        return a + b

    assert await add(1, 2) == 3

    with pytest.raises(TypeError, match="required positional argument"):
        add()  # no await — the error happens at call-time


@pytest.mark.parametrize("with_parens", [False, True], ids=["no-parens", "with-parens"])
async def test_context_alone_raises_arg_error_at_call_time(
    with_parens: bool,
) -> None:
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
async def test_context_alone_on_sync_function_raises_arg_error_at_call_time(
    with_parens: bool,
) -> None:
    """
    Baseline for test_context_on_top_of_sync_function_raises_arg_error_at_call_time:
    @promising.context alone on a sync function that requires arguments should
    raise TypeError immediately at call-time when called with wrong arguments.

    Unlike test_context_on_top_of_sync_function_raises_arg_error_at_call_time,
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
        add()  # the error should happen at call-time


def test_plain_sync_raises_arg_error_at_call_time() -> None:
    """
    Baseline: a plain sync function with required arguments raises TypeError
    immediately at call-time when called with wrong arguments.
    This is standard Python behavior — no decorators involved.
    """

    def add(a: int, b: int) -> int:
        return a + b

    assert add(1, 2) == 3

    with pytest.raises(TypeError, match="required positional argument"):
        add()


@pytest.mark.parametrize("use_thread_pool", [True, False])
@pytest.mark.parametrize("with_parens", [False, True], ids=["no-parens", "with-parens"])
async def test_function_alone_raises_use_thread_pool_error_at_call_time(
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
        add(1, 2, use_thread_pool=use_thread_pool)


@pytest.mark.parametrize("with_parens", [False, True], ids=["no-parens", "with-parens"])
async def test_function_alone_raises_arg_error_at_call_time(
    with_parens: bool,
) -> None:
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
        add(1, 2, use_thread_pool=None)


@pytest.mark.parametrize("decorator_use_thread_pool", [True, False])
async def test_function_alone_on_sync_raises_arg_error_at_call_time(
    decorator_use_thread_pool: bool,
) -> None:
    """
    Baseline: @promising.function on a sync function should raise TypeError
    immediately at call-time when called with wrong arguments.
    """

    @promising.function(use_thread_pool=decorator_use_thread_pool)
    def add(a: int, b: int) -> int:
        return a + b

    ground_truth = add(1, 2)
    assert isinstance(ground_truth, promising.Promise)
    assert await ground_truth == 3

    with pytest.raises(TypeError, match="required positional argument"):
        add()  # the error should happen at call-time


# ── Unusual Decorator Stacking ──────────────────────────────────


@pytest.mark.parametrize("use_thread_pool", [True, False])
@pytest.mark.parametrize("context_with_parens", [False, True], ids=["ctx-no-parens", "ctx-with-parens"])
@pytest.mark.parametrize("function_with_parens", [False, True], ids=["func-no-parens", "func-with-parens"])
async def test_context_on_top_of_function_raises_use_thread_pool_error_at_call_time(
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

    Currently, @promising.context defers the inner call into the coroutine
    body (_async_wrapper), which delays the use_thread_pool validation
    error until the coroutine is awaited.  This test is expected to fail
    until the bug is fixed.

    See: https://github.com/teremterem/Promising/pull/79#discussion_r2959328724
    """
    context_decorator = promising.context() if context_with_parens else promising.context
    function_decorator = promising.function() if function_with_parens else promising.function

    @context_decorator
    @function_decorator
    async def add(a: int, b: int) -> int:
        return a + b

    ground_truth = add(1, 2)
    assert isinstance(ground_truth, promising.Promise)
    assert await ground_truth == 3

    # Passing use_thread_pool at call time on an async function should raise immediately
    with pytest.raises(promising.DecorationError, match="cannot be set for async function"):
        add(1, 2, use_thread_pool=use_thread_pool)  # no await — the error should happen at call-time


@pytest.mark.parametrize("context_with_parens", [False, True], ids=["ctx-no-parens", "ctx-with-parens"])
@pytest.mark.parametrize("function_with_parens", [False, True], ids=["func-no-parens", "func-with-parens"])
async def test_context_on_top_of_function_raises_arg_error_at_call_time(
    function_with_parens: bool,
    context_with_parens: bool,
) -> None:
    """
    When @promising.context is stacked on top of @promising.function —
    an unusual combination that is not a realistic usage pattern —
    calling the decorated function with wrong arguments should raise
    TypeError immediately at call-time, not defer it to await-time.

    Currently, @promising.context defers the inner call into the coroutine
    body (_async_wrapper), which delays argument validation errors until
    the coroutine is awaited.  This test is expected to fail until the
    bug is fixed.

    See: https://github.com/teremterem/Promising/pull/79#discussion_r2959328724
    """
    context_decorator = promising.context() if context_with_parens else promising.context
    function_decorator = promising.function() if function_with_parens else promising.function

    @context_decorator
    @function_decorator
    async def add(a: int, b: int) -> int:
        return a + b

    ground_truth = add(1, 2)
    assert isinstance(ground_truth, promising.Promise)
    assert await ground_truth == 3

    # Calling with missing required arguments should raise immediately
    with pytest.raises(TypeError, match="required positional argument"):
        add()  # no await — the error should happen at call-time


@pytest.mark.parametrize("use_thread_pool", [True, False])
@pytest.mark.parametrize("outer_with_parens", [False, True], ids=["outer-no-parens", "outer-with-parens"])
@pytest.mark.parametrize("inner_with_parens", [False, True], ids=["inner-no-parens", "inner-with-parens"])
async def test_function_on_top_of_function_raises_use_thread_pool_error_at_call_time(
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
        add(1, 2, use_thread_pool=use_thread_pool)


@pytest.mark.parametrize("outer_with_parens", [False, True], ids=["outer-no-parens", "outer-with-parens"])
@pytest.mark.parametrize("inner_with_parens", [False, True], ids=["inner-no-parens", "inner-with-parens"])
async def test_function_on_top_of_function_raises_arg_error_at_call_time(
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
        add(1, 2, use_thread_pool=use_thread_pool)


@pytest.mark.parametrize("func_with_parens", [False, True], ids=["func-no-parens", "func-with-parens"])
@pytest.mark.parametrize("ctx_with_parens", [False, True], ids=["ctx-no-parens", "ctx-with-parens"])
async def test_function_on_top_of_context_raises_arg_error_at_call_time(
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
def test_context_on_top_of_context_on_sync_raises_arg_error_at_call_time(
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
        add()  # the error should happen at call-time


# ── Sync Counterparts for Argument-Error-at-Call-Time Tests ──────


@pytest.mark.parametrize("decorator_use_thread_pool", [True, False])
@pytest.mark.parametrize("context_with_parens", [False, True], ids=["ctx-no-parens", "ctx-with-parens"])
async def test_context_on_top_of_sync_function_accepts_use_thread_pool_at_call_time(
    context_with_parens: bool,
    decorator_use_thread_pool: bool,
) -> None:
    """
    Sync counterpart of test_context_on_top_of_function_raises_use_thread_pool_error_at_call_time.

    For sync functions, ``use_thread_pool`` is a valid call-time override — unlike
    async functions, where any ``use_thread_pool`` value raises DecorationError.
    However, passing ``use_thread_pool=None`` at call-time is still an error
    because it attempts to unset the required thread-pool setting.

    This test verifies the error is raised immediately at call-time even when
    @promising.context is stacked on top.
    """
    context_decorator = promising.context() if context_with_parens else promising.context

    @context_decorator
    @promising.function(use_thread_pool=decorator_use_thread_pool)
    def add(a: int, b: int) -> int:
        return a + b

    ground_truth = add(1, 2)
    assert isinstance(ground_truth, promising.Promise)
    assert await ground_truth == 3

    # use_thread_pool=None tries to unset the thread-pool setting, which is not allowed
    with pytest.raises(promising.DecorationError, match="requires an explicit `use_thread_pool` setting"):
        add(1, 2, use_thread_pool=None)


@pytest.mark.parametrize("decorator_use_thread_pool", [True, False])
@pytest.mark.parametrize("context_with_parens", [False, True], ids=["ctx-no-parens", "ctx-with-parens"])
async def test_context_on_top_of_sync_function_raises_arg_error_at_call_time(
    context_with_parens: bool,
    decorator_use_thread_pool: bool,
) -> None:
    """
    Sync counterpart of test_context_on_top_of_function_raises_arg_error_at_call_time.

    When @promising.context is stacked on top of @promising.function on a sync
    function, calling with wrong arguments should raise TypeError immediately at
    call-time — even though @promising.function turns the sync function into a
    Promise-returning one.
    """
    context_decorator = promising.context() if context_with_parens else promising.context

    @context_decorator
    @promising.function(use_thread_pool=decorator_use_thread_pool)
    def add(a: int, b: int) -> int:
        return a + b

    ground_truth = add(1, 2)
    assert isinstance(ground_truth, promising.Promise)
    assert await ground_truth == 3

    # Calling with missing required arguments should raise immediately
    with pytest.raises(TypeError, match="required positional argument"):
        add()  # the error should happen at call-time


@pytest.mark.parametrize("decorator_use_thread_pool", [True, False])
@pytest.mark.parametrize("outer_with_parens", [False, True], ids=["outer-no-parens", "outer-with-parens"])
@pytest.mark.parametrize("inner_with_parens", [False, True], ids=["inner-no-parens", "inner-with-parens"])
async def test_function_on_top_of_function_on_sync_raises_use_thread_pool_error_at_call_time(
    inner_with_parens: bool,
    outer_with_parens: bool,
    decorator_use_thread_pool: bool,
) -> None:
    """
    Sync counterpart of test_function_on_top_of_function_raises_use_thread_pool_error_at_call_time.

    When @promising.function is stacked on top of another @promising.function
    on a sync function, passing use_thread_pool=None at call-time should raise
    DecorationError immediately at call-time.
    """
    outer_decorator = promising.function() if outer_with_parens else promising.function
    inner_decorator = (
        promising.function(use_thread_pool=decorator_use_thread_pool) if inner_with_parens else promising.function
    )

    @outer_decorator
    @inner_decorator
    def add(a: int, b: int) -> int:
        return a + b

    ground_truth = add(1, 2)
    assert isinstance(ground_truth, promising.Promise)
    assert await ground_truth == 3

    with pytest.raises(promising.DecorationError, match="requires an explicit `use_thread_pool` setting"):
        add(1, 2, use_thread_pool=None)


@pytest.mark.parametrize("decorator_use_thread_pool", [True, False])
@pytest.mark.parametrize("outer_with_parens", [False, True], ids=["outer-no-parens", "outer-with-parens"])
@pytest.mark.parametrize("inner_with_parens", [False, True], ids=["inner-no-parens", "inner-with-parens"])
async def test_function_on_top_of_function_on_sync_raises_arg_error_at_call_time(
    inner_with_parens: bool,
    outer_with_parens: bool,
    decorator_use_thread_pool: bool,
) -> None:
    """
    Sync counterpart of test_function_on_top_of_function_raises_arg_error_at_call_time.

    When @promising.function is stacked on top of another @promising.function
    on a sync function, calling with wrong arguments should raise TypeError
    immediately at call-time.
    """
    outer_decorator = promising.function() if outer_with_parens else promising.function
    inner_decorator = (
        promising.function(use_thread_pool=decorator_use_thread_pool) if inner_with_parens else promising.function
    )

    @outer_decorator
    @inner_decorator
    def add(a: int, b: int) -> int:
        return a + b

    ground_truth = add(1, 2)
    assert isinstance(ground_truth, promising.Promise)
    assert await ground_truth == 3

    with pytest.raises(TypeError, match="required positional argument"):
        add()  # the error should happen at call-time


@pytest.mark.parametrize("func_with_parens", [False, True], ids=["func-no-parens", "func-with-parens"])
@pytest.mark.parametrize("ctx_with_parens", [False, True], ids=["ctx-no-parens", "ctx-with-parens"])
async def test_function_on_top_of_context_on_sync_raises_use_thread_pool_error_at_call_time(
    ctx_with_parens: bool,
    func_with_parens: bool,
) -> None:
    """
    Sync counterpart of test_function_on_top_of_context_raises_use_thread_pool_error_at_call_time.

    When @promising.function is stacked on top of @promising.context on a sync
    function, passing use_thread_pool=None at call-time should raise
    DecorationError immediately at call-time.
    """
    func_decorator = promising.function() if func_with_parens else promising.function
    ctx_decorator = promising.context() if ctx_with_parens else promising.context

    @func_decorator
    @ctx_decorator
    def add(a: int, b: int) -> int:
        return a + b

    ground_truth = add(1, 2)
    assert isinstance(ground_truth, promising.Promise)
    assert await ground_truth == 3

    with pytest.raises(promising.DecorationError, match="requires an explicit `use_thread_pool` setting"):
        add(1, 2, use_thread_pool=None)


@pytest.mark.parametrize("func_with_parens", [False, True], ids=["func-no-parens", "func-with-parens"])
@pytest.mark.parametrize("ctx_with_parens", [False, True], ids=["ctx-no-parens", "ctx-with-parens"])
async def test_function_on_top_of_context_on_sync_raises_arg_error_at_call_time(
    ctx_with_parens: bool,
    func_with_parens: bool,
) -> None:
    """
    Sync counterpart of test_function_on_top_of_context_raises_arg_error_at_call_time.

    When @promising.function is stacked on top of @promising.context on a sync
    function, calling with wrong arguments should raise TypeError immediately
    at call-time.
    """
    func_decorator = promising.function() if func_with_parens else promising.function
    ctx_decorator = promising.context() if ctx_with_parens else promising.context

    @func_decorator
    @ctx_decorator
    def add(a: int, b: int) -> int:
        return a + b

    ground_truth = add(1, 2)
    assert isinstance(ground_truth, promising.Promise)
    assert await ground_truth == 3

    with pytest.raises(TypeError, match="required positional argument"):
        add()  # the error should happen at call-time
