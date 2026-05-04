import threading

import pytest

from tests.utils_for_tests import run_in_thread


def test_run_in_thread_success_returns_normally() -> None:
    calls: list[int] = []

    def _ok() -> None:
        calls.append(1)

    run_in_thread(_ok)
    assert calls == [1]


def test_run_in_thread_propagates_exception() -> None:
    class BoomError(Exception):
        pass

    def _raise() -> None:
        raise BoomError("kaboom")

    with pytest.raises(BoomError, match="kaboom"):
        run_in_thread(_raise)


def test_run_in_thread_propagates_assertion_error() -> None:
    def _assert_false() -> None:
        assert False, "expected failure"  # noqa: B011, PT015

    with pytest.raises(AssertionError, match="expected failure"):
        run_in_thread(_assert_false)


def test_run_in_thread_propagates_base_exception() -> None:
    def _system_exit() -> None:
        raise SystemExit(2)

    with pytest.raises(SystemExit):
        run_in_thread(_system_exit)


def test_run_in_thread_timeout_raises_when_thread_hangs() -> None:
    release = threading.Event()

    def _hang() -> None:
        release.wait(timeout=5.0)

    try:
        with pytest.raises(AssertionError, match="Thread did not finish in time"):
            run_in_thread(_hang, timeout=0.05)
    finally:
        release.set()


def test_run_in_thread_timeout_does_not_raise_when_fast_enough() -> None:
    def _fast() -> None:
        pass

    run_in_thread(_fast, timeout=5.0)
