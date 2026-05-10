import asyncio
import concurrent.futures
import logging
import os
import shutil
import sys
import threading
import traceback
from types import TracebackType

_logger = logging.getLogger(__name__)

# TODO [TRACES] Is it ok that we are not using Pathlib here ?
# TODO [TRACES] A unit test is needed to verify that these directories are
#  correct
_FRAMEWORK_DIR: str = os.path.dirname(os.path.abspath(__file__)) + os.sep
_ASYNCIO_DIR: str = os.path.dirname(os.path.abspath(asyncio.__file__)) + os.sep


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

    separator = "━" * shutil.get_terminal_size().columns

    print(separator)

    promising_context = getattr(exc_value, "__promising_context__", None)
    if promising_context is not None:
        for ctx in promising_context.get_trace(parents_first=True):
            if not isinstance(ctx, Promise):
                continue

            print(f"{ctx!r}\n")
            _print_frames_collapsing_internals(list(reversed(ctx.frame_summary_tuple)))
            print(separator)

    _print_frames_collapsing_internals(list(traceback.extract_tb(exc_tb)))
    print(separator)
    print(f"💥  {exc_type.__name__}: {exc_value}")
    print(separator)


def _print_frames_collapsing_internals(frames: list[traceback.FrameSummary]) -> None:
    i = 0
    n = len(frames)
    while i < n:
        if _is_promising_or_asyncio_frame(frames[i]):
            while i < n and _is_promising_or_asyncio_frame(frames[i]):
                i += 1
            print("\n  ... (promising/asyncio internals omitted) ...\n")
        else:
            start = i
            while i < n and not _is_promising_or_asyncio_frame(frames[i]):
                i += 1
            for line in traceback.StackSummary.from_list(frames[start:i]).format():
                print(line, end="")


def _is_promising_or_asyncio_frame(frame: traceback.FrameSummary) -> bool:
    return frame.filename.startswith(_FRAMEWORK_DIR) or frame.filename.startswith(_ASYNCIO_DIR)
