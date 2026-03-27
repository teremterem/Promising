import threading

import pytest

import promising
from promising import get_active_promise

# ── Core: Sync Function Wrapping & Argument Forwarding ──────────
# ── Thread Verification ──────────────────────────────────────────


async def test_sync_function_runs_in_different_thread() -> None:
    """
    The sync function actually runs in a different thread
    than the event loop thread.
    """
    main_thread = threading.current_thread()

    @promising.function(use_thread_pool=True)
    def get_thread() -> threading.Thread:
        return threading.current_thread()

    worker_thread = await get_thread()
    assert worker_thread is not main_thread


# ── Error Cases ──────────────────────────────────────────────────


async def test_exception_propagates_through_promise() -> None:
    """
    An exception raised inside the sync function
    propagates through the Promise when awaited.
    """

    @promising.function(use_thread_pool=True)
    def failing() -> None:
        raise ValueError("test error")

    with pytest.raises(ValueError, match="test error"):
        await failing()


@pytest.mark.parametrize(
    "exc_type",
    [ValueError, TypeError, RuntimeError, KeyError],
)
async def test_various_exception_types(*, exc_type: type) -> None:
    """
    Parametrized: each exception type propagates
    through the Promise correctly.
    """

    @promising.function(use_thread_pool=True)
    def failing() -> None:
        raise exc_type("specific error")

    with pytest.raises(exc_type):
        await failing()


# ── function() Decorator Modes ───────────────────────────────────


async def test_decorator_with_empty_parens() -> None:
    """
    @promising.function() (empty parens) behaves
    identically to bare @promising.function for sync functions.
    """

    @promising.function(use_thread_pool=True)
    def greet() -> str:
        return "hello"

    assert isinstance(greet, promising.PromisingFunction)
    assert await greet() == "hello"


async def test_used_as_direct_call() -> None:
    """
    promising.function(my_func) used as a direct call
    (non-decorator) works for sync functions.
    """

    def my_func() -> str:
        return "direct"

    pf = promising.function(my_func, use_thread_pool=True)
    assert isinstance(pf, promising.PromisingFunction)
    assert await pf() == "direct"


async def test_preserves_original_func() -> None:
    """
    decorated.__wrapped__ is the original function passed
    to the decorator.
    """

    def original() -> str:
        return "preserved"

    decorated = promising.function(original, use_thread_pool=True)
    assert decorated.__wrapped__ is original


# ── Context Propagation ─────────────────────────────────────────


async def test_active_promise_accessible_inside_sync_function() -> None:
    """
    get_active_promise() inside a sync promising function
    (running in a thread pool) returns the wrapping Promise.
    """

    @promising.function(use_thread_pool=True)
    def sync_func() -> promising.Promise:
        return get_active_promise(raise_if_none=False)

    promise = sync_func()
    current_from_inside = await promise.unpack_once()
    assert current_from_inside is promise


async def test_sync_parent_child_relationship() -> None:
    """
    A child Promise created inside a sync promising
    function has the sync function's Promise as its parent.
    """
    child_promise = None

    @promising.function
    async def child_func() -> str:
        return "child"

    @promising.function(use_thread_pool=True)
    def sync_parent() -> None:
        nonlocal child_promise
        child_promise = child_func(start_soon=False)

    parent_promise = sync_parent()
    await parent_promise

    assert child_promise is not None
    assert child_promise.get_parent_context(raise_if_none=False) is parent_promise
    assert child_promise.get_parent_promise(raise_if_none=False) is parent_promise
    await child_promise
