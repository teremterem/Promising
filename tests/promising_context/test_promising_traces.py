import promising
from tests.utils_for_tests import normalize_object_repr


async def test_get_promising_trace_single_context() -> None:
    """A single context with no parent returns a one-element trace."""
    with promising.context(namespace="Root") as ctx:
        trace = ctx.get_promising_trace()
        assert isinstance(trace, list)
        assert len(trace) == 1
        assert trace[0] is ctx


async def test_get_promising_trace_with_promise() -> None:
    """A Promise inside a context shows in the trace as the innermost entry."""
    with promising.context(namespace="Outer") as outer:
        promise = promising.Promise(prefilled_result=42, namespace="MyPromise")
        trace = promise.get_promising_trace()
        assert isinstance(trace, list)
        assert len(trace) == 2
        assert trace[0] is outer
        assert trace[1] is promise
        await promise


async def test_get_promising_trace_repr_nested_contexts() -> None:
    """get_promising_trace_repr returns string representations top-to-bottom."""
    with promising.context(namespace="App"):
        with promising.context(namespace="Service"):
            with promising.context(namespace="Handler") as handler:
                trace_repr = handler.get_promising_trace_repr()
                assert isinstance(trace_repr, list)
                assert [normalize_object_repr(s) for s in trace_repr] == [
                    "<'App' PromisingContext id=999>",
                    "<'Service' PromisingContext id=999>",
                    "<'Handler' PromisingContext id=999>",
                ]


async def test_get_promising_trace_repr_no_namespace() -> None:
    """Contexts without namespaces still appear in the trace repr."""
    with promising.context():
        with promising.context() as child:
            trace_repr = child.get_promising_trace_repr()
            assert isinstance(trace_repr, list)
            assert [normalize_object_repr(s) for s in trace_repr] == [
                "<PromisingContext id=999>",
                "<PromisingContext id=999>",
            ]


async def test_get_promising_trace_repr_nested_promising_functions() -> None:
    """Nested @promising.function and @promising.context calls with auto-derived
    namespaces produce a correct trace repr from outermost to innermost."""
    innermost_promise = None

    @promising.function
    async def outer() -> str:
        return await middle_ctx()

    @promising.context
    async def middle_ctx() -> str:
        return await middle_fn()

    @promising.function
    async def middle_fn() -> str:
        return await inner()

    @promising.function
    async def inner() -> str:
        nonlocal innermost_promise
        innermost_promise = promising.get_active_context()
        return "done"

    outer_promise = outer()
    assert await outer_promise == "done"

    # outer is the root — one entry
    outer_trace_repr = outer_promise.get_promising_trace_repr()
    assert isinstance(outer_trace_repr, list)
    assert [normalize_object_repr(s) for s in outer_trace_repr] == [
        "<'test_promising_traces::test_get_promising_trace_repr_nested_promising_functions.<locals>.outer'"
        " Promise id=999>",
    ]

    # inner is at the bottom — four entries
    assert innermost_promise is not None
    inner_trace_repr = innermost_promise.get_promising_trace_repr()
    assert isinstance(inner_trace_repr, list)
    assert [normalize_object_repr(s) for s in inner_trace_repr] == [
        "<'test_promising_traces::test_get_promising_trace_repr_nested_promising_functions.<locals>.outer'"
        " Promise id=999>",
        "<'test_promising_traces::test_get_promising_trace_repr_nested_promising_functions.<locals>.middle_ctx'"
        " PromisingContext id=999>",
        "<'test_promising_traces::test_get_promising_trace_repr_nested_promising_functions.<locals>.middle_fn'"
        " Promise id=999>",
        "<'test_promising_traces::test_get_promising_trace_repr_nested_promising_functions.<locals>.inner'"
        " Promise id=999>",
    ]
