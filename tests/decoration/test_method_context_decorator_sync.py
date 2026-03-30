import pytest

import promising


async def test_instance_method_activates_context() -> None:
    """
    @promising.context on a sync instance method: the context
    is active inside the method body and `self` is received.
    """

    class Greeter:
        @promising.context
        def greet(self) -> str:
            assert promising.get_active_context() is not None
            return "hello"

    assert Greeter().greet() == "hello"


async def test_instance_method_receives_self() -> None:
    """
    The sync method receives the correct `self` instance.
    """

    class Counter:
        def __init__(self, value: int) -> None:
            self.value = value

        @promising.context
        def get_value(self) -> int:
            return self.value

    obj1 = Counter(42)
    obj2 = Counter(100)
    obj3 = Counter(200)
    assert obj1.get_value() == 42
    assert obj2.get_value() == 100
    assert obj3.get_value() == 200
    assert obj3.get_value() == 200
    assert obj1.get_value() == 42
    assert obj2.get_value() == 100


async def test_instance_method_forwards_args() -> None:
    """
    Positional and keyword arguments are forwarded to
    the sync instance method correctly.
    """

    class Adder:
        def __init__(self, base: int) -> None:
            self.base = base

        @promising.context
        def add(self, x: int, *, multiplier: int = 2) -> int:
            return (self.base + x) * multiplier

    obj = Adder(10)
    assert obj.add(5) == 30
    assert obj.add(5, multiplier=3) == 45


async def test_instance_method_exception_propagates() -> None:
    """
    An exception raised inside a sync instance method
    propagates to the caller.
    """

    class MyClass:
        @promising.context
        def failing(self) -> None:
            raise ValueError("instance method error")

    with pytest.raises(ValueError, match="instance method error"):
        MyClass().failing()

    # Verify context is properly deactivated after exception
    # TODO Apply this check to other tests as well ? Make it more elaborate ?
    #  Get rid of it ?
    #  https://github.com/teremterem/Promising/pull/89#discussion_r3008493421
    assert promising.get_active_context(raise_if_none=False) is None


async def test_instance_method_with_parens() -> None:
    class MyClass:
        @promising.context()
        def greet(self) -> str:
            return "parens-method"

    assert MyClass().greet() == "parens-method"


async def test_static_method_decorator() -> None:
    """
    @promising.context below @staticmethod: the context is
    active and the function works via class and instance access.
    """

    class MathUtils:
        @staticmethod
        @promising.context
        def double(x: int) -> int:
            assert promising.get_active_context() is not None
            return x * 2

    assert MathUtils.double(7) == 14
    assert MathUtils().double(7) == 14


async def test_static_method_exception_propagates() -> None:
    """
    An exception raised inside a static method decorated with
    @promising.context propagates to the caller.
    """

    class MyClass:
        @staticmethod
        @promising.context
        def failing() -> None:
            raise RuntimeError("static method error")

    with pytest.raises(RuntimeError, match="static method error"):
        MyClass.failing()

    with pytest.raises(RuntimeError, match="static method error"):
        MyClass().failing()


async def test_class_method_decorator() -> None:
    """
    @promising.context below @classmethod: the context is
    active and `cls` is received correctly.
    """

    class Factory:
        @classmethod
        @promising.context
        def create_name(cls) -> str:
            assert promising.get_active_context() is not None
            return cls.__name__

    assert Factory.create_name() == "Factory"
    assert Factory().create_name() == "Factory"


async def test_class_method_receives_cls_via_inheritance() -> None:
    """
    Sync classmethod receives the correct class through inheritance.
    """

    class Base:
        @classmethod
        @promising.context
        def get_class_name(cls) -> str:
            return cls.__name__

    class Child(Base):
        pass

    assert Base.get_class_name() == "Base"
    assert Base().get_class_name() == "Base"
    assert Child.get_class_name() == "Child"
    assert Child().get_class_name() == "Child"


async def test_class_method_forwards_args() -> None:
    """
    Extra arguments are forwarded to the sync classmethod
    alongside cls.
    """

    class Formatter:
        @classmethod
        @promising.context
        def format_value(cls, value: int, *, prefix: str = "") -> str:
            return f"{prefix}{cls.__name__}:{value}"

    assert Formatter.format_value(42) == "Formatter:42"
    assert Formatter.format_value(42, prefix=">>") == ">>Formatter:42"
    assert Formatter().format_value(42) == "Formatter:42"
    assert Formatter().format_value(42, prefix=">>") == ">>Formatter:42"


async def test_class_method_exception_propagates() -> None:
    """
    An exception raised inside a classmethod decorated with
    @promising.context propagates to the caller.
    """

    class MyClass:
        @classmethod
        @promising.context
        def failing(cls) -> None:
            raise TypeError("class method error")

    with pytest.raises(TypeError, match="class method error"):
        MyClass.failing()

    with pytest.raises(TypeError, match="class method error"):
        MyClass().failing()


async def test_context_on_top_of_staticmethod() -> None:
    """
    Applying @promising.context on top of @staticmethod still
    works, both when called via the class and via an instance.
    """

    class MyClass:
        @promising.context
        @staticmethod
        def my_method() -> str:
            return "ok"

    assert MyClass.my_method() == "ok"
    assert MyClass().my_method() == "ok"


async def test_context_on_top_of_classmethod() -> None:
    """
    Applying @promising.context on top of @classmethod still
    works, both when called via the class and via an instance,
    and `cls` is correctly received in both cases.
    """

    class MyClass:
        @promising.context
        @classmethod
        def my_method(cls) -> type:
            return cls

    assert MyClass.my_method() is MyClass
    assert MyClass().my_method() is MyClass


async def test_context_on_top_of_classmethod_with_args() -> None:
    """
    @promising.context above @classmethod with extra arguments:
    cls and all user-supplied args are forwarded correctly.
    """

    class MyClass:
        @promising.context
        @classmethod
        def my_method(cls, value: int, *, prefix: str = "") -> str:
            return f"{prefix}{cls.__name__}:{value}"

    assert MyClass.my_method(7) == "MyClass:7"
    assert MyClass.my_method(7, prefix=">>") == ">>MyClass:7"
    assert MyClass().my_method(7) == "MyClass:7"
    assert MyClass().my_method(7, prefix=">>") == ">>MyClass:7"


async def test_context_with_parens_on_top_of_staticmethod() -> None:
    class MyClass:
        @promising.context()
        @staticmethod
        def my_method() -> None: ...

    assert MyClass.my_method() is None
    assert MyClass().my_method() is None


async def test_context_with_parens_on_top_of_classmethod() -> None:
    class MyClass:
        @promising.context()
        @classmethod
        def my_method(cls) -> type:
            return cls

    assert MyClass.my_method() is MyClass
    assert MyClass().my_method() is MyClass
