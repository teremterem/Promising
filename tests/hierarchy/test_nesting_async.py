"""
Tests for parent-chain resolution when decorated functions contain nested
contexts.

Parent linkage is always determined at *call-site*, never at await-site. Both
@promising.function (creates a promise) and @promising.context (creates a plain
context) follow this rule. Each decorator is tested across three scenarios that
vary where the call and await happen relative to an outer context:

1. Called and awaited inside an outer context — outer IS a parent.
2. Called outside, awaited inside an outer context — outer is NOT a parent.
3. Called inside, awaited outside an outer context — outer IS still a parent.

The @promising.function tests assert the promise appears in the parent chain;
the @promising.context tests assert no promises appear at all.
"""

import promising
from tests.utils_for_tests import collect_parent_contexts, collect_parent_promises


async def test_promising_function_called_and_awaited_inside() -> None:
    """
    Promise created and awaited inside an outer context.

    The promise captures `outer` as its parent at call-site.

    Expected parent chain for inner3:
        inner3 -> inner2 -> inner1 -> promise -> outer
    """

    @promising.function
    async def some_func() -> tuple[promising.PromisingContext, promising.PromisingContext, promising.PromisingContext]:
        with promising.context() as inner1:
            with promising.context() as inner2:
                with promising.context() as inner3:
                    return inner1, inner2, inner3

    with promising.context() as outer:
        promise = some_func()
        inner1, inner2, inner3 = await promise

    inner3_parent_contexts = collect_parent_contexts(inner3)
    inner3_parent_promises = collect_parent_promises(inner3)

    assert inner3_parent_contexts == [inner2, inner1, promise, outer]
    assert inner3_parent_promises == [promise]


async def test_promising_function_called_outside_awaited_inside() -> None:
    """
    Promise created outside any context, then awaited inside one.

    Because the promise is *called* with no active context, it has no parent
    context — the outer context active at await-time is irrelevant.

    Expected parent chain for inner3:
        inner3 -> inner2 -> inner1 -> promise   (no outer)
    """

    @promising.function
    async def some_func() -> tuple[promising.PromisingContext, promising.PromisingContext, promising.PromisingContext]:
        with promising.context() as inner1:
            with promising.context() as inner2:
                with promising.context() as inner3:
                    return inner1, inner2, inner3

    promise = some_func()
    with promising.context():
        inner1, inner2, inner3 = await promise

    inner3_parent_contexts = collect_parent_contexts(inner3)
    inner3_parent_promises = collect_parent_promises(inner3)

    assert inner3_parent_contexts == [inner2, inner1, promise]
    assert inner3_parent_promises == [promise]


async def test_promising_function_called_inside_awaited_outside() -> None:
    """
    Promise created inside an outer context, then awaited outside it.

    The parent is determined at call-site, so `outer` is captured even though
    the await happens after `outer` has exited.

    Expected parent chain for inner3:
        inner3 -> inner2 -> inner1 -> promise -> outer
    """

    @promising.function
    async def some_func() -> tuple[promising.PromisingContext, promising.PromisingContext, promising.PromisingContext]:
        with promising.context() as inner1:
            with promising.context() as inner2:
                with promising.context() as inner3:
                    return inner1, inner2, inner3

    with promising.context() as outer:
        promise = some_func()
    inner1, inner2, inner3 = await promise

    inner3_parent_contexts = collect_parent_contexts(inner3)
    inner3_parent_promises = collect_parent_promises(inner3)

    assert inner3_parent_contexts == [inner2, inner1, promise, outer]
    assert inner3_parent_promises == [promise]


async def test_promising_context_called_and_awaited_inside() -> None:
    """
    Contexted function called and awaited inside an outer context.

    func_ctx captures `outer` as its parent at call-site.

    Expected parent chain for inner3:
        inner3 -> inner2 -> inner1 -> func_ctx -> outer
    """
    func_ctx = None

    @promising.context
    async def some_func() -> tuple[promising.PromisingContext, promising.PromisingContext, promising.PromisingContext]:
        nonlocal func_ctx
        func_ctx = promising.get_active_context()

        with promising.context() as inner1:
            with promising.context() as inner2:
                with promising.context() as inner3:
                    return inner1, inner2, inner3

    with promising.context() as outer:
        inner1, inner2, inner3 = await some_func()

    inner3_parent_contexts = collect_parent_contexts(inner3)
    inner3_parent_promises = collect_parent_promises(inner3)

    assert inner3_parent_contexts == [inner2, inner1, func_ctx, outer]
    assert inner3_parent_promises == []


async def test_promising_context_called_outside_awaited_inside() -> None:
    """
    Contexted function called outside any context, awaited inside one.

    Because the coroutine is *created* with no active context, func_ctx has no
    parent — the outer context active at await-time is irrelevant.

    Expected parent chain for inner3:
        inner3 -> inner2 -> inner1 -> func_ctx   (no outer)
    """
    func_ctx = None

    @promising.context
    async def some_func() -> tuple[promising.PromisingContext, promising.PromisingContext, promising.PromisingContext]:
        nonlocal func_ctx
        func_ctx = promising.get_active_context()

        with promising.context() as inner1:
            with promising.context() as inner2:
                with promising.context() as inner3:
                    return inner1, inner2, inner3

    coro = some_func()
    with promising.context():
        inner1, inner2, inner3 = await coro

    inner3_parent_contexts = collect_parent_contexts(inner3)
    inner3_parent_promises = collect_parent_promises(inner3)

    assert inner3_parent_contexts == [inner2, inner1, func_ctx]
    assert inner3_parent_promises == []


async def test_promising_context_called_inside_awaited_outside() -> None:
    """
    Contexted function called inside an outer context, awaited outside it.

    The parent is determined at call-site, so func_ctx captures `outer` even
    though the await happens after `outer` has exited.

    Expected parent chain for inner3:
        inner3 -> inner2 -> inner1 -> func_ctx -> outer
    """
    func_ctx = None

    @promising.context
    async def some_func() -> tuple[promising.PromisingContext, promising.PromisingContext, promising.PromisingContext]:
        nonlocal func_ctx
        func_ctx = promising.get_active_context()

        with promising.context() as inner1:
            with promising.context() as inner2:
                with promising.context() as inner3:
                    return inner1, inner2, inner3

    with promising.context() as outer:
        coro = some_func()
    inner1, inner2, inner3 = await coro

    inner3_parent_contexts = collect_parent_contexts(inner3)
    inner3_parent_promises = collect_parent_promises(inner3)

    assert inner3_parent_contexts == [inner2, inner1, func_ctx, outer]
    assert inner3_parent_promises == []
