"""
Tests that stacking two identical decorators (``@promising.function`` on top of
``@promising.function``, or ``@promising.context`` on top of
``@promising.context``) preserves each layer's attributes independently.

Reproduces the clobbering bug described in
https://github.com/teremterem/Promising/issues/77 — ``functools.update_wrapper``
copies ``func_or_method.__dict__`` onto the outer decorator instance, silently
overwriting attributes that were already set during ``__init__``.
"""

from concurrent.futures import ThreadPoolExecutor

import pytest

import promising
from promising.sentinels import INHERIT

# ---------------------------------------------------------------------------
# @promising.function stacked twice
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_double_function_decorator_attrs_stay_independent() -> None:
    """Outer @promising.function attributes must not be clobbered by inner."""
    outer_pool = ThreadPoolExecutor(max_workers=1)
    inner_pool = ThreadPoolExecutor(max_workers=2)

    @promising.function(
        namespace="outer",
        start_soon=True,
        children_start_soon=True,
        start_soon_default=True,
        thread_pool=outer_pool,
    )
    @promising.function(
        namespace="inner",
        start_soon=False,
        children_start_soon=False,
        start_soon_default=False,
        thread_pool=inner_pool,
    )
    async def add(a: int, b: int) -> int:
        return a + b

    # The outermost wrapper is what `add` is bound to.
    assert add.namespace == "outer"
    assert add.start_soon is True
    assert add.children_start_soon is True
    assert add.start_soon_default is True
    assert add.thread_pool is outer_pool

    # The inner wrapper is accessible via __wrapped__.
    inner = add.__wrapped__
    assert inner.namespace == "inner"
    assert inner.start_soon is False
    assert inner.children_start_soon is False
    assert inner.start_soon_default is False
    assert inner.thread_pool is inner_pool

    # Sanity-check: the decorated function still works.
    result = add(1, 2)
    assert isinstance(result, promising.Promise)
    assert await result == 3


# ---------------------------------------------------------------------------
# @promising.context stacked twice
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_double_context_decorator_attrs_stay_independent() -> None:
    """Outer @promising.context attributes must not be clobbered by inner."""
    outer_pool = ThreadPoolExecutor(max_workers=1)
    inner_pool = ThreadPoolExecutor(max_workers=2)

    @promising.context(
        namespace="outer",
        children_start_soon=True,
        start_soon_default=True,
        thread_pool=outer_pool,
        parent=None,
    )
    @promising.context(
        namespace="inner",
        children_start_soon=False,
        start_soon_default=False,
        thread_pool=inner_pool,
    )
    async def add(a: int, b: int) -> int:
        return a + b

    # The outermost wrapper is what `add` is bound to.
    assert add.namespace == "outer"
    assert add.children_start_soon is True
    assert add.start_soon_default is True
    assert add.thread_pool is outer_pool
    assert add.parent is None

    # The inner wrapper is accessible via __wrapped__.
    inner = add.__wrapped__
    assert inner.namespace == "inner"
    assert inner.children_start_soon is False
    assert inner.start_soon_default is False
    assert inner.thread_pool is inner_pool
    assert inner.parent is INHERIT

    # Sanity-check: the decorated function still works.
    result = await add(1, 2)
    assert result == 3
