import asyncio
import inspect
from asyncio import AbstractEventLoop
from collections.abc import Awaitable
from typing import Any

from promising.errors import NoRunningEventLoopError, SyncUsageError
from promising.types import DecoratableFunctionType


def is_func_or_method_async(func_or_method: DecoratableFunctionType) -> bool:
    # We use `iscoroutinefunction()` from `asyncio` rather than `inspect`
    # because asyncio's version also checks for the `_is_coroutine` marker,
    # which allows it to recognize objects like `PromisingFunction` as
    # coroutine functions
    if isinstance(func_or_method, (classmethod, staticmethod)):
        return asyncio.iscoroutinefunction(func_or_method.__func__)
    return asyncio.iscoroutinefunction(func_or_method)


def resolve_module_name(obj: Any) -> str | None:
    module = getattr(obj, "__module__", None)
    if module is not None:
        return module

    # Coroutine and async-generator objects carry __qualname__ (inherited
    # from the function that created them) but NOT __module__.  However,
    # they do hold a reference to their compiled code object via cr_code
    # (coroutines) or ag_code (async generators).  The code object's
    # co_filename lets inspect.getmodule() map back to the originating
    # module.
    code = getattr(obj, "cr_code", None) or getattr(obj, "ag_code", None)
    if code is None:
        return None

    # The reason we are giving inspect.getmodule() the code object is because
    # it does not work on coroutines directly.
    code_module = inspect.getmodule(code)
    if code_module is None:
        return None

    return code_module.__name__


def get_running_asyncio_loop(*, raise_if_none: bool = True) -> AbstractEventLoop | None:
    try:
        return asyncio.get_running_loop()
    except RuntimeError as e:
        if raise_if_none:
            raise NoRunningEventLoopError(e) from e
        return None


def resolve_namespace(*, provided_explicitly: str | None, named_object_fallback: Any | None) -> str | None:
    from promising import Defaults  # noqa: PLC0415 (import-outside-top-level)

    if provided_explicitly is not None:
        return provided_explicitly

    if named_object_fallback is None:
        return None

    if Defaults.QUALNAMES_IN_NAMESPACES:
        prefix = resolve_module_name(named_object_fallback)
        prefix = f"{prefix}::" if prefix else ""
        if hasattr(named_object_fallback, "__qualname__"):
            return f"{prefix}{named_object_fallback.__qualname__}"
    else:
        prefix = ""

    if hasattr(named_object_fallback, "__name__"):
        return f"{prefix}{named_object_fallback.__name__}"

    return f"{prefix}{named_object_fallback}"


def assert_no_sync_usage_deadlock(loop_of_future: AbstractEventLoop, message: str) -> None:
    try:
        running_loop = asyncio.get_running_loop()
    except RuntimeError:
        running_loop = None

    if running_loop is loop_of_future:
        raise SyncUsageError(message)


async def awaitable_as_coroutine(awaitable: Awaitable[Any]) -> Any:
    return await awaitable
