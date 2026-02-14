# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Promising is a hierarchical asynchronous Promise/coroutine management library that extends `asyncio.Future`. It provides parent-child relationships between asynchronous operations via context variables.

## Common Commands

```bash
# Run all tests
pytest

# Run a single test file
pytest tests/promises/test_concurrent_future.py

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

Note: Tests use `pytest-asyncio` in auto mode - all async test functions are automatically detected without needing `@pytest.mark.asyncio`.

## Architecture

**Core hierarchy flow:** `PromisingFunction` wraps an async function/class → calling it creates a `Promise[T]` → during execution, the Promise sets itself as the current context via `ContextVar` → any Promises created during that execution become its children via `WeakSet`.

**Key components:**

- `Promise[T]` (`promising/promise.py`) - Extends `asyncio.Future` with hierarchical context management. Uses `ContextVar` (`Promise._current`) to track the currently active Promise. Key lifecycle: `__init__` → `_create_task()` (if `start_soon`) → `_afulfill()` (activates context, runs coro, waits for `make_parent_wait` children, sets result) → `_afinalize()` (resets context). Also contains `_PromiseBackedConcurrentFuture` for thread-safe bridging to `concurrent.futures.Future`.

- `PromisingConfig` (`promising/config.py`) - Configuration with inheritance. Values use `INHERIT` sentinel to inherit from the nearest inheritable parent config. Key settings:
  - `start_soon`: Execute immediately vs defer until awaited (default: True)
  - `make_parent_wait`: Parent waits for completion of "this" Promise (default: False)
  - `config_inheritable`: Config inheritance from "this" Promise to children (default: True)

- `PromisingFunction` (`promising/promising_function.py`) - Decorator/wrapper that turns async functions or classes into Promise-producing callables. Calling a `PromisingFunction` returns a `Promise[T]`.

- `PromisingBackend` (`promising/backends.py`) - WIP abstraction for pluggable backends with `_try_persisted_result` / `_persist_result` hooks.

**Sentinel pattern:** `NOT_SET` and `INHERIT` in `sentinels.py` raise on boolean coercion to prevent misuse. `NOT_SET` means "use default", `INHERIT` means "inherit from parent config".

**Public API** (exported from `promising/__init__.py`):
- `Promise`, `PromisingConfig`, `PromisingFunction`, `function`, `get_current_promise()`
- `function()` is the decorator: use as `@promising.function()` with config args or `@promising.function` bare.

**Example usage** (`examples/keyword_agent.py`): Shows idiomatic `@promising.function` decorator usage — decorate an async function, call it to get a `Promise`, await it for the result. Install example deps with `uv sync --extra examples`.

## Code Style

- Line length for all the code: 119 characters (Ruff)
- Line length for docstrings and comments specifically: 80 characters (to make them easily readable even when they are put in markdown blocks for documentation)
- Python version: 3.10+
- Pre-commit hooks enforce: trailing whitespace, YAML validation, Ruff formatting and linting
