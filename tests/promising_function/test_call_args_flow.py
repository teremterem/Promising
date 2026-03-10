"""
Tests that verify what arguments flow through
``PromisingFunction.__call__`` for every
combination of method type, decorator ordering, and access
pattern (via class vs via instance).

Each test spies on ``PromisingFunction.__call__`` using
``unittest.mock.patch.object`` on the **class** to capture the
exact positional args without affecting behaviour.

NOTE: patching ``__call__`` on an *instance* does not work
because Python resolves dunder methods on the type, not the
instance (the data-model looks up ``type(obj).__call__``).

Key finding: both decorator orderings produce identical args
in ``__call__()``:
- Instance methods: ``(instance, <user_args>)``
- Classmethods: ``(cls, <user_args>)``
- Staticmethods: ``(<user_args>)``
"""

from unittest.mock import MagicMock, patch

import pytest

import promising

# ── fixtures ─────────────────────────────────────────────────


@pytest.fixture()
def spy_on_call():
    """Spy on ``PromisingFunction.__call__`` at the class level."""
    original = promising.PromisingFunction.__call__
    spy = MagicMock()

    def wrapper(self, *a, **kw):
        spy(*a, **kw)
        return original(self, *a, **kw)

    with patch.object(promising.PromisingFunction, "__call__", wrapper):
        yield spy


# ── Instance method ──────────────────────────────────────────


async def test_instance_method_via_instance(spy_on_call):
    """
    Instance method called on an instance: ``__call__()``
    receives ``(instance, <user_arg>)``.
    """

    class MyClass:
        @promising.function
        async def method(self, x: int) -> int:
            return x

    obj = MyClass()
    result = obj.method(42)
    spy_on_call.assert_called_once_with(obj, 42)
    assert await result == 42


async def test_instance_method_via_instance__not_decorated(spy_on_call):
    """
    Instance method called on an instance (but promising.function
    is applied to a method that is already bound to the instance):
    ``__call__()`` receives ``(<user_arg>,)``.
    """

    class MyClass:
        async def method(self, x: int) -> int:
            return x

    obj = MyClass()
    pf = promising.function(obj.method)
    result = pf(42)
    # With this setup the obj does not go through the
    # PromisingFunction, it's already bound with the method
    spy_on_call.assert_called_once_with(42)
    assert await result == 42


# ── Classmethods ─────────────────────────────────────────────


async def test_classmethod_via_class__classmethod_on_top(spy_on_call):
    """
    ``@classmethod`` on top, called via the class:
    ``__call__()`` receives ``(cls, <user_arg>)``.
    """

    class MyClass:
        @classmethod
        @promising.function
        async def method(cls, x: int) -> int:
            return x

    result = MyClass.method(42)
    spy_on_call.assert_called_once_with(MyClass, 42)
    assert await result == 42


async def test_classmethod_via_class__promising_on_top(spy_on_call):
    """
    ``@promising.function`` on top, called via the class:
    ``__call__()`` receives ``(cls, <user_arg>)``.
    """

    class MyClass:
        @promising.function
        @classmethod
        async def method(cls, x: int) -> int:
            return x

    result = MyClass.method(42)
    spy_on_call.assert_called_once_with(MyClass, 42)
    assert await result == 42


async def test_classmethod_via_instance__classmethod_on_top(spy_on_call):
    """
    ``@classmethod`` on top, called via an instance:
    ``__call__()`` receives ``(cls, <user_arg>)``.
    """

    class MyClass:
        @classmethod
        @promising.function
        async def method(cls, x: int) -> int:
            return x

    result = MyClass().method(42)
    spy_on_call.assert_called_once_with(MyClass, 42)
    assert await result == 42


async def test_classmethod_via_instance__promising_on_top(spy_on_call):
    """
    ``@promising.function`` on top, called via an instance:
    ``__call__()`` receives ``(cls, <user_arg>)``.
    """

    class MyClass:
        @promising.function
        @classmethod
        async def method(cls, x: int) -> int:
            return x

    result = MyClass().method(42)
    spy_on_call.assert_called_once_with(MyClass, 42)
    assert await result == 42


# ── Staticmethods ────────────────────────────────────────────


async def test_staticmethod_via_class__staticmethod_on_top(spy_on_call):
    """
    ``@staticmethod`` on top, called via the class:
    ``__call__()`` receives ``(<user_arg>,)`` only.
    """

    class MyClass:
        @staticmethod
        @promising.function
        async def method(x: int) -> int:
            return x

    result = MyClass.method(42)
    spy_on_call.assert_called_once_with(42)
    assert await result == 42


async def test_staticmethod_via_class__promising_on_top(spy_on_call):
    """
    ``@promising.function`` on top, called via the class:
    ``__call__()`` receives ``(<user_arg>,)`` only.
    """

    class MyClass:
        @promising.function
        @staticmethod
        async def method(x: int) -> int:
            return x

    result = MyClass.method(42)
    spy_on_call.assert_called_once_with(42)
    assert await result == 42


async def test_staticmethod_via_instance__staticmethod_on_top(spy_on_call):
    """
    ``@staticmethod`` on top, called via an instance:
    ``__call__()`` receives ``(<user_arg>,)`` only.
    """

    class MyClass:
        @staticmethod
        @promising.function
        async def method(x: int) -> int:
            return x

    result = MyClass().method(42)
    spy_on_call.assert_called_once_with(42)
    assert await result == 42


async def test_staticmethod_via_instance__promising_on_top(spy_on_call):
    """
    ``@promising.function`` on top, called via an instance:
    ``__call__()`` receives ``(<user_arg>,)`` only.
    """

    class MyClass:
        @promising.function
        @staticmethod
        async def method(x: int) -> int:
            return x

    result = MyClass().method(42)
    spy_on_call.assert_called_once_with(42)
    assert await result == 42
