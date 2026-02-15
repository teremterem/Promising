import functools
from collections.abc import Callable
from typing import Any, Generic

from promising.errors import PromisingFunctionNotCallableError
from promising.promise import Promise
from promising.sentinels import NOT_SET, Sentinel
from promising.types import T_co


class PromisingFunction(Generic[T_co]):
    original: Callable[..., T_co] | type | None = None

    def __init__(
        self,
        func_or_class: Callable[..., T_co] | type | None = None,
        *,
        start_soon: bool | Sentinel = NOT_SET,
        make_parent_wait: bool | Sentinel = NOT_SET,
        config_inheritable: bool | Sentinel = NOT_SET,
    ):
        self.original = func_or_class

        # TODO Is maintaining these attributes here like this directly a good
        #  idea ?
        self.start_soon = start_soon
        self.make_parent_wait = make_parent_wait
        self.config_inheritable = config_inheritable

    def __call__(
        self,
        *args: Any,
        **kwargs: Any,
        # TODO Add PromisingConfig parameters ?
    ) -> Promise[T_co]:
        return self.call(*args, **kwargs)

    def call(
        self,
        *args: Any,
        **kwargs: Any,
        # TODO Add PromisingConfig parameters ?
    ) -> Promise[T_co]:
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

        # TODO TODO TODO Create a PromisingConfig object beforehand, so its
        #  validations are passed before we create any coroutines and get the
        #  `Coroutine was not awaited` warning as a result of such validation
        #  errors.

        # Assume the function is asynchronous and get the coroutine out of it
        # TODO TODO TODO Support synchronous functions too. (How to identify
        #  them without trying to get the coroutine, thought ?)
        coro = actual_func()

        # TODO TODO TODO Introduce "backends"
        return Promise[T_co](
            coro=coro,
            start_soon=self.start_soon,
            make_parent_wait=self.make_parent_wait,
            config_inheritable=self.config_inheritable,
        )


def function(
    func_or_class: Callable[..., T_co] | type | None = None,
    *,
    start_soon: bool | Sentinel = NOT_SET,
    make_parent_wait: bool | Sentinel = NOT_SET,
    config_inheritable: bool | Sentinel = NOT_SET,
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
      other kinds of databases or caches that can handle the data sturctures.
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
                make_parent_wait=make_parent_wait,
                config_inheritable=config_inheritable,
            )

        return _decorator

    # The decorator was used either without arguments or as a direct function
    # call
    return PromisingFunction[T_co](
        func_or_class,
        start_soon=start_soon,
        make_parent_wait=make_parent_wait,
        config_inheritable=config_inheritable,
    )
