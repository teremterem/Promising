# Contributing to Promising

## Common Commands

```bash
# Install dependencies (uses uv with Hatchling build backend)
uv sync --all-extras

# Run all tests
pytest

# Run a single test file
pytest tests/promise/sync/test_concurrent_future.py

# Run a single test function
pytest tests/promising_function/test_promising_function.py::test_calling_promising_function_returns_promise

# Run tests with coverage
pytest --cov=promising

# Disable parallel test execution (useful for debugging)
pytest -n0

# Format code
ruff format

# Lint code
ruff check

# Run pre-commit hooks manually
pre-commit run --all-files
```

Tests use `pytest-asyncio` in auto mode — all async test functions are automatically detected without needing `@pytest.mark.asyncio`. Each test gets its own event loop (`asyncio_default_fixture_loop_scope = "function"`). Tests run in parallel by default via pytest-xdist (`-n auto`). A global 10-second timeout per test is enforced via pytest-timeout. Tests are organized into subdirectories by component (e.g., `tests/promise/`, `tests/promising_context/`, `tests/promising_function/`), each with a `sync/` subdirectory for sync-related tests. `tests/misc/` contains cross-cutting tests (decorator robustness, `asyncio.run()` integration, traces).

## Code Style

- Line length for all code: 119 characters (Ruff)
- Line length for docstrings and comments specifically: 80 characters (to make them easily readable even when they are put in markdown blocks for documentation)
- Python version: 3.11+ (one of the reasons: in 3.11, both `asyncio.TimeoutError` and `concurrent.futures.TimeoutError` became aliases for the builtin `TimeoutError`, so timeout handling across async and threaded code can use a single exception type — this matters for a library that bridges both worlds)
- Pre-commit hooks enforce: trailing whitespace, end-of-file newline, YAML validation, large file check, Ruff linting (with `--fix`) and formatting
- There is no CI/CD — pre-commit is the main automated gate

## Architecture

**Settings are frozen at creation time.** All configuration (`start_soon`, `children_start_soon`, `start_soon_default`, `thread_pool`, etc.) is fully resolved when a `Promise` or `PromisingContext` is constructed. Sentinels like `INHERIT` and `PROMISING_DEFAULT` are replaced with concrete values immediately — no deferred resolution happens at execution time. This is a core design principle: because a promise may run eagerly or be deferred, the user cannot predict *when* execution will happen, so settings must reflect the state of the world at the moment the promise was created.

**Core hierarchy flow:** `PromisingFunction` wraps an async or sync function → calling it creates a `Promise[T]` → during execution, the Promise sets itself as the current context via `ContextVar` → any Promises created during that execution become its children via `WeakSet`.

### PromisingContext (`promising/promising_context.py`)

The base class for hierarchical context management. Manages parent-child relationships, namespacing (`namespace` parameter), configuration inheritance (`children_start_soon`, `start_soon_default`, `thread_pool`), child-waiting (`await_children` / `await_children_sync`), child inspection (`collect_remaining_children`), and trace/debugging (`get_trace`, `format_trace`, `print_trace`). Also provides `get_parent_promise()` to walk up past non-Promise contexts. Uses a `ContextVar` (`PromisingContext.__active_context`) to track the currently active context. Children are tracked via `WeakSet`.

This file also contains the `context` class — a context manager / decorator that creates a `PromisingContext` without producing a `Promise`. It extends `PromisingDecorator` (from `decorator_support.py`) for decorator and descriptor support.

### Promise (`promising/promise.py`)

Extends both `PromisingContext` and `asyncio.Future`. Adds coroutine execution lifecycle on top of the hierarchy: `__init__` → `_ensure_task_scheduled()` (if `start_soon`) → `_fulfill()` (activates context, runs coro, sets result) → context restoration (resets `ContextVar` token). Also contains `PromiseBackedConcurrentFuture` for thread-safe bridging to `concurrent.futures.Future`. Both `__await__` and `PromiseBackedConcurrentFuture`'s blocking methods (`result()`, `exception()`) call `_ensure_task_scheduled()` before waiting, so deferred Promises (`start_soon=False`) are automatically started when consumed — no manual scheduling is needed.

**Awaitable auto-wrapping:** When a Promise's result (set via `set_result()`) is an awaitable that is not already a `Promise`, it is automatically wrapped in a child `Promise`. This guarantees that `unpack_once()` and `unpack_once_sync()` always return either a concrete value or a `Promise` (never a plain awaitable).

**Exception breadcrumbs:** During `_fulfill()`, if the awaitable raises an exception, the Promise attaches itself as `exception.__promising_context__` (only at the deepest level where the exception originates). This is intended for future error tracing / breadcrumb features.

**Unpacking semantics:** A `PromisingFunction` always returns a `Promise`, regardless of whether the underlying function returns a concrete value, a coroutine, or another `Promise`. From there, `await promise` and `promise.sync()` always return a concrete value — they recursively unpack nested Promises until a non-Promise result is reached. `promise.unpack_once()` and `promise.unpack_once_sync()` unpack only one level, returning either a concrete value or another `Promise` (never a plain awaitable, thanks to auto-wrapping above). Notably, `unpack_once_sync()` returns the same dual-purpose `Promise` objects as `unpack_once()` — the caller can continue with `.sync()` in a sync context or switch to `await` in an async one. The async unpacking logic lives in `_AwaitablePromiseUnpacker`, a helper class used by both `__await__` (with `unpack_all=True`) and `unpack_once` (with `unpack_all=False`).

### DecoratorSupport and PromisingDecorator (`promising/decorator_support.py`)

`DecoratorSupport` is the base class that provides decorator and descriptor plumbing shared by `promising.context` and `PromisingFunction`. It handles `functools.update_wrapper` bookkeeping and implements `__get__` so that decorators work correctly on instance methods, `@classmethod`, and `@staticmethod`. `PromisingDecorator` extends `DecoratorSupport` with the common configuration parameters (`children_start_soon`, `start_soon_default`, `thread_pool`) and the `__call__` dispatch logic that distinguishes "still decorating" from "calling the decorated function".

### PromisingFunction (`promising/promising_function.py`)

Decorator/wrapper that turns async **or sync** functions into Promise-producing callables. Calling a `PromisingFunction` returns a `Promise[T]`. Extends `PromisingDecorator` (from `decorator_support.py`) for decorator and descriptor support. Sets a class-level `_is_coroutine` marker so that `asyncio.iscoroutinefunction()` recognizes all promising functions as coroutine functions — even those wrapping sync functions — since they always return awaitable `Promise` objects.

- **Async functions** produce coroutines directly.
- **Sync functions** are detected via `asyncio.iscoroutinefunction()` (cached at decoration time as `_is_wrapped_async` on `DecoratorSupport`) and require an explicit `use_thread_pool` setting. With `use_thread_pool=True` (recommended), they run in a `ThreadPoolExecutor` (configurable via the `thread_pool` parameter, defaulting to `Defaults.PROMISING_THREAD_POOL`) via `loop.run_in_executor()` with `contextvars.copy_context()` to propagate the active context to the executor thread. With `use_thread_pool=False`, the sync function runs directly on the event loop thread instead (useful for lightweight transforms, but blocks the loop). Omitting `use_thread_pool` on a sync function raises `DecorationError`. Conversely, setting `use_thread_pool` on an async function also raises `DecorationError` — async functions always run on the event loop regardless. An alternative to `use_thread_pool=False` is to simply mark the function as `async` without using `await` inside, which avoids the thread pool naturally (same caveat: CPU-heavy work will block the event loop). Unlike `thread_pool`, `use_thread_pool` is intentionally not inheritable — it must be set per-function at decoration time (and can be overridden at call time for sync functions).
- **`run()`** is a top-level entrypoint for running a decorated function from non-async code — analogous to `asyncio.run()`. It calls `asyncio.run()` on `protected_run()`, creating its own event loop, awaiting the result, and by default awaiting all children recursively (`await_children=RECURSIVELY`). This is distinct from `promise.sync()`, which is for consuming a promise's result from within a sync promising function that already runs inside an event loop (in a thread pool).
- **`protected_run()`** returns a **coroutine** (not a `Promise`), making it safe to pass to `asyncio.run()` — unlike calling the decorated function directly, which would construct a `Promise` (an `asyncio.Future` subclass) before the event loop exists and fail. Inside, the coroutine calls the decorated function, awaits the resulting `Promise`, and then — in a `finally` block, so regardless of success or failure — awaits its children (controlled by the `await_children` parameter, defaulting to `RECURSIVELY`). Used by `run()` internally.

### Sentinel Pattern (`promising/sentinels.py`)

`UNCHANGED`, `INHERIT`, `PROMISING_DEFAULT`, `ASYNCIO_DEFAULT`, and `RECURSIVELY` raise `SentinelUsageError` on boolean coercion to prevent misuse. `UNCHANGED` means "no call-time override — use the decorator-level value", `INHERIT` means "inherit from parent", `PROMISING_DEFAULT` means "read the current global setting directly", `ASYNCIO_DEFAULT` means "let the event loop use its own default executor", `RECURSIVELY` means "await all descendants recursively" (used as the default for `await_children` in `PromisingFunction.run()` and `protected_run()`).

### Error Classes (`promising/errors.py`)

- `PromisingError` — base class for all promising errors
- `ContextError(PromisingError)` — base class for context-related errors
  - `ContextAlreadyActiveError` — attempting to enter a `PromisingContext` that is already active
  - `ContextNotActiveError` — attempting to exit a `PromisingContext` that is not active
  - `ContextNotFoundError` — no active `PromisingContext` found
- `DecorationError` — invalid decorator usage (also covers misuse of `promising.context`, e.g. using the same instance as both context manager and decorator)
- `EventLoopError(PromisingError)` — base class for event loop-related errors
  - `EventLoopMismatchError(EventLoopError, ValueError)` — awaiting a `Promise` from a different event loop than the one it belongs to
  - `NoRunningEventLoopError(EventLoopError, RuntimeError)` — no running event loop found when one is required
- `PromiseNotFoundError` — no active `Promise` found (the active context is not a `Promise`)
- `SentinelUsageError` — a `Sentinel` was used in a boolean context (e.g. `if INHERIT:`)
- `SyncUsageError` — raised when `sync()` or `await_children_sync()` are called from the event loop thread

### Public API

Almost all of the library's public symbols — classes, functions, sentinels, errors — are exported from `promising/__init__.py`. The main entry points are `promising.function` (decorator that produces Promises) and `promising.context` (context manager / decorator that creates a bare `PromisingContext`). Both are usable bare or with configuration arguments.
