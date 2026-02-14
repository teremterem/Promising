import functools
from collections.abc import Callable
from typing import Any, Generic

from promising.errors import PromiseFunctionNotCallableError
from promising.promise import Promise
from promising.sentinels import NOT_SET, Sentinel
from promising.types import F_co, T_co


class PromisingFunction(Generic[T_co]):
    original_func_or_class: Callable[..., T_co] | type | None = None

    def __init__(
        self,
        func_or_class: Callable[..., T_co] | type | None = None,
        *,
        start_soon: bool | Sentinel = NOT_SET,
        make_parent_wait: bool | Sentinel = NOT_SET,
        config_inheritable: bool | Sentinel = NOT_SET,
    ):
        self.original_func_or_class = func_or_class

        # TODO Is maintaining all these attributes here like this directly a
        #  good idea ?
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
        if self.original_func_or_class is None:
            raise PromiseFunctionNotCallableError("This PromisingFunction is not callable")

        # TODO Develop a convenient and idiomatic (whatever that would mean)
        #  way of serializing/deserializing the arguments and ensuring
        #  immutability
        if isinstance(self.original_func_or_class, type):
            # It's a class - let's instantiate it
            actual_func = self.original_func_or_class(*args, **kwargs)
        else:
            # Otherwise, assume it is already a function
            actual_func = functools.partial(self.original_func_or_class, *args, **kwargs)

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
    func_or_class: Callable[..., F_co] | type | None = None,
    *,
    start_soon: bool | Sentinel = NOT_SET,
    make_parent_wait: bool | Sentinel = NOT_SET,
    config_inheritable: bool | Sentinel = NOT_SET,
    # TODO Mention in a comment that the real return type is
    #  `PromisingFunction[F_co]` only (as long as we eventually settle on
    #  it being the case, and not start returning the original function or
    #  class with duck-typed functionality instead)
) -> "PromisingFunction[F_co] | Callable[..., F_co]":
    if func_or_class is None:
        # The decorator was used with arguments
        # TODO Same thing about a comment for the return type as above
        def _decorator(f_or_cls: Callable[..., F_co] | type) -> "PromisingFunction[F_co] | Callable[..., F_co]":
            return PromisingFunction[F_co](
                f_or_cls,
                start_soon=start_soon,
                make_parent_wait=make_parent_wait,
                config_inheritable=config_inheritable,
            )

        return _decorator

    # The decorator was used either without arguments or as a direct function
    # call
    return PromisingFunction[F_co](
        func_or_class,
        start_soon=start_soon,
        make_parent_wait=make_parent_wait,
        config_inheritable=config_inheritable,
    )
