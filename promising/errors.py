import asyncio
import concurrent.futures
import logging
import shutil
import sys
import threading
import traceback
from collections.abc import Sequence
from types import SimpleNamespace, TracebackType
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


def install_promising_tracebacks() -> bool:
    """
    Install the promising overrides for ``sys.excepthook`` and
    ``threading.excepthook`` so that uncaught exceptions are rendered with
    their promising-context trace (and, when ``collapse_tracebacks`` is
    enabled, with promising-internal frames collapsed).

    Idempotent: calling this function while the hooks are already
    installed is a no-op. Whichever hooks were in place before the first
    successful installation are captured and used as a fallback if the
    promising renderer itself raises.

    ``Promise._unpack_once_from_loop`` calls this function automatically
    the first time a Promise runs, so applications rarely need to invoke
    it directly. It is exposed in the public API for cases where you want
    to enable promising tracebacks before any Promise has executed (for
    example, in a test fixture that asserts on traceback output).

    Returns ``True`` if at least one of the two hooks was actually
    replaced by this call; ``False`` if both were already in place.
    """
    replaced = False
    if sys.excepthook is _promising_sys_excepthook and threading.excepthook is _promising_threading_excepthook:
        return replaced

    with _excepthooks_lock:
        if sys.excepthook is not _promising_sys_excepthook:
            _excepthook_state.previous_sys = sys.excepthook
            sys.excepthook = _promising_sys_excepthook
            _logger.debug(
                "Installed promising sys.excepthook (previous=%r)",
                _excepthook_state.previous_sys,
            )
            replaced = True

        if threading.excepthook is not _promising_threading_excepthook:
            _excepthook_state.previous_threading = threading.excepthook
            threading.excepthook = _promising_threading_excepthook
            _logger.debug(
                "Installed promising threading.excepthook (previous=%r)",
                _excepthook_state.previous_threading,
            )
            replaced = True

    return replaced


_excepthooks_lock = threading.Lock()
_excepthook_state = SimpleNamespace(previous_sys=None, previous_threading=None)


def _promising_sys_excepthook(
    exc_type: type[BaseException],
    exc_value: BaseException,
    exc_tb: TracebackType | None,
) -> None:
    try:
        _print_exception_with_promising_context(
            exc_type,
            exc_value,
            exc_tb,
        )
    except Exception as e:
        _excepthook_state.previous_sys(exc_type, exc_value, exc_tb)
        _report_failure_to_print_promising_trace(e)


def _promising_threading_excepthook(args: threading.ExceptHookArgs) -> None:
    try:
        if args.thread is not None:
            print(f"Exception in thread {args.thread.name}:", file=sys.stderr)
        _print_exception_with_promising_context(
            args.exc_type,
            args.exc_value,
            args.exc_traceback,
        )
    except Exception as e:
        _excepthook_state.previous_threading(args)
        _report_failure_to_print_promising_trace(e)


def _print_exception_with_promising_context(
    exc_type: type[BaseException],
    exc_value: BaseException,
    exc_tb: TracebackType | None,
) -> None:
    """
    Print ``exc_value`` along with its ``__cause__`` / ``__context__`` chain,
    mirroring the default interpreter behavior (respecting
    ``__suppress_context__``), while enriching each link in the chain with
    its own promising context (if any).
    """
    _print_exception_chain(exc_type, exc_value, exc_tb, seen=set())


def _print_exception_chain(
    exc_type: type[BaseException],
    exc_value: BaseException,
    exc_tb: TracebackType | None,
    seen: set[int],
) -> None:
    if exc_value is None or id(exc_value) in seen:
        return
    seen.add(id(exc_value))

    cause = exc_value.__cause__
    context = exc_value.__context__
    suppress_context = exc_value.__suppress_context__

    if cause is not None:
        _print_exception_chain(type(cause), cause, cause.__traceback__, seen)
        print("\nThe above exception was the direct cause of the following exception:\n", file=sys.stderr)
    elif context is not None and not suppress_context:
        _print_exception_chain(type(context), context, context.__traceback__, seen)
        print("\nDuring handling of the above exception, another exception occurred:\n", file=sys.stderr)

    _print_single_exception(exc_type, exc_value, exc_tb)


def _print_single_exception(
    exc_type: type[BaseException],
    exc_value: BaseException,
    exc_tb: TracebackType | None,
) -> None:
    separator = "-" * shutil.get_terminal_size().columns
    print(f"{separator}\n  Traceback\n{separator}\n", file=sys.stderr)

    promising_context: PromisingContext | None = getattr(exc_value, "__promising_context__", None)
    collapse: bool = getattr(exc_value, "__promising_collapse_traceback__", False)

    is_first_stack = True

    if promising_context is not None:
        for ctx in promising_context.get_trace(ancestors_first=True):
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
                print(line, end="", file=sys.stderr)

            is_first_stack = False

            print(f"\n{separator}\n{ctx!r}\n{separator}\n", file=sys.stderr)

    last_stack = traceback.extract_tb(exc_tb)

    if collapse and not is_first_stack:
        lines = _format_last_stack(last_stack)
    else:
        lines = traceback.StackSummary.from_list(last_stack).format()

    for line in lines:
        print(line, end="", file=sys.stderr)

    print(f"\n{separator}\n💥  {exc_type.__name__}: {exc_value}\n{separator}", file=sys.stderr)


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
    # We walk `frames` innermost-to-outermost, appending each formatted group
    # to `lines`, then reverse `lines` at the end to restore the conventional
    # outermost-to-innermost order. This relies on `StackSummary.format()`
    # producing one string per frame so that reversing the list of strings is
    # equivalent to reversing the list of frames. (How reliable is one string
    # per frame assumption versus future versions of Python ?)
    # TODO [TRACES] Change approach and stop reversing ?
    # ruff: noqa: PLC0415 (import-outside-top-level)
    from promising import _PACKAGE_ABS_PATH
    from promising.promise import _MODULE_ABS_PATH as _CORE_MODULE_ABS_PATH

    pos = len(frames) - 1
    # If the error originated from the framework itself (an input validation
    # error etc.), we want to see those frames as well
    stack_portion = []
    while pos > -1 and frames[pos].filename.startswith(_PACKAGE_ABS_PATH):
        stack_portion.append(frames[pos])
        pos -= 1

    lines = []
    if stack_portion:
        lines.extend(traceback.StackSummary.from_list(stack_portion).format())

    while pos > -1:
        stack_portion = []
        while pos > -1 and not frames[pos].filename.startswith(_CORE_MODULE_ABS_PATH):
            stack_portion.append(frames[pos])
            pos -= 1

        if stack_portion:
            lines.extend(traceback.StackSummary.from_list(stack_portion).format())

        collapsed = False
        while pos > -1 and frames[pos].filename.startswith(_CORE_MODULE_ABS_PATH):
            collapsed = True
            pos -= 1

        if not collapsed:
            continue

        collapsed_line = "  ... (collapsed frames)\n"
        if stack_portion:
            collapsed_line = "\n" + collapsed_line
        if pos > -1:
            collapsed_line += "\n"
        lines.append(collapsed_line)

    lines.reverse()
    return lines


def _report_failure_to_print_promising_trace(failure: BaseException) -> None:
    print(f"\nWARNING: FAILED TO PRINT PROMISING TRACE: {failure}\n", file=sys.stderr)
    _logger.debug("FAILED TO PRINT PROMISING TRACE", exc_info=failure)
