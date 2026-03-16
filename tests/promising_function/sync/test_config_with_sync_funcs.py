import promising


async def test_config_params_work_with_sync_functions() -> None:
    """
    start_soon, children_start_soon, and
    start_soon_default config params
    work with sync functions.
    """

    @promising.function(
        start_soon=False,
        children_start_soon=False,
        start_soon_default=False,
        use_thread_pool=True,
    )
    def noop() -> None:
        pass

    promise = noop()
    assert promise._start_soon is False
    assert promise._children_start_soon is False
    assert promise._start_soon_default is False
    await promise


async def test_call_time_config_overrides_work_with_sync_functions() -> None:
    """
    Config params passed at call time override the
    PromisingFunction-level defaults for sync functions.
    """

    @promising.function(
        start_soon=False,
        children_start_soon=False,
        start_soon_default=False,
        use_thread_pool=True,
    )
    def noop() -> None:
        pass

    promise = noop(
        start_soon=True,
        children_start_soon=True,
        start_soon_default=True,
    )
    assert promise._start_soon is True
    assert promise._children_start_soon is True
    assert promise._start_soon_default is True
    await promise


async def test_config_kwargs_do_not_leak_into_sync_function() -> None:
    """
    start_soon etc. passed at call time are consumed by
    call() and not forwarded to the wrapped sync function.
    """

    @promising.function(use_thread_pool=True)
    def add(a: int, b: int) -> int:
        return a + b

    result = await add(
        3,
        4,
        start_soon=True,
        children_start_soon=True,
        start_soon_default=True,
    )
    assert result == 7
