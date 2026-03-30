import promising


async def test_promise_has_no_parent_outside_context() -> None:
    """
    A Promise from promising function called at top level (outside any parent
    context) has no parent.
    """

    @promising.function
    async def noop() -> None:
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

    @promising.function
    async def func() -> promising.Promise:
        return promising.get_active_promise(raise_if_none=False)

    promise = func()
    current_from_inside = await promise.unpack_once()
    assert current_from_inside is promise


async def test_parent_child_relationship() -> None:
    child_promise = None

    @promising.function
    async def child_func() -> str:
        return "child"

    @promising.function
    async def parent_func() -> None:
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

    @promising.function(use_thread_pool=True)
    def child_func() -> str:
        return "child"

    @promising.function
    async def parent_func() -> None:
        nonlocal child_promise
        child_promise = child_func()

    parent_promise = parent_func()
    # `parent_func` does not return anything
    assert await parent_promise is None

    assert child_promise is not None
    assert child_promise.get_parent_context() is parent_promise
    assert child_promise.get_parent_promise() is parent_promise
    assert await child_promise == "child"
