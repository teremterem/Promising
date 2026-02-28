import types
from collections.abc import Callable
from typing import Any, TypeVar

T_co = TypeVar("T_co", covariant=True)

# TODO Make it parametrizable with T_co instead of Any ?
# TODO This type does not mention async functions
DecoratableFunctionType = Callable[..., Any] | types.MethodType | classmethod | staticmethod
