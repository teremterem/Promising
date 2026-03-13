"""
Tests for namespace resolution and its effect on __repr__ across
Promises, PromisingFunctions, and promising.context instances.
"""

import re
import types

import promising
from promising.sentinels import NOT_SET
from promising.utils import resolve_namespace

M = "tests.test_namespace"


# ── resolve_namespace (unit) ────────────────────────────────────


def test_explicit_namespace_wins_over_fallback() -> None:
    """Explicitly provided namespace always takes priority."""

    async def some_func() -> None: ...

    result = resolve_namespace(
        provided_explicitly="custom",
        named_object_fallback=some_func,
    )
    assert result == "custom"


def test_explicit_namespace_wins_even_with_not_set_fallback() -> None:
    result = resolve_namespace(
        provided_explicitly="explicit",
        named_object_fallback=NOT_SET,
    )
    assert result == "explicit"


def test_not_set_when_both_are_not_set() -> None:
    result = resolve_namespace(
        provided_explicitly=NOT_SET,
        named_object_fallback=NOT_SET,
    )
    assert result is NOT_SET


def test_qualname_from_function() -> None:
    """Falls back to module::qualname for a plain function."""

    async def my_func() -> None: ...

    result = resolve_namespace(
        provided_explicitly=NOT_SET,
        named_object_fallback=my_func,
    )
    assert result == "tests.test_namespace::test_qualname_from_function.<locals>.my_func"


def test_qualname_from_sync_function() -> None:
    def my_sync_func() -> None: ...

    result = resolve_namespace(
        provided_explicitly=NOT_SET,
        named_object_fallback=my_sync_func,
    )
    assert result == "tests.test_namespace::test_qualname_from_sync_function.<locals>.my_sync_func"


def test_qualname_from_class() -> None:
    """Classes have __qualname__ and __module__."""

    class Foo: ...

    result = resolve_namespace(
        provided_explicitly=NOT_SET,
        named_object_fallback=Foo,
    )
    assert result == "tests.test_namespace::test_qualname_from_class.<locals>.Foo"


def test_qualname_from_method_of_class() -> None:
    class MyClass:
        def method(self) -> None: ...

    result = resolve_namespace(
        provided_explicitly=NOT_SET,
        named_object_fallback=MyClass.method,
    )
    assert result == "tests.test_namespace::test_qualname_from_method_of_class.<locals>.MyClass.method"


def test_name_fallback_when_no_qualname() -> None:
    """Object with __name__ but no __qualname__ uses __name__."""
    ns = types.SimpleNamespace(__name__="simple_ns")
    # SimpleNamespace has neither __qualname__ nor __module__

    result = resolve_namespace(
        provided_explicitly=NOT_SET,
        named_object_fallback=ns,
    )
    assert result == "simple_ns"


def test_name_fallback_with_module_but_no_qualname() -> None:
    """Object with __name__ and __module__ but no __qualname__."""
    ns = types.SimpleNamespace(__name__="my_thing", __module__="some.module")

    result = resolve_namespace(
        provided_explicitly=NOT_SET,
        named_object_fallback=ns,
    )
    assert result == "some.module::my_thing"


def test_str_fallback_for_object_without_name_attrs() -> None:
    """Object with neither __name__ nor __qualname__ uses str()."""
    result = resolve_namespace(
        provided_explicitly=NOT_SET,
        named_object_fallback=42,
    )
    assert result == "42"


def test_str_fallback_for_string_object() -> None:
    result = resolve_namespace(
        provided_explicitly=NOT_SET,
        named_object_fallback="hello",
    )
    assert result == "hello"


def test_module_prefix_on_function() -> None:
    """Auto-resolved namespace is module::qualname."""

    def f() -> None: ...

    result = resolve_namespace(
        provided_explicitly=NOT_SET,
        named_object_fallback=f,
    )
    assert result == "tests.test_namespace::test_module_prefix_on_function.<locals>.f"


# ── Promise.__repr__ ────────────────────────────────────────────


async def test_promise_repr_with_explicit_namespace() -> None:
    """Promise with explicit namespace shows it quoted before the class name."""
    promise = promising.Promise(prefilled_result="x", namespace="MyOp")
    assert re.fullmatch(r"<'MyOp' Promise id=\d+>", repr(promise))
    await promise


async def test_promise_repr_without_namespace() -> None:
    """Prefilled promise with no namespace and no awaitable: bare repr."""
    promise = promising.Promise(prefilled_result="x")
    assert re.fullmatch(r"<Promise id=\d+>", repr(promise))
    await promise


async def test_promise_repr_auto_resolves_from_coroutine() -> None:
    """Promise wrapping a coroutine auto-resolves namespace from its qualname.

    Coroutine objects have __qualname__ but NOT __module__, so the
    auto-resolved namespace is just the qualname without a module prefix.
    """

    async def do_work() -> str:
        return "done"

    promise = promising.Promise(do_work())
    assert re.fullmatch(
        r"<'test_promise_repr_auto_resolves_from_coroutine"
        r"\.<locals>\.do_work' Promise id=\d+>",
        repr(promise),
    )
    await promise


async def test_promise_repr_explicit_overrides_coroutine_name() -> None:
    """Explicit namespace wins even when a named coroutine is provided."""

    async def do_work() -> str:
        return "done"

    promise = promising.Promise(do_work(), namespace="Override")
    assert re.fullmatch(r"<'Override' Promise id=\d+>", repr(promise))
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


async def test_promising_function_promise_inherits_namespace() -> None:
    """Promise returned by a PromisingFunction carries its explicit namespace."""

    @promising.function(namespace="FetchOp")
    async def fetch() -> str:
        return "result"

    promise = fetch()
    assert re.fullmatch(r"<'FetchOp' Promise id=\d+>", repr(promise))
    await promise


async def test_promising_function_auto_namespace_in_promise_repr() -> None:
    """Promise from @promising.function (no explicit ns) shows module::qualname."""

    @promising.function
    async def compute() -> int:
        return 42

    promise = compute()
    assert re.fullmatch(
        rf"<'{re.escape(M)}::test_promising_function_auto_namespace_in_promise_repr"
        r"\.<locals>\.compute' Promise id=\d+>",
        repr(promise),
    )
    await promise


async def test_promising_function_namespace_override_at_call_time() -> None:
    """Namespace can be overridden per-call via keyword argument."""

    @promising.function(namespace="Default")
    async def work() -> str:
        return "done"

    promise = work(namespace="PerCall")
    assert re.fullmatch(r"<'PerCall' Promise id=\d+>", repr(promise))
    await promise


async def test_promising_function_call_namespace_none_uses_decorator_ns() -> None:
    """Passing namespace=None at call time falls back to decorator's namespace."""

    @promising.function(namespace="FromDecorator")
    async def work() -> str:
        return "done"

    promise = work(namespace=None)
    assert re.fullmatch(r"<'FromDecorator' Promise id=\d+>", repr(promise))
    await promise


# ── promising.context namespace ─────────────────────────────────


async def test_context_manager_explicit_namespace() -> None:
    """promising.context() as context manager with explicit namespace."""
    with promising.context(namespace="BatchCtx") as ctx:
        assert ctx.namespace == "BatchCtx"
        assert re.fullmatch(r"<'BatchCtx' PromisingContext id=\d+>", repr(ctx))


async def test_context_manager_no_namespace() -> None:
    """promising.context() with no namespace: namespace is NOT_SET."""
    with promising.context() as ctx:
        assert ctx.namespace is NOT_SET
        assert re.fullmatch(r"<PromisingContext id=\d+>", repr(ctx))


async def test_context_decorator_auto_namespace() -> None:
    """@promising.context() as decorator auto-resolves to module::qualname."""
    captured_ctx = None

    @promising.context()
    async def pipeline() -> str:
        nonlocal captured_ctx
        captured_ctx = promising.get_active_context()
        return "done"

    await pipeline()
    assert captured_ctx is not None
    assert captured_ctx.namespace == "tests.test_namespace::test_context_decorator_auto_namespace.<locals>.pipeline"
    assert re.fullmatch(
        rf"<'{re.escape(M)}::test_context_decorator_auto_namespace"
        r"\.<locals>\.pipeline' PromisingContext id=\d+>",
        repr(captured_ctx),
    )


async def test_context_decorator_explicit_namespace() -> None:
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
    assert re.fullmatch(
        r"<'MyPipeline' PromisingContext id=\d+>",
        repr(captured_ctx),
    )


# ── PromisingContext repr ───────────────────────────────────────


async def test_promising_context_repr_with_namespace() -> None:
    ctx = promising.PromisingContext(namespace="Worker")
    assert re.fullmatch(r"<'Worker' PromisingContext id=\d+>", repr(ctx))


async def test_promising_context_repr_without_namespace() -> None:
    ctx = promising.PromisingContext()
    assert re.fullmatch(r"<PromisingContext id=\d+>", repr(ctx))


# ── Method decorators and qualname ──────────────────────────────


async def test_promising_function_on_instance_method_qualname() -> None:
    """Decorating an instance method: namespace is module::Class.method."""

    class Service:
        @promising.function
        async def process(self) -> str:
            return "processed"

    assert Service.process.namespace == (
        "tests.test_namespace::test_promising_function_on_instance_method_qualname.<locals>.Service.process"
    )
    svc = Service()
    assert await svc.process() == "processed"


async def test_promising_function_on_static_method_qualname() -> None:
    """Decorating a staticmethod: namespace is module::Class.method."""

    class Service:
        @promising.function
        @staticmethod
        async def helper() -> str:
            return "helped"

    assert Service.helper.namespace == (
        "tests.test_namespace::test_promising_function_on_static_method_qualname.<locals>.Service.helper"
    )
    assert await Service.helper() == "helped"


async def test_promising_function_on_class_method_qualname() -> None:
    """Decorating a classmethod: namespace is module::Class.method."""

    class Service:
        @promising.function
        @classmethod
        async def create(cls) -> str:
            return "created"

    assert Service.create.namespace == (
        "tests.test_namespace::test_promising_function_on_class_method_qualname.<locals>.Service.create"
    )
    assert await Service.create() == "created"
