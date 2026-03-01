"""
Tests for parent-chain resolution when promises (@promising.function) contain
nested contexts.

A promise acts as both a context and a boundary: inner contexts see the promise
in their parent chain, and the promise itself links to whichever context was
active at *call-site* (not at await-site). These tests verify that relationship
across three scenarios:

- Promise created and awaited inside an outer context.
- Promise created outside, awaited inside an outer context (outer is NOT a
  parent).
- Promise created inside, awaited outside an outer context (outer IS still a
  parent).
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


async def test_promise_outside_outer_context() -> None:
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


async def test_promise_await_outside_outer_context() -> None:
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
