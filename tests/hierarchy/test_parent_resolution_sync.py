import pytest

import promising


async def test_promise_has_no_parent_outside_context() -> None:
    """
    A Promise from promising function called at top level (outside any parent
    context) has no parent.
    """

    @promising.function(use_thread_pool=True)
    def noop() -> None:
        pass

    promise = noop()
    assert promise.get_parent_context(raise_if_none=False) is None
    assert promise.get_parent_promise(raise_if_none=False) is None
    await promise


async def test_active_promise_inside_promising_function() -> None:
    """
    get_active_promise() inside a promising function returns the wrapping
    Promise.
    """

    @promising.function(use_thread_pool=True)
    def func() -> promising.Promise:
        return promising.get_active_promise(raise_if_none=False)

    promise = func()
    current_from_inside = await promise.unpack_once()
    assert current_from_inside is promise


async def test_parent_child_relationship() -> None:
    child_promise = None

    @promising.function(use_thread_pool=True)
    def child_func() -> str:
        return "child"

    @promising.function(use_thread_pool=True)
    def parent_func() -> None:
        nonlocal child_promise
        child_promise = child_func()

    parent_promise = parent_func()
    # `parent_func` does not return anything
    assert await parent_promise is None

    assert child_promise is not None
    assert child_promise.get_parent_context() is parent_promise
    assert child_promise.get_parent_promise() is parent_promise
    assert await child_promise == "child"


async def test_parent_child_relationship_sync_async() -> None:
    child_promise = None

    @promising.function
    async def child_func() -> str:
        return "child"

    @promising.function(use_thread_pool=True)
    def parent_func() -> None:
        nonlocal child_promise
        child_promise = child_func()

    parent_promise = parent_func()
    # `parent_func` does not return anything
    assert await parent_promise is None

    assert child_promise is not None
    assert child_promise.get_parent_context() is parent_promise
    assert child_promise.get_parent_promise() is parent_promise
    assert await child_promise == "child"


async def test_get_active_promise_skips_plain_context() -> None:
    """
    get_active_promise() walks past a plain context to find the wrapping
    Promise.
    """

    @promising.function(use_thread_pool=True)
    def outer() -> promising.Promise | None:
        with promising.context(namespace="middle"):
            return promising.get_active_promise(raise_if_none=False)

    promise = outer()
    result = await promise.unpack_once()
    assert result is promise


async def test_get_active_promise_skips_multiple_plain_contexts() -> None:
    """
    get_active_promise() walks past several plain contexts to find the
    wrapping Promise.
    """

    @promising.function(use_thread_pool=True)
    def outer() -> promising.Promise | None:
        with promising.context(namespace="mid1"):
            with promising.context(namespace="mid2"):
                return promising.get_active_promise(raise_if_none=False)

    promise = outer()
    result = await promise.unpack_once()
    assert result is promise


async def test_get_active_promise_finds_nearest_promise() -> None:
    """
    With nested promises separated by a plain context,
    get_active_promise() returns the innermost (nearest) promise.
    """
    captured_active = None

    @promising.function(use_thread_pool=True)
    def inner() -> str:
        nonlocal captured_active
        with promising.context(namespace="gap"):
            captured_active = promising.get_active_promise(raise_if_none=False)
        return "done"

    @promising.function(use_thread_pool=True)
    def outer() -> promising.Promise:
        return inner()

    outer_promise = outer()
    inner_promise = await outer_promise.unpack_once()
    await inner_promise

    assert captured_active is inner_promise


async def test_get_active_promise_none_without_promise() -> None:
    """
    get_active_promise() returns None (or raises) when only plain contexts
    are active and no Promise exists in the hierarchy.
    """
    with promising.context():
        with promising.context():
            assert promising.get_active_promise(raise_if_none=False) is None
            with pytest.raises(promising.PromiseNotFoundError):
                promising.get_active_promise(raise_if_none=True)
