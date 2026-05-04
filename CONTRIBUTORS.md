# Contributing to Promising

## Common Commands

```bash
# Install dependencies (uses uv with Hatchling build backend)
uv sync --all-extras

# Run all tests
pytest

# Run a single test file
pytest tests/resolution/test_promise_sync_api.py

# Run a single test function
pytest tests/decoration/test_function_decorator_async.py::test_calling_promising_function_returns_promise

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

Tests use `pytest-asyncio` in auto mode — all async test functions are automatically detected without needing `@pytest.mark.asyncio`. Each test gets its own event loop (`asyncio_default_fixture_loop_scope = "function"`). Tests run in parallel by default via pytest-xdist (`-n auto`). A global timeout is enforced via pytest-timeout per each test. Tests are organized into subdirectories by concern: `tests/configuration/` (settings: `start_soon`, `thread_pool`, `use_thread_pool`, call-time overrides), `tests/decoration/` (decorator/descriptor plumbing for `@promising.function` and `@promising.context`), `tests/hierarchy/` (parent-child registration, nesting, cascading unregister), `tests/observability/` (namespaces, traces), `tests/resolution/` (awaiting, sync/await-children, timeout, cycle detection, future-like API), and `tests/misc/` (`run_in_executor`, `run_in_thread`, sentinels).

## Code Style

- Line length for all code: 119 characters (Ruff)
- Line length for docstrings and comments specifically: 80 characters (to make them easily readable even when they are put in markdown blocks for documentation)
- Python version: 3.11+ (one of the reasons: in 3.11, both `asyncio.TimeoutError` and `concurrent.futures.TimeoutError` became aliases for the builtin `TimeoutError`, so timeout handling across async and threaded code can use a single exception type — this matters for a library that bridges both worlds)
- Pre-commit hooks enforce: trailing whitespace, end-of-file newline, YAML validation, large file check, Ruff linting (with `--fix`) and formatting
- There is no CI/CD — pre-commit is the main automated gate

## Architecture

**Settings are frozen at creation time.** All configuration (`start_soon`, `children_start_soon`, `start_soon_default`, `thread_pool`, etc.) is fully resolved when a `Promise` or `PromisingContext` is constructed. Sentinels like `INHERIT` and `PROMISING_DEFAULT` are replaced with concrete values immediately — no deferred resolution happens at execution time. This is a core design principle: because a promise may run eagerly or be deferred, the user cannot predict *when* execution will happen, so settings must reflect the state of the world at the moment the promise was created.

**Core hierarchy flow:** `PromisingFunction` wraps an async or sync function → calling it creates a `Promise[T]` → during execution, the Promise sets itself as the current context via `ContextVar` → any Promises (and `PromisingContext` instances) created during that execution register themselves as its children via thread-safe strong-ref sets.

### PromisingContext (`promising/promising_context.py`)

The base class for hierarchical context management. Manages parent-child relationships, namespacing (`namespace` parameter), configuration inheritance (`children_start_soon`, `start_soon_default`, `thread_pool`), child-waiting (`await_children` / `await_children_sync`), child inspection (`collect_unsettled_children`), and trace/debugging (`get_trace`, `format_trace`, `print_trace`). Also provides `get_parent_promise()` to walk up past non-Promise contexts. Uses a `ContextVar` (`PromisingContext.__active_context`) to track the currently active context.

**Lifecycle and child tracking.** Each `PromisingContext` keeps an `_unsettled_children: set[PromisingContext]` (a strong-ref set) protected by a `threading.Lock`. Children are added via `_register_children_threadsafe()` when they are constructed (unless born closed via `close_context_immediately=True`, in which case registration is skipped entirely) and removed via `_unregister_children_threadsafe()` once they are both *closed* and have no remaining unsettled descendants. A context is "closed" when its `with` block has exited (`close_context_threadsafe()` runs in `__exit__`'s `finally`); for a `Promise`, the `with self:` block lives inside `_unpack_once_from_loop`, so the context closes the moment the wrapped awaitable produces its first result (intermediate Promise or final value). Closed contexts that still have unsettled descendants stay registered until those descendants drain — this is what `collect_unsettled_children` traverses recursively. Attempting to register a child on an already-closed context raises `ContextAlreadyClosedError`; re-entering an already-closed context raises the same error.

`PromisingContext` exposes two doneness predicates: `closed()` tracks the context-manager lifecycle (`__exit__` flips it to `True`), and `done()` is what `await_children()` actually waits on. By default `done()` simply delegates to `closed()`. Subclasses can override `done()` to track a non-lifecycle condition — `Promise` does exactly this (it ties `done()` to its own result/cancellation state machine, since "fully unpacked" can come *after* the `with self:` block has already exited).

**Custom awaitable contexts.** A subclass that defines `__await__` MUST either enter the context inside `__await__` (`with self: ...`) or override `done()` to track a non-lifecycle condition — otherwise `closed()`/`done()` never flip to `True` and any parent's `await_children()` will silently hang on it. See `tests/utils_for_tests.py::NonPromiseAwaitableContext` for a minimal pattern. Any `PromisingContext` subclass that satisfies the contract above can participate as an awaitable child of the hierarchy.

This file also contains the `context` class — a context manager / decorator that creates a `PromisingContext` without producing a `Promise`. It extends `PromisingDecorator` (from `decorator_support.py`) for decorator and descriptor support.

### Promise (`promising/promise.py`)

`Promise[T_co]` is a direct subclass of `PromisingContext`. It owns a small state machine — `_PENDING` → `_UNPACKED_ONCE` → `_FINISHED`, with `_CANCELLED_BEFORE_UNPACKED_ONCE` / `_CANCELLED_AFTER_UNPACKED_ONCE` as alternative terminals — exposed through `done()`, `unpacked_once()`, `unpacked_once_or_done()`, and `cancelled()`, and queried for results via `result()`, `exception()`, and `intermediate_promise()`. All of those readers are thread-safe (state can only move forward). `loop`, `thread_pool`, and the rest of the configuration are inherited from `PromisingContext`.

**Two-step unpacking on the loop.** Resolution is split into two cooperating tasks, both pinned to `self.loop`:

- `_unpack_once_from_loop()` — drives a single unpacking step. It enters the `with self:` block, awaits the wrapped `_awaitable`, and either records an intermediate `Promise` (via `_set_intermediate_promise`, transition to `_UNPACKED_ONCE`) or stores the final value/exception (via `_set_result` / `_set_exception`, transition to `_FINISHED`). This is the task `unpack_once()` waits on.
- `_fully_unpack_from_loop()` — drives the Promise to completion. It ensures the single-unpacking task is scheduled, awaits it, then walks the chain of intermediate Promises (`while isinstance(result, Promise): result = await result`) until a non-Promise value is reached, and records that value as the final result. This is the task `__await__` (and, indirectly, `sync()`) waits on.

Scheduling is driven by `_ensure_from_loop_single_unpacking_scheduled()` and `_ensure_from_loop_full_unpacking_scheduled()`, both of which create the underlying `loop.create_task(...)` lazily on first need. `__init__` schedules `_fully_unpack_from_loop` via `call_soon_threadsafe` when `start_soon` is `True`, so eager Promises start as soon as the loop is reachable; deferred Promises (`start_soon=False`) are scheduled the first time anyone consumes them (`__await__`, `sync()`, `unpack_once()`, `unpack_once_sync()`).

**Sync and thread-safe consumption.** `sync()` and `unpack_once_sync()` dispatch onto the Promise's own event loop via `asyncio.run_coroutine_threadsafe` and block the calling thread on the resulting `concurrent.futures.Future`. Both refuse to run on the Promise's loop thread (`assert_no_sync_usage_deadlock` → `SyncUsageError`). `cancel()` is similarly thread-safe: when called from outside the loop, it dispatches `_cancel_from_loop` via `call_soon_threadsafe` and blocks until the cancellation has run.

**Prefilled Promises.** A Promise constructed without an `awaitable` (using `prefilled_result` or `prefilled_exception`) passes `close_context_immediately=True` to `PromisingContext.__init__`, so it is born already closed and immediately set to `_FINISHED` — there is no coroutine to run inside a `with self:` block, and no parent registration happens.

**Exception breadcrumbs.** When `_set_exception` (or the last-resort `_force_finished_with_internal_error`) records an exception, `set_as_promising_context_on_exception` attaches the Promise to the exception as `__promising_context__`, but only at the deepest level (i.e. only if the attribute isn't already set). Intended for future error-tracing features.

**Unpacking semantics.** A `PromisingFunction` always returns a `Promise`, regardless of whether the underlying function returns a concrete value or another `Promise`. `await promise` and `promise.sync()` recursively chase nested `Promise`s until a non-`Promise` value is reached. `promise.unpack_once()` and `promise.unpack_once_sync()` unpack a single level — they return either a concrete value or the intermediate `Promise`.

**Non-`Promise` awaitables.** Unpacking only traverses `Promise` instances specifically. Anything else a function might return — a plain coroutine, an `asyncio.Future`, an async generator — is treated as a concrete value by the framework: it is surfaced to the caller as-is, with no auto-wrapping and no further unpacking. In practice the typical return value is either a concrete value or another `Promise`; non-`Promise` awaitables are an edge case the framework deliberately leaves to the caller.

**Module helpers.** `wrap_awaitable(awaitable, **kwargs)` is the recommended way to lift a bare coroutine (or other awaitable) into a `Promise` from outside a decorated function. `get_active_promise()` walks the active context chain skipping non-`Promise` nodes.

### DecoratorSupport and PromisingDecorator (`promising/decorator_support.py`)

`DecoratorSupport` is the base class that provides decorator and descriptor plumbing shared by `promising.context` and `PromisingFunction`. It handles `functools.update_wrapper` bookkeeping and implements `__get__` so that decorators work correctly on instance methods, `@classmethod`, and `@staticmethod`. `PromisingDecorator` extends `DecoratorSupport` with the common configuration parameters (`children_start_soon`, `start_soon_default`, `thread_pool`) and the `__call__` dispatch logic that distinguishes "still decorating" from "calling the decorated function".

### PromisingFunction (`promising/promising_function.py`)

Decorator/wrapper that turns async **or sync** functions into Promise-producing callables. Calling a `PromisingFunction` returns a `Promise[T]`. Extends `PromisingDecorator` (from `decorator_support.py`) for decorator and descriptor support. Sets a class-level `_is_coroutine` marker so that `asyncio.iscoroutinefunction()` recognizes all promising functions as coroutine functions — even those wrapping sync functions — since they always return awaitable `Promise` objects.

- **Async functions** produce coroutines directly.
- **Sync functions** are detected via `asyncio.iscoroutinefunction()` (cached at decoration time as `_is_wrapped_async` on `DecoratorSupport`) and require an explicit `use_thread_pool` setting. With `use_thread_pool=True` (recommended), they run in a `ThreadPoolExecutor` (configurable via the `thread_pool` parameter, defaulting to `Defaults.PROMISING_THREAD_POOL`) via `loop.run_in_executor()` with `contextvars.copy_context()` to propagate the active context to the executor thread. With `use_thread_pool=False`, the sync function runs directly on the event loop thread instead (useful for lightweight transforms, but blocks the loop). Omitting `use_thread_pool` on a sync function raises `DecorationError`. Conversely, setting `use_thread_pool` on an async function also raises `DecorationError` — async functions always run on the event loop regardless. An alternative to `use_thread_pool=False` is to simply mark the function as `async` without using `await` inside, which avoids the thread pool naturally (same caveat: CPU-heavy work will block the event loop). Unlike `thread_pool`, `use_thread_pool` is intentionally not inheritable — it must be set per-function at decoration time (and can be overridden at call time for sync functions).
- **`run()`** is a top-level entrypoint for running a decorated function from non-async code — analogous to `asyncio.run()`. It calls `asyncio.run()` on `protected_run()`, creating its own event loop, awaiting the result, and by default awaiting all children recursively (`await_children=WHOLE_SUBTREE`). This is distinct from `promise.sync()`, which is for consuming a promise's result from within a sync promising function that already runs inside an event loop (in a thread pool).
- **`protected_run()`** returns a **coroutine** (not a `Promise`), making it safe to pass to `asyncio.run()` — unlike calling the decorated function directly, which would construct a `Promise` before the event loop exists and fail (a root `PromisingContext` requires a running loop). Inside, the coroutine calls the decorated function, awaits the resulting `Promise`, and then — in a `finally` block, so regardless of success or failure — awaits its children (controlled by the `await_children` parameter, defaulting to `WHOLE_SUBTREE`). Used by `run()` internally.

### Sentinel Pattern (`promising/sentinels.py`)

All public sentinels (`UNCHANGED`, `AUTO`, `INHERIT`, `PROMISING_DEFAULT`, `ASYNCIO_DEFAULT`, `WHOLE_SUBTREE`) raise `SentinelUsageError` on boolean coercion to prevent misuse — use `is` / `is not` identity comparisons instead. `UNCHANGED` means "no call-time override — use the decorator-level value", `AUTO` is the default for the `parent` parameter and means "pick up the currently active context automatically" (pass `None` to opt out and create a root), `INHERIT` means "inherit from parent", `PROMISING_DEFAULT` means "read the current global setting directly, ignoring the parent chain", `ASYNCIO_DEFAULT` means "let the event loop use its own default executor", and `WHOLE_SUBTREE` means "await all descendants recursively" (used as the default for `await_children` in `PromisingFunction.run()` / `protected_run()`).

This module also defines the private state-machine sentinels used by `Promise` (`_PENDING`, `_UNPACKED_ONCE`, `_FINISHED`, `_CANCELLED_BEFORE_UNPACKED_ONCE`, `_CANCELLED_AFTER_UNPACKED_ONCE`). They are not part of the public API but follow the same `Sentinel` mechanics.

### Error Classes (`promising/errors.py`)

- `PromisingError` — base class for all promising errors
- `ContextError(PromisingError)` — base class for context-related errors
  - `ContextAlreadyActiveError` — attempting to enter a `PromisingContext` that is already active
  - `ContextAlreadyClosedError` — attempting to re-enter a `PromisingContext` that has already been closed, or registering a child on a closed context
  - `ContextNotActiveError` — attempting to exit a `PromisingContext` that is not active
  - `ContextNotFoundError` — no active `PromisingContext` found
- `DecorationError` — invalid decorator usage (also covers misuse of `promising.context`, e.g. using the same instance as both context manager and decorator)
- `EventLoopError(PromisingError)` — base class for event loop-related errors
  - `EventLoopMismatchError(EventLoopError, ValueError)` — awaiting a `Promise` from a different event loop than the one it belongs to
  - `NoRunningEventLoopError(EventLoopError, RuntimeError)` — no running event loop found when one is required
- `PromiseNotDoneError(PromisingError, asyncio.InvalidStateError, concurrent.futures.InvalidStateError)` — `Promise.result()` / `Promise.exception()` was called before the Promise was done
- `PromiseNotFoundError` — no active `Promise` found (the active context is not a `Promise`)
- `PromiseNotUnpackedError(PromisingError, asyncio.InvalidStateError, concurrent.futures.InvalidStateError)` — `Promise.intermediate_promise()` was called before the first unpacking step
- `SentinelUsageError` — a `Sentinel` was used in a boolean context (e.g. `if INHERIT:`)
- `SyncUsageError` — raised when a sync method (`promise.sync()`, `promise.unpack_once_sync()`, `await_children_sync()`) is called from the event loop thread

### Public API

Almost all of the library's public symbols — classes, functions, sentinels, errors — are exported from `promising/__init__.py`. The main entry points are `promising.function` (decorator that produces Promises) and `promising.context` (context manager / decorator that creates a bare `PromisingContext`). Both are usable bare or with configuration arguments.
