"""
Sanity checks for ``loop.run_in_executor`` — used throughout the sync-API tests
to drive blocking calls from an async test without deadlocking the
pytest-asyncio event loop.

This file does not exercise our own code; it pins down the standard-library
behaviors that the sync-API tests assume — exceptions (including
``AssertionError`` and ``BaseException``) surface through ``await``, the
worker runs on another thread, and a cancelled awaiter does not stop the
worker. Treat it as executable documentation of those guarantees, useful
when reviewing whether a given test pattern is safe.
"""

import asyncio
import threading

import pytest


async def test_run_in_executor_returns_value_from_worker_thread() -> None:
    main_thread_id = threading.get_ident()
    worker_thread_id: list[int] = []

    def _work() -> str:
        worker_thread_id.append(threading.get_ident())
        return "ok"

    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, _work)

    assert result == "ok"
    assert worker_thread_id and worker_thread_id[0] != main_thread_id


async def test_run_in_executor_propagates_exception() -> None:
    class BoomError(Exception):
        pass

    def _raise() -> None:
        raise BoomError("kaboom")

    loop = asyncio.get_running_loop()
    with pytest.raises(BoomError, match="kaboom"):
        await loop.run_in_executor(None, _raise)


async def test_run_in_executor_propagates_assertion_error() -> None:
    def _assert_false() -> None:
        assert False, "expected failure"  # noqa: B011, PT015

    loop = asyncio.get_running_loop()
    with pytest.raises(AssertionError, match="expected failure"):
        await loop.run_in_executor(None, _assert_false)


async def test_run_in_executor_propagates_base_exception() -> None:
    def _system_exit() -> None:
        raise SystemExit(2)

    loop = asyncio.get_running_loop()
    with pytest.raises(SystemExit):
        await loop.run_in_executor(None, _system_exit)


async def test_run_in_executor_preserves_original_traceback() -> None:
    def _raise() -> None:
        raise RuntimeError("original")

    loop = asyncio.get_running_loop()
    with pytest.raises(RuntimeError, match="original") as exc_info:
        await loop.run_in_executor(None, _raise)

    # Frame from the worker function must appear in the traceback so that
    # pytest can point at the actual failure site inside the executor.
    frames = []
    tb = exc_info.tb
    while tb is not None:
        frames.append(tb.tb_frame.f_code.co_name)
        tb = tb.tb_next
    assert "_raise" in frames


async def test_run_in_executor_does_not_block_event_loop() -> None:
    release = threading.Event()
    started = threading.Event()

    def _blocking() -> str:
        started.set()
        release.wait(timeout=2)
        return "released"

    loop = asyncio.get_running_loop()
    fut = loop.run_in_executor(None, _blocking)

    # The event loop must remain responsive while the worker is blocked.
    await asyncio.sleep(0.1)
    assert started.wait(timeout=0.1)
    assert not fut.done()

    release.set()
    assert await fut == "released"


async def test_run_in_executor_cancellation_does_not_stop_worker() -> None:
    """
    Document a sharp edge: cancelling the awaiting coroutine does NOT
    interrupt a thread already running in the default executor. The worker
    keeps running until it returns. Tests that rely on ``run_in_executor``
    must not assume otherwise.
    """
    started = threading.Event()
    finished = threading.Event()
    release = threading.Event()

    def _worker() -> None:
        started.set()
        release.wait(timeout=2)
        finished.set()

    loop = asyncio.get_running_loop()
    fut = loop.run_in_executor(None, _worker)

    async def _await_it() -> None:
        await fut

    task = asyncio.create_task(_await_it())
    assert started.wait(timeout=0.1)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    # Worker thread is still running — release it and let it finish so the
    # test does not leak a zombie thread into the executor pool.
    assert not finished.is_set()
    release.set()
    await asyncio.wrap_future(fut)
    assert finished.is_set()
