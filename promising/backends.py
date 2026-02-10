import typing
from typing import Any

from promising.promise import Promise
from promising.sentinels import NOT_SET
from promising.types import F_co

if typing.TYPE_CHECKING:
    from promising.promising_function import PromisingFunction


class PromisingBackend:
    def call_function(
        self,
        promising_function: "PromisingFunction[F_co]",
        *args: Any,
        **kwargs: Any,
    ) -> Promise[F_co]:
        # TODO TODO TODO How to reconcile sync and async ?
        persisted_result = self._try_persisted_result(promising_function, *args, **kwargs)
        if persisted_result is not NOT_SET:
            return Promise[F_co](prefill_result=persisted_result)
        # TODO TODO TODO

    def _try_persisted_result(
        self,
        promising_function: "PromisingFunction[F_co]",
        *args: Any,
        **kwargs: Any,
    ) -> F_co | NOT_SET:
        return NOT_SET

    def _persist_result(
        self,
        promising_function: "PromisingFunction[F_co]",
        *args: Any,
        result: F_co,
        **kwargs: Any,
    ) -> None:
        pass
