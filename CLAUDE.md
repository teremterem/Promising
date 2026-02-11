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

**Core Components:**

- `Promise[T]` (`promising/promise.py`) - Main class extending `asyncio.Future` with hierarchical context management. Uses `ContextVar` (`Promise._current`) to track the currently active Promise and `WeakSet` for parent-child relationships. Key behavior: when a Promise's coroutine creates other Promises during execution, those become children of the active Promise (regardless of when they complete).

- `PromisingConfig` (`promising/config.py`) - Configuration system with inheritance. Config values use `INHERIT` sentinel to inherit from the nearest inheritable parent config. Key settings:
  - `start_soon`: Execute immediately vs defer until awaited (default: True)
  - `make_parent_wait`: Parent waits for completion of "this" Promise (default: False)
  - `config_inheritable`: Config inheritance from "this" Promise to children (default: True)

- `PromisingFunction` (`promising/promising_function.py`) - Decorator/wrapper that turns async functions or classes into Promise-producing callables. Supports both `@promising.function(...)` decorator syntax (with config args) and direct `PromisingFunction(func)` construction. Calling a `PromisingFunction` returns a `Promise[T]`.

- `PromisingBackend` (`promising/backends.py`) - WIP abstraction for pluggable backends that can intercept function calls to provide persisted/cached results. Has `_try_persisted_result` / `_persist_result` hooks.

- `_PromiseBackedConcurrentFuture` (`promising/promise.py`) - Bridges asyncio Promises to `concurrent.futures.Future` for multi-threaded contexts.

**Supporting modules:**

- `sentinels.py` - `NOT_SET` and `INHERIT` sentinels (raise on boolean coercion to prevent misuse)
- `errors.py` - Exception hierarchy: `BasePromisingError` → `PromiseError` → `NoCurrentPromiseError`, `NoParentPromiseError`; `BasePromisingError` → `BasePromiseConfigError` → `NoParentConfigError`; `PromiseError` → `PromiseFunctionError` → `PromiseFunctionNotCallableError`
- `utils.py` - `get_concrete_value()` resolves sentinel-or-concrete to concrete
- `types.py` - `T_co` (covariant TypeVar for Promise results), `F_co` (covariant TypeVar for function return types)

**Public API** (exported from `promising/__init__.py`):
- `Promise`, `PromisingConfig`, `PromisingFunction`, `get_current_promise()`

**Examples** (`examples/`):
- `htmx_ui/` - FastHTML web app demonstrating Promise integration with HTMX, DaisyUI, and optional Langfuse observability.
- `keyword_agent.py` - Demonstrates `PromisingFunction` usage: creates a `PromisingFunction` root, registers an async function via `@promising_root.function()`, and calls it to get a `Promise`. Uses litellm + pydantic for structured LLM output.
- Install example deps with `uv sync --extra examples`.

## Code Style

- Line length: 119 characters (Ruff)
- Python version: 3.10+
- Ruff lint rules: E, F, W, I, N, UP, B, C4, PL
- Pre-commit hooks enforce: trailing whitespace, YAML validation, Ruff formatting and linting
