import asyncio

import pytest

import promising
from promising import INHERIT, PROMISING_DEFAULT, Sentinel


@pytest.mark.parametrize("start_soon_default", [True, False, INHERIT, PROMISING_DEFAULT])
@pytest.mark.parametrize("start_soon", [True, False, INHERIT, None])
@pytest.mark.parametrize("children_start_soon", [True, False, INHERIT, None])
async def test_config_forwarding(
    *,
    start_soon: bool | Sentinel,
    children_start_soon: bool | Sentinel,
    start_soon_default: bool | Sentinel,
) -> None:
    """
    Parametrized over all three config parameters. At root
    level (no parent), INHERIT and PROMISING_DEFAULT for
    start_soon_default both resolve to the
    global default (True). For start_soon, both INHERIT and
    None fall back to start_soon_default.
    For children_start_soon, INHERIT resolves to
    start_soon_default, while None stays
    as None (no enforcement on children).
    """

    @promising.function(
        start_soon=start_soon,
        children_start_soon=children_start_soon,
        start_soon_default=start_soon_default,
    )
    async def noop() -> None:
        pass

    promise = noop()

    # At root level, INHERIT and PROMISING_DEFAULT both read
    # the global default (True).
    expected_everything = start_soon_default if isinstance(start_soon_default, bool) else True
    # INHERIT and None for start_soon fall back to
    # start_soon_default at root.
    expected_start_soon = start_soon if isinstance(start_soon, bool) else expected_everything
    # INHERIT resolves to start_soon_default;
    # None stays as None (no enforcement).
    expected_children = expected_everything if children_start_soon is INHERIT else children_start_soon

    assert promise._start_soon_default is expected_everything
    assert promise._start_soon is expected_start_soon
    assert promise._children_start_soon is expected_children

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


@pytest.mark.parametrize("start_soon_default", [True, False])
@pytest.mark.parametrize("parent_start_soon", [True, False])
async def test_start_soon_default_inherits_from_parent(*, start_soon_default: bool, parent_start_soon: bool) -> None:
    """
    INHERIT (the default for start_soon_default)
    propagates the parent's value to child Promises. A parent
    with start_soon_default=False causes
    children (with INHERIT) to also resolve to False,
    overriding the global default (True).
    """
    child_promise = None

    @promising.function  # start_soon=None, start_soon_default=INHERIT
    async def child_func() -> None:
        pass

    @promising.function(
        start_soon_default=start_soon_default,
        start_soon=parent_start_soon,
    )
    async def parent_func() -> None:
        nonlocal child_promise
        child_promise = child_func()

    await parent_func()
    assert child_promise._start_soon_default is start_soon_default
    # None for start_soon falls back to the inherited value.
    assert child_promise._start_soon is start_soon_default
    await child_promise
    # TODO Also test it NOT being inherited if it is overridden on the child


@pytest.mark.parametrize("parent_starts_soon_by_default", [True, False])
@pytest.mark.parametrize("parent_start_soon", [True, False])
@pytest.mark.parametrize("child_start_soon", [True, False])
async def test_start_soon_default_global_default_ignores_parent(
    *,
    parent_starts_soon_by_default: bool,
    parent_start_soon: bool,
    child_start_soon: bool,
) -> None:
    """
    PROMISING_DEFAULT always reads the live global setting,
    ignoring the parent's start_soon_default.
    """
    child_promise = None

    @promising.function(start_soon_default=PROMISING_DEFAULT, start_soon=child_start_soon)
    async def child_func() -> None:
        pass

    @promising.function(start_soon_default=parent_starts_soon_by_default, start_soon=parent_start_soon)
    async def parent_func() -> None:
        nonlocal child_promise
        child_promise = child_func()

    await parent_func()
    # PROMISING_DEFAULT always reads the live global (True).
    assert child_promise._start_soon_default is True
    await child_promise


@pytest.mark.parametrize("children_start_soon", [True, False, None])
@pytest.mark.parametrize("parent_start_soon", [True, False])
async def test_children_start_soon_enforced_on_children(
    *,
    children_start_soon: bool | Sentinel,
    parent_start_soon: bool,
) -> None:
    """
    children_start_soon on the parent controls
    the start_soon resolution of child Promises that leave
    start_soon as None. A concrete bool enforces that
    value; None means no enforcement (child falls back
    to start_soon_default).
    """
    child_promise = None

    @promising.function  # start_soon=None
    async def child_func() -> None:
        pass

    @promising.function(
        start_soon=parent_start_soon,
        children_start_soon=children_start_soon,
    )
    async def parent_func() -> None:
        nonlocal child_promise
        child_promise = child_func()

    await parent_func()

    # None means no enforcement; child falls back to
    # start_soon_default (global default: True).
    expected_start_soon = True if children_start_soon is None else children_start_soon
    assert child_promise._start_soon is expected_start_soon
    await child_promise
    # TODO Also test it NOT being enforced if it is overridden on the child
