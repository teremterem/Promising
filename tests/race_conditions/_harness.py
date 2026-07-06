"""Shared primitives for the race-condition test suite.

The helpers here are intentionally small and dependency-free so they can
be composed inside the per-invariant test files. They cover the four
patterns the suite relies on over and over:

- ``spin_until`` — observe an asynchronous flag-flip from a tight loop.
- ``run_on_many_threads`` — fork N threads, release them simultaneously
  via a ``threading.Barrier``, collect their results and any exceptions.
- ``assert_monotonic`` — validate that an observed sequence of states
  forms a valid walk through an allowed transition graph.
- ``ExceptionAggregator`` — capture exceptions raised on background
  threads so a thread-only failure cannot be silently lost by the
  driver.
- ``dual_loop`` — a pytest fixture that pairs the pytest-asyncio loop on
  the main thread with a second loop on a background thread, used to
  exercise cross-loop invariants.
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, TypeVar

import pytest

T = TypeVar("T")


def spin_until(predicate: Callable[[], bool], timeout: float = 2.0, interval: float = 0.0) -> bool:
    """Tight-loop wait for ``predicate`` to return truthy.

    Returns ``True`` if the predicate flipped within ``timeout``, else
    ``False``. ``interval=0.0`` keeps the loop maximally tight so the
    caller observes the flip in the same scheduling quantum where
    possible.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        if interval:
            time.sleep(interval)
    return predicate()


@dataclass
class ThreadStormResult:
    """Outcome of a :func:`run_on_many_threads` storm."""

    results: list[Any] = field(default_factory=list)
    exceptions: list[BaseException] = field(default_factory=list)

    @property
    def successes(self) -> list[Any]:
        return [r for r in self.results if r is not _UNSET]

    def raise_if_any(self) -> None:
        if self.exceptions:
            raise self.exceptions[0]


_UNSET = object()


def run_on_many_threads(
    target: Callable[..., T],
    n: int,
    *args: Any,
    barrier_timeout: float = 5.0,
    join_timeout: float = 5.0,
    **kwargs: Any,
) -> ThreadStormResult:
    """Fork *n* threads, release them simultaneously via a ``Barrier``.

    Each thread calls ``target(*args, **kwargs)``. Return values and
    exceptions are collected per-thread; the i-th element of
    ``results`` is what thread i returned (or ``_UNSET`` on failure),
    and the i-th element of ``exceptions`` is the corresponding
    exception (or ``None``).
    """
    barrier = threading.Barrier(n, timeout=barrier_timeout)
    results: list[Any] = [_UNSET] * n
    exceptions: list[BaseException | None] = [None] * n

    def _runner(idx: int) -> None:
        try:
            barrier.wait()
            results[idx] = target(*args, **kwargs)
        except BaseException as exc:  # noqa: BLE001 — re-raised via the aggregator
            exceptions[idx] = exc

    threads = [threading.Thread(target=_runner, args=(i,), daemon=True) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=join_timeout)
        if t.is_alive():
            raise TimeoutError(f"Thread {t.name} did not finish within {join_timeout}s")

    real_exceptions = [exc for exc in exceptions if exc is not None]
    return ThreadStormResult(results=results, exceptions=real_exceptions)


def assert_monotonic(
    samples: Iterable[Any],
    allowed_transitions: set[tuple[Any, Any]],
    *,
    label: str = "state",
) -> None:
    """Assert *samples* is a walk through *allowed_transitions*.

    Consecutive duplicates are allowed (a reader may sample the same
    state multiple times before it advances). A transition from state
    ``a`` to a different state ``b`` is allowed iff
    ``(a, b) in allowed_transitions``.
    """
    prev = None
    for sample in samples:
        if prev is not None and sample is not prev and (prev, sample) not in allowed_transitions:
            raise AssertionError(f"Illegal {label} transition: {prev!r} -> {sample!r}")
        prev = sample


class ExceptionAggregator:
    """Capture ``BaseException``-derived errors raised on any thread.

    Wrap a callable via :meth:`capture`; failures land in
    :attr:`errors` instead of propagating out of the thread. Use
    :meth:`raise_if_any` from the driver thread to surface them.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.errors: list[BaseException] = []

    def capture(self, fn: Callable[..., T]) -> Callable[..., T | None]:
        def _wrapper(*args: Any, **kwargs: Any) -> T | None:
            try:
                return fn(*args, **kwargs)
            except BaseException as exc:  # noqa: BLE001
                with self._lock:
                    self.errors.append(exc)
                return None

        return _wrapper

    def raise_if_any(self) -> None:
        if self.errors:
            raise self.errors[0]


@contextmanager
def exception_aggregator() -> Iterator[ExceptionAggregator]:
    agg = ExceptionAggregator()
    try:
        yield agg
    finally:
        agg.raise_if_any()


@dataclass
class DualLoop:
    """Pair of event loops for cross-loop invariant tests.

    ``main_loop`` is the pytest-asyncio loop on the main thread (the
    one the test coroutine itself runs on). ``other_loop`` runs in a
    background thread so the test can hand work to a foreign loop and
    still ``await`` on its own.
    """

    main_loop: asyncio.AbstractEventLoop
    other_loop: asyncio.AbstractEventLoop
    other_thread: threading.Thread


@pytest.fixture
async def dual_loop() -> Iterator[DualLoop]:
    """Spin up a second event loop on a background thread.

    Yields a :class:`DualLoop`. Cleans the background loop up at teardown.
    """
    main_loop = asyncio.get_running_loop()
    other_loop = asyncio.new_event_loop()
    started = threading.Event()

    def _runner() -> None:
        asyncio.set_event_loop(other_loop)
        started.set()
        other_loop.run_forever()

    thread = threading.Thread(target=_runner, name="dual-loop-other", daemon=True)
    thread.start()
    started.wait(timeout=2.0)

    try:
        yield DualLoop(main_loop=main_loop, other_loop=other_loop, other_thread=thread)
    finally:
        other_loop.call_soon_threadsafe(other_loop.stop)
        thread.join(timeout=2.0)
        other_loop.close()
