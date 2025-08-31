# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Commands
- Install deps: uv pip install -e .[dev]
- Format: uv run black .
- Lint: uv run pylint promising tests
- Test all: uv run pytest -q --cov=promising --cov-report=term-missing
- Test single file: uv run pytest tests/promises/test_concurrent_future.py -q
- Build dist: uv run python -m build

Architecture
- Package promising provides asyncio-native Promise abstraction extending asyncio.Future with parent/child context and inheritable config.
- Core modules:
  - promising/promises.py: Promise[T] extends Future. Key pieces: contextvar current Promise, parent linkage, WeakSet children, config inheritance via PromiseConfig; start_soon scheduling; __await__ triggers _afulfill; concurrent.futures bridge via _PromiseBackedConcurrentFuture (result/exception propagate and consume underlying Future to avoid warnings); await_for_children gathers children where config.make_parent_wait.
  - promising/configs.py: PromiseConfig with hierarchical inheritance. Root defaults from env PROMISING_DEFAULT_* via utils.get_bool_env; inheritance resolution via find_inheritable_config; guards against non-inheritable root.
  - promising/sentinels.py: NOT_SET sentinel for tri-state params preventing bool usage.
  - promising/utils.py: get_bool_env strict true/false parser; get_concrete_value resolves NOT_SET.
  - promising/errors.py: Typed exception hierarchy.
  - promising/__init__.py and types.py: public API exports and typing.
- Tests: tests/promises/test_concurrent_future.py covers concurrent.futures interop, exceptions, and threading behavior across start_soon/await permutations.

Conventions
- Python 3.10+, black line length 119 (pyproject). Use uv for running tools. Prefer explicit awaits to avoid asyncio warnings. Keep config inheritance semantics intact when adding features.
