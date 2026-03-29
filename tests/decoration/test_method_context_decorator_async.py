import pytest

import promising


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
