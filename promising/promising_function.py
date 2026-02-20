import functools
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
    # TODO Will @classmethod decoration ordering matter for the way caching
    #  works in PromisingFunction ?
    #
    #    @classmethod
    #    @promising.function
    #
    #  versus
    #
    #    @promising.function
    #    @classmethod
    #
    #  Inspect the following things in PromisingFunction.__call__:
    #
    #  - How instance is passed through __call__ when regular instance method
    #    is called (shouldn't be passed through __call__)
    #  - How class is passed through __call__ to classmethod
    #  - The same but with decorators in reverse order
    #  - The same but when classmethod is called via an instance
    #  - The same but when classmethod is called via an instance AND decorators
    #    are in reverse order
    #  - What goes through when staticmethod is called on a class
    #  - What goes through when staticmethod is called via an instance
    #
    #  Do it via tests ? Allow passing in a custom function class to this
    #  decorator or just call PromisingFunction directly in those tests ?

    # TODO Make sure to use `get_type_hints()` instead of `__annotations__` to
    #  resolve postponed type hints correctly, when you implement input params
    #  as Promises.

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
    __wrapped__: Callable[..., T_co] | types.MethodType | classmethod | staticmethod

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
        # This will also set `self.__wrapped__` to `func_or_method`
        functools.update_wrapper(self, func_or_method)

        self.start_soon = start_soon
        self.children_start_soon_by_default = children_start_soon_by_default
        self.everything_starts_soon_by_default = everything_starts_soon_by_default

    def __get__(self, obj: Any, objtype: type | None = None) -> "PromisingFunction[T_co] | types.MethodType":
        if isinstance(self.__wrapped__, classmethod):
            # Classmethod: bind the class as the first argument regardless of
            # whether the lookup is via the class or an instance.
            cls = objtype if obj is None else type(obj)
            return types.MethodType(self, cls)
        if obj is not None and isinstance(self.__wrapped__, types.FunctionType):
            # Regular instance method: bind the instance as the first argument.
            return types.MethodType(self, obj)
        # Intentionally return unbound self for all remaining cases (e.g. when
        # self.__wrapped__ is a staticmethod object). This is safe because
        # call() invokes self.__wrapped__(*args, **kwargs) directly, and
        # staticmethod objects are callable without going through the
        # descriptor protocol since Python 3.10 (bpo-43682). No binding is
        # required or desired here.
        return self

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
        if isinstance(self.__wrapped__, classmethod):
            # self.__wrapped__ is a classmethod object; args[0] is the class,
            # already prepended by MethodType in __get__. classmethod objects
            # are not directly callable, so we reach through to the underlying
            # function.
            coro = self.__wrapped__.__func__(*args, **kwargs)
        else:
            coro = self.__wrapped__(*args, **kwargs)

        return Promise[T_co](
            coro=coro,
            start_soon=self.start_soon,
            children_start_soon_by_default=self.children_start_soon_by_default,
            everything_starts_soon_by_default=self.everything_starts_soon_by_default,
        )
