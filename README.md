# Promising

Hierarchical async and sync Promise management for Python.

Decorate any function with `@promising.function` and it runs concurrently. Async functions run on the event loop as usual; sync functions require an explicit `use_thread_pool` setting — `True` (recommended) dispatches them to a thread pool, `False` runs them directly on the event loop thread. The caller always gets back a `Promise` — regardless of whether the function is async or sync, and regardless of whether it returns a concrete value, a coroutine, or another Promise. You don't have to think about any of that — just call it and let it run. By default, everything starts eagerly and in parallel.

## Installation

***TODO [P0]*** *Publish to PyPI*

```bash
pip install promising
```

Requires Python 3.11+.

## Quick Start

Decorate an async function with `@promising.function` to make it return a `Promise` instead of a coroutine:

```python
import asyncio
import promising

@promising.function
async def fetch_data(url: str) -> dict:
    # ... fetch something ...
    return {"url": url, "status": "ok"}

async def main():
    promise = fetch_data("https://example.com")  # Returns a Promise, not a coroutine
    result = await promise                        # Await it to get the result
    print(result)

asyncio.run(main())
```

A Promise can be consumed multiple times — via `await`, `.sync()`, `unpack_once()`, or `unpack_once_sync()` — without re-executing the underlying function. The result is cached on first resolution:

```python
promise = fetch_data("https://example.com")
result1 = await promise  # Executes the function
result2 = await promise  # Returns the cached result
...
# Somewhere in a sync promising function
# (which runs in a worker thread by default)
result3 = promise.sync()  # Same cached result
...
assert result1 is result2 is result3
```

## Parent-Child Hierarchy

The core feature. When a Promise creates other Promises during its execution, those are automatically registered as children:

```python
@promising.function
async def child_task(name: str) -> str:
    return f"done: {name}"

@promising.function
async def parent_task() -> str:
    # These Promises become children of parent_task's Promise
    a = child_task("a")
    b = child_task("b")
    return "parent done"

promise = parent_task()
await promise

# The parent-child relationship is tracked automatically
```

### Waiting for Children

By default, a parent resolves as soon as its own coroutine finishes — children may still be running. Use `await_children()` to wait for the entire subtree (children, grandchildren, etc.) before the parent resolves:

```python
@promising.function
async def parent_task() -> str:
    child_task("a")
    child_task("b")

    # Wait for all descendants to complete before returning
    await promising.await_children()
    return "all done"
```

To wait only for direct children (not grandchildren), pass `whole_subtree=False`:

```python
await promising.await_children(whole_subtree=False)
```

> **Note:** `await_children()` and `await_children_sync()` are purely for
> timing/synchronization — they do **not** propagate child exceptions.
> Internally they use `return_exceptions=True` so that all children are
> awaited even when some fail, but the exceptions are discarded. To handle
> errors from children, capture their `Promise` references and await them
> directly:
>
> ```python
> @promising.function
> async def parent_task() -> str:
>     a = child_task("a")
>     b = child_task("b")
>
>     # Await each child to propagate its exceptions
>     await a
>     await b
>     return "all done"
> ```

## Sync Function Support

`@promising.function` works on regular (non-async) functions too. Sync functions require an explicit `use_thread_pool` setting — `True` (recommended for most cases) runs them in a thread pool so CPU-heavy workloads don't block the event loop thread:

```python
@promising.function(use_thread_pool=True)
def compute(x: int, y: int) -> int:
    # Runs in a ThreadPoolExecutor
    return x + y

async def main():
    result = await compute(3, 4)
    assert result == 7
```

Inside a sync promising function, use `.sync()` instead of `await` to get a child Promise's result. Like `await`, `.sync()` recursively unpacks nested Promises (see [Result Unpacking](#result-unpacking)):

```python
@promising.function
async def async_greet(name: str) -> str:
    return f"hello, {name}"

@promising.function(use_thread_pool=True)
def sync_caller() -> str:
    greeting = async_greet("world", start_soon=False)
    return greeting.sync()  # Blocks until resolved
```

The sync counterpart of `await_children()` is also available:

```python
@promising.function(use_thread_pool=True)
def sync_parent() -> str:
    child_task("a")
    child_task("b")
    promising.await_children_sync()
    return "done"
```

`sync()`, `unpack_once_sync()`, and `await_children_sync()` all guard against being called from the event loop thread (which would deadlock) by raising `SyncUsageError`.

### Thread Pool Configuration

When `use_thread_pool=True`, sync promising functions run in a global `ThreadPoolExecutor` (`Defaults.PROMISING_THREAD_POOL`) by default. You can control which thread pool is used via the `thread_pool` parameter on `@promising.function`, `promising.context`, or `Promise`:

```python
from concurrent.futures import ThreadPoolExecutor
import promising
from promising import ASYNCIO_DEFAULT, PROMISING_DEFAULT

# Use a custom thread pool for a specific function
my_pool = ThreadPoolExecutor(max_workers=4)

@promising.function(use_thread_pool=True, thread_pool=my_pool)
def cpu_bound_work(data: list) -> list:
    return sorted(data)

# Let the event loop use its own default executor
@promising.function(use_thread_pool=True, thread_pool=ASYNCIO_DEFAULT)
def io_work() -> str:
    ...

# Override at call time
result = await cpu_bound_work(data, thread_pool=ASYNCIO_DEFAULT)
```

Thread pool settings inherit through the context hierarchy. A `promising.context` can set the thread pool for all sync functions within its scope:

```python
custom_pool = ThreadPoolExecutor(max_workers=8)

with promising.context(thread_pool=custom_pool):
    # All sync promising functions here use custom_pool
    await compute(3, 4)
```

The `thread_pool` parameter accepts:

- **`INHERIT`** (default) — inherit from the parent context; falls back to `PROMISING_DEFAULT` at the root.
- **`PROMISING_DEFAULT`** — use `Defaults.PROMISING_THREAD_POOL`.
- **`ASYNCIO_DEFAULT`** — pass `None` to `run_in_executor`, letting the event loop use its own default executor.
- A concrete **`ThreadPoolExecutor`** instance.

### `use_thread_pool`: Required for Sync, Disallowed for Async

The `use_thread_pool` parameter is **required** when decorating a sync function — omitting it raises `DecorationError`. Set it to `True` (recommended for most cases) to run in a thread pool, or `False` for lightweight transforms that won't block the event loop:

```python
@promising.function(use_thread_pool=True)
def cpu_heavy(data: list) -> list:
    return sorted(data)

@promising.function(use_thread_pool=False)
def lightweight_transform(data: list) -> list:
    return [x * 2 for x in data]
```

> **Warning:** When `use_thread_pool=False`, calling `.sync()` or `await_children_sync()` from within the function will raise `SyncUsageError` because those calls would deadlock the event loop.

For async functions, `use_thread_pool` is **disallowed** — passing it (at decoration or call time) raises `DecorationError`. Async functions always run on the event loop regardless, so the parameter would be misleading.

An alternative to `use_thread_pool=False` is to simply mark the decorated function as `async` but treat it as synchronous (don't use `await` inside). This avoids the thread pool naturally, since async functions always run on the event loop. The same caveat applies: CPU-heavy work in such a function will block the event loop.

Unlike `thread_pool`, the `use_thread_pool` parameter is intentionally not inheritable through the context hierarchy — it must be set per-function at decoration time. For sync functions, it can also be overridden at call time. Running sync functions on the event loop thread is problematic for CPU-bound workloads (it blocks the loop), so the user should make a conscious decision for each specific case.

## Method Decorators

`@promising.function` works with instance methods, `@classmethod`, and `@staticmethod`. Decorator order doesn't matter:

```python
class MyService:
    @promising.function
    async def instance_method(self) -> str:
        return "instance"

    # Either order works for classmethod and staticmethod
    @classmethod
    @promising.function
    async def from_config(cls, path: str) -> "MyService":
        return cls()

    @promising.function
    @staticmethod
    async def utility(x: int) -> int:
        return x * 2
```

## Lightweight Contexts: `promising.context`

`promising.context` creates a `PromisingContext` — a lightweight node in the hierarchy that does not represent an asynchronous computation. Its main use is scoping `start_soon`-related configuration locally, so that Promises created within it inherit specific defaults. It also lets you group child Promises under a shared context for awaiting or inspection.

### As a Context Manager

```python
import promising

@promising.function
async def child_task(name: str) -> str:
    return f"done: {name}"

async def main():
    # All children created inside default to start_soon=False
    with promising.context(children_start_soon=False) as ctx:
        a = child_task("a")  # deferred — won't start until awaited
        b = child_task("b")  # same

    result_a = await a
    result_b = await b
```

Nesting works as expected — inner contexts become children of outer ones:

```python
with promising.context() as outer:
    with promising.context() as inner:
        assert promising.get_active_context() is inner
        assert inner.get_parent_context() is outer
    assert promising.get_active_context() is outer
```

### As a Decorator

`@promising.context` wraps a function so that each call runs inside a fresh `PromisingContext`. This works on both async and sync functions:

```python
@promising.context(children_start_soon=False)
async def do_work() -> str:
    # Children created here inherit start_soon=False
    a = child_task("x")
    b = child_task("y")
    return "done"

await do_work()
```

Settings specified on the decorator can be overridden at call time by passing them as keyword arguments:

```python
await do_work(children_start_soon=True)  # overrides decorator default for this call
```

Like `@promising.function`, it works with `@classmethod`, `@staticmethod`, and instance methods in either decorator order.

### `promising.context` vs `promising.function`

The key difference: `@promising.function` creates a `Promise` (an awaitable that caches its result and appears in the parent promise chain), while `@promising.context` creates a bare `PromisingContext` that only participates in the context hierarchy. Calling a `@promising.context`-decorated function executes the function as is and returns its result directly (not wrapped in a `Promise`). If the decorated function is async, the result will still need to be awaited, though. Use `@promising.context` when you want to scope configuration or group children without the function itself becoming a Promise.

## Execution Timing: `start_soon`

By default, Promises start executing immediately upon creation (at the nearest event loop opportunity). This is controlled by the `start_soon` parameter:

```python
# Starts immediately (default behavior)
promise = fetch_data("https://example.com")

# Defers execution until awaited
@promising.function(start_soon=False)
async def lazy_fetch(url: str) -> dict:
    ...

promise = lazy_fetch("https://example.com")  # Not running yet
result = await promise                        # Now it starts
```

### Configuration Inheritance

Promises inherit configuration from their parents through these parameters:

- **`start_soon`** — whether the Promise starts executing immediately upon creation. When left as `None` (the default), it defers to its parent's `children_start_soon`, or falls back to `start_soon_default`. `INHERIT` copies the parent's `start_soon` directly.
- **`children_start_soon`** — enforces a `start_soon` default for child Promises that left their `start_soon` as `None`. `None` means no enforcement. `INHERIT` copies the parent's `children_start_soon` setting. Note: `Promise` defaults to `None` (no enforcement unless explicitly chosen), while `PromisingContext` / `promising.context` defaults to `INHERIT` (transparent pass-through of the parent's policy).
- **`start_soon_default`** — a per-Promise local override for the global default. `INHERIT` (default) propagates from the parent. `PROMISING_DEFAULT` reads the current global setting directly, ignoring the parent chain.

These can be set on the decorator or overridden at call time by passing them as keyword arguments. Call-time values always take precedence over decorator-level defaults — even passing `None` explicitly at call time overrides the decorator value:

```python
@promising.function(children_start_soon=False)
async def parent() -> str:
    # All children created here will default to start_soon=False
    a = child_task("a")                        # Deferred (inherits from parent)
    b = child_task("b", start_soon=True)       # Overridden: starts immediately
    ...
```

The global default can be changed:

```python
import promising

# All Promises start immediately by default (this is the initial value)
promising.Defaults.START_SOON = True

# Change to lazy execution globally
promising.Defaults.START_SOON = False
```

## Thread-Safe Access

`promise.sync()` (and `promise.unpack_once_sync()`) lets non-async threads block on a Promise's result. Both are thread-safe and schedule work on the Promise's event loop via `asyncio.run_coroutine_threadsafe`:

```python
import threading

async def main():
    promise = fetch_data("https://example.com")

    def worker():
        # Blocks until the Promise resolves (thread-safe)
        result = promise.sync(timeout=5.0)
        print(result)

    thread = threading.Thread(target=worker)
    thread.start()
    await promise
    thread.join()
```

Like `await`, calling `promise.sync()` automatically triggers the Promise's execution if it was created with `start_soon=False`. There is no need to start the Promise manually before blocking on it.

`promise.sync()`, `promise.unpack_once_sync()`, and `await_children_sync()` all raise `SyncUsageError` if called from the event loop thread (which would deadlock).

`Promise.cancel()` is also thread-safe — it can be invoked from any thread and is dispatched onto the Promise's event loop when the caller is not already on it.

## Result Unpacking

A decorated function always returns a `Promise`, regardless of whether the underlying function returns a concrete value, a coroutine, or another Promise. This means:

- `await promise` and `promise.sync()` recursively unpack nested `Promise` results until a non-`Promise` value is reached. Note that unpacking only traverses `Promise` instances specifically — it does **not** unpack arbitrary awaitables (e.g. an `asyncio.Future` returned by your function comes back to you as an `asyncio.Future`, not as a wrapped Promise).
- `promise.unpack_once()` and `promise.unpack_once_sync()` unpack only one level — they return either a non-`Promise` value (which may itself be a plain awaitable) or another `Promise`.

```python
@promising.function
async def inner() -> str:
    return "hello"

@promising.function
async def outer() -> Promise:
    return inner()  # Returns a Promise, not a string

result = await outer()  # Recursively unpacks: "hello"
```

To inspect intermediate layers, use `unpack_once()` (async) or `unpack_once_sync()` (sync) — they resolve only one level and return whatever the awaitable returned (which is a `Promise` if the function returned another decorated call, or a plain value otherwise):

```python
one_level = await outer().unpack_once()  # Returns the inner Promise
final = await one_level                   # Returns "hello"
```

The sync counterparts follow the same pattern — `promise.sync()` fully unpacks, while `promise.unpack_once_sync()` resolves only one level. Like `unpack_once()`, it returns the same dual-purpose `Promise` objects that support both async and sync consumption — the caller can continue with `.sync()` if still in a sync context, or switch to `await` if the context is async:

```python
@promising.function(use_thread_pool=True)
def sync_example() -> str:
    promise = outer()
    inner_promise = promise.unpack_once_sync()  # Returns the inner Promise
    return inner_promise.sync()                  # Continue synchronously

@promising.function(use_thread_pool=True)
def sync_full_unpack() -> str:
    promise = outer()
    return promise.sync()  # Fully unpacks to "hello"
```

## Working with Promise Directly

You can create Promises without `@promising.function` by passing a coroutine or a prefilled value:

```python
from promising import Promise

# From a coroutine
async def my_coro() -> str:
    return "hello"

promise = Promise(my_coro(), start_soon=True)
result = await promise

# Prefilled with a result (immediately resolved)
promise = Promise(prefilled_result=42)
assert promise.done()
assert promise.result() == 42

# Prefilled with an exception
promise = Promise(prefilled_exception=ValueError("oops"))

# Explicit parent (overrides automatic context-based detection)
parent = Promise(prefilled_result="parent")
child = Promise(my_coro(), parent=parent)

# No parent (opt out of automatic parent detection)
orphan = Promise(my_coro(), parent=None)
```

## Examples

The `examples/` directory contains runnable examples. To install example dependencies:

```bash
uv sync --extra examples
```

- `examples/keyword_agent.py` — an LLM-powered keyword extraction agent using `@promising.function` with `litellm` and `pydantic`.

## Design Note: Settings Are Frozen at Creation Time

All configuration — `start_soon`, `children_start_soon`, `start_soon_default`, `thread_pool`, etc. — is resolved and frozen the moment a `Promise` or `PromisingContext` is created. Sentinels like `INHERIT` and `PROMISING_DEFAULT` are replaced with concrete values immediately, so later changes to `Defaults` have no effect on already-created promises.

This is intentional: because a `Promise` may execute eagerly (the default) or be deferred, the user cannot predict *when* the underlying coroutine will run. Freezing settings at creation time guarantees that the behavior a promise was *created with* is the behavior it *runs with*, regardless of scheduling.

## Summary: Why Promises?

A plain coroutine in Python is a one-shot object: you can `await` it once, then it's consumed. You can't re-await it, you can't inspect its result from another thread, and there is no built-in way to know which coroutine spawned which. `asyncio.Task` solves some of this, but doesn't track parent-child relationships or propagate configuration.

Wrapping every async (or sync) operation in a `Promise` gives you:

- **Effortless parallelism.** Call your decorated functions and they start running immediately — async on the event loop, sync in a thread pool (with `use_thread_pool=True`). Mix and match freely; the Promise abstraction papers over the difference. No manual `asyncio.gather`, no explicit executor management, no boilerplate to bridge async and threaded code.
- **Multiple awaits.** A Promise caches its result. Any number of consumers can `await`, `.sync()`, `unpack_once()`, or `unpack_once_sync()` the same Promise and get the same value — the underlying function is never executed more than once.
- **Automatic hierarchy.** Promises created during another Promise's execution become its children. You can wait for the entire subtree (`await_children()`), inspect what's still running (`collect_unsettled_children`), or scope configuration to a subtree — all without manual bookkeeping.
- **Thread-safe synchronous access.** Every Promise exposes `.sync()` and `.unpack_once_sync()`, so threads that can't `await` can still block on a Promise's result. Blocking automatically triggers execution of deferred (`start_soon=False`) Promises, just like `await` does.
- **Consistent interface.** A decorated function always returns a `Promise` — whether the underlying function returns a concrete value, a coroutine, or another Promise. `await` and `.sync()` recursively unpack nested Promises and return the final non-`Promise` value, so consumers get a uniform interface regardless of how deep the chain is.
- **Configurable execution.** `start_soon`, `children_start_soon`, `thread_pool`, and other settings propagate through the hierarchy, letting you control eager vs. deferred execution and thread pool usage at any level.

In short, a `Promise` turns a fire-and-forget coroutine into a first-class object you can pass around, await from anywhere (async or sync), and organize into a tree.

## API Reference

### Decorator

| Symbol | Description |
|---|---|
| `promising.function` | Decorator that wraps async or sync functions to return `Promise` objects. Usable as `@promising.function` (async) or `@promising.function(use_thread_pool=True\|False)` (sync). For sync functions, `use_thread_pool` is **required** — set to `True` to run in a thread pool or `False` for lightweight transforms that won't block the event loop. For async functions, `use_thread_pool` is **disallowed**. Also accepts `namespace`, `start_soon`, `children_start_soon`, `start_soon_default`, and `thread_pool`. |
| `promising.PromisingFunction` | The wrapper class created by the decorator. Implements the descriptor protocol for method support. |
| `promising.PromisingFunction.run(*args, **kwargs)` | Top-level entrypoint for running a decorated function from non-async code — analogous to `asyncio.run()`. Calls `asyncio.run()` on `protected_run()`, which means it creates its own event loop, awaits the result, and by default awaits all children recursively (`await_children=WHOLE_SUBTREE`). This is **not** the same as `promise.sync()`: `.sync()` is for consuming a promise's result from within a sync promising function that already runs inside an event loop (in a thread pool), whereas `.run()` is for starting the whole promise tree from scratch. Accepts the same configuration overrides as `__call__` (as well as all the parameters of the underlying decorated function), plus `await_children`. |
| `promising.PromisingFunction.protected_run(*args, **kwargs)` | Returns a **coroutine** (not a `Promise`), making it safe to pass to `asyncio.run()` — unlike calling the decorated function directly, which would construct a root `Promise` before the event loop exists and fail (a root `PromisingContext` requires a running loop). Inside, the coroutine calls the decorated function, awaits the resulting `Promise`, and awaits its children (controlled by `await_children`, which defaults to `WHOLE_SUBTREE`). Used by `run()` internally. Accepts the same configuration overrides as `__call__` (as well as all the parameters of the underlying decorated function), plus `await_children`. |
| `promising.context` | Context manager and decorator that creates a `PromisingContext` without producing a `Promise`. Usable as `with promising.context():` or `@promising.context`. Accepts `namespace`, `loop`, `parent`, `thread_pool`, `children_start_soon`, and `start_soon_default`. |

### Promise

`Promise` is a subclass of `PromisingContext` that adds an awaitable lifecycle: it executes a coroutine on the event loop, caches the result, and exposes both async and sync consumption APIs. It inherits all hierarchy and configuration methods from `PromisingContext` (see below).

| Method / Property | Description |
|---|---|
| `await promise` | Wait for and return the result. Recursively unpacks nested Promises and always returns a concrete value. All consumption methods (`await`, `sync`, `unpack_once`, `unpack_once_sync`) can be called multiple times and always return the same cached result. Must be awaited on the Promise's own event loop (raises `EventLoopMismatchError` otherwise). |
| `promise.unpack_once()` | Async — resolve the Promise but unpack only one level. Returns either a concrete value or another `Promise`. Must be awaited on the Promise's own event loop. |
| `promise.sync(timeout=None)` | Synchronous counterpart of `await promise` — blocks the calling thread, recursively unpacks nested Promises, and always returns a concrete value. Thread-safe; must not be called from the Promise's own event loop thread (raises `SyncUsageError`). |
| `promise.unpack_once_sync(timeout=None)` | Synchronous counterpart of `unpack_once` — blocks the calling thread and unpacks only one level. Returns either a concrete value or another `Promise`. Thread-safe; must not be called from the Promise's own event loop thread. |
| `promise.done()` | Whether the Promise is "done" — finished (with a result or exception) or cancelled. Thread-safe. Overrides `PromisingContext.done()`, which by default tracks the context-manager lifecycle. |
| `promise.cancelled()` | Whether the Promise has been cancelled. Thread-safe. |
| `promise.unpacked_once()` | Whether the Promise has been unpacked at least one level (i.e. its awaitable has produced either an intermediate Promise or a final value). Thread-safe. |
| `promise.unpacked_once_or_done()` | True if the Promise is at least one-level unpacked, fully done, or cancelled. Thread-safe. |
| `promise.result()` | The resolved value. Raises the underlying exception if the Promise finished with one, `PromiseNotDoneError` if it is not done yet, or `asyncio.CancelledError` if it was cancelled. Thread-safe. |
| `promise.exception()` | The exception that the Promise finished with, or `None`. Same readiness/cancellation rules as `result()`. Thread-safe. |
| `promise.intermediate_promise()` | The intermediate `Promise` produced by the first unpacking step, or `None` if the awaitable's result was already a non-Promise value. Raises `PromiseNotUnpackedError` if the Promise has not yet been unpacked once. Thread-safe. |
| `promise.cancel(msg=None)` | Cancel the Promise. Thread-safe — when called from outside the Promise's event loop, the cancellation is dispatched onto that loop. |
| `promise.loop` | The event loop this Promise is bound to (inherited from `PromisingContext`). |

### `wrap_awaitable`

`promising.wrap_awaitable(awaitable=None, **kwargs)` is the recommended way to construct a `Promise` from a bare awaitable (for example, around an arbitrary coroutine that you didn't decorate with `@promising.function`). Accepts the same keyword arguments as the `Promise` constructor — `namespace`, `loop`, `parent`, `thread_pool`, `start_soon`, `children_start_soon`, `start_soon_default`, `prefilled_result`, `prefilled_exception`.

### PromisingContext

`PromisingContext` is the base class that manages the parent-child hierarchy, configuration inheritance, and context-variable tracking. `Promise` inherits from it directly. It can also be used standalone as a lightweight context node that participates in the hierarchy without representing an asynchronous computation.

To plug a *custom awaitable* into the hierarchy as an awaitable child, subclass `PromisingContext` and define `__await__`. You **must** either enter the context inside `__await__` (`with self: ...`) or override `done()` to track a non-lifecycle condition — otherwise `closed()`/`done()` never flip to True and any parent's `await_children()` will hang on your instance. See `tests/utils_for_tests.py::NonPromiseAwaitableContext` for a minimal example.

| Method / Property | Description |
|---|---|
| `ctx.namespace` | Optional human-readable namespace string. Used in `__repr__` output. Set via the `namespace` constructor parameter. |
| `ctx.loop` | The event loop this context is bound to. |
| `ctx.get_parent_context(raise_if_none=True)` | Get the immediate parent context (may be a `PromisingContext` or a `Promise`). |
| `ctx.get_parent_promise(raise_if_none=True)` | Get the nearest ancestor that is a `Promise` (walks up past non-Promise contexts). |
| `ctx.await_children(whole_subtree=True, unpack_promises_fully=True)` | Async — wait for child contexts to finish. With `unpack_promises_fully=False`, Promise children are only unpacked one level (via `unpack_once()`) instead of being fully awaited. |
| `ctx.await_children_sync(whole_subtree=True, unpack_promises_fully=True, timeout=None)` | Sync — block until child contexts finish. With `unpack_promises_fully=False`, Promise children are only unpacked one level instead of being fully awaited. |
| `ctx.collect_unsettled_children(whole_subtree=True, awaitables_only=True)` | Get the set of child contexts that are still being tracked by this context and have not yet been unregistered. Pass `awaitables_only=False` to include non-awaitable contexts (e.g. bare `PromisingContext` instances created via `promising.context`). |
| `ctx.closed()` | Whether the context is closed. A `PromisingContext` is "open" from construction until its `with` block exits (after which `closed()` returns True). A closed context cannot be re-entered (raises `ContextAlreadyClosedError`) and cannot accept new child registrations. |
| `ctx.done()` | Whether the context is "done". For a vanilla `PromisingContext`, the same as `closed()`. `Promise` overrides this to mean "finished or cancelled". `await_children()` uses this to decide when each child has settled. |
| `ctx.get_thread_pool_executor()` | Return the resolved thread pool executor for this context (`ThreadPoolExecutor`, or `None` if `ASYNCIO_DEFAULT`). |
| `ctx.get_trace(parents_first=True)` | Get a list of `PromisingContext` objects from this context up to the root (or, rather, root down to this context when `parents_first=True`). |
| `ctx.format_trace(parents_first=True)` | Like `get_trace`, but returns a list of string representations of each context. |
| `ctx.print_trace(parents_first=True)` | Print each context in the trace on a separate line. |

### Top-Level Convenience Functions

| Function | Description |
|---|---|
| `promising.get_active_context(raise_if_none=True)` | Get the currently active `PromisingContext` (may be a `PromisingContext` or a `Promise`). |
| `promising.get_active_promise(raise_if_none=True)` | Get the currently active `Promise` (walks up the parent chain past non-Promise contexts). |
| `promising.await_children(whole_subtree=True, unpack_promises_fully=True)` | Wait for all children of the current context. With `unpack_promises_fully=False`, Promise children are only unpacked one level. |
| `promising.await_children_sync(whole_subtree=True, unpack_promises_fully=True, timeout=None)` | Sync counterpart — block until children finish. With `unpack_promises_fully=False`, Promise children are only unpacked one level. |
| `promising.collect_unsettled_children(whole_subtree=True, awaitables_only=True)` | Get the set of child contexts of the active context that are still being tracked. Pass `awaitables_only=False` to include non-awaitable contexts (e.g. bare `PromisingContext` instances). |
| `promising.get_trace(parents_first=True)` | Get a list of `PromisingContext` objects from the active context up to the root (or, rather, root down to the active context when `parents_first=True`). |
| `promising.format_trace(parents_first=True)` | Like `get_trace`, but returns a list of string representations of each context. |
| `promising.print_trace(parents_first=True)` | Print each context in the trace on a separate line. |
| `promising.Defaults.START_SOON` | Class attribute holding the global default for eager execution (`True` by default). Set it to `False` to switch to lazy execution globally. |
| `promising.Defaults.PROMISING_THREAD_POOL` | The global `ThreadPoolExecutor` used by sync promising functions when `thread_pool` resolves to `PROMISING_DEFAULT`. |
| `promising.Defaults.QUALNAMES_IN_NAMESPACES` | When `True` (the default), auto-derived namespaces include the fully qualified name (`module::qualname`). When `False`, only the short `__name__` is used. |

### Sentinels

| Sentinel | Meaning |
|---|---|
| `promising.UNCHANGED` | No call-time override — use the decorator-level value. |
| `promising.AUTO` | Used as the default for the `parent` parameter of `Promise` / `PromisingContext` / `promising.context`: pick up the currently active context automatically. Pass `None` instead to opt out and create a root. |
| `promising.INHERIT` | Copy from the parent context; fall back to the global default when there is no parent. |
| `promising.PROMISING_DEFAULT` | Read the current global setting directly, ignoring the parent chain. |
| `promising.ASYNCIO_DEFAULT` | Let the event loop use its own default executor (passes `None` to `run_in_executor`). Used with the `thread_pool` parameter. |
| `promising.WHOLE_SUBTREE` | Used as the default for the `await_children` parameter in `PromisingFunction.run()` and `protected_run()`, indicating that all descendants (not just direct children) should be awaited. |
| `promising.Sentinel` | The sentinel class. All sentinels above are instances of it. |

All sentinels raise `SentinelUsageError` on boolean coercion to prevent misuse.

### Errors

| Error | Description |
|---|---|
| `promising.PromisingError` | Base class for all promising errors. |
| `promising.ContextError` | Base class for context-related errors. Inherits from `PromisingError`. |
| `promising.ContextNotFoundError` | No active `PromisingContext` is found (e.g. calling `get_active_context()` or `await_children()` outside a promising function). Inherits from `ContextError`. |
| `promising.ContextAlreadyActiveError` | Attempting to enter a `PromisingContext` that is already active (e.g. nested `with ctx:` on the same instance). Inherits from `ContextError`. |
| `promising.ContextAlreadyClosedError` | Attempting to re-enter a `PromisingContext` that has already been closed, or registering a child on a closed context. A `PromisingContext` can only be entered once — once it has been exited, it is closed for good. Inherits from `ContextError`. |
| `promising.ContextNotActiveError` | Attempting to exit a `PromisingContext` that is not active. Inherits from `ContextError`. |
| `promising.DecorationError` | Invalid decorator usage (e.g. passing a non-callable to `@promising.function` or `@promising.context`, omitting `use_thread_pool` on a sync function, setting `use_thread_pool` on an async function, or using the same `promising.context` instance as both context manager and decorator). |
| `promising.EventLoopError` | Base class for event loop-related errors. Inherits from `PromisingError`. |
| `promising.EventLoopMismatchError` | Awaiting a `Promise` from a different event loop than the one it belongs to. Inherits from both `EventLoopError` and `ValueError`. |
| `promising.NoRunningEventLoopError` | No running event loop found when one is required (e.g. creating a root `PromisingContext` outside an async context, awaiting a `Promise` without a running event loop, or scheduling work on a context whose event loop has stopped). Inherits from both `EventLoopError` and `RuntimeError`. |
| `promising.PromiseNotFoundError` | No active `Promise` is found (e.g. calling `get_active_promise()` when the active context is not a `Promise`). |
| `promising.PromiseNotDoneError` | `Promise.result()` or `Promise.exception()` is called before the Promise is done. Inherits from `PromisingError`, `asyncio.InvalidStateError`, and `concurrent.futures.InvalidStateError`. |
| `promising.PromiseNotUnpackedError` | `Promise.intermediate_promise()` is called before the Promise has been unpacked at least once. Inherits from `PromisingError`, `asyncio.InvalidStateError`, and `concurrent.futures.InvalidStateError`. |
| `promising.SentinelUsageError` | A `Sentinel` was used in a boolean context (e.g. `if INHERIT:`). Use `is` / `is not` identity comparisons instead. |
| `promising.SyncUsageError` | A sync method (`promise.sync()`, `promise.unpack_once_sync()`, `await_children_sync()`) is called from the event loop thread, which would deadlock. |

All errors inherit from `promising.PromisingError`. Context-related errors also inherit from `promising.ContextError`, and event loop-related errors also inherit from `promising.EventLoopError`.

## License

MIT
