# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Repo overview
- Python package: promising/
- Tests: tests/
- Config: pyproject.toml (Black, pytest, coverage, build backend)

Common commands
- Install deps (uv or pip):
  - uv: uv pip install -r pyproject.toml -e .[dev]
  - pip: python -m venv .venv && source .venv/bin/activate && pip install -e .[dev]
- Lint/format:
  - black .
  - pylint promising tests
- Tests:
  - pytest -q
  - Single test file: pytest tests/promises/test_concurrent_future.py -q
  - With coverage HTML: pytest --cov=promising --cov-report=html
- Build:
  - python -m build  # requires build
  - or hatch build   # requires hatch

Architecture (high level)
- Core abstraction: Promise (promising/promises.py) extends asyncio.Future to add:
  - Parent/child relationships via ContextVar current Promise
  - Config inheritance (PromiseConfig) with environment-backed defaults
  - Optional start_soon execution and parent waiting semantics
  - Bridge to concurrent.futures via _PromiseBackedConcurrentFuture
- Configuration (promising/configs.py):
  - PromiseConfig encapsulates start_soon, make_parent_wait, config_inheritable
  - Inheritance chain with find_inheritable_config(); root reads defaults from env via PromisingDefaults
- Sentinels (promising/sentinels.py): NOT_SET sentinel for explicit tri-state args
- Utils (promising/utils.py): env parsing and NOT_SET resolution
- Errors (promising/errors.py): typed exceptions for Promise and config lookup
- Public API (promising/__init__.py): Promise, PromiseConfig, get_current_promise

Testing focus
- tests/promises/test_concurrent_future.py covers thread-compat result/exception consumption

Notes for future changes
- Follow Black line length 119 from pyproject.
- Python >=3.10 required.
- Some TODOs reference cancellation and lint suppression; keep pylint clean when modifying code.
