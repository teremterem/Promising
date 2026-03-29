"""
Sync counterparts to test_nested_contexts_and_promises.py and
test_nested_contexts.py.

The decorated functions here are synchronous (plain `def`), but the parent-chain
rules are the same: parents are determined at call-site, and promises appear in
the chain while plain contexts do not count as promises.
"""

import promising
from tests.utils_for_tests import collect_parent_contexts, collect_parent_promises


async def test_promise_inside_outer_context() -> None:
    """
    Sync promising function called and awaited inside an outer context.

    The decorated function is synchronous, but calling it still produces a
    promise that must be awaited. The promise captures `outer` at call-site.

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
    Sync promising function called outside any context, awaited inside one.

    The decorated function is synchronous, but calling it still produces a
    promise. Because the promise is *called* with no active context, it has no
    parent — the outer context active at await-time is irrelevant.

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
    Sync promising function called inside an outer context, awaited outside.

    The decorated function is synchronous, but calling it still produces a
    promise. The parent is determined at call-site, so `outer` is captured even
    though the await happens after `outer` has exited.

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
    Sync contexted function called inside an outer context.

    func_ctx captures `outer` as its parent at call-site. The sync function
    returns directly (no await).

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
