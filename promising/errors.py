import asyncio
import concurrent.futures
import logging
import shutil
import sys
import threading
import traceback
from collections.abc import Sequence
from types import TracebackType
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from promising.promising_context import PromisingContext

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
    separator = "-" * shutil.get_terminal_size().columns
    print(f"{separator}\n  Traceback\n{separator}\n")

    promising_context: PromisingContext | None = getattr(exc_value, "__promising_context__", None)
    collapse: bool = getattr(exc_value, "__promising_collapse_traceback__", False)

    is_first_stack = True

    if promising_context is not None:
        for ctx in promising_context.get_trace(parents_first=True):
            frame_summary_tuple = getattr(ctx, "frame_summary_tuple", None)
            if frame_summary_tuple is None:
                # This is not a Promise instance (or any other [hypothetical]
                # context supporting this attribute)
                continue

            stack = list(frame_summary_tuple)
            stack.reverse()

            if collapse:
                if is_first_stack:
                    lines = _format_first_stack(stack)
                else:
                    lines = _format_middle_stack(stack)
            else:
                lines = traceback.StackSummary.from_list(stack).format()

            for line in lines:
                print(line, end="")

            is_first_stack = False

            print(f"\n{separator}\n{ctx!r}\n{separator}\n")

    last_stack = traceback.extract_tb(exc_tb)

    if collapse and not is_first_stack:
        lines = _format_last_stack(last_stack)
    else:
        lines = traceback.StackSummary.from_list(last_stack).format()

    for line in lines:
        print(line, end="")

    print(f"\n{separator}\n💥  {exc_type.__name__}: {exc_value}\n{separator}")


def _format_first_stack(frames: Sequence[traceback.FrameSummary]) -> list[str]:
    # ruff: noqa: PLC0415 (import-outside-top-level)
    from promising import _PACKAGE_ABS_PATH

    pos = len(frames) - 1
    # Skip over the trailing framework frames - they are part of the plumbing
    # that leads into the next promise, not something the user needs to see
    while pos > -1 and frames[pos].filename.startswith(_PACKAGE_ABS_PATH):
        pos -= 1

    if -1 < pos < len(frames) - 1:
        return [*traceback.StackSummary.from_list(frames[: pos + 1]).format(), "\n  ... (collapsed frames)\n"]

    # Either there was nothing to collapse at all or everything was going to be
    # collapsed => let's show the full traceback in both cases
    return traceback.StackSummary.from_list(frames).format()


def _format_middle_stack(frames: Sequence[traceback.FrameSummary]) -> list[str]:
    # ruff: noqa: PLC0415 (import-outside-top-level)
    from promising import _PACKAGE_ABS_PATH
    from promising.promise import _MODULE_ABS_PATH as _CORE_MODULE_ABS_PATH

    pos = len(frames) - 1
    # Skip over the trailing framework frames - they are part of the plumbing
    # that leads into the next promise, not something the user needs to see
    while pos > -1 and frames[pos].filename.startswith(_PACKAGE_ABS_PATH):
        pos -= 1
    bottom_pos = pos

    # Walk back to the nearest `promising/promise.py` frame - that frame and
    # everything above it also going to be collapsed, leaving only the user
    # code between `top_pos` and `bottom_pos`
    while pos > -1 and not frames[pos].filename.startswith(_CORE_MODULE_ABS_PATH):
        pos -= 1
    top_pos = pos

    collapse_top: bool = -1 < top_pos < len(frames) - 1
    collapse_bottom: bool = -1 < bottom_pos < len(frames) - 1

    collapsed_frames = frames[top_pos + 1 : bottom_pos + 1]
    if not collapsed_frames:
        # Everything was collapsed => let's show the full traceback, because
        # we don't want to show nothing
        collapsed_frames = frames

    lines = traceback.StackSummary.from_list(collapsed_frames).format()
    if collapse_top:
        lines.insert(0, "  ... (collapsed frames)\n\n")
    if collapse_bottom:
        lines.append("\n  ... (collapsed frames)\n")
    return lines


def _format_last_stack(frames: Sequence[traceback.FrameSummary]) -> list[str]:
    # ruff: noqa: PLC0415 (import-outside-top-level)
    from promising import _PACKAGE_ABS_PATH
    from promising.promise import _MODULE_ABS_PATH as _CORE_MODULE_ABS_PATH

    pos = len(frames) - 1
    # If the error originated from the framework itself (an input validation
    # error etc.), we want to see those frames as well, so let's skip them to
    # make sure they are preserved
    while pos > -1 and frames[pos].filename.startswith(_PACKAGE_ABS_PATH):
        pos -= 1

    # Now, let's move from here upwards to the nearest `promising/promise.py`
    # frame - that frame and everything above it are the only parts that need
    # to be collapsed
    # TODO [TRACES] Don't cut off everything above like that ! There might
    #  still be user frames, that were captured as the error was bubbling up !
    while pos > -1 and not frames[pos].filename.startswith(_CORE_MODULE_ABS_PATH):
        pos -= 1

    if -1 < pos < len(frames) - 1:
        return ["  ... (collapsed frames)\n\n", *traceback.StackSummary.from_list(frames[pos + 1 :]).format()]

    # Either there was nothing to collapse at all or everything was going to be
    # collapsed => let's show the full traceback in both cases
    return traceback.StackSummary.from_list(frames).format()


def _report_failure_to_print_promising_trace(failure: BaseException) -> None:
    print(f"\nWARNING: FAILED TO PRINT PROMISING TRACE: {failure}\n")
    _logger.debug("FAILED TO PRINT PROMISING TRACE", exc_info=failure)
