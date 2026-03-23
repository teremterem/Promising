import asyncio
import functools
from types import FunctionType, MethodType
from typing import Any

from promising.errors import DecorationError
from promising.sentinels import UNCHANGED
from promising.types import CallableType, DecoratableFunctionType
from promising.utils import is_func_or_method_async, resolve_namespace


class DecoratorSupport:
    """
    Base class that provides decorator and descriptor plumbing for
    ``promising.context`` and ``PromisingFunction``.

    Handles ``functools.update_wrapper`` bookkeeping and implements
    ``__get__`` so that the decorator works correctly on instance
    methods, ``@classmethod``, and ``@staticmethod``.
    """

    __wrapped__: DecoratableFunctionType | None
    namespace: str | None

    def __init__(
        self,
        func_or_method: DecoratableFunctionType | None,
        *,
        namespace: str | None,
    ) -> None:
        self.__wrapped__ = None
        self._is_wrapped_async = UNCHANGED  # Prevent boolean coercion to None
        self.namespace = namespace
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

        self.namespace = resolve_namespace(
            provided_explicitly=self.namespace,
            named_object_fallback=func_or_method,
        )
        self._is_wrapped_async = is_func_or_method_async(func_or_method)
        if self._is_wrapped_async:
            # A magic marker for `asyncio.iscoroutinefunction()` to recognize
            # the decorator instance itself as a coroutine function too
            self._is_coroutine = asyncio.coroutines._is_coroutine

        # Copy standard wrapper attributes (`__module__`, `__name__`,
        # `__qualname__`, `__doc__`, `__annotations__`) from
        # `func_or_method` onto `self` and set `self.__wrapped__` to
        # `func_or_method`, using `functools.update_wrapper`.
        # NOTE: We pass `updated=()` to skip the default
        # `self.__dict__.update(func_or_method.__dict__)` step. Without
        # this, any matching attribute names in `func_or_method.__dict__`
        # would silently overwrite instance attributes that were already
        # set on `self` (e.g. `namespace`, `children_start_soon`, etc.).
        functools.update_wrapper(self, func_or_method, updated=())

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
