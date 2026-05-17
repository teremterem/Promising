"""
Race conditions around multi-thread consumption of Promises and
context hierarchies via the sync API:

- ``Promise.sync()`` / ``Promise.unpack_once_sync()`` — invoked by
  multiple worker threads simultaneously on the same Promise.
- ``promising.await_children_sync()`` — invoked from one thread while
  workers on other threads keep registering new child Promises under
  the same parent.

All of these end up reading/writing ``Promise._state``,
``Promise._full_unpacking_task``, ``Promise._single_unpacking_task``,
``PromisingContext._unsettled_children`` — none of which are protected.
"""

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

import promising

# ── concurrent sync() consumption ──────────────────────────────


async def test_many_threads_calling_sync_on_same_promise_consistent() -> None:
    """
    N worker threads simultaneously call ``promise.sync()`` on the same
    Promise. All must return the same value; none must hang or raise.

    NOTE [race-injection / 2026-05-17]: this test could not be made to
    fail even by deliberately introducing race-prone breakage in
    ``promising/`` (lost children, non-atomic state writes, dropped
    ContextVar copy, etc.). All ``.sync()`` callers dispatch their
    awaiting onto the Promise's single event loop via
    ``run_coroutine_threadsafe``, so the actual ``await self`` runs
    serialized on the loop thread; only one ``_full_unpacking_task`` is
    ever scheduled, every coroutine yields from the same task, and the
    final ``_result`` is written once by the task itself. There is no
    race surface to inject into without changing this serialization.
    Keep as a regression guard against future refactors that try to
    short-circuit the loop dispatch (e.g. a "fast path" returning a
    cached ``_result`` directly from the caller thread).
    """
    loop = asyncio.get_running_loop()

    for _ in range(10):

        async def coro() -> int:
            await asyncio.sleep(0.01)
            return 1234

        promise = promising.wrap_awaitable(coro(), parent=None, loop=loop, start_soon=False)

        N = 32
        results: list[int] = []
        errors: list[BaseException] = []
        lock = threading.Lock()

        def consumer() -> None:
            try:
                value = promise.sync(timeout=5)
                with lock:
                    results.append(value)
            except BaseException as exc:  # noqa: BLE001
                with lock:
                    errors.append(exc)

        with ThreadPoolExecutor(max_workers=N) as ex:
            await asyncio.gather(*[loop.run_in_executor(ex, consumer) for _ in range(N)])

        assert not errors, errors
        assert results == [1234] * N, f"inconsistent results from concurrent sync(): {set(results)}"


async def test_many_threads_calling_unpack_once_sync_on_same_promise_consistent() -> None:
    """
    Same scenario as ``test_many_threads_calling_sync_on_same_promise``
    but using ``unpack_once_sync``. All threads should observe the same
    one-level-unpacking outcome (here: a concrete value, since the
    coroutine does not return a Promise).

    NOTE [race-injection / 2026-05-17]: same finding as the ``.sync()``
    sibling above — could not be broken by deliberate framework
    sabotage. ``unpack_once_sync`` also goes through
    ``run_coroutine_threadsafe`` and the single
    ``_single_unpacking_task``. Only one task ever drives the unpack,
    all callers share its result. Keep as regression guard against
    future refactors that bypass the loop dispatch.
    """
    loop = asyncio.get_running_loop()

    async def coro() -> str:
        await asyncio.sleep(0.01)
        return "ok"

    promise = promising.wrap_awaitable(coro(), parent=None, loop=loop, start_soon=False)

    N = 32
    results: list[object] = []
    errors: list[BaseException] = []
    lock = threading.Lock()

    def consumer() -> None:
        try:
            value = promise.unpack_once_sync(timeout=5)
            with lock:
                results.append(value)
        except BaseException as exc:  # noqa: BLE001
            with lock:
                errors.append(exc)

    with ThreadPoolExecutor(max_workers=N) as ex:
        await asyncio.gather(*[loop.run_in_executor(ex, consumer) for _ in range(N)])

    assert not errors, errors
    assert results == ["ok"] * N


# ── sync() race with cancel() ──────────────────────────────────


async def test_sync_consumer_thread_observes_clean_terminal_after_cancel() -> None:
    """
    One thread waits on ``promise.sync()`` while another fires
    ``promise.cancel()``. The sync caller must observe a clean
    terminal state — either the value (if cancel lost the race) or
    ``CancelledError``. It must never observe an internal
    ``RuntimeError`` from a racing state transition.
    """
    loop = asyncio.get_running_loop()

    for _ in range(40):
        cancel_event = asyncio.Event()

        async def coro() -> int:
            try:
                await cancel_event.wait()
            except asyncio.CancelledError:
                raise
            return 9

        promise = promising.wrap_awaitable(coro(), parent=None, loop=loop, start_soon=True)

        consumer_done = threading.Event()
        consumer_result: dict[str, object] = {}

        def consume() -> None:
            try:
                consumer_result["value"] = promise.sync(timeout=5)
            except BaseException as exc:  # noqa: BLE001
                consumer_result["exception"] = exc
            finally:
                consumer_done.set()

        consumer = threading.Thread(target=consume, daemon=True)
        consumer.start()

        # Let the consumer thread get into run_coroutine_threadsafe()
        await asyncio.sleep(0)

        promise.cancel()

        # Park the loop until the consumer thread is done.
        while not consumer_done.is_set():
            await asyncio.sleep(0)

        consumer.join(timeout=5)
        assert not consumer.is_alive()

        # The sync caller must end up with a clean terminal outcome:
        # either the value (cancel lost the race) or a CancelledError.
        # Anything else (RuntimeError, internal state errors, ...) means
        # the racing state-machine paths leaked an internal exception.
        if "exception" in consumer_result:
            exc = consumer_result["exception"]
            # Compare by class name to side-step asyncio vs.
            # concurrent.futures CancelledError class differences.
            assert type(exc).__name__ == "CancelledError", (
                f"sync() raised an unexpected internal exception during cancel race: "
                f"{type(exc).__module__}.{type(exc).__qualname__}: {exc!r}"
            )
        else:
            assert consumer_result["value"] == 9


# ── await_children_sync race with thread-side registration ──────


async def test_await_children_sync_during_thread_registration_does_not_raise() -> None:
    """
    A sync promising function runs in the thread pool and calls
    ``promising.await_children_sync()``; meanwhile additional threads
    keep creating child Promises under the same parent. The sync
    waiter must drain all children without raising "set changed size
    during iteration" from the underlying ``collect_unsettled_children``.
    """
    loop = asyncio.get_running_loop()

    @promising.function
    async def root() -> None:
        active = promising.get_active_promise()
        stop = threading.Event()
        thread_errors: list[BaseException] = []
        registered_children: list[promising.Promise] = []
        registered_lock = threading.Lock()

        async def _quick() -> int:
            return 0

        def writer() -> None:
            try:
                while not stop.is_set():
                    p = promising.wrap_awaitable(
                        _quick(),
                        parent=active,
                        loop=loop,
                        start_soon=False,
                    )
                    with registered_lock:
                        registered_children.append(p)
            except BaseException as exc:  # noqa: BLE001
                thread_errors.append(exc)

        @promising.function(use_thread_pool=True)
        def sync_waiter() -> str:
            # Each iteration triggers a fresh collect_unsettled_children
            # via await_children_sync.
            for _ in range(20):
                promising.await_children_sync(whole_subtree=True)
            return "drained"

        writers = [threading.Thread(target=writer, daemon=True) for _ in range(4)]
        for w in writers:
            w.start()
        try:
            waiter_promise = sync_waiter()
            try:
                await waiter_promise
            finally:
                stop.set()
                for w in writers:
                    w.join(timeout=5)
        finally:
            for c in registered_children:
                c.cancel()

        assert not thread_errors, thread_errors

    await root()


# ── concurrent .sync() consumption *and* registration ───────────


async def test_concurrent_sync_consumers_and_child_registrations() -> None:
    """
    Realistic stress: half the workers consume a published Promise
    via ``.sync()`` while the other half register fresh child Promises
    on the same parent. The framework must keep both the consumption
    path and the parent's set consistent.
    """
    loop = asyncio.get_running_loop()

    @promising.function
    async def root() -> int:
        active = promising.get_active_promise()

        @promising.function
        async def published() -> int:
            await asyncio.sleep(0.01)
            return 99

        async def _quick() -> int:
            return 0

        N_CONSUMERS = 16
        N_REGISTRARS = 16

        for _ in range(30):
            target = published()

            errors: list[BaseException] = []
            errors_lock = threading.Lock()
            consumer_results: list[int] = []
            new_children: list[promising.Promise] = []

            def consumer() -> None:
                try:
                    consumer_results.append(target.sync(timeout=5))
                except BaseException as exc:  # noqa: BLE001
                    with errors_lock:
                        errors.append(exc)

            def registrar() -> None:
                try:
                    for _ in range(20):
                        new_children.append(
                            promising.wrap_awaitable(
                                _quick(),
                                parent=active,
                                loop=loop,
                                start_soon=False,
                            )
                        )
                except BaseException as exc:  # noqa: BLE001
                    with errors_lock:
                        errors.append(exc)

            with ThreadPoolExecutor(max_workers=N_CONSUMERS + N_REGISTRARS) as ex:
                consumer_futs = [loop.run_in_executor(ex, consumer) for _ in range(N_CONSUMERS)]
                registrar_futs = [loop.run_in_executor(ex, registrar) for _ in range(N_REGISTRARS)]
                await asyncio.gather(*consumer_futs, *registrar_futs)

            assert not errors, errors
            assert consumer_results == [99] * N_CONSUMERS

            # All registrars' children must be tracked.
            actual = active.collect_unsettled_children(whole_subtree=False, awaitables_only=True)
            missing = set(new_children) - actual
            assert not missing, f"{len(missing)} children were lost from the parent's set"

            for c in new_children:
                c.cancel()
        return 0

    await root()


# ── sanity ──────────────────────────────────────────────────────


@pytest.mark.skip(reason="Sanity reference — single-thread consumption is fine.")
async def test_single_threaded_sync_consumption_works_sanity() -> None:
    async def coro() -> int:
        return 1

    promise = promising.wrap_awaitable(coro(), parent=None, start_soon=True)
    loop = asyncio.get_running_loop()
    value = await loop.run_in_executor(None, promise.sync)
    assert value == 1
