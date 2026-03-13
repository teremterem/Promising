import asyncio
import functools
import inspect
from asyncio import AbstractEventLoop
from types import FunctionType, MethodType
from typing import Any

from promising.errors import DecorationError, SyncUsageError
from promising.sentinels import NOT_SET, Sentinel
from promising.types import CallableType, DecoratableFunctionType


def is_func_or_method_async(func_or_method: DecoratableFunctionType) -> bool:
    if isinstance(func_or_method, (classmethod, staticmethod)):
        return inspect.iscoroutinefunction(func_or_method.__func__)
    return inspect.iscoroutinefunction(func_or_method)


def assert_no_sync_usage_deadlock(loop_of_future: AbstractEventLoop, message: str) -> None:
    try:
        running_loop = asyncio.get_running_loop()
    except RuntimeError:
        running_loop = None

    if running_loop is loop_of_future:
        raise SyncUsageError(message)


def resolve_namespace(*, provided_explicitly: str | Sentinel, named_object_fallback: Any | Sentinel) -> str | Sentinel:
    if provided_explicitly is not NOT_SET:
        return provided_explicitly

    if named_object_fallback is NOT_SET:
        return NOT_SET

    module = getattr(named_object_fallback, "__module__", None)
    prefix = f"{module}::" if module else ""

    if hasattr(named_object_fallback, "__qualname__"):
        return f"{prefix}{named_object_fallback.__qualname__}"

    if hasattr(named_object_fallback, "__name__"):
        return f"{prefix}{named_object_fallback.__name__}"

    return f"{prefix}{named_object_fallback}" if prefix else str(named_object_fallback)


class DecoratorSupport:
    """
    Base class that provides decorator and descriptor plumbing for
    ``promising.context`` and ``PromisingFunction``.

    Handles ``functools.update_wrapper`` bookkeeping and implements
    ``__get__`` so that the decorator works correctly on instance
    methods, ``@classmethod``, and ``@staticmethod``.
    """

    __wrapped__: DecoratableFunctionType | None
    namespace: str | Sentinel

    def __init__(
        self,
        func_or_method: DecoratableFunctionType | Sentinel,  # can be NOT_SET
        *,
        namespace: str | Sentinel,  # can be NOT_SET
    ) -> None:
        self.__wrapped__ = None
        self.namespace = namespace
        if func_or_method is NOT_SET:
            # For the constructor it is OK not to have a function or method to
            # decorate - this would mean that the decorator is being used as a
            # decorator with parameters.
            return
        self._update_wrapper(func_or_method)

    def _update_wrapper(self, func_or_method: Any) -> None:
        if func_or_method is NOT_SET:
            raise DecorationError("The function or method to decorate was not provided")

        if not callable(func_or_method) and not isinstance(func_or_method, classmethod):
            # (`MethodType` and `staticmethod` are callable by themselves)
            raise DecorationError(
                "Expected a function, a method, a staticmethod, or a "
                f"classmethod, but `{type(func_or_method)}` was given instead"
            )
        # This also sets `self.__wrapped__` to equal `func_or_method`
        functools.update_wrapper(self, func_or_method)

        # Update the namespace to the new function or method (if it wasn't set
        # explicitly)
        self.namespace = resolve_namespace(
            provided_explicitly=self.namespace,
            named_object_fallback=func_or_method,
        )

    def __get__(self, obj: Any, objtype: type | None = None) -> CallableType:
        """
        Descriptor hook that binds this wrapper to the appropriate first
        argument before the decorated function is called.

        For classmethods, binds the class; for regular instance methods,
        binds the instance; for staticmethods (and class-level access of
        plain functions), returns the wrapper unbound.
        """
        if isinstance(self.__wrapped__, classmethod):
            cls = objtype if obj is None else type(obj)
            return MethodType(self, cls)
        if obj is not None and isinstance(self.__wrapped__, FunctionType):
            return MethodType(self, obj)
        # Intentionally return unbound self for all remaining cases (e.g. when
        # self.__wrapped__ is a staticmethod object). This is safe because
        # call() invokes self.__wrapped__(*args, **kwargs) directly, and
        # staticmethod objects are callable without going through the
        # descriptor protocol. No binding is required or desired here.
        return self

    @property
    def _wrapped_as_callable(self) -> CallableType:
        """
        Return the wrapped object in a directly callable form.

        For classmethod objects, returns the underlying ``__func__`` because
        classmethod descriptors are not directly callable (the class argument
        is already prepended by :class:`~types.MethodType` in ``__get__``).
        For all other wrapped objects, returns ``__wrapped__`` as-is.
        """
        if isinstance(self.__wrapped__, classmethod):
            return self.__wrapped__.__func__
        return self.__wrapped__
