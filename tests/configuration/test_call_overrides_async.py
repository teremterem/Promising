"""
Tests for overriding start_soon, children_start_soon, and
start_soon_default at call time (via keyword arguments
to __call__ / call()).
"""

import promising
from promising import ASYNCIO_DEFAULT, INHERIT, PROMISING_DEFAULT

# ── start_soon ────────────────────────────────────────────────────────────────


async def test_call_overrides_start_soon() -> None:
    """
    start_soon set on PromisingFunction is overridden when
    a different value is passed at call time.
    """

    @promising.function(start_soon=False)
    async def noop() -> None:
        pass

    promise = noop(start_soon=True)
    assert promise._start_soon is True
    await promise


async def test_call_without_start_soon_uses_constructor_value() -> None:
    """
    When start_soon is not passed at call time, the
    PromisingFunction constructor's value is used.
    """

    @promising.function(start_soon=False)
    async def noop() -> None:
        pass

    promise = noop()
    assert promise._start_soon is False
    await promise


async def test_call_start_soon_none_overrides_constructor() -> None:
    """
    Explicitly passing None at call time overrides the constructor's
    concrete bool value (in this particular case, falling back to the global
    Defaults.START_SOON, as there is no context hierarchy and no
    intermediate defaults).
    """

    @promising.function(start_soon=False)
    async def noop() -> None:
        pass

    # Passing None explicitly still overrides the constructor's False
    promise = noop(start_soon=None)
    # At root, None falls back to start_soon_default (True)
    assert promise._start_soon is True
    await promise


# ── children_start_soon ────────────────────────────────────────────


async def test_call_overrides_children_start_soon() -> None:
    """
    children_start_soon set on PromisingFunction is
    overridden when a different value is passed at call time.
    """

    @promising.function(children_start_soon=False)
    async def noop() -> None:
        pass

    promise = noop(children_start_soon=True)
    assert promise._children_start_soon is True
    await promise


async def test_call_without_children_start_soon_uses_constructor_value() -> None:
    """
    When children_start_soon is not passed at call
    time, the PromisingFunction constructor's value is used.
    """

    @promising.function(children_start_soon=True)
    async def noop() -> None:
        pass

    promise = noop()
    assert promise._children_start_soon is True
    await promise


# ── start_soon_default ─────────────────────────────────────────


async def test_call_overrides_start_soon_default() -> None:
    """
    start_soon_default set on PromisingFunction is
    overridden when a different value is passed at call time.
    """

    @promising.function(start_soon_default=True)
    async def noop() -> None:
        pass

    promise = noop(start_soon_default=False)
    assert promise._start_soon_default is False
    await promise


async def test_call_without_start_soon_default_uses_constructor_value() -> None:
    """
    When start_soon_default is not passed at call
    time, the PromisingFunction constructor's value is used.
    """

    @promising.function(start_soon_default=False)
    async def noop() -> None:
        pass

    promise = noop()
    assert promise._start_soon_default is False
    await promise


# ── All three overridden at once ──────────────────────────────────────────────


async def test_call_time_config_overrides() -> None:
    """
    Config params passed at call time override the
    PromisingFunction-level defaults.
    """
    # TODO How not to forget to expand the list of params when they are added ?

    @promising.function(
        start_soon=False,
        children_start_soon=False,
        start_soon_default=False,
    )
    async def noop() -> None:
        pass

    promise = noop(
        start_soon=True,
        children_start_soon=True,
        start_soon_default=True,
    )
    assert promise._start_soon is True
    assert promise._children_start_soon is True
    assert promise._start_soon_default is True
    await promise


# ── Config kwargs don't interfere with function kwargs ────────────────────────


async def test_config_kwargs_do_not_leak_into_function() -> None:
    """
    start_soon etc. passed at call time are consumed by
    call() and not forwarded to the wrapped async function.
    """

    @promising.function
    async def add(a: int, b: int) -> int:
        return a + b

    result = await add(
        3,
        4,
        namespace="hello world",
        start_soon=True,
        children_start_soon=True,
        start_soon_default=True,
        thread_pool=ASYNCIO_DEFAULT,
        use_thread_pool=None,
    )
    assert result == 7


async def test_config_kwargs_alongside_function_kwargs() -> None:
    """
    Config kwargs and regular function kwargs coexist: config
    kwargs are consumed by call(), function kwargs pass through.
    """

    @promising.function(start_soon=False)
    async def greet(*, name: str) -> str:
        return f"hello, {name}"

    promise = greet(name="world", start_soon=True, children_start_soon=False)
    assert promise._start_soon is True
    assert promise._children_start_soon is False
    assert await promise == "hello, world"


# ── Sentinel values round-trip ────────────────────────────────────────────────


async def test_call_override_with_inherit() -> None:
    """
    Passing INHERIT at call time for start_soon_default
    overrides a concrete bool from the constructor; at root level
    INHERIT resolves to the global default (True).
    """

    @promising.function(start_soon_default=False)
    async def noop() -> None:
        pass

    promise = noop(start_soon_default=INHERIT)
    # At root, INHERIT reads the global default (True)
    assert promise._start_soon_default is True
    await promise


async def test_call_override_with_global_default() -> None:
    """
    Passing PROMISING_DEFAULT at call time for
    start_soon_default overrides a concrete bool from
    the constructor; at root level it also resolves to True.
    """

    @promising.function(start_soon_default=False)
    async def noop() -> None:
        pass

    promise = noop(start_soon_default=PROMISING_DEFAULT)
    assert promise._start_soon_default is True
    await promise
