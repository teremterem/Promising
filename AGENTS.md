# Repository Guidelines

## Project Structure & Module Organization
- `promising/`: library code — `promises.py` (core `Promise`), `configs.py` (`PromiseConfig`), `errors.py`, `utils.py`, `sentinels.py`, `types.py`.
- `tests/`: pytest suites (e.g., `tests/promises/test_concurrent_future.py`).
- Config: `pyproject.toml` (Black, pytest, coverage), `.pylintrc`, `.pre-commit-config.yaml`.
- Generated: `dist/` (builds), `htmlcov/` (coverage HTML). Do not edit these.

## Build, Test, and Development Commands
- Setup: `python -m venv .venv && source .venv/bin/activate && pip install -e '.[dev]' && pre-commit install`
- Lint/format: `black .` then `pylint promising tests`
- Run tests: `pytest -q`
- Coverage: `pytest --cov=promising --cov-report=term-missing --cov-report=html` (open `htmlcov/index.html`)
- Build artifacts: `hatch build` (produces wheels/sdist under `dist/`)

## Coding Style & Naming Conventions
- Formatting: Black with line length 119; 4‑space indentation.
- Naming: snake_case for functions/variables, PascalCase for classes, UPPER_CASE for constants (enforced by Pylint).
- Type hints: prefer complete annotations; keep public APIs typed.
- Pre-commit: hooks run Black and Pylint. Run `pre-commit run -a` before pushing.

## Testing Guidelines
- Frameworks: pytest, pytest-asyncio (asyncio mode is auto). Write `async def test_*` where appropriate.
- Layout: place tests under `tests/<area>/test_*.py` matching the module under test.
- Parametrization: use `pytest.mark.parametrize` (see `tests/promises/test_concurrent_future.py`).
- Coverage: no hard threshold enforced; aim to maintain or improve coverage and include edge cases.

## Commit & Pull Request Guidelines
- Commits: concise, present tense, include scope when helpful (e.g., `promises: add as_concurrent_future tests`); reference issues/PRs (e.g., `(#21)`).
- PRs: clear description and rationale, linked issues, tests updated/added, docs adjusted if needed. Ensure `pre-commit run -a` and test suite pass.

## Architecture Notes
- Primary API: `from promising import Promise, PromiseConfig`.
- `Promise` bridges asyncio tasks with `concurrent.futures.Future` for thread-safe access and compatibility.
- Use `start_soon` for eager execution or `prefill_result/prefill_exception` for immediate state.
