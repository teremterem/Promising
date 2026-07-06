"""
Shared helpers for the race-condition test suite.

The core primitive is ``run_racers`` — it releases a herd of callables
simultaneously from dedicated OS threads (synchronized on a
``threading.Barrier``) so that they collide inside the racy window a test
is targeting, and reports each racer's result/exception back to the test.

The helpers are intentionally framework-agnostic (plain ``threading`` +
``asyncio``): they must not depend on the synchronization machinery under
test.
"""

import asyncio
import threading
import time
from collections.abc import Callable
from typing import Any

from promising import Promise, PromisingContext
from promising.errors import (
    ContextAlreadyClosedError,
    PromiseNotDoneError,
    PromiseNotUnpackedError,
)

# How many times each racy window is re-created per test. Race conditions
# are probabilistic: a single interleaving proves nothing, so tests stage
# the same collision over and over.
RACE_ITERATIONS = 50

# Default number of racer threads hammering a single object.
RACER_THREADS = 6

# Upper bound for starting/joining racer threads. Generous, because a
# broken invariant must surface as an assertion failure — not as a test
# that never finishes.
JOIN_TIMEOUT = 10.0


class AtomicCounter:
    """
    Thread-safe counter used to detect duplicate/missing executions.

    A plain ``int += 1`` is not atomic across bytecode instructions, so we
    guard it with a lock — the counter itself must never be the source of
    a false positive in a race test.
    """

    def __init__(self) -> None:
        self._value = 0
        self._lock = threading.Lock()

    def increment(self) -> None:
        with self._lock:
            self._value += 1

    @property
    def value(self) -> int:
        with self._lock:
            return self._value


def run_racers_sync(
    *racers: Callable[[], Any],
    join_timeout: float = JOIN_TIMEOUT,
) -> tuple[list[Any], list[BaseException | None]]:
    """
    Run the given callables in parallel OS threads, released simultaneously
    via a ``threading.Barrier`` to maximize the chance that they all hit
    the racy window at the same moment.

    This is the blocking version — it must NOT be called from the event
    loop thread if any racer needs that loop to make progress (e.g. racers
    calling ``promise.sync()``); use the ``run_racers`` coroutine instead.

    Returns:
        ``(results, errors)`` — two lists index-aligned with ``racers``.
        For each racer exactly one of ``results[i]`` / ``errors[i]`` is
        meaningful; ``errors[i]`` is ``None`` when the racer returned
        normally. Errors are captured (not raised) so that a test can
        assert on *which* racer failed and how — pass the errors through
        ``assert_no_errors`` when any failure should fail the test.

    Raises:
        AssertionError: If any racer thread is still alive after
            ``join_timeout`` (i.e. the race deadlocked instead of failing).
    """
    barrier = threading.Barrier(len(racers))
    results: list[Any] = [None] * len(racers)
    errors: list[BaseException | None] = [None] * len(racers)

    def _run(index: int, racer: Callable[[], Any]) -> None:
        try:
            # Line all the racers up on the barrier so they enter the racy
            # window as close to simultaneously as the OS allows.
            barrier.wait(timeout=join_timeout)
            results[index] = racer()
        except BaseException as exc:  # noqa: PERF203 - deliberate blanket capture
            errors[index] = exc

    threads = [
        threading.Thread(target=_run, args=(index, racer), daemon=True, name=f"racer-{index}")
        for index, racer in enumerate(racers)
    ]
    for thread in threads:
        thread.start()

    deadline = time.monotonic() + join_timeout
    for thread in threads:
        thread.join(timeout=max(0.0, deadline - time.monotonic()))
    assert not any(thread.is_alive() for thread in threads), (
        "Racer threads did not finish in time — the race led to a deadlock or a lost wakeup"
    )
    return results, errors


async def run_racers(
    *racers: Callable[[], Any],
    join_timeout: float = JOIN_TIMEOUT,
) -> tuple[list[Any], list[BaseException | None]]:
    """
    Async wrapper around ``run_racers_sync`` — offloads the thread
    starting/joining to a separate thread so the event loop keeps running
    while the racers execute. This matters because racers typically need
    the loop to make progress (``sync()``, ``cancel()``, promise creation
    with ``start_soon=True``, ...).
    """
    return await asyncio.to_thread(run_racers_sync, *racers, join_timeout=join_timeout)


def assert_no_errors(errors: list[BaseException | None]) -> None:
    """Re-raise the first error captured by ``run_racers``, if any."""
    for error in errors:
        if error is not None:
            raise error


async def eventually(
    predicate: Callable[[], bool],
    *,
    timeout: float = 5.0,
    interval: float = 0.001,
    message: str | None = None,
) -> None:
    """
    Await until ``predicate()`` becomes truthy, failing after ``timeout``.

    Used for invariants that are allowed to become true *asynchronously
    soon* after a racy operation (e.g. "the promise eventually reaches a
    terminal state"), as opposed to invariants that must hold immediately.
    """
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError(message or f"Condition did not become true within {timeout} seconds")
        await asyncio.sleep(interval)


def assert_promise_snapshot_consistent(promise: Promise) -> None:
    """
    Assert that a single cross-thread snapshot of a Promise's state is
    internally consistent.

    This encodes the thread-safety contract documented on
    ``Promise.done()``: the state machine is monotonic and each state
    attribute (``_result`` / ``_exception`` / ``_intermediate_promise``)
    is written *before* the state advances, so a reader that observes an
    advanced state must also observe the matching attribute. Violations
    manifest as:

    - ``done()`` is True but ``result()`` / ``exception()`` raises
      ``PromiseNotDoneError`` (state advanced before the value landed);
    - ``result()`` raises the internal "result is UNCHANGED" RuntimeError
      (state says finished-without-exception but no result is stored);
    - ``unpacked_once_or_done()`` is True but ``intermediate_promise()``
      raises ``PromiseNotUnpackedError``;
    - ``cancelled()`` is True while ``done()`` is False.
    """
    if promise.cancelled():
        assert promise.done(), f"cancelled() is True but done() is False: {promise!r}"

    if promise.unpacked_once():
        assert promise.unpacked_once_or_done(), (
            f"unpacked_once() is True but unpacked_once_or_done() is False: {promise!r}"
        )

    if promise.done():
        try:
            promise.result()
        except PromiseNotDoneError:
            raise AssertionError(f"done() is True but result() raised PromiseNotDoneError: {promise!r}") from None
        except RuntimeError as exc:
            if "UNCHANGED" in str(exc):
                raise AssertionError(
                    f"done() is True but the result was not yet visible to this thread: {promise!r}"
                ) from exc
            # Any other RuntimeError is assumed to be the exception the
            # promise legitimately finished with.
        except BaseException:  # noqa: S110 - stored exception / CancelledError is a valid outcome
            pass

        try:
            promise.exception()
        except PromiseNotDoneError:
            raise AssertionError(f"done() is True but exception() raised PromiseNotDoneError: {promise!r}") from None
        except asyncio.CancelledError:
            assert promise.cancelled(), f"exception() raised CancelledError but cancelled() is False: {promise!r}"

    if promise.unpacked_once_or_done():
        try:
            promise.intermediate_promise()
        except PromiseNotUnpackedError:
            raise AssertionError(
                f"unpacked_once_or_done() is True but intermediate_promise() "
                f"raised PromiseNotUnpackedError: {promise!r}"
            ) from None
        except BaseException:  # noqa: S110 - stored exception is a valid outcome
            pass


class PromiseStateMonotonicityTracker:
    """
    Per-observer tracker asserting that a Promise's state flags never
    regress: once this observer has seen ``done()`` / ``cancelled()`` /
    ``unpacked_once_or_done()`` return True, any later read must agree.
    Each ``check()`` also validates the full snapshot consistency (see
    ``assert_promise_snapshot_consistent``).
    """

    def __init__(self, promise: Promise) -> None:
        self._promise = promise
        self._seen_done = False
        self._seen_cancelled = False
        self._seen_unpacked = False

    def check(self) -> None:
        assert_promise_snapshot_consistent(self._promise)

        done = self._promise.done()
        cancelled = self._promise.cancelled()
        unpacked = self._promise.unpacked_once_or_done()

        if self._seen_done:
            assert done, f"done() regressed from True to False: {self._promise!r}"
        if self._seen_cancelled:
            assert cancelled, f"cancelled() regressed from True to False: {self._promise!r}"
        if self._seen_unpacked:
            assert unpacked, f"unpacked_once_or_done() regressed from True to False: {self._promise!r}"

        self._seen_done = self._seen_done or done
        self._seen_cancelled = self._seen_cancelled or cancelled
        self._seen_unpacked = self._seen_unpacked or unpacked


def make_child_creator(
    parent_ctx: PromisingContext,
    loop: asyncio.AbstractEventLoop,
    executions: AtomicCounter,
    box: dict[str, Any],
) -> Callable[[], None]:
    """
    Build a racer callable that creates a child Promise under
    ``parent_ctx`` from whatever thread the racer runs in.

    The outcome is recorded in ``box``:

    - ``box["child"]`` — the created Promise, when creation succeeded;
    - ``box["rejected"] = True`` — when creation was cleanly rejected with
      ``ContextAlreadyClosedError`` (the only rejection the atomic-creation
      contract permits);
    - ``box["coro"]`` — the wrapped coroutine, always, so the test can
      close a never-scheduled coroutine and avoid "never awaited" warnings.

    The child's body increments ``executions`` — the test uses the counter
    to verify "accepted children run exactly once, rejected children never
    run".
    """

    def _create() -> None:
        async def _child_coro() -> str:
            executions.increment()
            return "child-done"

        coro = _child_coro()
        box["coro"] = coro
        try:
            box["child"] = Promise(coro, parent=parent_ctx, loop=loop, start_soon=True)
        except ContextAlreadyClosedError:
            box["rejected"] = True

    return _create


async def verify_atomic_creation_outcome(
    parent_ctx: PromisingContext,
    executions: AtomicCounter,
    box: dict[str, Any],
) -> None:
    """
    Verify the atomic-creation contract for a single ``make_child_creator``
    outcome (child creation raced against the parent closing/completing):

    - **Rejected** (``ContextAlreadyClosedError``): the child's awaitable
      must never execute. NOTE: the current implementation schedules
      execution (``call_soon_threadsafe``) *before* registering with the
      parent, so this half of the contract is expected to fail until
      creation is made atomic.
    - **Accepted**: the child must execute exactly once, must remain
      visible to the parent (``collect_unsettled_children``) until it is
      done, and must reach a terminal state.
    """
    if box.get("rejected"):
        # Give any (buggy) stray scheduling a chance to run before checking
        # that the rejected child never executed.
        await asyncio.sleep(0.005)
        assert executions.value == 0, (
            "Child creation was rejected with ContextAlreadyClosedError, but the child's awaitable was executed anyway"
        )
        # The coroutine was (correctly) never scheduled — close it so it
        # doesn't emit a "coroutine was never awaited" warning at GC time.
        box["coro"].close()
    else:
        child = box["child"]
        # A successfully created child must be either already done or still
        # visible to its parent — an accepted-but-untracked child would be
        # silently invisible to await_children().
        assert child.done() or child in parent_ctx.collect_unsettled_children(), (
            "Accepted child is neither done nor tracked by its parent (silently lost)"
        )
        await eventually(child.done, message="Accepted child never reached a terminal state")
        assert executions.value == 1, "Accepted child must execute exactly once"
