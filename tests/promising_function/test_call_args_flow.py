"""
Tests that verify what arguments flow through
``PromisingFunction.__call__`` (and thus ``call()``) for every
combination of method type, decorator ordering, and access
pattern (via class vs via instance).

Each test spies on ``pf.call`` using
``unittest.mock.patch.object(..., wraps=...)`` to capture the
exact positional args without affecting behaviour.

Key finding: both decorator orderings produce identical args
in ``call()``:
- Instance methods: ``(instance, <user_args>)``
- Classmethods: ``(cls, <user_args>)``
- Staticmethods: ``(<user_args>)``
"""

from unittest.mock import patch

import promising

# ── helpers ──────────────────────────────────────────────────


def _get_promising_function(cls, name):
    """
    Return the ``PromisingFunction`` instance for *name*
    from *cls.__dict__*, unwrapping ``classmethod`` /
    ``staticmethod`` wrappers when necessary.
    """
    raw = cls.__dict__[name]
    if isinstance(raw, (classmethod, staticmethod)):
        return raw.__func__
    return raw


# ── Instance method ──────────────────────────────────────────


async def test_instance_method_via_instance():
    """
    Instance method called on an instance: ``call()``
    receives ``(instance, <user_arg>)``.
    """

    class MyClass:
        @promising.function
        async def method(self, x: int) -> int:
            return x

    obj = MyClass()
    pf = _get_promising_function(MyClass, "method")

    with patch.object(pf, "call", wraps=pf.call) as spy:
        result = obj.method(42)
        spy.assert_called_once_with(obj, 42)
        assert await result == 42


async def test_instance_method_via_instance__not_decorated():
    """
    Instance method called on an instance (but promising.function
    is applied to a method that is already bound to the instance):
    ``call()`` receives ``(<user_arg>,)``.
    """

    class MyClass:
        async def method(self, x: int) -> int:
            return x

    obj = MyClass()
    pf = promising.function(obj.method)

    with patch.object(pf, "call", wraps=pf.call) as spy:
        result = pf(42)
        # With this setup the obj does not go through the
        # PromisingFunction, it's already bound with the method
        spy.assert_called_once_with(42)
        assert await result == 42


# ── Classmethods ─────────────────────────────────────────────


async def test_classmethod_via_class__classmethod_on_top():
    """
    ``@classmethod`` on top, called via the class:
    ``call()`` receives ``(cls, <user_arg>)``.
    """

    class MyClass:
        @classmethod
        @promising.function
        async def method(cls, x: int) -> int:
            return x

    pf = _get_promising_function(MyClass, "method")

    with patch.object(pf, "call", wraps=pf.call) as spy:
        result = MyClass.method(42)
        spy.assert_called_once_with(MyClass, 42)
        assert await result == 42


async def test_classmethod_via_class__promising_on_top():
    """
    ``@promising.function`` on top, called via the class:
    ``call()`` receives ``(cls, <user_arg>)``.
    """

    class MyClass:
        @promising.function
        @classmethod
        async def method(cls, x: int) -> int:
            return x

    pf = _get_promising_function(MyClass, "method")

    with patch.object(pf, "call", wraps=pf.call) as spy:
        result = MyClass.method(42)
        spy.assert_called_once_with(MyClass, 42)
        assert await result == 42


async def test_classmethod_via_instance__classmethod_on_top():
    """
    ``@classmethod`` on top, called via an instance:
    ``call()`` receives ``(cls, <user_arg>)``.
    """

    class MyClass:
        @classmethod
        @promising.function
        async def method(cls, x: int) -> int:
            return x

    pf = _get_promising_function(MyClass, "method")

    with patch.object(pf, "call", wraps=pf.call) as spy:
        result = MyClass().method(42)
        spy.assert_called_once_with(MyClass, 42)
        assert await result == 42


async def test_classmethod_via_instance__promising_on_top():
    """
    ``@promising.function`` on top, called via an instance:
    ``call()`` receives ``(cls, <user_arg>)``.
    """

    class MyClass:
        @promising.function
        @classmethod
        async def method(cls, x: int) -> int:
            return x

    pf = _get_promising_function(MyClass, "method")

    with patch.object(pf, "call", wraps=pf.call) as spy:
        result = MyClass().method(42)
        spy.assert_called_once_with(MyClass, 42)
        assert await result == 42


# ── Staticmethods ────────────────────────────────────────────


async def test_staticmethod_via_class__staticmethod_on_top():
    """
    ``@staticmethod`` on top, called via the class:
    ``call()`` receives ``(<user_arg>,)`` only.
    """

    class MyClass:
        @staticmethod
        @promising.function
        async def method(x: int) -> int:
            return x

    pf = _get_promising_function(MyClass, "method")

    with patch.object(pf, "call", wraps=pf.call) as spy:
        result = MyClass.method(42)
        spy.assert_called_once_with(42)
        assert await result == 42


async def test_staticmethod_via_class__promising_on_top():
    """
    ``@promising.function`` on top, called via the class:
    ``call()`` receives ``(<user_arg>,)`` only.
    """

    class MyClass:
        @promising.function
        @staticmethod
        async def method(x: int) -> int:
            return x

    pf = _get_promising_function(MyClass, "method")

    with patch.object(pf, "call", wraps=pf.call) as spy:
        result = MyClass.method(42)
        spy.assert_called_once_with(42)
        assert await result == 42


async def test_staticmethod_via_instance__staticmethod_on_top():
    """
    ``@staticmethod`` on top, called via an instance:
    ``call()`` receives ``(<user_arg>,)`` only.
    """

    class MyClass:
        @staticmethod
        @promising.function
        async def method(x: int) -> int:
            return x

    pf = _get_promising_function(MyClass, "method")

    with patch.object(pf, "call", wraps=pf.call) as spy:
        result = MyClass().method(42)
        spy.assert_called_once_with(42)
        assert await result == 42


async def test_staticmethod_via_instance__promising_on_top():
    """
    ``@promising.function`` on top, called via an instance:
    ``call()`` receives ``(<user_arg>,)`` only.
    """

    class MyClass:
        @promising.function
        @staticmethod
        async def method(x: int) -> int:
            return x

    pf = _get_promising_function(MyClass, "method")

    with patch.object(pf, "call", wraps=pf.call) as spy:
        result = MyClass().method(42)
        spy.assert_called_once_with(42)
        assert await result == 42
