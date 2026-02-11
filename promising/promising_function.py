from collections.abc import Callable
from typing import Any, Generic

from promising.backends import PromisingBackend
from promising.config import PromisingConfig
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
        backend: PromisingBackend,
        config: PromisingConfig | None = None,
        # TODO Support optional `children_config` too ?
        start_soon: bool | Sentinel = NOT_SET,
        make_parent_wait: bool | Sentinel = NOT_SET,
        config_inheritable: bool | Sentinel = NOT_SET,
    ):
        self.original_func_or_class = func_or_class
        self.backend = backend

        # TODO Is maintaining all these attributes here like this directly a
        #  good idea ?
        self.config = config
        self.start_soon = start_soon
        self.make_parent_wait = make_parent_wait
        self.config_inheritable = config_inheritable

    def function(
        self,
        func_or_class: Callable[..., F_co] | type | None = None,
        *,
        config: PromisingConfig | None = None,
        # TODO Support optional `children_config` too ?
        start_soon: bool | Sentinel = NOT_SET,
        make_parent_wait: bool | Sentinel = NOT_SET,
        config_inheritable: bool | Sentinel = NOT_SET,
    ) -> "PromisingFunction[F_co]":
        if func_or_class is None:
            # The decorator was used with arguments
            def _decorator(f_or_cls: Callable[..., F_co] | type) -> "PromisingFunction[F_co]":
                return PromisingFunction[F_co](
                    f_or_cls,
                    backend=self.backend,
                    config=config,
                    start_soon=start_soon,
                    make_parent_wait=make_parent_wait,
                    config_inheritable=config_inheritable,
                )

            return _decorator

        # The decorator was used either without arguments or as a direct
        # function call
        return PromisingFunction[F_co](
            func_or_class,
            backend=self.backend,
            config=config,
            start_soon=start_soon,
            make_parent_wait=make_parent_wait,
            config_inheritable=config_inheritable,
        )

    def call(
        self,
        *args: Any,
        **kwargs: Any,
        # TODO Add promise config parameters ?
    ) -> Promise[T_co]:
        if self.original_func_or_class is None:
            raise PromiseFunctionNotCallableError("This PromisingFunction is not callable")

        # TODO TODO TODO Put the logic here and use backend only for
        #  persistence ?

        return self.backend.call_function(self, *args, **kwargs)

    def __call__(
        self,
        *args: Any,
        **kwargs: Any,
        # TODO Add promise config parameters ?
    ) -> Promise[T_co]:
        return self.call(*args, **kwargs)
