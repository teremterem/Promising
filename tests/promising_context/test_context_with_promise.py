import promising


async def test_nested_contexts_and_promise1() -> None:
    # TODO TODO TODO Streamline the assertions below

    @promising.function
    async def some_func() -> tuple[promising.PromisingContext, promising.PromisingContext]:
        with promising.context() as inner1:
            with promising.context() as inner2:
                return inner1, inner2

    with promising.context() as outer:
        inner1, inner2 = await some_func()

        assert inner1 is not inner2
        assert inner1 is not outer
        assert inner2 is not outer

        assert inner2.get_parent_context() is inner1
        assert inner2.get_parent_promise() is not inner1
        assert inner2.get_parent_promise() is inner1.get_parent_context()
        # Both inner contexts share the same parent promise
        assert inner2.get_parent_promise() is inner1.get_parent_promise()

        assert inner1.get_parent_promise() is inner1.get_parent_context()
        assert inner1.get_parent_promise().get_parent_context() is outer
        assert inner1.get_parent_promise().get_parent_promise(raise_if_none=False) is None

        assert outer.get_parent_context(raise_if_none=False) is None
        assert outer.get_parent_promise(raise_if_none=False) is None
