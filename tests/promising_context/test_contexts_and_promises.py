import promising


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

        inner3_parent_contexts = _collect_parent_contexts(inner3)
        inner3_parent_promises = _collect_parent_promises(inner3)

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

        inner3_parent_contexts = _collect_parent_contexts(inner3)
        inner3_parent_promises = _collect_parent_promises(inner3)

        assert inner3_parent_contexts == [inner2, inner1, promise]
        assert inner3_parent_promises == [promise]


def _collect_parent_contexts(ctx: promising.PromisingContext) -> list[promising.PromisingContext]:
    result = []
    while (parent := ctx.get_parent_context(raise_if_none=False)) is not None:
        result.append(parent)
        ctx = parent
    return result


def _collect_parent_promises(ctx: promising.PromisingContext) -> list[promising.PromisingContext]:
    result = []
    while (parent := ctx.get_parent_promise(raise_if_none=False)) is not None:
        result.append(parent)
        ctx = parent
    return result
