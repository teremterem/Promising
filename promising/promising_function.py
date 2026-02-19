import types
from collections.abc import Callable
from typing import Any, Generic

from promising.promise import Promise
from promising.sentinels import INHERIT, NOT_SET, Sentinel
from promising.types import T_co


def function(
    func_or_method: Callable[..., T_co] | None = None,
    *,
    start_soon: bool | Sentinel = NOT_SET,
    children_start_soon_by_default: bool | Sentinel = NOT_SET,
    everything_starts_soon_by_default: bool | Sentinel = INHERIT,
) -> "PromisingFunction[T_co] | Callable[..., T_co]":
    """
    TODO Finalize this docstring by explaining why we need the
     PromisingFunction wrapper at all. List the advantages it provides:

    - Decorated functions always return Promises.
    - Returned Promises can be awaited any number of times without
      re-executing the function.
    - TODO Should input parameters always be passed as promises as well ?
       All of them ? Only those, that were typehinted as `Promise` explicitly ?
    - Both, input parameters and results are strictly serializable and are
      serialized/deserialized in transit
    - All these interactions are stored/storable in graph databases, or any
      other kinds of databases or caches that can handle the data structures.
    """
    # TODO Stop returning PromisingFunction, return another function instead
    #  (just "instrument" it with some attribute to access PromisingFunction
    #  object ?)
    # TODO Allow this decorator to be used as a method decorator as well.
    # TODO Or is it impossible ? (Will we want to have some sort of function
    #  registry to find and call functions dynamically ?)
    # TODO Make sure to use `get_type_hints()` instead of `__annotations__` to
    #  resolve postponed type hints correctly as well, when you implement
    #  input params as Promises.
    if func_or_method is None:
        # The decorator was used with arguments
        # TODO Same thing about a comment for the return type as above
        def _decorator(f_or_m: Callable[..., T_co]) -> "PromisingFunction[T_co] | Callable[..., T_co]":
            return PromisingFunction[T_co](
                f_or_m,
                start_soon=start_soon,
                children_start_soon_by_default=children_start_soon_by_default,
                everything_starts_soon_by_default=everything_starts_soon_by_default,
            )

        return _decorator

    # The decorator was used either without arguments or as a direct function
    # call
    return PromisingFunction[T_co](
        func_or_method,
        start_soon=start_soon,
        children_start_soon_by_default=children_start_soon_by_default,
        everything_starts_soon_by_default=everything_starts_soon_by_default,
    )


class PromisingFunction(Generic[T_co]):
    __func__: Callable[..., T_co]

    # TODO Explain the idea behind parent-child relationships between Promise
    #  objects with respect to PromisingFunction calls

    def __init__(
        self,
        func_or_method: Callable[..., T_co],
        *,
        start_soon: bool | Sentinel = NOT_SET,
        children_start_soon_by_default: bool | Sentinel = NOT_SET,
        everything_starts_soon_by_default: bool | Sentinel = INHERIT,
    ) -> None:
        self.__func__ = func_or_method
        self.start_soon = start_soon
        self.children_start_soon_by_default = children_start_soon_by_default
        self.everything_starts_soon_by_default = everything_starts_soon_by_default

    def __get__(self, obj: Any, objtype: type | None = None) -> "PromisingFunction[T_co]":
        # Descriptor protocol support so PromisingFunction works as a method
        # decorator inside a class body.
        if isinstance(self.__func__, staticmethod):
            # Static methods don't bind to instance or class - return as-is
            # so that call() can unwrap __func__ itself.
            return self
        if obj is None:
            # Class-level attribute access (e.g. MyClass.my_method).
            if isinstance(self.__func__, classmethod):
                # Bind the class so the underlying coroutine receives cls as
                # its first argument.
                bound = self.__func__.__get__(None, objtype)
                return self.__class__(
                    bound,
                    start_soon=self.start_soon,
                    children_start_soon_by_default=self.children_start_soon_by_default,
                    everything_starts_soon_by_default=self.everything_starts_soon_by_default,
                )
            return self
        # Instance-level attribute access (e.g. obj.my_method).
        if isinstance(self.__func__, classmethod):
            # Bind the class (not the instance) - same semantics as the
            # built-in classmethod descriptor.
            bound = self.__func__.__get__(obj, objtype if objtype is not None else type(obj))
            return self.__class__(
                bound,
                start_soon=self.start_soon,
                children_start_soon_by_default=self.children_start_soon_by_default,
                everything_starts_soon_by_default=self.everything_starts_soon_by_default,
            )
        # Regular instance method: create a bound method so that `obj` is
        # automatically prepended as the first argument on every call.
        return types.MethodType(self, obj)  # type: ignore[return-value]

    def __call__(
        self,
        *args: Any,
        **kwargs: Any,
    ) -> Promise[T_co]:
        # TODO Add start_soon and children_start_soon_by_default parameters
        #  here too. They should take precedence over the ones
        #  passed to the PromisingFunction constructor.
        return self.call(*args, **kwargs)

    def call(
        self,
        *args: Any,
        **kwargs: Any,
    ) -> Promise[T_co]:
        # TODO Develop a convenient and idiomatic (whatever that would mean)
        #  way of serializing/deserializing the arguments and ensuring
        #  immutability
        # TODO Support synchronous functions too. (How to identify them without
        #  trying to get the coroutine, thought ?)
        coro = self.__func__(*args, **kwargs)

        return Promise[T_co](
            coro=coro,
            start_soon=self.start_soon,
            children_start_soon_by_default=self.children_start_soon_by_default,
            everything_starts_soon_by_default=self.everything_starts_soon_by_default,
        )
