import inspect

from promising.types import DecoratableFunctionType


def is_func_or_method_coro(func_or_method: DecoratableFunctionType) -> bool:
    """
    Check if a function or method is a coroutine.
    """
    if isinstance(func_or_method, (classmethod, staticmethod)):
        return inspect.iscoroutinefunction(func_or_method.__func__)
    return inspect.iscoroutinefunction(func_or_method)
