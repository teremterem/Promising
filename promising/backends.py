import typing
from typing import Any

from promising.promise import Promise
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
        # TODO TODO TODO
        pass
