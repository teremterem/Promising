import asyncio
import re
import threading
from collections.abc import Awaitable, Callable, Generator
from typing import Any

import pytest

import promising

MARKERS_TO_XFAIL = [
    "xfail_cycle_detection_gh_issue_66",
]


def possibly_xfail(
    *markers: str | pytest.Mark,
    reason: str | None = None,
    item: pytest.Item | None = None,
    skip_entirely: bool = False,
) -> None:
    marker_strings: list[str] = []
    reason_strings: list[str] = [reason] if reason else []

    for marker in markers:
        if isinstance(marker, pytest.Mark):
            if marker.name not in MARKERS_TO_XFAIL:
                continue
            marker_strings.append(marker.name)

            reason_string = marker.kwargs.get("reason", None)
            if reason_string:
                reason_strings.append(reason_string)

            skip_entirely = skip_entirely or marker.kwargs.get("skip_entirely", False)

        elif isinstance(marker, str):
            if marker not in MARKERS_TO_XFAIL:
                continue
            marker_strings.append(marker)

        else:
            raise ValueError(f"Unknown marker type: {type(marker)} ")

    if not marker_strings:
        # None of the markers are in the MARKERS_TO_XFAIL list - nothing to xfail!
        return

    final_reason = " | ".join(reason_strings)
    if final_reason:
        final_reason = f": {final_reason}"
    final_reason = ",".join(sorted(marker_strings)) + final_reason

    if item is not None and not skip_entirely:
        # This only works while still in pytest_runtest_setup - it will not
        # work if called after the test has started
        item.add_marker(pytest.mark.xfail(reason=final_reason))
    else:
        # This works at any time. Also, useful for tests that time out.
        # `skip_entirely` parameter can be passed to the markers themselves to
        # enforce skipping (by default skipping is disabled for decorator level
        # markers but enabled for in-test calls to this function).
        pytest.skip(reason=final_reason)


def normalize_object_repr(s: str) -> str:
    """
    Replace hex addresses and digit sequences with X for stable comparisons.
    """
    assert isinstance(s, str)
    s = re.sub(r"\d+", "999", s)
    # After the previous sub, hex addresses like "0x7f3a" have become
    # "999x999f999a". This pattern matches "999x" followed by any mix of
    # digits-turned-999 and hex letters, normalizing to "0xfff".
    s = re.sub(r"999x[9a-f]+", "0xfff", s)
    return s


def run_in_thread(fn: Callable[[], None], timeout: float | None = None) -> None:
    """Run *fn* in a dedicated thread, re-raising any error.

    Useful for tests that call .run() (which needs asyncio.run()) without
    interfering with the pytest-asyncio event loop.
    """
    # TODO [P2] Add a test for this utility function - we want to make sure errors
    # that assertion failures inside it actually propagate to the test
    error = None

    def _target():
        nonlocal error
        try:
            fn()
        except BaseException as exc:
            error = exc

    t = threading.Thread(target=_target, daemon=True)
    t.start()
    t.join(timeout=timeout)
    if timeout is not None:
        assert not t.is_alive(), "Thread did not finish in time"

    if error is not None:
        raise error


def collect_parent_contexts(ctx: promising.PromisingContext) -> list[promising.PromisingContext]:
    result = []
    while (parent := ctx.get_parent_context(raise_if_none=False)) is not None:
        result.append(parent)
        ctx = parent
    return result


def collect_parent_promises(ctx: promising.PromisingContext) -> list[promising.Promise[Any]]:
    result = []
    while (parent := ctx.get_parent_promise(raise_if_none=False)) is not None:
        result.append(parent)
        ctx = parent
    return result


class NonPromiseAwaitableContext(promising.PromisingContext):
    def __init__(
        self,
        coro: Awaitable[Any],
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._coro = coro

    def __await__(self) -> Generator[Any, None, Any]:
        # TODO [P2] There is a pitfall: should someone decide to extend their own
        #  awaitable from PromisingContext and forget to use a with statement
        #  like the one below, the await_children will confusingly hang on such
        #  an instance. How to hint at the need to enter and exit the context
        #  for those who would want to extend PromisingContext ?
        with self:
            return (yield from asyncio.ensure_future(self._coro))
