"""
Tests for synchronous functions decorated with @promising.function.
Sync functions are executed in a thread pool executor and their results
are delivered through a Promise just like async functions.
"""

import threading

import pytest

import promising

# ── Core: Sync Function Wrapping & Argument Forwarding ──────────


async def test_calling_sync_promising_function_returns_promise() -> None:
    """
    Calling a decorated sync function returns a Promise;
    awaiting it returns the expected value.
    """

    @promising.function
    def greet() -> str:
        return "hello"

    assert isinstance(greet, promising.PromisingFunction)
    result = greet()
    assert isinstance(result, promising.Promise)
    assert await result == "hello"


async def test_forwards_positional_args() -> None:
    """
    Positional args are correctly forwarded to the
    wrapped sync function.
    """

    @promising.function
    def add(a: int, b: int) -> int:
        return a + b

    assert await add(1, 2) == 3


async def test_forwards_keyword_args() -> None:
    """
    Keyword-only params are correctly forwarded to the
    wrapped sync function.
    """

    @promising.function
    def greet(*, greeting: str, name: str) -> str:
        return f"{greeting}, {name}"

    assert await greet(greeting="hi", name="world") == "hi, world"


async def test_forwards_mixed_args() -> None:
    """
    A mix of positional and keyword args is forwarded
    correctly.
    """

    @promising.function
    def mixed(a: int, b: int, *, suffix: str = "!") -> str:
        return f"{a + b}{suffix}"

    assert await mixed(3, 4, suffix="?") == "7?"


async def test_default_args() -> None:
    """
    Calling with no args uses defaults; calling with
    explicit args overrides them.
    """

    @promising.function
    def with_defaults(x: int = 10, y: int = 20) -> int:
        return x + y

    assert await with_defaults() == 30
    assert await with_defaults(1, 2) == 3


async def test_star_args_and_kwargs() -> None:
    """
    *args and **kwargs are forwarded to the wrapped
    sync function correctly.
    """

    @promising.function
    def variadic(*args: int, **kwargs: str) -> tuple:
        return (args, kwargs)

    result = await variadic(1, 2, 3, key="value")
    assert result == ((1, 2, 3), {"key": "value"})


async def test_sync_function_executes_once() -> None:
    """
    A nonlocal counter confirms the sync function runs
    exactly once per call; second call increments to 2.
    """
    call_count = 0

    @promising.function
    def counted() -> str:
        nonlocal call_count
        call_count += 1
        return "done"

    promise_one = counted()
    assert await promise_one == "done"
    assert await promise_one == "done"
    assert call_count == 1

    promise_two = counted()
    assert await promise_two == "done"
    assert await promise_two == "done"
    assert call_count == 2


# ── Thread Verification ──────────────────────────────────────────


async def test_sync_function_runs_in_different_thread() -> None:
    """
    The sync function actually runs in a different thread
    than the event loop thread.
    """
    main_thread = threading.current_thread()

    @promising.function
    def get_thread() -> threading.Thread:
        return threading.current_thread()

    worker_thread = await get_thread()
    assert worker_thread is not main_thread


# ── Error Cases ──────────────────────────────────────────────────


async def test_exception_propagates_through_promise() -> None:
    """
    An exception raised inside the sync function
    propagates through the Promise when awaited.
    """

    @promising.function
    def failing() -> None:
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
    def failing() -> None:
        raise exc_type("specific error")

    with pytest.raises(exc_type):
        await failing()


# ── function() Decorator Modes ───────────────────────────────────


async def test_decorator_with_empty_parens() -> None:
    """
    @promising.function() (empty parens) behaves
    identically to bare @promising.function for sync functions.
    """

    @promising.function()
    def greet() -> str:
        return "hello"

    assert isinstance(greet, promising.PromisingFunction)
    assert await greet() == "hello"


async def test_used_as_direct_call() -> None:
    """
    promising.function(my_func) used as a direct call
    (non-decorator) works for sync functions.
    """

    def my_func() -> str:
        return "direct"

    pf = promising.function(my_func)
    assert isinstance(pf, promising.PromisingFunction)
    assert await pf() == "direct"


async def test_preserves_original_func() -> None:
    """
    decorated.__wrapped__ is the original function passed
    to the decorator.
    """

    def original() -> str:
        return "preserved"

    decorated = promising.function(original)
    assert decorated.__wrapped__ is original


# ── Instance Methods ─────────────────────────────────────────────


async def test_instance_method_returns_promise() -> None:
    """
    @promising.function on a sync instance method: calling
    the method on an instance returns a Promise.
    """

    class Greeter:
        @promising.function
        def greet(self) -> str:
            return "hello"

    obj = Greeter()
    result = obj.greet()
    assert isinstance(result, promising.Promise)
    assert await result == "hello"


async def test_instance_method_receives_self() -> None:
    """
    The sync function receives the correct `self` instance.
    """

    class Counter:
        def __init__(self, value: int) -> None:
            self.value = value

        @promising.function
        def get_value(self) -> int:
            return self.value

    obj = Counter(42)
    assert await obj.get_value() == 42


async def test_instance_method_forwards_args() -> None:
    """
    Positional and keyword arguments are forwarded to
    the sync instance method correctly.
    """

    class Adder:
        def __init__(self, base: int) -> None:
            self.base = base

        @promising.function
        def add(self, x: int, *, multiplier: int = 1) -> int:
            return (self.base + x) * multiplier

    obj = Adder(10)
    assert await obj.add(5) == 15
    assert await obj.add(5, multiplier=3) == 45


async def test_instance_method_exception_propagates() -> None:
    """
    An exception raised inside a sync instance method
    propagates through the Promise when awaited.
    """

    class MyClass:
        @promising.function
        def failing(self) -> None:
            raise ValueError("instance method error")

    with pytest.raises(ValueError, match="instance method error"):
        await MyClass().failing()


# ── Static Methods ───────────────────────────────────────────────


async def test_static_method_via_class_returns_promise() -> None:
    """
    @promising.function @staticmethod accessed on the class
    returns a Promise when called (sync).
    """

    class MathUtils:
        @staticmethod
        @promising.function
        def double(x: int) -> int:
            return x * 2

    assert isinstance(MathUtils.double, promising.PromisingFunction)
    result = MathUtils.double(7)
    assert isinstance(result, promising.Promise)
    assert await result == 14


async def test_static_method_via_instance_returns_promise() -> None:
    """
    @promising.function @staticmethod accessed on an instance
    returns a Promise when called (sync).
    """

    class MathUtils:
        @staticmethod
        @promising.function
        def double(x: int) -> int:
            return x * 2

    obj = MathUtils()
    result = obj.double(7)
    assert isinstance(result, promising.Promise)
    assert await result == 14


async def test_static_method_exception_propagates() -> None:
    """
    An exception raised inside a sync static method
    propagates through the Promise when awaited.
    """

    class MyClass:
        @staticmethod
        @promising.function
        def failing() -> None:
            raise RuntimeError("static method error")

    with pytest.raises(RuntimeError, match="static method error"):
        await MyClass.failing()

    with pytest.raises(RuntimeError, match="static method error"):
        await MyClass().failing()


# ── Class Methods ────────────────────────────────────────────────


async def test_class_method_via_class_returns_promise() -> None:
    """
    @promising.function @classmethod accessed on the class
    returns a Promise when called (sync).
    """

    class Factory:
        @classmethod
        @promising.function
        def create_name(cls) -> str:
            return cls.__name__

    result = Factory.create_name()
    assert isinstance(result, promising.Promise)
    assert await result == "Factory"


async def test_class_method_via_instance_returns_promise() -> None:
    """
    @promising.function @classmethod accessed on an instance
    returns a Promise when called (sync).
    """

    class Factory:
        @classmethod
        @promising.function
        def create_name(cls) -> str:
            return cls.__name__

    obj = Factory()
    result = obj.create_name()
    assert isinstance(result, promising.Promise)
    assert await result == "Factory"


async def test_class_method_receives_cls() -> None:
    """
    The sync classmethod receives the correct class,
    including through inheritance.
    """

    class Base:
        @classmethod
        @promising.function
        def get_class_name(cls) -> str:
            return cls.__name__

    class Child(Base):
        pass

    assert await Base.get_class_name() == "Base"
    assert await Child.get_class_name() == "Child"


async def test_class_method_exception_propagates() -> None:
    """
    An exception raised inside a sync classmethod
    propagates through the Promise when awaited.
    """

    class MyClass:
        @classmethod
        @promising.function
        def failing(cls) -> None:
            raise TypeError("class method error")

    with pytest.raises(TypeError, match="class method error"):
        await MyClass.failing()

    with pytest.raises(TypeError, match="class method error"):
        await MyClass().failing()


# ── Alternative Decorator Ordering ───────────────────────────────


async def test_promising_function_on_top_of_staticmethod() -> None:
    """
    Applying @promising.function on top of @staticmethod
    still works for sync functions.
    """

    class MyClass:
        @promising.function
        @staticmethod
        def my_method() -> None: ...

    assert await MyClass.my_method() is None
    assert await MyClass().my_method() is None


async def test_promising_function_on_top_of_classmethod() -> None:
    """
    Applying @promising.function on top of @classmethod
    still works for sync functions, and `cls` is correctly
    received.
    """

    class MyClass:
        @promising.function
        @classmethod
        def my_method(cls) -> type:
            return cls

    assert await MyClass.my_method() is MyClass
    assert await MyClass().my_method() is MyClass


# ── Config Parameters ────────────────────────────────────────────


async def test_config_params_work_with_sync_functions() -> None:
    """
    start_soon, children_start_soon_by_default, and
    everything_starts_soon_by_default config params
    work with sync functions.
    """

    @promising.function(
        start_soon=False,
        children_start_soon_by_default=False,
        everything_starts_soon_by_default=False,
    )
    def noop() -> None:
        pass

    promise = noop()
    assert promise._start_soon is False
    assert promise._children_start_soon_by_default is False
    assert promise._everything_starts_soon_by_default is False
    await promise


async def test_call_time_config_overrides_work_with_sync_functions() -> None:
    """
    Config params passed at call time override the
    PromisingFunction-level defaults for sync functions.
    """

    @promising.function(
        start_soon=False,
        children_start_soon_by_default=False,
        everything_starts_soon_by_default=False,
    )
    def noop() -> None:
        pass

    promise = noop(
        start_soon=True,
        children_start_soon_by_default=True,
        everything_starts_soon_by_default=True,
    )
    assert promise._start_soon is True
    assert promise._children_start_soon_by_default is True
    assert promise._everything_starts_soon_by_default is True
    await promise


async def test_config_kwargs_do_not_leak_into_sync_function() -> None:
    """
    start_soon etc. passed at call time are consumed by
    call() and not forwarded to the wrapped sync function.
    """

    @promising.function
    def add(a: int, b: int) -> int:
        return a + b

    result = await add(
        3,
        4,
        start_soon=True,
        children_start_soon_by_default=True,
        everything_starts_soon_by_default=True,
    )
    assert result == 7
