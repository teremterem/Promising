# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development Commands

### Package Management
- **Install dependencies**: `uv sync --dev` (uses uv package manager)
- **Activate virtual environment**: `source .venv/bin/activate` (auto-created by uv)

### Code Quality
- **Format code**: `black .` (line length: 119 characters)
- **Lint code**: `pylint promising/` or `pylint <specific_file.py>`
- **Pre-commit hooks**: `pre-commit run --all-files`

### Testing
- **Run all tests**: `pytest`
- **Run specific test**: `pytest tests/promises/test_concurrent_future.py`
- **Run with coverage**: `pytest --cov=promising`
- **Async tests**: Uses pytest-asyncio with auto mode

### Building
- **Build package**: `uv build` (uses hatchling build backend)

## Code Architecture

### Core Components

**Promise System (`promising/promises.py`)**:
- `Promise` class extends asyncio.Future with hierarchical context management
- Supports parent-child relationships between asynchronous operations
- Provides configuration inheritance and automatic child task management
- Key methods: `get_current_promise()`, `as_concurrent_future()`

**Configuration System (`promising/configs.py`)**:
- `PromiseConfig` class for hierarchical configuration
- `PromisingDefaults` class with environment variable support
- Configuration inheritance from parent promises
- Environment variables prefixed with `PROMISING_DEFAULT_`

**Supporting Modules**:
- `types.py`: Generic type definitions (T_co covariant TypeVar)
- `errors.py`: Exception hierarchy for Promise and Config errors
- `sentinels.py`: Sentinel values for unset states
- `utils.py`: Utility functions for environment variable handling

### Project Structure
- Main package: `promising/`
- Tests: `tests/promises/` (single comprehensive test file currently)
- Configuration: Uses pyproject.toml with uv.lock for dependencies

### Key Patterns
- Context variable-based current promise tracking
- Hierarchical promise relationships with automatic child management
- Thread-safe concurrent.futures compatibility
- Environment variable-backed configuration defaults
- Comprehensive async testing with parametrized test cases

## Configuration Notes
- Python 3.10+ required
- Black formatting with 119 character line limit
- Pylint configuration in `.pylintrc`
- Pre-commit hooks include black and pylint validation
- Coverage tracking enabled for `promising` package
