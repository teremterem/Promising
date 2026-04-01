"""
Tests for detecting cyclic promise resolution.

When a Promise resolves to itself (directly or through a chain), the library
should raise a clear error instead of hitting infinite recursion.

TODO Unskip tests after the following issue is taken care of:
https://github.com/teremterem/Promising/issues/66
"""

import pytest

import promising


@pytest.mark.skip(reason="Cycle detection not implemented yet (issue #66)")
@pytest.mark.parametrize("await_before_return", [False, True], ids=["return_as_is", "await_first"])
async def test_promise_resolving_to_itself(await_before_return: bool) -> None:
    """
    A promising function that returns get_active_promise() creates a
    direct self-reference: the promise resolves to itself. Awaiting it
    should raise a clear error, not RecursionError.
    """

    @promising.function
    async def self_referencing() -> promising.Promise:
        p = promising.get_active_promise()
        if await_before_return:
            return await p
        return p

    promise = self_referencing()
    # TODO Replace PromisingError with the dedicated cycle error once defined
    with pytest.raises(promising.PromisingError):
        await promise


@pytest.mark.skip(reason="Cycle detection not implemented yet (issue #66)")
@pytest.mark.parametrize("await_before_return", [False, True], ids=["return_as_is", "await_first"])
async def test_inner_returns_parent_promise(await_before_return: bool) -> None:
    """
    An inner promising function returns get_parent_promise(), which is the
    outer promise. When the outer awaits the inner, unpacking leads back to
    the outer — a cycle.
    """

    @promising.function
    async def inner() -> promising.Promise:
        p = promising.get_active_promise().get_parent_promise()
        if await_before_return:
            return await p
        return p

    @promising.function
    async def outer() -> promising.Promise:
        return await inner()

    promise = outer()
    # TODO Replace PromisingError with the dedicated cycle error once defined
    with pytest.raises(promising.PromisingError):
        await promise


@pytest.mark.skip(reason="Cycle detection not implemented yet (issue #66)")
@pytest.mark.parametrize("await_before_return", [False, True], ids=["return_as_is", "await_first"])
async def test_indirect_promise_cycle(await_before_return: bool) -> None:
    """
    Two promising functions that return each other's promises form an
    indirect cycle. Awaiting either should raise a clear error, not
    RecursionError.
    """

    @promising.function
    async def func_a() -> promising.Promise:
        p = func_b()
        if await_before_return:
            return await p
        return p

    @promising.function
    async def func_b() -> promising.Promise:
        p = promising.get_active_promise()
        if await_before_return:
            return await p
        return p

    promise_a = func_a()
    # TODO Replace PromisingError with the dedicated cycle error once defined
    with pytest.raises(promising.PromisingError):
        await promise_a
