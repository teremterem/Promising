from collections.abc import Callable
from types import MethodType
from typing import Any, TypeVar

T_co = TypeVar("T_co", covariant=True)

CallableType = Callable[..., Any] | MethodType | staticmethod
DecoratableFunctionType = CallableType | classmethod
