import pytest

import promising
from tests.utils_for_tests import normalize_object_repr


async def test_get_trace_single_context() -> None:
    """A single context with no parent returns a one-element trace."""
    with promising.context(namespace="Root") as ctx:
        trace = ctx.get_trace()
        assert isinstance(trace, list)
        assert len(trace) == 1
        assert trace[0] is ctx


@pytest.mark.parametrize("parents_first", [True, False], ids=["parents_first", "children_first"])
async def test_get_trace_with_promise(parents_first: bool) -> None:
    """A Promise inside a context shows in the trace as the innermost entry."""
    with promising.context(namespace="Outer") as outer:
        promise = promising.Promise(prefilled_result=42, namespace="MyPromise")
        trace = promise.get_trace(parents_first=parents_first)
        assert isinstance(trace, list)
        assert len(trace) == 2
        if parents_first:
            assert trace[0] is outer
            assert trace[1] is promise
        else:
            assert trace[0] is promise
            assert trace[1] is outer
        await promise


@pytest.mark.parametrize(
    ("parents_first", "expected"),
    [
        (
            True,
            [
                "<'App' PromisingContext id=999>",
                "<'Service' PromisingContext id=999>",
                "<'Handler' PromisingContext id=999>",
            ],
        ),
        (
            False,
            [
                "<'Handler' PromisingContext id=999>",
                "<'Service' PromisingContext id=999>",
                "<'App' PromisingContext id=999>",
            ],
        ),
    ],
    ids=["parents_first", "children_first"],
)
async def test_format_trace_nested_contexts(parents_first: bool, expected: list[str]) -> None:
    """format_trace returns string representations in the requested order."""
    with promising.context(namespace="App"):
        with promising.context(namespace="Service"):
            with promising.context(namespace="Handler") as handler:
                trace_strs = handler.format_trace(parents_first=parents_first)
                assert isinstance(trace_strs, list)
                assert [normalize_object_repr(s) for s in trace_strs] == expected


async def test_format_trace_no_namespace() -> None:
    """Contexts without namespaces still appear in the trace."""
    with promising.context():
        with promising.context() as child:
            trace_strs = child.format_trace()
            assert isinstance(trace_strs, list)
            assert [normalize_object_repr(s) for s in trace_strs] == [
                "<PromisingContext id=999>",
                "<PromisingContext id=999>",
            ]


async def test_format_trace_nested_promising_functions() -> None:
    """Nested @promising.function and @promising.context calls with auto-derived
    namespaces produce a correct trace from outermost to innermost."""
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
    outer_trace_strs = outer_promise.format_trace()
    assert isinstance(outer_trace_strs, list)
    assert [normalize_object_repr(s) for s in outer_trace_strs] == [
        "<'test_traces::test_format_trace_nested_promising_functions.<locals>.outer' Promise id=999>",
    ]

    # inner is at the bottom — four entries
    assert innermost_promise is not None
    inner_trace_strs = innermost_promise.format_trace()
    assert isinstance(inner_trace_strs, list)
    assert [normalize_object_repr(s) for s in inner_trace_strs] == [
        "<'test_traces::test_format_trace_nested_promising_functions.<locals>.outer' Promise id=999>",
        "<'test_traces::test_format_trace_nested_promising_functions.<locals>.middle_ctx' PromisingContext id=999>",
        "<'test_traces::test_format_trace_nested_promising_functions.<locals>.middle_fn' Promise id=999>",
        "<'test_traces::test_format_trace_nested_promising_functions.<locals>.inner' Promise id=999>",
    ]
