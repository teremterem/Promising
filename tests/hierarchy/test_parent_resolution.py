import promising

# TODO This test file does not seem to be systematic enough. Expand it into a
#  fully fledged set of sync and async counterparts that mirror each other
#  perfectly ?


async def test_promise_has_no_parent_outside_context() -> None:
    """
    A Promise created at top level (outside any parent
    context) has no parent.
    """

    @promising.function
    async def noop() -> None:
        pass

    promise = noop()
    assert promise.get_parent_context(raise_if_none=False) is None
    assert promise.get_parent_promise(raise_if_none=False) is None
    await promise


async def test_active_promise_accessible_inside_sync_function() -> None:
    """
    get_active_promise() inside a sync promising function
    (running in a thread pool) returns the wrapping Promise.
    """

    @promising.function(use_thread_pool=True)
    def sync_func() -> promising.Promise:
        return promising.get_active_promise(raise_if_none=False)

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
