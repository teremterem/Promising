"""
Tests for parent-chain resolution when decorated functions contain nested
contexts.

Parent linkage is always determined at *call-site*, never at resolve-site. Both
@promising.function (creates a promise) and @promising.context (creates a plain
context) follow this rule. Each decorator is tested across three scenarios that
vary where the call and resolve happen relative to an outer context:

1. Called and resolved inside an outer context — outer IS a parent.
2. Called outside, resolved inside an outer context — outer is NOT a parent.
3. Called inside, resolved outside an outer context — outer IS still a parent.

The @promising.function tests assert the promise appears in the parent chain;
the @promising.context tests assert no promises appear at all.
"""

import promising
from tests.utils_for_tests import collect_parent_contexts, collect_parent_promises


async def test_promise_inside_outer_context() -> None:
    """
    Promise created and awaited inside an outer context.

    The promise captures `outer` as its parent at call-site.

    Expected parent chain for inner3:
        inner3 -> inner2 -> inner1 -> promise -> outer
    """

    @promising.function(use_thread_pool=True)
    def some_func() -> tuple[promising.PromisingContext, promising.PromisingContext, promising.PromisingContext]:
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


async def test_promise_outside_outer_context() -> None:
    """
    Promise created outside any context, then awaited inside one.

    Because the promise is *called* with no active context, it has no parent
    context — the outer context active at await-time is irrelevant.

    Expected parent chain for inner3:
        inner3 -> inner2 -> inner1 -> promise   (no outer)
    """

    @promising.function(use_thread_pool=True)
    def some_func() -> tuple[promising.PromisingContext, promising.PromisingContext, promising.PromisingContext]:
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


async def test_promise_await_outside_outer_context() -> None:
    """
    Promise created inside an outer context, then awaited outside it.

    The parent is determined at call-site, so `outer` is captured even though
    the await happens after `outer` has exited.

    Expected parent chain for inner3:
        inner3 -> inner2 -> inner1 -> promise -> outer
    """

    @promising.function(use_thread_pool=True)
    def some_func() -> tuple[promising.PromisingContext, promising.PromisingContext, promising.PromisingContext]:
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


async def test_contexted_function_inside_outer_context() -> None:
    """
    Contexted function called and awaited inside an outer context.

    func_ctx captures `outer` as its parent at call-site.

    Expected parent chain for inner3:
        inner3 -> inner2 -> inner1 -> func_ctx -> outer
    """
    func_ctx = None

    @promising.context
    def some_func() -> tuple[promising.PromisingContext, promising.PromisingContext, promising.PromisingContext]:
        nonlocal func_ctx
        func_ctx = promising.get_active_context()

        with promising.context() as inner1:
            with promising.context() as inner2:
                with promising.context() as inner3:
                    return inner1, inner2, inner3

    with promising.context() as outer:
        inner1, inner2, inner3 = some_func()

    inner3_parent_contexts = collect_parent_contexts(inner3)
    inner3_parent_promises = collect_parent_promises(inner3)

    assert inner3_parent_contexts == [inner2, inner1, func_ctx, outer]
    assert inner3_parent_promises == []
