# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Promising is a hierarchical asynchronous Promise/coroutine management library that extends `asyncio.Future`. It provides parent-child relationships between asynchronous operations via context variables.

## Common Commands

```bash
# Run all tests
pytest

# Run a single test file
pytest tests/promise/test_concurrent_future.py

# Run a single test function
pytest tests/promising_function/test_promising_function.py::test_calling_promising_function_returns_promise

# Run tests with coverage
pytest --cov=promising

# Format code
ruff format

# Lint code
ruff check

# Run pre-commit hooks manually
pre-commit run --all-files

# Install dependencies (uses uv with Hatchling build backend)
uv sync --all-extras
```

Note: Tests use `pytest-asyncio` in auto mode - all async test functions are automatically detected without needing `@pytest.mark.asyncio`. Each test gets its own event loop (`asyncio_default_fixture_loop_scope = "function"`). Tests run in parallel by default via pytest-xdist (`-n auto`); use `-n0` to disable parallelism for debugging. Tests are organized into subdirectories by component (e.g., `tests/promise/`, `tests/promising_function/`).

## Architecture

**Core hierarchy flow:** `PromisingFunction` wraps an async or sync function → calling it creates a `Promise[T]` → during execution, the Promise sets itself as the current context via `ContextVar` → any Promises created during that execution become its children via `WeakSet`.

**Key components:**

- `Promise[T]` (`promising/promise.py`) - Extends `asyncio.Future` with hierarchical context management. Uses `ContextVar` (`Promise._current`) to track the currently active Promise. Key lifecycle: `__init__` → `_create_task()` (if `start_soon`) → `_afulfill()` (activates context, runs coro, waits for children, sets result) → `_afinalize()` (resets context). Also contains `_PromiseBackedConcurrentFuture` for thread-safe bridging to `concurrent.futures.Future`. Configuration is handled directly on Promise via `start_soon`, `children_start_soon_by_default`, and `everything_starts_soon_by_default` parameters, which are either set to concrete boolean values or use sentinels (`INHERIT`, `NOT_SET`, `GLOBAL_DEFAULT`) to control inheritance from parent Promises.

- `PromisingFunction` (`promising/promising_function.py`) - Decorator/wrapper that turns async **or sync** functions into Promise-producing callables. Calling a `PromisingFunction` returns a `Promise[T]`. Async functions produce coroutines directly; sync functions are detected via `inspect.iscoroutinefunction()` and run in a module-level `ThreadPoolExecutor` (`_sync_function_executor`) via `loop.run_in_executor()` with `contextvars.copy_context()` to propagate `Promise._current` to the executor thread. Works with instance methods, `@classmethod`, and `@staticmethod` (decorator order doesn't matter — `@promising.function` can go above or below `@classmethod`/`@staticmethod`). Implements the descriptor protocol (`__get__`) to correctly bind `self`/`cls`. Accepts `start_soon`, `children_start_soon_by_default`, and `everything_starts_soon_by_default` config, which are forwarded to the created Promise. These three config params can also be passed as keyword arguments **at call time** (e.g. `my_func(arg, start_soon=False)`) to override the `PromisingFunction`-level defaults for that specific call; note that even passing `NOT_SET` explicitly at call time overrides the constructor value.

**Sentinel pattern:** `NOT_SET`, `INHERIT`, and `GLOBAL_DEFAULT` in `sentinels.py` raise on boolean coercion to prevent misuse. `NOT_SET` means "unset / no enforcement", `INHERIT` means "inherit from parent", `GLOBAL_DEFAULT` means "read the current global setting directly".

**Configuration:** `start_soon` determines whether a Promise starts executing immediately upon creation (or at the nearest available event loop window) or defers until awaited. `children_start_soon_by_default`, when set, enforces a `start_soon` default for child Promises. `everything_starts_soon_by_default` is a per-Promise local override (normally inherited by children, grandchildren, etc. as well) for the global `EVERYTHING_STARTS_SOON_BY_DEFAULT`. The global `EVERYTHING_STARTS_SOON_BY_DEFAULT` is set to `True`, although it can be changed via `promising.EVERYTHING_STARTS_SOON_BY_DEFAULT = False`. For the detailed inheritance logic of these parameters and their sentinel values, see the `Promise` class docstring.

**Key Promise methods:** `await_children()` — can be called inside a parent coroutine to wait for all child Promises before the parent resolves (otherwise children run concurrently and may outlive the parent). `as_concurrent_future()` — returns a thread-safe `concurrent.futures.Future` view of the Promise, allowing it to be used from non-async threads. `sync()` — the synchronous counterpart of `await promise`, blocks the calling thread until the Promise resolves; intended for use inside sync promising functions running in a thread pool. `sync_remaining_children()` — the synchronous counterpart of `await_children()`. Both `sync()` and `sync_remaining_children()` guard against being called from the event loop thread (raises `SyncPromiseUsageError` to prevent deadlock).

**Public API:** Almost all of the library's public symbols — classes, functions, sentinels, errors — are exported from `promising/__init__.py`. The decorator is `promising.function` — usable as `@promising.function()` with config args or `@promising.function` bare.

**Error classes** (`promising/errors.py`):
- `BasePromisingError` - base class
- `NoCurrentPromiseError` - raised when `get_current_promise()` is called outside a Promise context
- `NoParentPromiseError` - raised when a Promise has no parent
- `SyncPromiseUsageError` - raised when `sync()` or `sync_remaining_children()` are called from the event loop thread

**Example usage** (`examples/keyword_agent.py`): Shows idiomatic `@promising.function` decorator usage — decorate an async function, call it to get a `Promise`, await it for the result. Install example deps with `uv sync --extra examples`.

## Code Style

- Line length for all the code: 119 characters (Ruff)
- Line length for docstrings and comments specifically: 80 characters (to make them easily readable even when they are put in markdown blocks for documentation)
- Python version: 3.10+
- Pre-commit hooks enforce: trailing whitespace, end-of-file newline, YAML validation, Ruff linting (with `--fix`) and formatting
- There is no CI/CD — pre-commit is the main automated gate
