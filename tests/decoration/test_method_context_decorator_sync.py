import pytest

import promising


async def test_sync_instance_method_activates_context() -> None:
    """
    @promising.context on a sync instance method: the context
    is active inside the method body and `self` is received.
    """

    class Greeter:
        @promising.context
        def greet(self) -> str:
            assert promising.get_active_context() is not None
            return "hello-sync"

    assert Greeter().greet() == "hello-sync"


async def test_sync_instance_method_receives_self() -> None:
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


async def test_sync_instance_method_forwards_args() -> None:
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


async def test_sync_instance_method_exception_propagates() -> None:
    """
    An exception raised inside a sync instance method
    propagates to the caller.
    """

    class MyClass:
        @promising.context
        def failing(self) -> None:
            raise ValueError("sync instance method error")

    with pytest.raises(ValueError, match="sync instance method error"):
        MyClass().failing()


async def test_sync_static_method_decorator() -> None:
    """
    @promising.context below @staticmethod for sync functions.
    """

    class MathUtils:
        @staticmethod
        @promising.context
        def double(x: int) -> int:
            assert promising.get_active_context() is not None
            return x * 2

    assert MathUtils.double(7) == 14
    assert MathUtils().double(7) == 14


async def test_sync_class_method_decorator() -> None:
    """
    @promising.context below @classmethod for sync methods.
    """

    class Factory:
        @classmethod
        @promising.context
        def create_name(cls) -> str:
            assert promising.get_active_context() is not None
            return cls.__name__

    assert Factory.create_name() == "Factory"
    assert Factory().create_name() == "Factory"


async def test_sync_class_method_receives_cls_via_inheritance() -> None:
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
    assert Child.get_class_name() == "Child"
    assert Child().get_class_name() == "Child"
    assert Base().get_class_name() == "Base"
    assert Child().get_class_name() == "Child"
    assert Child.get_class_name() == "Child"


async def test_sync_context_on_top_of_staticmethod() -> None:
    """
    @promising.context on top of @staticmethod for sync functions.
    """

    class MyClass:
        @promising.context
        @staticmethod
        def my_method() -> str:
            return "ok"

    assert MyClass.my_method() == "ok"
    assert MyClass().my_method() == "ok"


async def test_sync_context_on_top_of_classmethod() -> None:
    """
    @promising.context on top of @classmethod for sync functions.
    """

    class MyClass:
        @promising.context
        @classmethod
        def my_method(cls) -> type:
            return cls

    assert MyClass.my_method() is MyClass
    assert MyClass().my_method() is MyClass
