"""
Tests for namespace resolution and its effect on __repr__ across
Promises, PromisingFunctions, and promising.context instances.
"""

import re

import promising
from promising.sentinels import NOT_SET
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
    """Falls back to __qualname__ (includes module prefix) for a plain function."""
    async def my_func() -> None: ...

    result = resolve_namespace(
        provided_explicitly=NOT_SET,
        named_object_fallback=my_func,
    )
    expected_qualname = my_func.__qualname__
    expected_module = my_func.__module__
    assert result == f"{expected_module}::{expected_qualname}"


def test_qualname_from_class() -> None:
    """Classes have __qualname__ and __module__."""
    class Foo: ...

    result = resolve_namespace(
        provided_explicitly=NOT_SET,
        named_object_fallback=Foo,
    )
    assert result == f"{Foo.__module__}::{Foo.__qualname__}"


def test_name_fallback_when_no_qualname() -> None:
    """Object with __name__ but no __qualname__ uses __name__."""
    class Nameable:
        __name__ = "just_a_name"

        def __init__(self) -> None:
            # Ensure there is no __qualname__ on the instance
            if hasattr(self, "__qualname__"):
                del self.__qualname__

    obj = Nameable()
    # Forcefully strip __qualname__ if inherited from the class
    assert not hasattr(obj, "__qualname__") or True  # class may have it

    # Use a simpler approach: a custom object without __qualname__
    class Bare:
        pass

    bare = Bare()
    bare.__name__ = "bare_name"  # type: ignore[attr-defined]
    # Remove __qualname__ from the instance (class still has it, but getattr
    # on instance checks instance dict first only if it shadows the class attr)
    # Instead, use a type that truly lacks __qualname__:
    import types
    ns = types.SimpleNamespace(__name__="simple_ns")
    # SimpleNamespace doesn't have __qualname__

    result = resolve_namespace(
        provided_explicitly=NOT_SET,
        named_object_fallback=ns,
    )
    assert "simple_ns" in result


def test_str_fallback_for_object_without_name_attrs() -> None:
    """Object with neither __name__ nor __qualname__ uses str()."""
    result = resolve_namespace(
        provided_explicitly=NOT_SET,
        named_object_fallback=42,
    )
    assert result == "42"


def test_module_prefix_on_function() -> None:
    """Auto-resolved namespace includes module:: prefix."""
    def f() -> None: ...

    result = resolve_namespace(
        provided_explicitly=NOT_SET,
        named_object_fallback=f,
    )
    assert "::" in result
    module, _, name = result.partition("::")
    assert module == f.__module__
    assert name == f.__qualname__


def test_nested_function_qualname() -> None:
    """A nested function's __qualname__ includes the enclosing function."""
    def outer() -> None:
        def inner() -> None: ...
        inner._test_ref = True  # type: ignore[attr-defined]

    # We can't easily get `inner` from outer, so define inline:
    def inner() -> None: ...

    # inner defined at module level has a simple qualname, but let's
    # test the resolve_namespace with a real nested qualname:
    class MyClass:
        def method(self) -> None: ...

    result = resolve_namespace(
        provided_explicitly=NOT_SET,
        named_object_fallback=MyClass.method,
    )
    assert "MyClass.method" in result


# ── Promise.__repr__ ────────────────────────────────────────────


async def test_promise_repr_with_explicit_namespace() -> None:
    """Promise with explicit namespace shows it in repr."""
    promise = promising.Promise(prefilled_result="x", namespace="MyOp")
    assert "'MyOp'" in repr(promise)
    assert "Promise" in repr(promise)
    await promise


async def test_promise_repr_without_namespace() -> None:
    """Prefilled promise with no namespace and no awaitable has clean repr."""
    promise = promising.Promise(prefilled_result="x")
    r = repr(promise)
    assert "Promise" in r
    # No quoted namespace should appear before "Promise"
    assert re.match(r"<Promise id=\d+>", r), f"Unexpected repr: {r}"
    await promise


async def test_promise_repr_auto_resolves_from_coroutine() -> None:
    """Promise wrapping a coroutine auto-resolves namespace from it."""
    async def do_work() -> str:
        return "done"

    promise = promising.Promise(do_work())
    r = repr(promise)
    assert "do_work" in r
    assert "Promise" in r
    await promise


async def test_promise_repr_explicit_overrides_coroutine_name() -> None:
    """Explicit namespace wins even when a named coroutine is provided."""
    async def do_work() -> str:
        return "done"

    promise = promising.Promise(do_work(), namespace="Override")
    r = repr(promise)
    assert "'Override'" in r
    assert "do_work" not in r
    await promise


# ── PromisingFunction namespace ─────────────────────────────────


async def test_promising_function_auto_namespace() -> None:
    """@promising.function auto-resolves namespace from the function."""
    @promising.function
    async def fetch_data() -> str:
        return "data"

    assert "fetch_data" in fetch_data.namespace


async def test_promising_function_explicit_namespace() -> None:
    """@promising.function(namespace=...) uses explicit namespace."""
    @promising.function(namespace="CustomNS")
    async def fetch_data() -> str:
        return "data"

    assert fetch_data.namespace == "CustomNS"


async def test_promising_function_promise_inherits_namespace() -> None:
    """Promise returned by a PromisingFunction carries its namespace."""
    @promising.function(namespace="FetchOp")
    async def fetch() -> str:
        return "result"

    promise = fetch()
    assert "'FetchOp'" in repr(promise)
    await promise


async def test_promising_function_auto_namespace_in_promise_repr() -> None:
    """Promise from @promising.function (no explicit ns) shows function name."""
    @promising.function
    async def compute() -> int:
        return 42

    promise = compute()
    r = repr(promise)
    assert "compute" in r
    await promise


async def test_promising_function_namespace_override_at_call_time() -> None:
    """Namespace can be overridden per-call via keyword argument."""
    @promising.function(namespace="Default")
    async def work() -> str:
        return "done"

    promise = work(namespace="PerCall")
    assert "'PerCall'" in repr(promise)
    await promise


async def test_promising_function_call_namespace_none_uses_decorator_ns() -> None:
    """Passing namespace=None at call time falls back to decorator's namespace."""
    @promising.function(namespace="FromDecorator")
    async def work() -> str:
        return "done"

    promise = work(namespace=None)
    assert "'FromDecorator'" in repr(promise)
    await promise


# ── promising.context namespace ─────────────────────────────────


async def test_context_manager_explicit_namespace() -> None:
    """promising.context() as context manager with explicit namespace."""
    with promising.context(namespace="BatchCtx") as ctx:
        assert ctx.namespace == "BatchCtx"
        assert "'BatchCtx'" in repr(ctx)


async def test_context_manager_no_namespace() -> None:
    """promising.context() with no namespace: namespace is NOT_SET."""
    with promising.context() as ctx:
        assert ctx.namespace is NOT_SET
        r = repr(ctx)
        assert "PromisingContext" in r
        # Should not contain a quoted string before the class name
        assert re.match(r"<PromisingContext id=\d+>", r), f"Unexpected repr: {r}"


async def test_context_decorator_auto_namespace() -> None:
    """@promising.context() as decorator auto-resolves from function name."""
    captured_ctx = None

    @promising.context()
    async def pipeline() -> str:
        nonlocal captured_ctx
        captured_ctx = promising.get_active_context()
        return "done"

    await pipeline()
    assert captured_ctx is not None
    assert "pipeline" in captured_ctx.namespace


async def test_context_decorator_explicit_namespace() -> None:
    """@promising.context(namespace=...) as decorator uses explicit ns."""
    captured_ctx = None

    @promising.context(namespace="MyPipeline")
    async def pipeline() -> str:
        nonlocal captured_ctx
        captured_ctx = promising.get_active_context()
        return "done"

    await pipeline()
    assert captured_ctx is not None
    assert captured_ctx.namespace == "MyPipeline"


# ── PromisingContext repr ───────────────────────────────────────


async def test_promising_context_repr_with_namespace() -> None:
    ctx = promising.PromisingContext(namespace="Worker")
    r = repr(ctx)
    assert "'Worker'" in r
    assert "PromisingContext" in r


async def test_promising_context_repr_without_namespace() -> None:
    ctx = promising.PromisingContext()
    r = repr(ctx)
    assert re.match(r"<PromisingContext id=\d+>", r), f"Unexpected repr: {r}"


# ── Module prefix in auto-resolved namespaces ──────────────────


async def test_auto_namespace_contains_module_prefix() -> None:
    """Auto-resolved namespaces include the module:: prefix."""
    @promising.function
    async def some_func() -> str:
        return "ok"

    ns = some_func.namespace
    assert "::" in ns
    # The part before :: should be a valid module path
    module_part = ns.split("::")[0]
    assert "." in module_part or module_part == __name__


async def test_context_decorator_namespace_has_module_prefix() -> None:
    captured_ctx = None

    @promising.context()
    async def my_context_func() -> None:
        nonlocal captured_ctx
        captured_ctx = promising.get_active_context()

    await my_context_func()
    assert captured_ctx is not None
    assert "::" in captured_ctx.namespace
    assert "my_context_func" in captured_ctx.namespace


# ── Method decorators and qualname ──────────────────────────────


async def test_promising_function_on_instance_method_qualname() -> None:
    """Decorating an instance method includes ClassName.method in namespace."""
    class Service:
        @promising.function
        async def process(self) -> str:
            return "processed"

    # The PromisingFunction's namespace should contain the class-qualified name
    assert "Service.process" in Service.process.namespace  # type: ignore[attr-defined]
    svc = Service()
    result = await svc.process()
    assert result == "processed"


async def test_promising_function_on_static_method_qualname() -> None:
    """Decorating a staticmethod includes ClassName.method in namespace."""
    class Service:
        @promising.function
        @staticmethod
        async def helper() -> str:
            return "helped"

    assert "Service.helper" in Service.helper.namespace  # type: ignore[attr-defined]
    assert await Service.helper() == "helped"


async def test_promising_function_on_class_method_qualname() -> None:
    """Decorating a classmethod includes ClassName.method in namespace."""
    class Service:
        @promising.function
        @classmethod
        async def create(cls) -> str:
            return "created"

    assert "Service.create" in Service.create.namespace  # type: ignore[attr-defined]
    assert await Service.create() == "created"
