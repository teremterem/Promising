import asyncio
import threading

import pytest

import promising

# ── Async Function Decorator ─────────────────────────────────────


def test_async_context_decorator_with_asyncio_run() -> None:
    """
    @promising.context on an async function used with asyncio.run(f()).

    asyncio.run(f()) evaluates f() — and therefore the decorator's
    __call__ — *before* asyncio.run creates and starts its own event
    loop.  The PromisingContext must resolve the event loop lazily
    (when the coroutine body runs) rather than eagerly (when the
    coroutine object is constructed), otherwise it captures a stale
    loop and child Promises will fail with SyncUsageError because
    the captured loop is not running.

    Runs in a separate thread to avoid interfering with the
    pytest-asyncio event loop.
    """
    error = None

    def _run_in_thread() -> None:
        nonlocal error
        try:
            captured_ctx = None

            @promising.context
            async def work() -> str:
                nonlocal captured_ctx
                captured_ctx = promising.get_active_context()
                return "done"

            result = asyncio.run(work())
            assert result == "done"
            assert captured_ctx is not None
            assert isinstance(captured_ctx, promising.PromisingContext)
        except BaseException as exc:
            error = exc

    t = threading.Thread(target=_run_in_thread)
    t.start()
    t.join()
    if error is not None:
        raise error


def test_async_context_decorator_with_asyncio_run_and_child_promise() -> None:
    """
    Same as above but also creates a child Promise inside the context,
    which is the scenario that originally surfaced the bug: the Promise
    calls _call_soon_threadsafe, which checks that _ctx_loop.is_running().

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

            @promising.context
            async def work() -> int:
                result = await child_work(21)
                return result

            assert asyncio.run(work()) == 42
        except BaseException as exc:
            error = exc

    t = threading.Thread(target=_run_in_thread)
    t.start()
    t.join()
    if error is not None:
        raise error


async def test_async_context_decorator_resolves_parent_at_call_site() -> None:
    """
    The parent of a @promising.context-decorated async function's context
    is determined at call-site (when the coroutine object is created),
    not at await-site (when the coroutine body runs).

    Scenario: coroutine created inside `outer`, awaited outside it.
    func_ctx should still have `outer` as its parent.
    """
    func_ctx = None

    @promising.context
    async def work() -> str:
        nonlocal func_ctx
        func_ctx = promising.get_active_context()
        return "done"

    with promising.context() as outer:
        coro = work()
    await coro

    assert func_ctx is not None
    assert func_ctx.get_parent_context(raise_if_none=False) is outer


async def test_async_context_decorator_no_parent_when_called_outside_context() -> None:
    """
    Coroutine created outside any context, awaited inside one.
    func_ctx should have no parent — the context active at await-time
    is irrelevant.
    """
    func_ctx = None

    @promising.context
    async def work() -> str:
        nonlocal func_ctx
        func_ctx = promising.get_active_context()
        return "done"

    coro = work()
    with promising.context():
        await coro

    assert func_ctx is not None
    assert func_ctx.get_parent_context(raise_if_none=False) is None


async def test_async_function_decorator_activates_context() -> None:
    """
    @promising.context on an async function: the context is
    active inside the function body.
    """
    captured_ctx = None

    @promising.context
    async def work() -> str:
        nonlocal captured_ctx
        captured_ctx = promising.get_active_context()
        return "done"

    assert await work() == "done"
    assert captured_ctx is not None
    assert isinstance(captured_ctx, promising.PromisingContext)


async def test_async_function_decorator_deactivates_after() -> None:
    """
    After the decorated async function returns, the context is
    no longer active.
    """

    @promising.context
    async def work() -> str:
        return "done"

    assert promising.get_active_context(raise_if_none=False) is None
    await work()
    assert promising.get_active_context(raise_if_none=False) is None


async def test_async_function_decorator_forwards_args() -> None:
    """
    Positional and keyword arguments are forwarded to the
    decorated async function.
    """

    @promising.context
    async def add(a: int, b: int, *, multiplier: int = 1) -> int:
        return (a + b) * multiplier

    assert await add(3, 4) == 7
    assert await add(3, 4, multiplier=2) == 14


async def test_async_function_decorator_exception_propagates() -> None:
    """
    An exception raised inside the decorated async function
    propagates to the caller.
    """

    @promising.context
    async def failing() -> None:
        raise ValueError("async func error")

    with pytest.raises(ValueError, match="async func error"):
        await failing()


async def test_async_function_decorator_deactivates_on_exception() -> None:
    """
    The context is deactivated even if the decorated async function
    raises.
    """

    @promising.context
    async def failing() -> None:
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        await failing()

    assert promising.get_active_context(raise_if_none=False) is None


async def test_async_function_decorator_with_parens() -> None:
    @promising.context()
    async def work() -> str:
        return "parens"

    assert await work() == "parens"


async def test_async_function_decorator_each_call_gets_fresh_context() -> None:
    """
    Each call to the decorated function gets a fresh
    PromisingContext (not the same instance).
    """
    contexts: list[promising.PromisingContext] = []

    @promising.context
    async def capture() -> None:
        contexts.append(promising.get_active_context())

    await capture()
    await capture()
    assert len(contexts) == 2
    assert contexts[0] is not contexts[1]


# ── Instance Methods ─────────────────────────────────────────────


async def test_instance_method_activates_context() -> None:
    """
    @promising.context on an async instance method: the context
    is active inside the method body and `self` is received.
    """

    class Greeter:
        @promising.context
        async def greet(self) -> str:
            assert promising.get_active_context() is not None
            return "hello"

    assert await Greeter().greet() == "hello"


async def test_instance_method_receives_self() -> None:
    """
    The coroutine receives the correct `self` instance.
    """

    class Counter:
        def __init__(self, value: int) -> None:
            self.value = value

        @promising.context
        async def get_value(self) -> int:
            return self.value

    obj1 = Counter(42)
    obj2 = Counter(100)
    obj3 = Counter(200)
    assert await obj1.get_value() == 42
    assert await obj2.get_value() == 100
    assert await obj3.get_value() == 200
    assert await obj3.get_value() == 200
    assert await obj1.get_value() == 42
    assert await obj2.get_value() == 100


async def test_instance_method_forwards_args() -> None:
    """
    Positional and keyword arguments are forwarded to
    the instance method coroutine correctly.
    """

    class Adder:
        def __init__(self, base: int) -> None:
            self.base = base

        @promising.context
        async def add(self, x: int, *, multiplier: int = 2) -> int:
            return (self.base + x) * multiplier

    obj = Adder(10)
    assert await obj.add(5) == 30
    assert await obj.add(5, multiplier=3) == 45


async def test_instance_method_exception_propagates() -> None:
    """
    An exception raised inside an instance method coroutine
    propagates when awaited.
    """

    class MyClass:
        @promising.context
        async def failing(self) -> None:
            raise ValueError("instance method error")

    with pytest.raises(ValueError, match="instance method error"):
        await MyClass().failing()


async def test_instance_method_with_parens() -> None:
    class MyClass:
        @promising.context()
        async def greet(self) -> str:
            return "parens-method"

    assert await MyClass().greet() == "parens-method"


# ── Static Methods ───────────────────────────────────────────────


async def test_static_method_decorator() -> None:
    """
    @promising.context below @staticmethod: the context is
    active and the function works via class and instance access.
    """

    class MathUtils:
        @staticmethod
        @promising.context
        async def double(x: int) -> int:
            assert promising.get_active_context() is not None
            return x * 2

    assert await MathUtils.double(7) == 14
    assert await MathUtils().double(7) == 14


async def test_static_method_exception_propagates() -> None:
    """
    An exception raised inside a static method decorated with
    @promising.context propagates when awaited.
    """

    class MyClass:
        @staticmethod
        @promising.context
        async def failing() -> None:
            raise RuntimeError("static method error")

    with pytest.raises(RuntimeError, match="static method error"):
        await MyClass.failing()

    with pytest.raises(RuntimeError, match="static method error"):
        await MyClass().failing()


# ── Class Methods ────────────────────────────────────────────────


async def test_class_method_decorator() -> None:
    """
    @promising.context below @classmethod: the context is
    active and `cls` is received correctly.
    """

    class Factory:
        @classmethod
        @promising.context
        async def create_name(cls) -> str:
            assert promising.get_active_context() is not None
            return cls.__name__

    assert await Factory.create_name() == "Factory"
    assert await Factory().create_name() == "Factory"


async def test_class_method_receives_cls_via_inheritance() -> None:
    """
    The classmethod receives the correct class through inheritance.
    """

    class Base:
        @classmethod
        @promising.context
        async def get_class_name(cls) -> str:
            return cls.__name__

    class Child(Base):
        pass

    assert await Base.get_class_name() == "Base"
    assert await Child.get_class_name() == "Child"
    assert await Child().get_class_name() == "Child"
    assert await Base().get_class_name() == "Base"
    assert await Child().get_class_name() == "Child"
    assert await Child.get_class_name() == "Child"


async def test_class_method_forwards_args() -> None:
    """
    Extra arguments are forwarded to the classmethod coroutine
    alongside cls.
    """

    class Formatter:
        @classmethod
        @promising.context
        async def format_value(cls, value: int, *, prefix: str = "") -> str:
            return f"{prefix}{cls.__name__}:{value}"

    assert await Formatter.format_value(42) == "Formatter:42"
    assert await Formatter.format_value(42, prefix=">>") == ">>Formatter:42"


async def test_class_method_exception_propagates() -> None:
    """
    An exception raised inside a classmethod decorated with
    @promising.context propagates when awaited.
    """

    class MyClass:
        @classmethod
        @promising.context
        async def failing(cls) -> None:
            raise TypeError("class method error")

    with pytest.raises(TypeError, match="class method error"):
        await MyClass.failing()

    with pytest.raises(TypeError, match="class method error"):
        await MyClass().failing()


# ── Alternative Decorator Ordering ───────────────────────────────


async def test_context_on_top_of_staticmethod() -> None:
    """
    Applying @promising.context on top of @staticmethod still
    works, both when called via the class and via an instance.
    """

    class MyClass:
        @promising.context
        @staticmethod
        async def my_method() -> str:
            return "ok"

    assert await MyClass.my_method() == "ok"
    assert await MyClass().my_method() == "ok"


async def test_context_on_top_of_classmethod() -> None:
    """
    Applying @promising.context on top of @classmethod still
    works, both when called via the class and via an instance,
    and `cls` is correctly received in both cases.
    """

    class MyClass:
        @promising.context
        @classmethod
        async def my_method(cls) -> type:
            return cls

    assert await MyClass.my_method() is MyClass
    assert await MyClass().my_method() is MyClass


async def test_context_on_top_of_classmethod_with_args() -> None:
    """
    @promising.context above @classmethod with extra arguments:
    cls and all user-supplied args are forwarded correctly.
    """

    class MyClass:
        @promising.context
        @classmethod
        async def my_method(cls, value: int, *, prefix: str = "") -> str:
            return f"{prefix}{cls.__name__}:{value}"

    assert await MyClass.my_method(7) == "MyClass:7"
    assert await MyClass.my_method(7, prefix=">>") == ">>MyClass:7"
    assert await MyClass().my_method(7) == "MyClass:7"
    assert await MyClass().my_method(7, prefix=">>") == ">>MyClass:7"


async def test_context_with_parens_on_top_of_staticmethod() -> None:
    class MyClass:
        @promising.context()
        @staticmethod
        async def my_method() -> None: ...

    assert await MyClass.my_method() is None
    assert await MyClass().my_method() is None


async def test_context_with_parens_on_top_of_classmethod() -> None:
    class MyClass:
        @promising.context()
        @classmethod
        async def my_method(cls) -> type:
            return cls

    assert await MyClass.my_method() is MyClass
    assert await MyClass().my_method() is MyClass


# ── Decorator With Configuration ─────────────────────────────────


@pytest.mark.parametrize("parent", [None, promising.INHERIT])
async def test_decorator_with_explicit_parent(parent) -> None:
    """
    @promising.context(parent=None) creates a root context even
    when called inside another context.
    """

    @promising.context(parent=parent)
    async def work() -> promising.PromisingContext | None:
        ctx = promising.get_active_context()
        return ctx.get_parent_context(raise_if_none=False)

    with promising.context() as parent_ctx:
        returned_parent_ctx = await work()
        if parent is None:
            assert returned_parent_ctx is None
        else:
            assert returned_parent_ctx is parent_ctx


# ── Argument Errors at Call-Time ─────────────────────────────────


@pytest.mark.parametrize("use_thread_pool", [True, False])
@pytest.mark.parametrize("context_with_parens", [False, True], ids=["ctx-no-parens", "ctx-with-parens"])
@pytest.mark.parametrize("function_with_parens", [False, True], ids=["func-no-parens", "func-with-parens"])
async def test_context_on_top_of_function_raises_use_thread_pool_error_at_call_time(
    function_with_parens: bool,
    context_with_parens: bool,
    use_thread_pool: bool,
) -> None:
    """
    When @promising.context is stacked on top of @promising.function,
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
    When @promising.context is stacked on top of @promising.function,
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

    # Calling with missing required arguments should raise immediately
    with pytest.raises(TypeError):
        add()  # no await — the error should happen at call-time


@pytest.mark.parametrize("with_parens", [False, True], ids=["no-parens", "with-parens"])
async def test_context_alone_raises_arg_error_at_call_time(
    with_parens: bool,
) -> None:
    """
    Baseline 1 for test_context_on_top_of_function_raises_arg_error_at_call_time:
    @promising.context alone on an async function that requires arguments
    should raise TypeError immediately at call-time when called with
    wrong arguments (not defer it to await-time).
    """
    context_decorator = promising.context() if with_parens else promising.context

    @context_decorator
    async def add(a: int, b: int) -> int:
        return a + b

    with pytest.raises(TypeError):
        add()  # no await — the error should happen at call-time


async def test_plain_async_raises_arg_error_at_call_time() -> None:
    """
    Baseline 2 for test_context_on_top_of_function_raises_arg_error_at_call_time:
    a plain async function with required arguments raises TypeError
    immediately at call-time when called with wrong arguments.
    This is standard Python behavior — no decorators involved.
    """

    async def add(a: int, b: int) -> int:
        return a + b

    with pytest.raises(TypeError):
        add()  # no await — the error happens at call-time


# ── Sync Counterparts for Argument-Error-at-Call-Time Tests ──────


@pytest.mark.parametrize("context_with_parens", [False, True], ids=["ctx-no-parens", "ctx-with-parens"])
async def test_context_on_top_of_sync_function_accepts_use_thread_pool_at_call_time(
    context_with_parens: bool,
) -> None:
    """
    Sync counterpart of test_context_on_top_of_function_raises_use_thread_pool_error_at_call_time.

    For sync functions, ``use_thread_pool`` is valid at call-time (it overrides
    the decoration-time setting). When @promising.context is stacked on top of
    @promising.function on a sync function, passing use_thread_pool at call-time
    should NOT raise — unlike the async case which raises DecorationError.

    The sync path in @promising.context calls the inner function directly (not
    deferred into a coroutine body), so no deferral issue exists.
    """
    context_decorator = promising.context() if context_with_parens else promising.context

    @context_decorator
    @promising.function(use_thread_pool=True)
    def add(a: int, b: int) -> int:
        return a + b

    ground_truth = add(1, 2)
    assert isinstance(ground_truth, promising.Promise)
    assert await ground_truth == 3

    # For sync functions, use_thread_pool CAN be passed at call-time — no error
    with pytest.raises(promising.DecorationError, match="requires an explicit `use_thread_pool` setting"):
        add(1, 2, use_thread_pool=None)


@pytest.mark.parametrize("context_with_parens", [False, True], ids=["ctx-no-parens", "ctx-with-parens"])
async def test_context_on_top_of_sync_function_raises_arg_error_at_call_time(
    context_with_parens: bool,
) -> None:
    """
    Sync counterpart of test_context_on_top_of_function_raises_arg_error_at_call_time.

    When @promising.context is stacked on top of @promising.function on a sync
    function, calling with wrong arguments raises TypeError immediately at
    call-time.

    The sync path in @promising.context calls the inner function directly (not
    deferred into a coroutine body), so argument validation happens at call-time
    rather than being deferred.
    """
    context_decorator = promising.context() if context_with_parens else promising.context

    @context_decorator
    @promising.function(use_thread_pool=True)
    def add(a: int, b: int) -> int:
        return a + b

    # Calling with missing required arguments should raise immediately
    with pytest.raises(TypeError):
        add()  # the error should happen at call-time


@pytest.mark.parametrize("with_parens", [False, True], ids=["no-parens", "with-parens"])
async def test_context_alone_on_sync_function_raises_arg_error_at_call_time(
    with_parens: bool,
) -> None:
    """
    Sync counterpart of test_context_alone_raises_arg_error_at_call_time.

    @promising.context alone on a sync function that requires arguments should
    raise TypeError immediately at call-time when called with wrong arguments.

    The sync path in @promising.context calls the inner function directly, so
    argument validation happens immediately — no deferral.
    """
    context_decorator = promising.context() if with_parens else promising.context

    @context_decorator
    def add(a: int, b: int) -> int:
        return a + b

    # Unlike `@promising.function`, `@promising.context` does not convert
    # functions (either sync or async) into PromiseFunctions, it only wraps the
    # code in a PromisingContext manager. The contract of the function remains
    # the same - which, in this case, means synchronous.
    assert add(1, 2) == 3

    with pytest.raises(TypeError):
        add()  # the error should happen at call-time
