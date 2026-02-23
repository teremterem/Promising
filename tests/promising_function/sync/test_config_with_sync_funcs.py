import promising


async def test_config_params_work_with_sync_functions() -> None:
    """
    start_soon, children_start_soon_by_default, and
    everything_starts_soon_by_default config params
    work with sync functions.
    """

    @promising.function(
        start_soon=False,
        children_start_soon_by_default=False,
        everything_starts_soon_by_default=False,
    )
    def noop() -> None:
        pass

    promise = noop()
    assert promise._start_soon is False
    assert promise._children_start_soon_by_default is False
    assert promise._everything_starts_soon_by_default is False
    await promise


async def test_call_time_config_overrides_work_with_sync_functions() -> None:
    """
    Config params passed at call time override the
    PromisingFunction-level defaults for sync functions.
    """

    @promising.function(
        start_soon=False,
        children_start_soon_by_default=False,
        everything_starts_soon_by_default=False,
    )
    def noop() -> None:
        pass

    promise = noop(
        start_soon=True,
        children_start_soon_by_default=True,
        everything_starts_soon_by_default=True,
    )
    assert promise._start_soon is True
    assert promise._children_start_soon_by_default is True
    assert promise._everything_starts_soon_by_default is True
    await promise


async def test_config_kwargs_do_not_leak_into_sync_function() -> None:
    """
    start_soon etc. passed at call time are consumed by
    call() and not forwarded to the wrapped sync function.
    """

    @promising.function
    def add(a: int, b: int) -> int:
        return a + b

    result = await add(
        3,
        4,
        start_soon=True,
        children_start_soon_by_default=True,
        everything_starts_soon_by_default=True,
    )
    assert result == 7
