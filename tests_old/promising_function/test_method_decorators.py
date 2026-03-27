import pytest

import promising

# ── Instance Methods ──────────────────────────────────────────────


async def test_instance_method_returns_promise() -> None:
    """
    @promising.function on an instance method: calling the
    method on an instance returns a Promise.
    """

    class Greeter:
        @promising.function
        async def greet(self) -> str:
            return "hello"

    obj = Greeter()
    result = obj.greet()
    assert isinstance(result, promising.Promise)
    assert await result == "hello"


async def test_instance_method_receives_self() -> None:
    """
    The coroutine receives the correct `self` instance.
    """

    class Counter:
        def __init__(self, value: int) -> None:
            self.value = value

        @promising.function
        async def get_value(self) -> int:
            return self.value

    obj = Counter(42)
    assert await obj.get_value() == 42


async def test_instance_method_forwards_args() -> None:
    """
    Positional and keyword arguments are forwarded to
    the instance method coroutine correctly.
    """

    class Adder:
        def __init__(self, base: int) -> None:
            self.base = base

        @promising.function
        async def add(self, x: int, *, multiplier: int = 1) -> int:
            return (self.base + x) * multiplier

    obj = Adder(10)
    assert await obj.add(5) == 15
    assert await obj.add(5, multiplier=3) == 45


async def test_instance_method_class_access_is_promising_function() -> None:
    """
    Accessing the decorated method on the class itself returns the
    PromisingFunction (unbound).
    """

    class MyClass:
        @promising.function
        async def my_method(self) -> str:
            return "ok"

    assert isinstance(MyClass.my_method, promising.PromisingFunction)


async def test_instance_method_with_empty_parens_decorator() -> None:
    """
    @promising.function() with empty parens also works as an
    instance method decorator.
    """

    class MyClass:
        @promising.function()
        async def greet(self) -> str:
            return "hi"

    obj = MyClass()
    assert isinstance(MyClass.greet, promising.PromisingFunction)
    assert await obj.greet() == "hi"


async def test_instance_method_executes_once() -> None:
    """
    The coroutine executes exactly once per call regardless of
    how many times the resulting Promise is awaited.
    """
    call_count = 0

    class MyClass:
        @promising.function
        async def counted(self) -> str:
            nonlocal call_count
            call_count += 1
            return "done"

    obj = MyClass()
    p = obj.counted()
    assert await p == "done"
    assert await p == "done"
    assert call_count == 1


async def test_instance_method_exception_propagates() -> None:
    """
    An exception raised inside an instance method coroutine
    propagates through the Promise when awaited.
    """

    class MyClass:
        @promising.function
        async def failing(self) -> None:
            raise ValueError("instance method error")

    with pytest.raises(ValueError, match="instance method error"):
        await MyClass().failing()


# ── Static Methods ────────────────────────────────────────────────


async def test_static_method_via_class_returns_promise() -> None:
    """
    @promising.function @staticmethod accessed on the class
    returns a Promise when called.
    """

    class MathUtils:
        @staticmethod
        @promising.function
        async def double(x: int) -> int:
            return x * 2

    assert isinstance(MathUtils.double, promising.PromisingFunction)
    result = MathUtils.double(7)
    assert isinstance(result, promising.Promise)
    assert await result == 14


async def test_static_method_via_instance_returns_promise() -> None:
    """
    @promising.function @staticmethod accessed on an instance
    returns a Promise when called.
    """

    class MathUtils:
        @staticmethod
        @promising.function
        async def double(x: int) -> int:
            return x * 2

    obj = MathUtils()
    result = obj.double(7)
    assert isinstance(result, promising.Promise)
    assert await result == 14


async def test_static_method_receives_no_implicit_arg() -> None:
    """
    The static method coroutine receives only the explicit
    arguments - no `self` or `cls` is prepended.
    """

    class MathUtils:
        @staticmethod
        @promising.function
        async def add(a: int, b: int) -> int:
            return a + b

    assert await MathUtils.add(3, 4) == 7
    assert await MathUtils().add(3, 4) == 7


async def test_static_method_with_empty_parens_decorator() -> None:
    """
    @promising.function() with empty parens also works as a
    static method decorator.
    """

    class MathUtils:
        @staticmethod
        @promising.function()
        async def triple(x: int) -> int:
            return x * 3

    assert await MathUtils.triple(5) == 15
    assert await MathUtils().triple(5) == 15


async def test_static_method_exception_propagates() -> None:
    """
    An exception raised inside a static method coroutine
    propagates through the Promise when awaited.
    """

    class MyClass:
        @staticmethod
        @promising.function
        async def failing() -> None:
            raise RuntimeError("static method error")

    with pytest.raises(RuntimeError, match="static method error"):
        await MyClass.failing()

    with pytest.raises(RuntimeError, match="static method error"):
        await MyClass().failing()


# ── Class Methods ─────────────────────────────────────────────────


async def test_class_method_via_class_returns_promise() -> None:
    """
    @promising.function @classmethod accessed on the class
    returns a Promise when called.
    """

    class Factory:
        @classmethod
        @promising.function
        async def create_name(cls) -> str:
            return cls.__name__

    result = Factory.create_name()
    assert isinstance(result, promising.Promise)
    assert await result == "Factory"


async def test_class_method_via_instance_returns_promise() -> None:
    """
    @promising.function @classmethod accessed on an instance
    returns a Promise when called.
    """

    class Factory:
        @classmethod
        @promising.function
        async def create_name(cls) -> str:
            return cls.__name__

    obj = Factory()
    result = obj.create_name()
    assert isinstance(result, promising.Promise)
    assert await result == "Factory"


async def test_class_method_receives_cls_via_class() -> None:
    """
    The class method coroutine receives the correct class when
    accessed through the class.
    """

    class Base:
        @classmethod
        @promising.function
        async def get_class_name(cls) -> str:
            return cls.__name__

    class Child(Base):
        pass

    assert await Base.get_class_name() == "Base"
    assert await Child.get_class_name() == "Child"


async def test_class_method_receives_cls_via_instance() -> None:
    """
    The class method coroutine receives the correct class when
    accessed through an instance.
    """

    class Base:
        @classmethod
        @promising.function
        async def get_class_name(cls) -> str:
            return cls.__name__

    class Child(Base):
        pass

    assert await Base().get_class_name() == "Base"
    assert await Child().get_class_name() == "Child"


async def test_class_method_forwards_args() -> None:
    """
    Extra arguments are forwarded to the classmethod coroutine
    alongside cls.
    """

    class Formatter:
        @classmethod
        @promising.function
        async def format_value(cls, value: int, *, prefix: str = "") -> str:
            return f"{prefix}{cls.__name__}:{value}"

    assert await Formatter.format_value(42) == "Formatter:42"
    assert await Formatter.format_value(42, prefix=">>") == ">>Formatter:42"


async def test_class_method_with_empty_parens_decorator() -> None:
    """
    @promising.function() with empty parens also works as a
    class method decorator.
    """

    class Factory:
        @classmethod
        @promising.function()
        async def create_name(cls) -> str:
            return cls.__name__

    assert await Factory.create_name() == "Factory"
    assert await Factory().create_name() == "Factory"


async def test_class_method_exception_propagates() -> None:
    """
    An exception raised inside a classmethod coroutine propagates
    through the Promise when awaited.
    """

    class MyClass:
        @classmethod
        @promising.function
        async def failing(cls) -> None:
            raise TypeError("class method error")

    with pytest.raises(TypeError, match="class method error"):
        await MyClass.failing()

    with pytest.raises(TypeError, match="class method error"):
        await MyClass().failing()


# ── Alternative Decorator Ordering ──────────────────────────────────────


async def test_promising_function_on_top_of_staticmethod() -> None:
    """
    Applying @promising.function on top of @staticmethod still works,
    both when called via the class and via an instance.
    """

    class MyClass:
        @promising.function
        @staticmethod
        async def my_method() -> str:
            return "success"

    assert await MyClass.my_method() == "success"
    assert await MyClass().my_method() == "success"


async def test_promising_function_on_top_of_classmethod() -> None:
    """
    Applying @promising.function on top of @classmethod still works,
    both when called via the class and via an instance, and `cls` is
    correctly received in both cases.
    """

    class MyClass:
        @promising.function
        @classmethod
        async def my_method(cls) -> type:
            return cls

    assert await MyClass.my_method() is MyClass
    assert await MyClass().my_method() is MyClass


async def test_promising_function_on_top_of_classmethod_with_args() -> None:
    """
    @promising.function above @classmethod with extra arguments:
    cls and all user-supplied args are forwarded correctly through
    the __func__.__func__ unwrapping path in call(), both when called
    via the class and via an instance.
    """

    class MyClass:
        @promising.function
        @classmethod
        async def my_method(cls, value: int, *, prefix: str = "") -> str:
            return f"{prefix}{cls.__name__}:{value}"

    assert await MyClass.my_method(7) == "MyClass:7"
    assert await MyClass.my_method(7, prefix=">>") == ">>MyClass:7"
    assert await MyClass().my_method(7) == "MyClass:7"
    assert await MyClass().my_method(7, prefix=">>") == ">>MyClass:7"


async def test_promising_function_called_with_parens_on_static_and_class() -> None:
    """
    Smoke test: @promising.function() with empty parens (parameterized /
    _decorator branch) above @staticmethod and @classmethod.  Calls from
    the class and from an instance must both produce the correct result.
    """

    class MyClass:
        @promising.function()
        @staticmethod
        async def static_add(a: int, b: int) -> int:
            return a + b

        @promising.function()
        @classmethod
        async def class_name(cls) -> str:
            return cls.__name__

    # staticmethod via class and instance
    assert await MyClass.static_add(3, 4) == 7
    assert await MyClass().static_add(3, 4) == 7

    # classmethod via class and instance
    assert await MyClass.class_name() == "MyClass"
    assert await MyClass().class_name() == "MyClass"
