import promising
from tests.test_utils import collect_parent_contexts, collect_parent_promises


async def test_contexted_function_inside_outer_context() -> None:
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
