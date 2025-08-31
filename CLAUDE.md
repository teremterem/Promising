# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Repo overview
- Python package: promising/
- Tests: tests/
- Tooling: pyproject.toml (black, pytest, pytest-asyncio, pytest-cov, pylint, hatch)

Common commands
- Install dev deps: uv pip install -e "."[dev]
- Run tests: pytest -q
- Run a single test file: pytest tests/promises/test_concurrent_future.py -q
- Run a single test: pytest -k "test_as_concurrent_future and not with_exception" -q
- Coverage (terminal): pytest --cov=promising --cov-report=term-missing -q
- Coverage (HTML): pytest --cov=promising --cov-report=html -q  # opens ./htmlcov/index.html
- Lint: pylint promising tests
- Format: black .
- Build wheel/sdist: uv build  # or: hatch build

Architecture
- Core abstraction: Promise[T] (promising/promises.py:36) extends asyncio.Future, adds:
  - Hierarchical parent/child relationships via contextvars
  - Config resolution/inheritance (PromiseConfig) and start semantics
  - Automatic waiting for selected children on finalize
  - Thread interop via as_concurrent_future() returning concurrent.futures.Future
- Current/parent accessors:
  - get_current_promise() -> Promise | None (promising/promises.py:19)
  - Promise.get_current(...) classmethod (promising/promises.py:273)
  - get_parent(...), get_pending_children(), await_for_children()
- Execution lifecycle:
  - Constructor wires parent/loop, registers child, sets config, optionally schedules task when start_soon
  - __await__ lazily runs _afulfill when not started
  - _afulfill activates context, awaits coro, then afinalize; sets result/exception
  - _activate/_afinalize maintain ContextVar and gather children with make_parent_wait
- Configs (promising/configs.py):
  - PromiseConfig supports chained parents; values may be NOT_SET sentinel-resolved
  - Defaults read from env via PromisingDefaults: START_SOON, MAKE_PARENT_WAIT, CONFIGS_INHERITABLE
  - Inheritance uses find_inheritable_config(); root configs are always inheritable
- Sentinels/utilities:
  - NOT_SET sentinel (promising/sentinels.py) to distinguish omitted vs explicit values
  - get_bool_env, get_concrete_value (promising/utils.py)
- Errors (promising/errors.py): typed exceptions for missing current/parent promise or config
- Public API (promising/__init__.py): Promise, PromiseConfig, get_current_promise

Notes for contributors
- Tests exercise concurrent.futures interop and threading scenarios (tests/promises/test_concurrent_future.py)
- Event loop consistency: parent/child must share loop; constructor enforces this
- Thread interop: _PromiseBackedConcurrentFuture mirrors Promise completion and consumes result/exception to avoid asyncio warnings

Local tips
- Use Python 3.10+
- Some defaults configurable via env: PROMISING_DEFAULT_START_SOON, PROMISING_DEFAULT_MAKE_PARENT_WAIT, PROMISING_DEFAULT_CONFIGS_INHERITABLE
