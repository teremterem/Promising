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
```

Note: Tests use `pytest-asyncio` in auto mode - all async test functions are automatically detected without needing `@pytest.mark.asyncio`.

## Architecture

**Core Components:**

- `Promise[T]` (`promising/promises.py`) - Main class extending `asyncio.Future` with hierarchical context management. Uses `ContextVar` (`Promise._current`) to track the currently active Promise and `WeakSet` for parent-child relationships. Key behavior: when a Promise's coroutine creates other Promises during execution, those become children of the active Promise (regardless of when they complete).

- `PromiseConfig` (`promising/configs.py`) - Configuration system with inheritance. Key settings:
  - `start_soon`: Execute immediately vs defer until awaited (default: True)
  - `make_parent_wait`: Parent waits for completion of "this" Promise (default: False)
  - `config_inheritable`: Config inheritance from "this" Promise to children (default: True)

- `_PromiseBackedConcurrentFuture` (`promising/promises.py`) - Bridges asyncio Promises to `concurrent.futures.Future` for multi-threaded contexts.

**Supporting modules:**

- `sentinels.py` - `NOT_SET` sentinel for distinguishing unset values from None
- `errors.py` - Custom exceptions (`NoCurrentPromiseError`, `NoParentPromiseError`, `NoParentConfigError`) inheriting from `PromiseError` and `BasePromisingError`
- `utils.py` - Helper functions like `get_concrete_value()`
- `types.py` - Type definitions (`T_co` covariant TypeVar used by Promise)

**Public API** (exported from `promising/__init__.py`):
- `Promise` - Main Promise class
- `PromiseConfig` - Configuration class
- `get_current_promise()` - Get active Promise from context

## Code Style

- Line length: 119 characters (Ruff)
- Python version: 3.10+
- Pre-commit hooks enforce: trailing whitespace, YAML validation, Ruff formatting and linting
