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


"""
Tests for parent-chain resolution when @promising.context-decorated functions
contain nested contexts.

Unlike @promising.function (which creates a promise), @promising.context used
as a decorator creates a plain context — so there are no promises in the parent
chain. The decorator's context (func_ctx) becomes the immediate parent of inner
contexts, and func_ctx itself links to whichever context was active at
*call-site*.

These tests mirror the three scenarios in test_nested_contexts_and_promises.py
(NOTE for AI agent doing the refactoring: these tests are now in this same
file, above this docstring),
but with @promising.context instead of @promising.function.
"""


async def test_contexted_function_inside_outer_context() -> None:
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


async def test_contexted_function_outside_outer_context() -> None:
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


async def test_contexted_function_await_outside_outer_context() -> None:
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
