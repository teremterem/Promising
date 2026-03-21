import asyncio
import functools
import inspect
from asyncio import AbstractEventLoop
from types import FunctionType, MethodType
from typing import Any

from promising.errors import DecorationError, SyncUsageError
from promising.sentinels import UNCHANGED
from promising.types import CallableType, DecoratableFunctionType


def is_func_or_method_async(func_or_method: DecoratableFunctionType) -> bool:
    # We use `iscoroutinefunction()` from `asyncio` rather than `inspect`
    # because asyncio's version also checks for the `_is_coroutine` marker,
    # which allows it to recognize objects like `PromisingFunction` as
    # coroutine functions
    if isinstance(func_or_method, (classmethod, staticmethod)):
        return asyncio.iscoroutinefunction(func_or_method.__func__)
    return asyncio.iscoroutinefunction(func_or_method)


def assert_no_sync_usage_deadlock(loop_of_future: AbstractEventLoop, message: str) -> None:
    try:
        running_loop = asyncio.get_running_loop()
    except RuntimeError:
        running_loop = None

    if running_loop is loop_of_future:
        raise SyncUsageError(message)


def resolve_namespace(*, provided_explicitly: str | None, named_object_fallback: Any | None) -> str | None:
    if provided_explicitly is not None:
        return provided_explicitly

    if named_object_fallback is None:
        return None

    prefix = resolve_module_name(named_object_fallback)
    prefix = f"{prefix}::" if prefix else ""

    if hasattr(named_object_fallback, "__qualname__"):
        return f"{prefix}{named_object_fallback.__qualname__}"

    if hasattr(named_object_fallback, "__name__"):
        return f"{prefix}{named_object_fallback.__name__}"

    return f"{prefix}{named_object_fallback}"


def resolve_module_name(obj: Any) -> str | None:
    module = getattr(obj, "__module__", None)
    if module is not None:
        return module

    # Coroutine and async-generator objects carry __qualname__ (inherited
    # from the function that created them) but NOT __module__.  However,
    # they do hold a reference to their compiled code object via cr_code
    # (coroutines) or ag_code (async generators).  The code object's
    # co_filename lets inspect.getmodule() map back to the originating
    # module.
    code = getattr(obj, "cr_code", None) or getattr(obj, "ag_code", None)
    if code is None:
        return None

    # The reason we are giving inspect.getmodule() the code object is because
    # it does not work on coroutines directly.
    code_module = inspect.getmodule(code)
    if code_module is None:
        return None

    return code_module.__name__


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
