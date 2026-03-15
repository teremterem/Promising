# Promising

Hierarchical async Promise management for Python.

Promising extends `asyncio.Future` with automatic parent-child relationships between asynchronous operations. When a Promise creates other Promises during its execution, those become its children — tracked via context variables, forming a tree you can await, inspect, or configure as a unit.

Decorate any function with `@promising.function` — async or sync, it doesn't matter — and it runs concurrently. Async functions run on the event loop as usual; sync functions are dispatched to a thread pool automatically. The caller always gets back a `Promise` — regardless of whether the function is async or sync, and regardless of whether it returns a concrete value, a coroutine, or another Promise. You don't have to think about any of that — just call it and let it run. By default, everything starts eagerly and in parallel.

## Why Promises?

A plain coroutine in Python is a one-shot object: you can `await` it once, then it's consumed. You can't re-await it, you can't inspect its result from another thread, and there is no built-in way to know which coroutine spawned which. `asyncio.Task` solves some of this, but doesn't track parent-child relationships or propagate configuration.

Wrapping every async (or sync) operation in a `Promise` gives you:

- **Effortless parallelism.** Call your decorated functions and they start running immediately — async on the event loop, sync in a thread pool. Mix and match freely; the Promise abstraction papers over the difference. No manual `asyncio.gather`, no explicit executor management, no boilerplate to bridge async and threaded code.
- **Multiple awaits.** A Promise caches its result. Any number of consumers can `await`, `.sync()`, `unpack_once()`, or `unpack_once_sync()` the same Promise and get the same value — the underlying function is never executed more than once.
- **Automatic hierarchy.** Promises created during another Promise's execution become its children. You can wait for the entire subtree (`await_children(recursively=True)`), inspect what's still running (`collect_remaining_children`), or scope configuration to a subtree — all without manual bookkeeping.
- **Thread-safe synchronous access.** Every Promise has a `.sync()` method and a `concurrent.futures.Future` view (`as_concurrent_future()`), so threads that can't `await` can still block on a Promise's result. Blocking automatically triggers execution of deferred (`start_soon=False`) Promises, just like `await` does.
- **Consistent interface.** A decorated function always returns a `Promise` — whether the underlying function returns a concrete value, a coroutine, or another Promise. `await` and `.sync()` always return a concrete value. Non-Promise awaitables are auto-wrapped into child Promises, so every layer in the chain is a `Promise` with the same uniform interface.
- **Configurable execution.** `start_soon`, `children_start_soon`, `thread_pool`, and other settings propagate through the hierarchy, letting you control eager vs. deferred execution and thread pool usage at any level.

In short, a `Promise` turns a fire-and-forget coroutine into a first-class object you can pass around, await from anywhere (async or sync), and organize into a tree.

## Installation

***TODO [P1]*** *Not yet published to PyPI*

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

By default, a parent resolves as soon as its own coroutine finishes — children may still be running. Use `await_children()` to wait for all children before the parent resolves:

```python
@promising.function
async def parent_task() -> str:
    child_task("a")
    child_task("b")

    # Wait for all children to complete before returning
    await promising.await_children()
    return "all done"
```

Use `recursively=True` to wait for the entire subtree (children, grandchildren, etc.):

```python
await promising.await_children(recursively=True)
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

`@promising.function` works on regular (non-async) functions too. They run in a thread pool while still participating in the Promise hierarchy:

```python
@promising.function
def compute(x: int, y: int) -> int:
    # Runs in a ThreadPoolExecutor
    return x + y

async def main():
    result = await compute(3, 4)
    assert result == 7
```

Inside a sync promising function, use `.sync()` instead of `await` to get a child Promise's result. Like `await`, `.sync()` recursively unpacks nested awaitables (see [Result Unpacking](#result-unpacking)):

```python
@promising.function
async def async_greet(name: str) -> str:
    return f"hello, {name}"

@promising.function
def sync_caller() -> str:
    greeting = async_greet("world", start_soon=False)
    return greeting.sync()  # Blocks until resolved
```

The sync counterpart of `await_children()` is also available:

```python
@promising.function
def sync_parent() -> str:
    child_task("a")
    child_task("b")
    promising.await_children_sync()
    return "done"
```

`sync()`, `await_children_sync()`, `concurrent_future.result()`, and `concurrent_future.exception()` all guard against being called from the event loop thread (which would deadlock) by raising `SyncUsageError`.

### Thread Pool Configuration

By default, sync promising functions run in a global `ThreadPoolExecutor` (`Defaults.SYNC_THREAD_POOL`). You can control which thread pool is used via the `thread_pool` parameter on `@promising.function`, `promising.context`, or `Promise`:

```python
from concurrent.futures import ThreadPoolExecutor
import promising
from promising import ASYNCIO_DEFAULT, GLOBAL_DEFAULT

# Use a custom thread pool for a specific function
my_pool = ThreadPoolExecutor(max_workers=4)

@promising.function(thread_pool=my_pool)
def cpu_bound_work(data: list) -> list:
    return sorted(data)

# Let the event loop use its own default executor
@promising.function(thread_pool=ASYNCIO_DEFAULT)
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

- **`INHERIT`** (default) — inherit from the parent context; falls back to `GLOBAL_DEFAULT` at the root.
- **`GLOBAL_DEFAULT`** — use `Defaults.SYNC_THREAD_POOL`.
- **`ASYNCIO_DEFAULT`** — pass `None` to `run_in_executor`, letting the event loop use its own default executor.
- A concrete **`ThreadPoolExecutor`** instance.

### Opting Out of the Thread Pool

If a sync function is lightweight and you want to avoid the overhead of dispatching it to a thread pool, set `use_thread_pool=False` to run it directly on the event loop thread:

```python
@promising.function(use_thread_pool=False)
def lightweight_transform(data: list) -> list:
    return [x * 2 for x in data]
```

> **Warning:** When `use_thread_pool=False`, calling `.sync()` or `await_children_sync()` from within the function will raise `SyncUsageError` because those calls would deadlock the event loop.

An alternative to `use_thread_pool=False` is to simply mark the decorated function as `async` but treat it as synchronous (don't use `await` inside). This avoids the thread pool naturally, since async functions always run on the event loop. The same caveat applies: CPU-heavy work in such a function will block the event loop.

Unlike `thread_pool`, the `use_thread_pool` parameter is intentionally not inheritable through the context hierarchy — it must be set per-function at decoration or call time. Running sync functions on the event loop thread is problematic for CPU-bound workloads (it blocks the loop), so the user should make a conscious decision for each specific case.

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

`promising.context` creates a `PromisingContext` — a lightweight node in the hierarchy that is not an `asyncio.Future`. Its main use is scoping `start_soon`-related configuration locally, so that Promises created within it inherit specific defaults. It also lets you group child Promises under a shared context for awaiting or inspection.

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

Like `@promising.function`, it works with `@classmethod`, `@staticmethod`, and instance methods in either decorator order.

### `promising.context` vs `promising.function`

The key difference: `@promising.function` creates a `Promise` (an `asyncio.Future` that can be awaited and appears in the parent promise chain), while `@promising.context` creates a bare `PromisingContext` that only participates in the context hierarchy. Calling a `@promising.context`-decorated function executes the function as is and returns its result directly (not wrapped in a `Promise`). If the decorated function is async, the result will still need to be awaited, though. Use `@promising.context` when you want to scope configuration or group children without the function itself becoming a Promise.

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

Promises inherit configuration from their parents through three parameters:

- **`start_soon`** — whether the Promise starts executing immediately upon creation. When left as `None` (the default), it defers to its parent's `children_start_soon`, or falls back to `start_soon_default`. `INHERIT` copies the parent's `start_soon` directly.
- **`children_start_soon`** — enforces a `start_soon` default for child Promises that left their `start_soon` as `None`. `None` means no enforcement. `INHERIT` copies the parent's `children_start_soon` setting. Note: `Promise` defaults to `None` (no enforcement unless explicitly chosen), while `PromisingContext` / `promising.context` defaults to `INHERIT` (transparent pass-through of the parent's policy).
- **`start_soon_default`** — a per-Promise local override for the global default. `INHERIT` (default) propagates from the parent. `GLOBAL_DEFAULT` reads the current global setting directly, ignoring the parent chain.

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

Every Promise has a `PromiseBackedConcurrentFuture` (a `concurrent.futures.Future` subclass) for use from non-async threads:

```python
import threading

async def main():
    promise = fetch_data("https://example.com")
    concurrent_future = promise.as_concurrent_future()

    def worker():
        # Blocks until the Promise resolves (thread-safe)
        result = concurrent_future.result(timeout=5.0)
        print(result)

    thread = threading.Thread(target=worker)
    thread.start()
    await promise
    thread.join()
```

Like `await`, blocking on the concurrent future (`concurrent_future.result()`, `concurrent_future.exception()`) or calling `promise.sync()` automatically triggers the Promise's execution if it was created with `start_soon=False`. There is no need to start the Promise manually before blocking on it.

`promise.sync()`, `concurrent_future.result()`, and `concurrent_future.exception()` all raise `SyncUsageError` if called from the event loop thread (which would deadlock).

## Result Unpacking

A decorated function always returns a `Promise`, regardless of whether the underlying function returns a concrete value, a coroutine, or another Promise. When a Promise's result is an awaitable that isn't already a `Promise`, it is automatically wrapped in a child `Promise`. This means:

- `await promise` and `promise.sync()` always return a concrete value — they recursively unpack nested Promises until a non-Promise result is reached.
- `promise.unpack_once()` and `promise.unpack_once_sync()` unpack only one level — they return either a concrete value or another `Promise`.

```python
@promising.function
async def inner() -> str:
    return "hello"

@promising.function
async def outer() -> Promise:
    return inner()  # Returns a Promise, not a string

result = await outer()  # Recursively unpacks: "hello"
```

To inspect intermediate layers, use `unpack_once()` (async) or `unpack_once_sync()` (sync) — they resolve only one level. Thanks to auto-wrapping, the result is guaranteed to be either a concrete value or a `Promise` (never a plain awaitable):

```python
one_level = await outer().unpack_once()  # Returns the inner Promise
final = await one_level                   # Returns "hello"
```

The sync counterparts follow the same pattern — `promise.sync()` fully unpacks, while `promise.unpack_once_sync()` resolves only one level. Like `unpack_once()`, it returns the same dual-purpose `Promise` objects that support both async and sync consumption — the caller can continue with `.sync()` if still in a sync context, or switch to `await` if the context is async:

```python
@promising.function
def sync_example() -> str:
    promise = outer()
    inner_promise = promise.unpack_once_sync()  # Returns the inner Promise
    return inner_promise.sync()                  # Continue synchronously

@promising.function
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

All configuration — `start_soon`, `children_start_soon`, `start_soon_default`, `thread_pool`, etc. — is resolved and frozen the moment a `Promise` or `PromisingContext` is created. Sentinels like `INHERIT` and `GLOBAL_DEFAULT` are replaced with concrete values immediately, so later changes to `Defaults` or parent contexts have no effect on already-created promises.

This is intentional: because a `Promise` may execute eagerly (the default) or be deferred, the user cannot predict *when* the underlying coroutine will run. Freezing settings at creation time guarantees that the behavior a promise was *created with* is the behavior it *runs with*, regardless of scheduling.

## API Reference

### Decorator

| Symbol | Description |
|---|---|
| `promising.function` | Decorator that wraps async or sync functions to return `Promise` objects. Usable as `@promising.function` or `@promising.function(start_soon=...)`. Accepts `namespace`, `start_soon`, `children_start_soon`, `start_soon_default`, `thread_pool`, and `use_thread_pool`. |
| `promising.PromisingFunction` | The wrapper class created by the decorator. Implements the descriptor protocol for method support. |
| `promising.context` | Context manager and decorator that creates a `PromisingContext` without producing a `Promise`. Usable as `with promising.context():` or `@promising.context()`. Accepts `namespace`, `loop`, `parent`, `thread_pool`, `children_start_soon`, and `start_soon_default`. |

### Promise

`Promise` extends both `PromisingContext` and `asyncio.Future`. It inherits all hierarchy and configuration methods from `PromisingContext` (see below) and adds coroutine execution and thread-safe access.

| Method / Property | Description |
|---|---|
| `await promise` | Wait for and return the result. Recursively unpacks nested Promises and always returns a concrete value. All consumption methods (`await`, `sync`, `unpack_once`, `unpack_once_sync`) can be called multiple times and always return the same cached result. |
| `promise.unpack_once()` | Async — resolve the Promise but unpack only one level. Returns either a concrete value or another `Promise`. |
| `promise.sync(timeout=None)` | Synchronous counterpart of `await promise` — blocks the calling thread, recursively unpacks nested Promises, and always returns a concrete value. Must not be called from the event loop thread. |
| `promise.unpack_once_sync(timeout=None)` | Synchronous counterpart of `unpack_once` — blocks the calling thread and unpacks only one level. Returns either a concrete value or another `Promise`. Must not be called from the event loop thread. |
| `promise.done()` | Whether the Promise has resolved (inherited from `asyncio.Future`). |
| `promise.result()` | The resolved value (inherited from `asyncio.Future`). |
| `promise.as_concurrent_future()` | Get a thread-safe `PromiseBackedConcurrentFuture` view. |

### PromisingContext

`PromisingContext` is the base class that manages the parent-child hierarchy, configuration inheritance, and context variable tracking. `Promise` inherits from it. It can also be used standalone as a lightweight context node that participates in the hierarchy without being an `asyncio.Future`.

| Method / Property | Description |
|---|---|
| `ctx.namespace` | Optional human-readable namespace string. Used in `__repr__` output. Set via the `namespace` constructor parameter. |
| `ctx.get_parent_context(raise_if_none=True)` | Get the immediate parent context (may be a `PromisingContext` or a `Promise`). |
| `ctx.get_parent_promise(raise_if_none=True)` | Get the nearest ancestor that is a `Promise` (walks up past non-Promise contexts). |
| `ctx.await_children(recursively=False)` | Async — wait for child contexts to finish. |
| `ctx.await_children_sync(recursively=False, timeout=None)` | Sync — block until child contexts finish. |
| `ctx.collect_remaining_children(recursively=False, exclude_non_awaitable=True, exclude_done=True)` | Get the set of child contexts that are still reachable and (optionally) still running. |
| `ctx.get_thread_pool_executor()` | Return the resolved thread pool executor for this context (`ThreadPoolExecutor`, or `None` if `ASYNCIO_DEFAULT`). |

### Top-Level Convenience Functions

| Function | Description |
|---|---|
| `promising.get_active_context(raise_if_none=True)` | Get the currently active `PromisingContext` (may be a `PromisingContext` or a `Promise`). |
| `promising.get_active_promise(raise_if_none=True)` | Get the currently active `Promise` (walks up the parent chain past non-Promise contexts). |
| `promising.await_children(recursively=False)` | Wait for all children of the current context. |
| `promising.await_children_sync(recursively=False, timeout=None)` | Sync counterpart — block until children finish. |
| `promising.Defaults.START_SOON` | Class attribute holding the global default for eager execution (`True` by default). Set it to `False` to switch to lazy execution globally. |
| `promising.Defaults.SYNC_THREAD_POOL` | The global `ThreadPoolExecutor` used by sync promising functions when `thread_pool` resolves to `GLOBAL_DEFAULT`. |

### Sentinels

| Sentinel | Meaning |
|---|---|
| `promising.UNCHANGED` | No value provided / no enforcement. |
| `promising.INHERIT` | Copy from the parent context; fall back to the global default when there is no parent. |
| `promising.GLOBAL_DEFAULT` | Read the current global setting directly, ignoring the parent chain. |
| `promising.ASYNCIO_DEFAULT` | Let the event loop use its own default executor (passes `None` to `run_in_executor`). Used with the `thread_pool` parameter. |
| `promising.Sentinel` | The sentinel class. All sentinels above are instances of it. |

All sentinels raise `RuntimeError` on boolean coercion to prevent misuse.

### Errors

| Error | Raised When |
|---|---|
| `promising.ContextNotFoundError` | No active `PromisingContext` is found (e.g. calling `get_active_context()` or `await_children()` outside a promising function). |
| `promising.ContextAlreadyActiveError` | Attempting to enter a `PromisingContext` that is already active (e.g. nested `with ctx:` on the same instance). |
| `promising.ContextNotActiveError` | Attempting to exit a `PromisingContext` that is not active. |
| `promising.ContextUsageError` | Misuse of `promising.context` (e.g. using the same instance as both context manager and decorator, or incorrect argument usage). |
| `promising.DecorationError` | Invalid decorator usage (e.g. passing a non-callable to `@promising.function` or `@promising.context`). |
| `promising.PromiseNotFoundError` | No active `Promise` is found (e.g. calling `get_active_promise()` when the active context is not a `Promise`). |
| `promising.SyncUsageError` | `sync()` or `await_children_sync()` is called from the event loop thread, which would deadlock. |

All inherit from `promising.BasePromisingError`.

## License

MIT
