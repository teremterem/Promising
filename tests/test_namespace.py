"""
Tests for namespace resolution and its effect on __repr__ and __str__ across
Promises, PromisingFunctions, and promising.context instances.
"""

import re
import types

import pytest

import promising
from promising import UNCHANGED
from promising.utils import resolve_namespace

# ── resolve_namespace (unit) ────────────────────────────────────


def test_explicit_namespace_wins_over_fallback() -> None:
    """Explicitly provided namespace always takes priority."""

    async def some_func() -> None: ...

    result = resolve_namespace(
        provided_explicitly="custom",
        named_object_fallback=some_func,
    )
    assert result == "custom"


def test_explicit_namespace_wins_even_with_none_fallback() -> None:
    result = resolve_namespace(
        provided_explicitly="explicit",
        named_object_fallback=None,
    )
    assert result == "explicit"


def test_none_when_both_are_none() -> None:
    result = resolve_namespace(
        provided_explicitly=None,
        named_object_fallback=None,
    )
    assert result is None


def test_qualname_from_function() -> None:
    """Falls back to module::qualname for a plain function."""

    async def my_func() -> None: ...

    result = resolve_namespace(
        provided_explicitly=None,
        named_object_fallback=my_func,
    )
    assert result == "tests.test_namespace::test_qualname_from_function.<locals>.my_func"


def test_qualname_from_sync_function() -> None:
    def my_sync_func() -> None: ...

    result = resolve_namespace(
        provided_explicitly=None,
        named_object_fallback=my_sync_func,
    )
    assert result == "tests.test_namespace::test_qualname_from_sync_function.<locals>.my_sync_func"


async def test_qualname_from_async_generator_object() -> None:
    """Async generator *objects* have __qualname__ but not __module__.

    The ag_code path in resolve_namespace recovers the module from the
    code object, mirroring what cr_code does for coroutines.
    """

    async def gen():
        yield 1

    ag = gen()

    result = resolve_namespace(
        provided_explicitly=None,
        named_object_fallback=ag,
    )
    assert result == "tests.test_namespace::test_qualname_from_async_generator_object.<locals>.gen"
    # Close to avoid ResourceWarning
    await ag.aclose()


def test_qualname_from_class() -> None:
    """Classes have __qualname__ and __module__."""

    class Foo: ...

    result = resolve_namespace(
        provided_explicitly=None,
        named_object_fallback=Foo,
    )
    assert result == "tests.test_namespace::test_qualname_from_class.<locals>.Foo"


def test_qualname_from_method_of_class() -> None:
    class MyClass:
        def method(self) -> None: ...

    result = resolve_namespace(
        provided_explicitly=None,
        named_object_fallback=MyClass.method,
    )
    assert result == "tests.test_namespace::test_qualname_from_method_of_class.<locals>.MyClass.method"


def test_name_fallback_when_no_qualname() -> None:
    """Object with __name__ but no __qualname__ uses __name__."""
    ns = types.SimpleNamespace(__name__="simple_ns")
    # SimpleNamespace has neither __qualname__ nor __module__

    result = resolve_namespace(
        provided_explicitly=None,
        named_object_fallback=ns,
    )
    assert result == "simple_ns"


def test_name_fallback_with_module_but_no_qualname() -> None:
    """Object with __name__ and __module__ but no __qualname__."""
    ns = types.SimpleNamespace(__name__="my_thing", __module__="some.module")

    result = resolve_namespace(
        provided_explicitly=None,
        named_object_fallback=ns,
    )
    assert result == "some.module::my_thing"


# ── Promise.__repr__ and __str__ ────────────────────────────────


@pytest.mark.parametrize("use_repr", [True, False])
async def test_promise_repr_with_explicit_namespace(use_repr: bool) -> None:
    """Promise with explicit namespace shows it quoted before the class name."""
    promise = promising.Promise(prefilled_result="x", namespace="MyOp")

    result = repr(promise) if use_repr else str(promise)
    assert re.fullmatch(r"<'MyOp' Promise id=\d+>", result)
    await promise


@pytest.mark.parametrize("use_repr", [True, False])
async def test_promise_repr_without_namespace(use_repr: bool) -> None:
    """Prefilled promise with no namespace and no awaitable: bare repr."""
    promise = promising.Promise(prefilled_result="x")

    result = repr(promise) if use_repr else str(promise)
    assert re.fullmatch(r"<Promise id=\d+>", result)
    await promise


@pytest.mark.parametrize("use_repr", [True, False])
async def test_promise_repr_auto_resolves_from_coroutine(use_repr: bool) -> None:
    """Promise wrapping a coroutine auto-resolves namespace from its qualname.

    Coroutine objects have __qualname__ but NOT __module__. The module is
    recovered from the coroutine's underlying code object (cr_code), so the
    auto-resolved namespace includes the module prefix.
    """

    async def do_work() -> str:
        return "done"

    promise = promising.Promise(do_work())
    result = repr(promise) if use_repr else str(promise)
    assert re.fullmatch(
        r"<'tests\.test_namespace::test_promise_repr_auto_resolves_from_coroutine"
        r"\.<locals>\.do_work' Promise id=\d+>",
        result,
    )
    await promise


@pytest.mark.parametrize("use_repr", [True, False])
async def test_promise_repr_explicit_overrides_coroutine_name(use_repr: bool) -> None:
    """Explicit namespace wins even when a named coroutine is provided."""

    async def do_work() -> str:
        return "done"

    promise = promising.Promise(do_work(), namespace="Override")
    result = repr(promise) if use_repr else str(promise)
    assert re.fullmatch(r"<'Override' Promise id=\d+>", result)
    await promise


# ── PromisingFunction namespace ─────────────────────────────────


async def test_promising_function_auto_namespace() -> None:
    """@promising.function auto-resolves namespace to module::qualname."""

    @promising.function
    async def fetch_data() -> str:
        return "data"

    assert fetch_data.namespace == "tests.test_namespace::test_promising_function_auto_namespace.<locals>.fetch_data"


async def test_promising_function_explicit_namespace() -> None:
    """@promising.function(namespace=...) uses the exact string provided."""

    @promising.function(namespace="CustomNS")
    async def fetch_data() -> str:
        return "data"

    assert fetch_data.namespace == "CustomNS"


@pytest.mark.parametrize("use_repr", [True, False])
async def test_promising_function_promise_inherits_namespace(use_repr: bool) -> None:
    """Promise returned by a PromisingFunction carries its explicit namespace."""

    @promising.function(namespace="FetchOp")
    async def fetch() -> str:
        return "result"

    promise = fetch()
    result = repr(promise) if use_repr else str(promise)
    assert re.fullmatch(r"<'FetchOp' Promise id=\d+>", result)
    await promise


@pytest.mark.parametrize("use_repr", [True, False])
async def test_promising_function_auto_namespace_in_promise_repr(use_repr: bool) -> None:
    """Promise from @promising.function (no explicit ns) shows module::qualname."""

    @promising.function
    async def compute() -> int:
        return 42

    promise = compute()
    result = repr(promise) if use_repr else str(promise)
    assert re.fullmatch(
        r"<'tests.test_namespace::test_promising_function_auto_namespace_in_promise_repr"
        r"\.<locals>\.compute' Promise id=\d+>",
        result,
    )
    await promise


@pytest.mark.parametrize("use_repr", [True, False])
async def test_promising_function_namespace_override_at_call_time(use_repr: bool) -> None:
    """Namespace can be overridden per-call via keyword argument."""

    @promising.function(namespace="Default")
    async def work() -> str:
        return "done"

    promise = work(namespace="PerCall")
    result = repr(promise) if use_repr else str(promise)
    assert re.fullmatch(r"<'PerCall' Promise id=\d+>", result)
    await promise


@pytest.mark.parametrize("use_repr", [True, False])
async def test_promising_function_call_unchanged_namespace_uses_decorator_ns(use_repr: bool) -> None:
    """
    Passing namespace=UNCHANGED at call time falls back to decorator's namespace.
    """

    @promising.function(namespace="FromDecorator")
    async def work() -> str:
        return "done"

    promise = work(namespace=UNCHANGED)
    result = repr(promise) if use_repr else str(promise)
    assert re.fullmatch(r"<'FromDecorator' Promise id=\d+>", result)
    await promise


# ── promising.context namespace ─────────────────────────────────


@pytest.mark.parametrize("use_repr", [True, False])
async def test_context_manager_explicit_namespace(use_repr: bool) -> None:
    """promising.context() as context manager with explicit namespace."""
    with promising.context(namespace="BatchCtx") as ctx:
        assert ctx.namespace == "BatchCtx"
        result = repr(ctx) if use_repr else str(ctx)
        assert re.fullmatch(r"<'BatchCtx' PromisingContext id=\d+>", result)


@pytest.mark.parametrize("use_repr", [True, False])
async def test_context_manager_no_namespace(use_repr: bool) -> None:
    """promising.context() with no namespace: namespace is None."""
    with promising.context() as ctx:
        assert ctx.namespace is None
        result = repr(ctx) if use_repr else str(ctx)
        assert re.fullmatch(r"<PromisingContext id=\d+>", result)


@pytest.mark.parametrize("use_repr", [True, False])
@pytest.mark.parametrize("parametrized_decorator", [True, False])
async def test_context_decorator_auto_namespace(use_repr: bool, parametrized_decorator: bool) -> None:
    """@promising.context() as decorator auto-resolves to module::qualname."""
    captured_ctx = None
    ctx_decorator = promising.context() if parametrized_decorator else promising.context

    @ctx_decorator
    async def pipeline() -> str:
        nonlocal captured_ctx
        captured_ctx = promising.get_active_context()
        return "done"

    await pipeline()
    assert captured_ctx is not None
    assert captured_ctx.namespace == "tests.test_namespace::test_context_decorator_auto_namespace.<locals>.pipeline"
    result = repr(captured_ctx) if use_repr else str(captured_ctx)
    assert re.fullmatch(
        r"<'tests.test_namespace::test_context_decorator_auto_namespace"
        r"\.<locals>\.pipeline' PromisingContext id=\d+>",
        result,
    )


@pytest.mark.parametrize("use_repr", [True, False])
async def test_context_decorator_explicit_namespace(use_repr: bool) -> None:
    """@promising.context(namespace=...) as decorator uses the exact string."""
    captured_ctx = None

    @promising.context(namespace="MyPipeline")
    async def pipeline() -> str:
        nonlocal captured_ctx
        captured_ctx = promising.get_active_context()
        return "done"

    await pipeline()
    assert captured_ctx is not None
    assert captured_ctx.namespace == "MyPipeline"
    result = repr(captured_ctx) if use_repr else str(captured_ctx)
    assert re.fullmatch(
        r"<'MyPipeline' PromisingContext id=\d+>",
        result,
    )


# ── PromisingContext repr ───────────────────────────────────────


@pytest.mark.parametrize("use_repr", [True, False])
async def test_promising_context_repr_with_namespace(use_repr: bool) -> None:
    ctx = promising.PromisingContext(namespace="Worker")
    result = repr(ctx) if use_repr else str(ctx)
    assert re.fullmatch(r"<'Worker' PromisingContext id=\d+>", result)


@pytest.mark.parametrize("use_repr", [True, False])
async def test_promising_context_repr_without_namespace(use_repr: bool) -> None:
    ctx = promising.PromisingContext()
    result = repr(ctx) if use_repr else str(ctx)
    assert re.fullmatch(r"<PromisingContext id=\d+>", result)


# ── Method decorators and qualname ──────────────────────────────


@pytest.mark.parametrize("use_promise_repr", [True, False, None])
async def test_promising_function_on_instance_method_qualname(use_promise_repr: bool | None) -> None:
    """Decorating an instance method: namespace is module::Class.method."""

    class Service:
        @promising.function
        async def process(self) -> str:
            return "processed"

    if use_promise_repr is None:
        assert Service.process.namespace == (
            "tests.test_namespace::test_promising_function_on_instance_method_qualname.<locals>.Service.process"
        )

    svc = Service()
    promise = svc.process()

    if use_promise_repr is not None:
        result = repr(promise) if use_promise_repr else str(promise)
        assert re.fullmatch(
            r"<'tests.test_namespace::test_promising_function_on_instance_method_qualname\."
            r"<locals>\.Service\.process' Promise id=\d+>",
            result,
        )
    assert await promise == "processed"


@pytest.mark.parametrize("use_promise_repr", [True, False, None])
async def test_promising_function_on_static_method_qualname(use_promise_repr: bool | None) -> None:
    """Decorating a staticmethod: namespace is module::Class.method."""

    class Service:
        @promising.function
        @staticmethod
        async def helper() -> str:
            return "helped"

    if use_promise_repr is None:
        assert Service.helper.namespace == (
            "tests.test_namespace::test_promising_function_on_static_method_qualname.<locals>.Service.helper"
        )

    promise = Service.helper()

    if use_promise_repr is not None:
        result = repr(promise) if use_promise_repr else str(promise)
        assert re.fullmatch(
            r"<'tests.test_namespace::test_promising_function_on_static_method_qualname"
            r"\.<locals>\.Service\.helper' Promise id=\d+>",
            result,
        )
    assert await promise == "helped"


@pytest.mark.parametrize("use_promise_repr", [True, False, None])
async def test_promising_function_on_class_method_qualname(use_promise_repr: bool | None) -> None:
    """Decorating a classmethod: namespace is module::Class.method."""

    class Service:
        @promising.function
        @classmethod
        async def create(cls) -> str:
            return "created"

    if use_promise_repr is None:
        assert Service.create.namespace == (
            "tests.test_namespace::test_promising_function_on_class_method_qualname.<locals>.Service.create"
        )

    promise = Service.create()

    if use_promise_repr is not None:
        result = repr(promise) if use_promise_repr else str(promise)
        assert re.fullmatch(
            r"<'tests.test_namespace::test_promising_function_on_class_method_qualname"
            r"\.<locals>\.Service\.create' Promise id=\d+>",
            result,
        )
    assert await promise == "created"


# ── Inherited __module__ on plain instances (reviewer edge cases) ──


def test_plain_instance_inherits_module_from_class() -> None:
    """A plain instance of a user-defined class inherits __module__ from its
    class but has no __qualname__ or __name__ of its own.

    Current behavior: the inherited __module__ is used as prefix, and str(obj)
    becomes the name — producing something like
    "tests.test_namespace::<...SomeObject object at 0x...>".
    """

    class SomeObject:
        pass

    obj = SomeObject()

    # Verify the attribute inheritance that causes this:
    assert hasattr(obj, "__module__")  # inherited from SomeObject
    assert not hasattr(obj, "__qualname__")  # NOT inherited
    assert not hasattr(obj, "__name__")  # NOT inherited

    result = resolve_namespace(
        provided_explicitly=None,
        named_object_fallback=obj,
    )
    # The module prefix comes from the CLASS, not from the instance itself
    # TODO Do we even care about this edge case ?
    #  https://github.com/teremterem/Promising/pull/71/changes#r2930305198
    #  Maybe... if the object is awaitable... (and/or callable ?)
    assert re.fullmatch(
        r"tests\.test_namespace::<tests\.test_namespace\."
        r"test_plain_instance_inherits_module_from_class\.<locals>\.SomeObject object at 0x[0-9a-f]+>",
        result,
    )


def test_instance_with_name_inherits_module_from_class() -> None:
    """An instance that has __name__ set also inherits __module__ from its
    class.

    Current behavior: the class's __module__ is used as prefix together with
    the instance's __name__ — e.g. "tests.test_namespace::custom_name".
    The module refers to where the CLASS is defined, not where the instance's
    __name__ semantically belongs.
    """

    class Widget:
        pass

    obj = Widget()
    obj.__name__ = "custom_name"  # type: ignore[attr-defined]

    # Verify: __module__ is inherited, __name__ is instance-level
    assert hasattr(obj, "__module__")  # inherited from Widget
    assert not hasattr(obj, "__qualname__")  # NOT inherited
    assert obj.__name__ == "custom_name"  # type: ignore[attr-defined]

    result = resolve_namespace(
        provided_explicitly=None,
        named_object_fallback=obj,
    )
    # Module prefix comes from Widget's class, not the instance
    # TODO Do we even care about this edge case ?
    #  https://github.com/teremterem/Promising/pull/71/changes#r2930305198
    #  Maybe... if the object is awaitable... (and/or callable ?)
    assert result == "tests.test_namespace::custom_name"


def test_callable_instance_inherits_module_from_class() -> None:
    """A callable instance (with __call__) still inherits __module__ from its
    class but is not a function or type.

    Current behavior: treated like any other instance — the class's __module__
    is used as prefix even though the object is "just" a callable instance.
    """

    class Handler:
        def __call__(self) -> str:
            return "handled"

    handler = Handler()

    assert callable(handler)
    assert hasattr(handler, "__module__")  # inherited from Handler
    assert not hasattr(handler, "__qualname__")
    assert not hasattr(handler, "__name__")

    result = resolve_namespace(
        provided_explicitly=None,
        named_object_fallback=handler,
    )
    # TODO Do we even care about this edge case ?
    #  https://github.com/teremterem/Promising/pull/71/changes#r2930305198
    #  Maybe... if the object is awaitable... (and/or callable ?)
    assert re.fullmatch(
        r"tests\.test_namespace::<tests\.test_namespace\."
        r"test_callable_instance_inherits_module_from_class\.<locals>\.Handler object at 0x[0-9a-f]+>",
        result,
    )


def test_builtin_int_has_no_inherited_module() -> None:
    """Built-in type instances (int, str, list) do NOT inherit __module__.

    Unlike user-defined class instances, built-ins block attribute inheritance
    for __module__ and __qualname__, so no misleading prefix appears.
    """
    assert not hasattr(42, "__module__")
    assert not hasattr(42, "__qualname__")
    assert not hasattr(42, "__name__")

    result = resolve_namespace(
        provided_explicitly=None,
        named_object_fallback=42,
    )
    assert result == "42"


def test_builtin_str_has_no_inherited_module() -> None:
    assert not hasattr("hello", "__module__")
    assert not hasattr("hello", "__qualname__")

    result = resolve_namespace(
        provided_explicitly=None,
        named_object_fallback="hello",
    )
    assert result == "hello"


def test_builtin_list_has_no_inherited_module() -> None:
    assert not hasattr([], "__module__")
    assert not hasattr([], "__qualname__")

    result = resolve_namespace(
        provided_explicitly=None,
        named_object_fallback=[1, 2, 3],
    )
    assert result == "[1, 2, 3]"


# ── get_promising_trace ─────────────────────────────────────────


async def test_get_promising_trace_single_context() -> None:
    """A single context with no parent returns a one-element trace."""
    with promising.context(namespace="Root", parent=None) as ctx:
        trace = ctx.get_promising_trace()
        assert len(trace) == 1
        assert "'Root'" in trace[0]
        assert "PromisingContext" in trace[0]


async def test_get_promising_trace_nested_contexts() -> None:
    """Nested contexts produce a trace from topmost parent to innermost child."""
    with promising.context(namespace="Grandparent", parent=None):
        with promising.context(namespace="Parent"):
            with promising.context(namespace="Child") as c:
                trace = c.get_promising_trace()
                assert len(trace) == 3
                assert "'Grandparent'" in trace[0]
                assert "'Parent'" in trace[1]
                assert "'Child'" in trace[2]

                joined = "\n".join(trace)
                assert "Grandparent" in joined.split("\n")[0]
                assert "Child" in joined.split("\n")[2]


async def test_get_promising_trace_with_promise() -> None:
    """A Promise inside a context shows in the trace as the innermost entry."""
    with promising.context(namespace="Outer", parent=None):
        promise = promising.Promise(prefilled_result=42, namespace="MyPromise")
        trace = promise.get_promising_trace()
        assert len(trace) == 2
        assert "'Outer'" in trace[0]
        assert "'MyPromise'" in trace[1]
        assert "Promise" in trace[1]
        await promise


async def test_get_promising_trace_join_output() -> None:
    """Validate the output of '\\n'.join(ctx.get_promising_trace())."""
    with promising.context(namespace="App", parent=None):
        with promising.context(namespace="Service"):
            with promising.context(namespace="Handler") as handler:
                output = "\n".join(handler.get_promising_trace())
                lines = output.split("\n")
                assert len(lines) == 3
                assert re.fullmatch(r"<'App' PromisingContext id=\d+>", lines[0])
                assert re.fullmatch(r"<'Service' PromisingContext id=\d+>", lines[1])
                assert re.fullmatch(r"<'Handler' PromisingContext id=\d+>", lines[2])


async def test_get_promising_trace_no_namespace() -> None:
    """Contexts without namespaces still appear in the trace."""
    with promising.context(parent=None):
        with promising.context() as child:
            trace = child.get_promising_trace()
            assert len(trace) == 2
            assert re.fullmatch(r"<PromisingContext id=\d+>", trace[0])
            assert re.fullmatch(r"<PromisingContext id=\d+>", trace[1])


async def test_get_promising_trace_nested_promising_functions() -> None:
    """Nested @promising.function calls with auto-derived namespaces produce a
    correct trace from outermost to innermost."""
    captured_traces: dict[str, list[str]] = {}

    @promising.function
    async def outer() -> str:
        captured_traces["outer"] = promising.get_active_context().get_promising_trace()
        result = await middle()
        return result

    @promising.function
    async def middle() -> str:
        captured_traces["middle"] = promising.get_active_context().get_promising_trace()
        result = await inner()
        return result

    @promising.function
    async def inner() -> str:
        captured_traces["inner"] = promising.get_active_context().get_promising_trace()
        return "done"

    assert await outer() == "done"

    # outer is the root — one entry
    assert len(captured_traces["outer"]) == 1
    assert re.fullmatch(
        r"<'tests\.test_namespace::test_get_promising_trace_nested_promising_functions"
        r"\.<locals>\.outer' Promise id=\d+>",
        captured_traces["outer"][0],
    )

    # middle is a child of outer — two entries
    assert len(captured_traces["middle"]) == 2
    assert "outer' Promise" in captured_traces["middle"][0]
    assert "middle' Promise" in captured_traces["middle"][1]

    # inner is a child of middle — three entries
    inner_trace = captured_traces["inner"]
    assert len(inner_trace) == 3
    assert "outer' Promise" in inner_trace[0]
    assert "middle' Promise" in inner_trace[1]
    assert "inner' Promise" in inner_trace[2]

    # Validate joined output format
    output = "\n".join(inner_trace)
    lines = output.split("\n")
    assert len(lines) == 3
    for line in lines:
        assert re.fullmatch(
            r"<'tests\.test_namespace::test_get_promising_trace_nested_promising_functions"
            r"\.<locals>\.\w+' Promise id=\d+>",
            line,
        )


async def test_get_promising_trace_mixed_context_and_function() -> None:
    """A @promising.function nested inside a promising.context, with another
    @promising.function nested further, produces a mixed trace."""
    captured_trace: list[str] = []

    @promising.function
    async def do_work() -> str:
        captured_trace.extend(promising.get_active_context().get_promising_trace())
        return "result"

    with promising.context(namespace="AppCtx", parent=None):
        assert await do_work() == "result"

    assert len(captured_trace) == 2
    assert re.fullmatch(r"<'AppCtx' PromisingContext id=\d+>", captured_trace[0])
    assert re.fullmatch(
        r"<'tests\.test_namespace::test_get_promising_trace_mixed_context_and_function"
        r"\.<locals>\.do_work' Promise id=\d+>",
        captured_trace[1],
    )
