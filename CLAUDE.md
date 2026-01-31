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
black .

# Lint code
pylint promising/

# Run pre-commit hooks manually
pre-commit run --all-files
```

## Architecture

**Core Components:**

- `Promise[T]` (`promising/promises.py`) - Main class extending `asyncio.Future` with hierarchical context management. Uses `ContextVar` to track parent-child relationships via `WeakSet`. Supports automatic child waiting and thread-safe `concurrent.futures.Future` compatibility.

- `PromiseConfig` (`promising/configs.py`) - Configuration system with inheritance. Key settings:
  - `start_soon`: Execute immediately vs defer until awaited
  - `make_parent_wait`: Parent waits for child completion
  - `config_inheritable`: Config inheritance to children

- `_PromiseBackedConcurrentFuture` (`promising/promises.py`) - Bridges asyncio Promises to `concurrent.futures.Future` for multi-threaded contexts.

**Public API** (exported from `promising/__init__.py`):
- `Promise` - Main Promise class
- `PromiseConfig` - Configuration class
- `get_current_promise()` - Get active Promise from context

**Configuration via Environment Variables:**
- `PROMISING_DEFAULT_START_SOON`
- `PROMISING_DEFAULT_MAKE_PARENT_WAIT`
- `PROMISING_DEFAULT_CONFIGS_INHERITABLE`

## Code Style

- Line length: 119 characters (Black)
- Python version: 3.10+
- Pre-commit hooks enforce: trailing whitespace, YAML validation, Black formatting, Pylint
