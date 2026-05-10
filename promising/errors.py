import asyncio
import concurrent.futures
import logging
import os
import shutil
import sys
import threading
import traceback
from collections.abc import Iterable
from types import TracebackType
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from promising.promising_context import PromisingContext

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
    """
    Caller must have verified ``exc_value`` carries ``__promising_context__``.

    Returns True if printed successfully, False if formatting itself raised —
    in which case the caller should fall back to the previous hook so the user
    still sees their traceback.
    """
    from promising.promise import Promise  # noqa: PLC0415 (import-outside-top-level)

    separator = "-" * shutil.get_terminal_size().columns
    print(separator)

    promising_context: PromisingContext | None = getattr(exc_value, "__promising_context__", None)
    collapse = getattr(exc_value, "__promising_collapse_traceback__", False)

    if promising_context is not None:
        collapse_top = False

        for ctx in promising_context.get_trace(parents_first=True):
            if not isinstance(ctx, Promise):
                continue

            for line in reversed(
                _format_frames_with_collapses(
                    ctx.frame_summary_tuple,
                    collapse_bottom=collapse,
                    collapse_top=collapse_top,
                )
            ):
                print(line, end="")

            collapse_top = collapse

            print(separator)
            print(repr(ctx))
            print(separator)

    lines = _format_frames_with_collapses(
        reversed(traceback.extract_tb(exc_tb)),
        collapse_bottom=False,
        collapse_top=collapse,
    )
    lines.reverse()
    for line in lines:
        print(line, end="")

    print(separator)
    print(f"💥  {exc_type.__name__}: {exc_value}")
    print(separator)


def _format_frames_with_collapses(
    frames: Iterable[traceback.FrameSummary],
    *,
    collapse_bottom: bool,
    collapse_top: bool,
) -> list[str]:
    frame_list = list(frames)
    start = 0
    if collapse_bottom:
        while start < len(frame_list) and _is_promising_or_asyncio_frame(frame_list[start]):
            start += 1
    end = len(frame_list)
    trailing_collapse = False
    if collapse_top:
        for i in range(start, len(frame_list)):
            if _is_promising_or_asyncio_frame(frame_list[i]):
                end = i
                trailing_collapse = True
                break
    lines = traceback.StackSummary.from_list(frame_list[start:end]).format()

    filler = "\n  ... (collapsed frames)\n\n"
    if start > 0:
        lines.insert(0, filler)
    if trailing_collapse:
        lines.append(filler)
    return lines


def _is_promising_or_asyncio_frame(frame: traceback.FrameSummary) -> bool:
    # TODO [TRACES] Don't just collapse frames from promising and asyncio
    #  entirely, identify "anchoring" frames instead to decide which part(s) of
    #  the traceback to collapse
    return frame.filename.startswith(_FRAMEWORK_DIR) or frame.filename.startswith(_ASYNCIO_DIR)


def _report_failure_to_print_promising_trace(failure: BaseException) -> None:
    print(f"\nWARNING: FAILED TO PRINT PROMISING TRACE: {failure}\n")
    _logger.debug("FAILED TO PRINT PROMISING TRACE", exc_info=failure)
