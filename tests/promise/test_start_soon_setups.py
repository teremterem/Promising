import asyncio

import pytest

import promising
from promising import GLOBAL_DEFAULT, INHERIT, NOT_SET, Sentinel


@pytest.mark.parametrize("everything_starts_soon_by_default", [True, False, INHERIT, GLOBAL_DEFAULT])
@pytest.mark.parametrize("start_soon", [True, False, INHERIT, NOT_SET])
@pytest.mark.parametrize("children_start_soon_by_default", [True, False, INHERIT, NOT_SET])
async def test_config_forwarding(
    *,
    start_soon: bool | Sentinel,
    children_start_soon_by_default: bool | Sentinel,
    everything_starts_soon_by_default: bool | Sentinel,
) -> None:
    """
    Parametrized over all three config parameters. At root
    level (no parent), INHERIT and GLOBAL_DEFAULT for
    everything_starts_soon_by_default both resolve to the
    global default (True). For start_soon, both INHERIT and
    NOT_SET fall back to everything_starts_soon_by_default.
    For children_start_soon_by_default, INHERIT resolves to
    everything_starts_soon_by_default, while NOT_SET stays
    as NOT_SET (no enforcement on children).
    """

    @promising.function(
        start_soon=start_soon,
        children_start_soon_by_default=children_start_soon_by_default,
        everything_starts_soon_by_default=everything_starts_soon_by_default,
    )
    async def noop() -> None:
        pass

    promise = noop()

    # At root level, INHERIT and GLOBAL_DEFAULT both read
    # the global default (True).
    expected_everything = (
        everything_starts_soon_by_default if isinstance(everything_starts_soon_by_default, bool) else True
    )
    # INHERIT and NOT_SET for start_soon fall back to
    # everything_starts_soon_by_default at root.
    expected_start_soon = start_soon if isinstance(start_soon, bool) else expected_everything
    # INHERIT resolves to everything_starts_soon_by_default;
    # NOT_SET stays as NOT_SET (no enforcement).
    expected_children = (
        expected_everything if children_start_soon_by_default is INHERIT else children_start_soon_by_default
    )

    assert promise._everything_starts_soon_by_default is expected_everything
    assert promise._start_soon is expected_start_soon
    assert promise._children_start_soon_by_default is expected_children

    await promise


@pytest.mark.parametrize("start_soon", [True, False])
async def test_start_soon_behavior(*, start_soon: bool) -> None:
    """
    With start_soon=True: after calling + sleeping,
    the coroutine has already executed. With False:
    it hasn't executed until explicitly awaited.
    """
    executed = False

    async def worker() -> str:
        nonlocal executed
        executed = True
        return "done"

    pf = promising.function(worker, start_soon=start_soon)
    promise = pf()

    # Give the event loop a chance to run scheduled tasks
    await asyncio.sleep(0.1)

    if start_soon:
        assert executed is True
    else:
        assert executed is False

    await promise
    assert executed is True


@pytest.mark.parametrize("everything_starts_soon_by_default", [True, False])
@pytest.mark.parametrize("parent_start_soon", [True, False])
async def test_everything_starts_soon_by_default_inherits_from_parent(
    *,
    everything_starts_soon_by_default: bool,
    parent_start_soon: bool,
) -> None:
    """
    INHERIT (the default for everything_starts_soon_by_default)
    propagates the parent's value to child Promises. A parent
    with everything_starts_soon_by_default=False causes
    children (with INHERIT) to also resolve to False,
    overriding the global default (True).
    """
    child_promise = None

    @promising.function  # start_soon=NOT_SET, everything_starts_soon_by_default=INHERIT
    async def child_func() -> None:
        pass

    @promising.function(
        everything_starts_soon_by_default=everything_starts_soon_by_default,
        start_soon=parent_start_soon,
    )
    async def parent_func() -> None:
        nonlocal child_promise
        child_promise = child_func()

    await parent_func()
    assert child_promise._everything_starts_soon_by_default is everything_starts_soon_by_default
    # NOT_SET for start_soon falls back to the inherited value.
    assert child_promise._start_soon is everything_starts_soon_by_default
    await child_promise
    # TODO Also test it NOT being inherited if it is overridden on the child


@pytest.mark.parametrize("parent_starts_soon_by_default", [True, False])
@pytest.mark.parametrize("parent_start_soon", [True, False])
@pytest.mark.parametrize("child_start_soon", [True, False])
async def test_everything_starts_soon_by_default_global_default_ignores_parent(
    *,
    parent_starts_soon_by_default: bool,
    parent_start_soon: bool,
    child_start_soon: bool,
) -> None:
    """
    GLOBAL_DEFAULT always reads the live global setting,
    ignoring the parent's everything_starts_soon_by_default.
    """
    child_promise = None

    @promising.function(everything_starts_soon_by_default=GLOBAL_DEFAULT, start_soon=child_start_soon)
    async def child_func() -> None:
        pass

    @promising.function(everything_starts_soon_by_default=parent_starts_soon_by_default, start_soon=parent_start_soon)
    async def parent_func() -> None:
        nonlocal child_promise
        child_promise = child_func()

    await parent_func()
    # GLOBAL_DEFAULT always reads the live global (True).
    assert child_promise._everything_starts_soon_by_default is True
    await child_promise


@pytest.mark.parametrize("children_start_soon_by_default", [True, False, NOT_SET])
@pytest.mark.parametrize("parent_start_soon", [True, False])
async def test_children_start_soon_by_default_enforced_on_children(
    *,
    children_start_soon_by_default: bool | Sentinel,
    parent_start_soon: bool,
) -> None:
    """
    children_start_soon_by_default on the parent controls
    the start_soon resolution of child Promises that leave
    start_soon as NOT_SET. A concrete bool enforces that
    value; NOT_SET means no enforcement (child falls back
    to everything_starts_soon_by_default).
    """
    child_promise = None

    @promising.function  # start_soon=NOT_SET
    async def child_func() -> None:
        pass

    @promising.function(
        start_soon=parent_start_soon,
        children_start_soon_by_default=children_start_soon_by_default,
    )
    async def parent_func() -> None:
        nonlocal child_promise
        child_promise = child_func()

    await parent_func()

    # NOT_SET means no enforcement; child falls back to
    # everything_starts_soon_by_default (global default: True).
    expected_start_soon = True if children_start_soon_by_default is NOT_SET else children_start_soon_by_default
    assert child_promise._start_soon is expected_start_soon
    await child_promise
    # TODO Also test it NOT being enforced if it is overridden on the child
