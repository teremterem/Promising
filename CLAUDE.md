# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Promising is an asynchronous Python library that extends asyncio Futures with hierarchical context management. It provides Promise objects that combine Future functionality with parent-child relationships between asynchronous operations.

## Key Architecture

### Core Components

1. **Promise** (`promising/promises.py`): Main class extending asyncio Future with:
   - Parent-child relationships between async operations
   - Configuration inheritance from parent Promises
   - Automatic child task management and waiting
   - Thread-safe concurrent.futures compatibility

2. **PromiseConfig** (`promising/configs.py`): Configuration system with:
   - Hierarchical config inheritance
   - Control over execution timing (`start_soon`)
   - Parent waiting behavior (`make_parent_wait`)
   - Inheritability settings

3. **Sentinels** (`promising/sentinels.py`): Special marker objects like `NOT_SET` for distinguishing unset values from None

4. **Error Hierarchy** (`promising/errors.py`): Custom exceptions for Promise-specific error cases

### Parent-Child Semantics

- Promises created during a parent Promise's coroutine execution automatically become its children
- Child execution timing is independent of parent execution window
- Explicit parent specification at creation time takes precedence
- Configuration inheritance flows from parent to child Promises

## Development Commands

### Testing
```bash
# Run all tests
pytest

# Run specific test file
pytest tests/promises/test_concurrent_future.py

# Run with coverage
pytest --cov=promising

# Run specific test
pytest -k test_as_concurrent_future
```

### Code Quality
```bash
# Format code with black (line-length: 119)
black promising/ tests/

# Run linting
pylint promising/ tests/

# Run pre-commit hooks
pre-commit run --all-files
```

### Build & Package
```bash
# Build the package
hatch build

# Install in development mode
pip install -e .

# Install with dev dependencies
pip install -e ".[dev]"
```

## Development Guidelines

1. **Python Version**: Requires Python >= 3.10
2. **Line Length**: 119 characters (configured in pyproject.toml)
3. **Type Hints**: Use generics and type annotations throughout
4. **Docstrings**: Follow the existing pattern with Args, Returns, Raises sections
5. **Testing**: Use pytest with asyncio mode enabled (auto-configured)

## Environment Variables

The library supports configuration via environment variables:
- `PROMISING_DEFAULT_START_SOON`: Default value for `start_soon` (true/false)
- `PROMISING_DEFAULT_MAKE_PARENT_WAIT`: Default value for `make_parent_wait` (true/false)
- `PROMISING_DEFAULT_CONFIGS_INHERITABLE`: Default value for `config_inheritable` (true/false)

## Current Work in Progress

Several TODOs exist in the codebase indicating areas under development:
- Support for cancellation of entire Promise trees
- Optional children_config support
- Performance optimizations for multithreading support
- Config system refinements
