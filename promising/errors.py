import asyncio
import concurrent.futures
import sys
import threading
import traceback
from types import TracebackType


class PromisingError(Exception):
    """
    A base class for all promising errors.
    """


class DecorationError(PromisingError):
    pass


class PromiseNotFoundError(PromisingError):
    pass


class SentinelUsageError(PromisingError):
    pass


class SyncUsageError(PromisingError):
    pass


# Context errors


class ContextError(PromisingError):
    """
    A base class for all context-related errors.
    """


class ContextAlreadyActiveError(ContextError):
    pass


class ContextAlreadyClosedError(ContextError):
    pass


class ContextNotActiveError(ContextError):
    pass


class ContextNotFoundError(ContextError):
    pass


# Event loop errors


class EventLoopError(PromisingError):
    """
    A base class for all event loop-related errors.
    """


class EventLoopMismatchError(EventLoopError, ValueError):
    pass


class NoRunningEventLoopError(EventLoopError, RuntimeError):
    pass


# Promise state errors


class PromiseInvalidStateError(
    PromisingError,
    asyncio.InvalidStateError,
    concurrent.futures.InvalidStateError,
):
    """
    A base class for all promise state-related errors.
    """


class PromiseNotDoneError(PromiseInvalidStateError):
    """
    A promise is queried for a result/exception before it is done.
    """


class PromiseNotUnpackedError(PromiseInvalidStateError):
    """
    A promise's intermediate_promise is queried before the first unpacking.
    """


def _promising_sys_excepthook(
    exc_type: type[BaseException],
    exc_value: BaseException,
    exc_tb: TracebackType,
) -> None:
    if hasattr(exc_value, "__promising_context__") and _print_exception_with_promising_context(
        exc_type,
        exc_value,
        exc_tb,
    ):
        return
    _previous_sys_excepthook(exc_type, exc_value, exc_tb)


def _promising_threading_excepthook(args: threading.ExceptHookArgs) -> None:
    if hasattr(args.exc_value, "__promising_context__") and _print_exception_with_promising_context(
        args.exc_type,
        args.exc_value,
        args.exc_traceback,
    ):
        return
    _previous_threading_excepthook(args)


_previous_sys_excepthook = sys.excepthook
_previous_threading_excepthook = threading.excepthook
sys.excepthook = _promising_sys_excepthook
threading.excepthook = _promising_threading_excepthook
# TODO [TRACES] How to offer the same feature for the loggers ?


def _print_exception_with_promising_context(
    exc_type: type[BaseException],
    exc_value: BaseException,
    exc_tb: TracebackType,
) -> bool:
    """Caller must have verified `exc_value` carries `__promising_context__`.

    Returns True if printed successfully, False if formatting itself raised —
    in which case the caller should fall back to the previous hook so the user
    still sees their traceback.
    """
    try:
        from promising.promise import Promise  # noqa: PLC0415 (import-outside-top-level)

        # TODO [TRACES] Is it possible to fetch the width of the terminal and use it for the
        #  horizontal line length ?
        print("━" * 60)
        print(f"💥  {exc_type.__name__}: {exc_value}")
        print("━" * 60)
        traceback.print_tb(exc_tb)
        print("━" * 60)

        pc = exc_value.__promising_context__
        if pc is None:
            return True

        print("📍  Promise creation stacks (outermost → innermost):")
        print("━" * 60)
        for ctx in pc.get_trace(parents_first=True):
            if not isinstance(ctx, Promise):
                continue
            stack_summary = getattr(ctx, "_creation_stack_summary", None)
            if stack_summary is None:
                continue
            print(f"{ctx!r}")
            for line in stack_summary.format():
                print(line, end="")
            print("━" * 60)
        # TODO [TRACES] At the very end the final traceback should be printed in
        #  the same filtered fashion - the actual traceback of the exception that
        #  was raised
        # TODO [TRACES] Make sure something like this is printed everytime
        #  framework frames are omitted ?
        #  `... (`promising` internals omitted) ...`
        # TODO [TRACES] Do the same with `asyncio` and simplify skipping logic
        #  (process whole trace - don't stop at framework frames)
    except BaseException as fmt_err:  # noqa: BLE001
        print(f"(promising traceback formatter failed: {fmt_err!r}; falling back)")
        return False
    return True
