import promising
from tests.test_utils import collect_parent_contexts, collect_parent_promises


async def test_promise_inside_outer_context() -> None:
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
