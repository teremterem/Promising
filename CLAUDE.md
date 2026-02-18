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
pytest tests/promising_function/test_promising_function.py::test_decorator_bare

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

Note: Tests use `pytest-asyncio` in auto mode - all async test functions are automatically detected without needing `@pytest.mark.asyncio`. Tests run in parallel by default via pytest-xdist (`-n auto`); use `-n0` to disable parallelism for debugging. Tests are organized into subdirectories by component (e.g., `tests/promise/`, `tests/promising_function/`).

## Architecture

**Core hierarchy flow:** `PromisingFunction` wraps an async function/class → calling it creates a `Promise[T]` → during execution, the Promise sets itself as the current context via `ContextVar` → any Promises created during that execution become its children via `WeakSet`.

**Key components:**

- `Promise[T]` (`promising/promise.py`) - Extends `asyncio.Future` with hierarchical context management. Uses `ContextVar` (`Promise._current`) to track the currently active Promise. Key lifecycle: `__init__` → `_create_task()` (if `start_soon`) → `_afulfill()` (activates context, runs coro, waits for children, sets result) → `_afinalize()` (resets context). Also contains `_PromiseBackedConcurrentFuture` for thread-safe bridging to `concurrent.futures.Future`. Configuration is handled directly on Promise via `start_soon` and `children_start_soon_by_default` parameters, which use `INHERIT` sentinel to inherit from the parent Promise.

- `PromisingFunction` (`promising/promising_function.py`) - Decorator/wrapper that turns async functions or classes into Promise-producing callables. Calling a `PromisingFunction` returns a `Promise[T]`. Accepts `start_soon` and `children_start_soon_by_default` config, which are forwarded to the created Promise.

**Sentinel pattern:** `NOT_SET` and `INHERIT` in `sentinels.py` raise on boolean coercion to prevent misuse. `NOT_SET` means "use default", `INHERIT` means "inherit from parent".

**Configuration:** `start_soon` determines whether a Promise starts executing immediately upon creation (or, upon the nearest event loop execution window which is not occupied by something else, to be precise) or defers until awaited explicitly. `children_start_soon_by_default`, if set, dictates the `start_soon` value for those child Promises which don't have it set explicitly. To put it another way, `INHERIT` in `start_soon` means that the value for `start_soon` should be taken from the parent Promise's `children_start_soon_by_default` value. Conversely, when `children_start_soon_by_default` itself is set to `INHERIT`, it simply means that the value for `children_start_soon_by_default` setting is inherited from the parent Promise's `children_start_soon_by_default`. If all of the above are set to `INHERIT`, then the value is taken from the global `EVERYTHING_STARTS_SOON_BY_DEFAULT`, which is set to `True` but can be overridden by the user by a simple assignment of `promising.EVERYTHING_STARTS_SOON_BY_DEFAULT = False` or similar.

**Public API** (exported from `promising/__init__.py`):
- `Promise`, `PromisingFunction`, `function`, `get_current_promise()`
- `INHERIT`, `NOT_SET`, `Sentinel` - sentinel values
- `EVERYTHING_STARTS_SOON_BY_DEFAULT`, `should_everything_start_soon_by_default()` - global default control
- `function()` is the decorator: use as `@promising.function()` with config args or `@promising.function` bare.

**Example usage** (`examples/keyword_agent.py`): Shows idiomatic `@promising.function` decorator usage — decorate an async function, call it to get a `Promise`, await it for the result. Install example deps with `uv sync --extra examples`.

## Code Style

- Line length for all the code: 119 characters (Ruff)
- Line length for docstrings and comments specifically: 80 characters (to make them easily readable even when they are put in markdown blocks for documentation)
- Python version: 3.10+
- Pre-commit hooks enforce: trailing whitespace, YAML validation, Ruff formatting and linting
