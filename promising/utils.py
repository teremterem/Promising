import functools
import inspect
from types import FunctionType, MethodType
from typing import Any

from promising.errors import DecorationError
from promising.types import CallableType, DecoratableFunctionType


def resolve_namespace(*, provided_explicitly: str | None, named_object_fallback: Any) -> str:
    if provided_explicitly:
        return provided_explicitly

    if named_object_fallback is None:
        return None

    if hasattr(named_object_fallback, "__qualname__"):
        return named_object_fallback.__qualname__

    if hasattr(named_object_fallback, "__name__"):
        return named_object_fallback.__name__

    return str(named_object_fallback)


class DecoratorSupport:
    __wrapped__: DecoratableFunctionType

    def __init__(self, func_or_method: DecoratableFunctionType | None) -> None:
        self.__wrapped__ = None
        if func_or_method is None:
            # For the constructor it is OK not to have a function or method to
            # decorate - this would mean that the decorator is being used as a
            # decorator with parameters.
            return
        self._update_wrapper(func_or_method)

    def _update_wrapper(self, func_or_method: Any) -> None:
        if func_or_method is None:
            raise DecorationError("The function or method to decorate was not provided")

        if not callable(func_or_method) and not isinstance(func_or_method, classmethod):
            # (`MethodType` and `staticmethod` are callable by themselves)
            raise DecorationError(
                "Expected a function, a method, a staticmethod, or a "
                f"classmethod, but `{type(func_or_method)}` was given instead"
            )
        # This also sets `self.__wrapped__` to equal `func_or_method`
        functools.update_wrapper(self, func_or_method)

    def __get__(self, obj: Any, objtype: type | None = None) -> CallableType:
        # TODO Explain in a docstring what this descriptor does and why. (This
        #  happens BEFORE decorator is executed, "outside of it", in other
        #  words.)
        if isinstance(self.__wrapped__, classmethod):
            # Classmethod: bind the class as the first argument regardless of
            # whether the lookup is via the class or an instance.
            cls = objtype if obj is None else type(obj)
            return MethodType(self, cls)
        if obj is not None and isinstance(self.__wrapped__, FunctionType):
            # Regular instance method: bind the instance as the first argument.
            return MethodType(self, obj)
        # Intentionally return unbound self for all remaining cases (e.g. when
        # self.__wrapped__ is a staticmethod object). This is safe because
        # call() invokes self.__wrapped__(*args, **kwargs) directly, and
        # staticmethod objects are callable without going through the
        # descriptor protocol since Python 3.10 (bpo-43682). No binding is
        # required or desired here.
        return self

    @property
    def _wrapped_as_callable(self) -> CallableType:
        if isinstance(self.__wrapped__, classmethod):
            # self.__wrapped__ is a classmethod object; args[0] is the
            # class, already prepended by MethodType in __get__.
            # classmethod objects are not directly callable, so we reach
            # through to the underlying function.
            # TODO Turn the comment above into a docstring
            return self.__wrapped__.__func__
        return self.__wrapped__

    @property
    def _is_wrapped_async(self) -> bool:
        """
        Check if the wrapped function or method is a coroutine function or
        method.
        """
        if isinstance(self.__wrapped__, (classmethod, staticmethod)):
            return inspect.iscoroutinefunction(self.__wrapped__.__func__)
        return inspect.iscoroutinefunction(self.__wrapped__)
