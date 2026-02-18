import functools
from collections.abc import Callable
from typing import Any, Generic

from promising.errors import PromisingFunctionNotCallableError
from promising.promise import Promise
from promising.sentinels import INHERIT, NOT_SET, Sentinel
from promising.types import T_co


class PromisingFunction(Generic[T_co]):
    original: Callable[..., T_co] | type | None = None

    def __init__(
        self,
        func_or_class: Callable[..., T_co] | type | None = None,
        *,
        start_soon: bool | Sentinel = NOT_SET,
        children_start_soon_by_default: bool | Sentinel = NOT_SET,
        everything_starts_soon_by_default: bool | Sentinel = INHERIT,
    ) -> None:
        self.original = func_or_class
        self.start_soon = start_soon
        self.children_start_soon_by_default = children_start_soon_by_default
        self.everything_starts_soon_by_default = everything_starts_soon_by_default

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
        # TODO Add start_soon and children_start_soon_by_default parameters
        #  here too. They should take precedence over the ones
        #  passed to the PromisingFunction constructor.
        if self.original is None:
            raise PromisingFunctionNotCallableError("This PromisingFunction is not callable")

        # TODO Develop a convenient and idiomatic (whatever that would mean)
        #  way of serializing/deserializing the arguments and ensuring
        #  immutability
        if isinstance(self.original, type):
            # It's a class - let's instantiate it
            actual_func = self.original(*args, **kwargs)
        else:
            # Otherwise, assume it is already a function
            actual_func = functools.partial(self.original, *args, **kwargs)

        # Assume the function is asynchronous and get the coroutine out of it
        # TODO Support synchronous functions too. (How to identify them without
        #  trying to get the coroutine, thought ?)
        coro = actual_func()

        return Promise[T_co](
            coro=coro,
            start_soon=self.start_soon,
            children_start_soon_by_default=self.children_start_soon_by_default,
            everything_starts_soon_by_default=self.everything_starts_soon_by_default,
        )


def function(
    func_or_class: Callable[..., T_co] | type | None = None,
    *,
    start_soon: bool | Sentinel = NOT_SET,
    children_start_soon_by_default: bool | Sentinel = NOT_SET,
    everything_starts_soon_by_default: bool | Sentinel = INHERIT,
    # TODO Mention in a comment that the real return type is
    #  `PromisingFunction[T_co]` only (as long as we eventually settle on
    #  it being the case, and not start returning the original function or
    #  class with duck-typed functionality instead)
) -> "PromisingFunction[T_co] | Callable[..., T_co]":
    """
    TODO Finalize this docstring by explaining why we need the
     PromisingFunction wrapper at all. List the advantages it provides:

    - Decorated functions (as well as decorated callable classes) always return
      Promises.
    - Returned Promises can be awaited any number of times without
      re-executing the function or class.
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
    # TODO Also, don't let this decorator be used as a class decorator, allow
    #  it as a method decorator instead.
    # TODO Or is it impossible ? (Will we want to have some sort of function
    #  registry to find and call functions dynamically ?)
    # TODO Make sure to use `get_type_hints()` instead of `__annotations__` to
    #  resolve postponed type hints correctly as well, when you implement
    #  input params as Promises.
    if func_or_class is None:
        # The decorator was used with arguments
        # TODO Same thing about a comment for the return type as above
        def _decorator(f_or_cls: Callable[..., T_co] | type) -> "PromisingFunction[T_co] | Callable[..., T_co]":
            return PromisingFunction[T_co](
                f_or_cls,
                start_soon=start_soon,
                children_start_soon_by_default=children_start_soon_by_default,
                everything_starts_soon_by_default=everything_starts_soon_by_default,
            )

        return _decorator

    # The decorator was used either without arguments or as a direct function
    # call
    return PromisingFunction[T_co](
        func_or_class,
        start_soon=start_soon,
        children_start_soon_by_default=children_start_soon_by_default,
        everything_starts_soon_by_default=everything_starts_soon_by_default,
    )
