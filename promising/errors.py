import asyncio
import concurrent.futures
import logging
import sys
import threading
import traceback
from types import TracebackType

_logger = logging.getLogger(__name__)


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
    if hasattr(exc_value, "__promising_context__"):
        try:
            _print_exception_with_promising_context(
                exc_type,
                exc_value,
                exc_tb,
            )
        except BaseException as e:
            _previous_sys_excepthook(exc_type, exc_value, exc_tb)
            _report_failure_to_print_promising_trace(e)
    else:
        _previous_sys_excepthook(exc_type, exc_value, exc_tb)


def _promising_threading_excepthook(args: threading.ExceptHookArgs) -> None:
    if hasattr(args.exc_value, "__promising_context__"):
        try:
            _print_exception_with_promising_context(
                args.exc_type,
                args.exc_value,
                args.exc_traceback,
            )
        except BaseException as e:
            _previous_threading_excepthook(args)
            _report_failure_to_print_promising_trace(e)
    else:
        _previous_threading_excepthook(args)


def _report_failure_to_print_promising_trace(failure: BaseException) -> None:
    print("\nWARNING: FAILED TO PRINT PROMISING TRACE\n")
    _logger.debug("FAILED TO PRINT PROMISING TRACE", exc_info=failure)


_previous_sys_excepthook = sys.excepthook
_previous_threading_excepthook = threading.excepthook
# TODO [TRACES] This feature needs to be unit-tested somehow
sys.excepthook = _promising_sys_excepthook
threading.excepthook = _promising_threading_excepthook
# TODO [TRACES] How to offer the same feature for the loggers ?


def _print_exception_with_promising_context(
    exc_type: type[BaseException],
    exc_value: BaseException,
    exc_tb: TracebackType,
) -> None:
    """Caller must have verified `exc_value` carries `__promising_context__`.

    Returns True if printed successfully, False if formatting itself raised —
    in which case the caller should fall back to the previous hook so the user
    still sees their traceback.
    """
    from promising.promise import Promise  # noqa: PLC0415 (import-outside-top-level)

    # TODO [TRACES] Is it possible to fetch the width of the terminal
    #  and use it for the horizontal line length ?
    print("━" * 60)

    promising_context = getattr(exc_value, "__promising_context__", None)
    if promising_context is not None:
        for ctx in promising_context.get_trace(parents_first=True):
            if not isinstance(ctx, Promise):
                continue

            print(f"{ctx!r}")
            stack_summary = traceback.StackSummary.from_list(reversed(ctx.frame_summary_tuple))
            for line in stack_summary.format():
                print(line, end="")
            print("━" * 60)

    traceback.print_tb(exc_tb)
    print("━" * 60)
    print(f"💥  {exc_type.__name__}: {exc_value}")
    print("━" * 60)

    # TODO [TRACES] Make sure something like this is printed everytime
    #  promising/asyncio frames are omitted ?
    #  `... (promising/asyncio internals omitted) ...`
    # TODO [TRACES] Do the same with `asyncio` and simplify skipping logic
    #  (process whole trace - don't stop at framework frames)
