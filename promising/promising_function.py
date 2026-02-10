from collections.abc import Callable
from typing import Any, Generic

from promising.backends import PromisingBackend
from promising.errors import PromiseFunctionNotCallableError
from promising.promise import Promise
from promising.types import F_co, T_co


class PromisingFunction(Generic[T_co]):
    original_func_or_class: Callable[..., T_co] | type | None = None

    def __init__(
        self,
        func_or_class: Callable[..., T_co] | type | None = None,
        *,
        backend: PromisingBackend,
    ):
        self.original_func_or_class = func_or_class
        self.backend = backend

    def function(self, func_or_class: Callable[..., F_co] | type | None = None) -> "PromisingFunction[F_co]":
        if func_or_class is None:
            # the decorator `@miniagent(...)` was used with arguments
            def _decorator(f_or_cls: Callable[..., F_co] | type) -> "PromisingFunction[F_co]":
                return PromisingFunction[F_co](
                    f_or_cls,
                    backend=self.backend,
                )

            return _decorator

        # the decorator was used either without arguments or as a direct
        # function call
        return PromisingFunction[F_co](
            func_or_class,
            backend=self.backend,
        )

    def call(self, *args: Any, **kwargs: Any) -> Promise[T_co]:
        if self.original_func_or_class is None:
            raise PromiseFunctionNotCallableError("This PromisingFunction is not callable")

        # TODO TODO TODO Put the logic here and use backend only for
        #  persistence ?

        return self.backend.call_function(self, *args, **kwargs)

    def __call__(self, *args: Any, **kwargs: Any) -> Promise[T_co]:
        return self.call(*args, **kwargs)
