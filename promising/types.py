import types
from collections.abc import Callable
from typing import TypeVar

T_co = TypeVar("T_co", covariant=True)

DecoratableFunctionType = Callable[..., T_co] | types.MethodType | classmethod | staticmethod
