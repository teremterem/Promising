# Test Reorganization Plan: tests_old/ -> tests/

## Context

Tests are being moved from `tests_old/` (organized by source module: `promise/`, `promising_context/`, `promising_function/`) to `tests/` (organized by behavioral concern). The `decoration/` and `resolution/` folders are already done. 18 files with ~161 test functions remain in `tests_old/`.

## Target Structure

Three new folders alongside the two existing ones:

```
tests/
├── decoration/          # EXISTING (10 files) - decorator application & behavior
├── resolution/          # EXISTING (5 files) + 5 NEW files - how promises produce results
│   ├── test_run.py                    # from misc/test_decorator_asyncio_run.py (partial)
│   ├── test_promise_sync_api.py       # from promise/sync/test_promise_sync.py
│   ├── test_deadlock_safeguards.py    # from promise/sync/test_concurrent_future_deadlock_safeguard.py
│   ├── test_await_children_async.py   # from promise/test_await_children.py
│   └── test_await_children_sync.py    # from promise/sync/test_await_children_sync.py
├── hierarchy/           # NEW (4 files) - parent-child relationships & context management
│   ├── test_context_manager.py        # from promising_context/test_context_manager.py
│   ├── test_nesting_async.py          # MERGE: promising_context/test_nested_contexts.py + test_nested_contexts_and_promises.py
│   ├── test_nesting_sync.py           # from promising_context/sync/test_sync_nested_contexts_and_promises.py
│   └── test_parent_resolution.py      # MERGE: misc/test_decorator_asyncio_run.py (2 tests) + promising_function/test_promising_function.py + promising_function/sync/test_sync_functions.py
├── configuration/       # NEW (5 files) - config params, inheritance, thread pools
│   ├── test_start_soon.py             # from promise/test_start_soon_setups.py
│   ├── test_call_overrides_async.py   # from promising_function/test_call_config_override.py
│   ├── test_call_overrides_sync.py    # from promising_function/sync/test_config_with_sync_funcs.py
│   ├── test_thread_pool.py            # from promising_function/sync/test_thread_pool.py
│   └── test_use_thread_pool.py        # from promising_function/sync/test_use_thread_pool.py
└── observability/       # NEW (2 files) - namespaces, repr, traces
    ├── test_namespaces.py             # from promising_context/test_namespaces.py
    └── test_traces.py                 # from misc/test_traces.py
```

## Mapping (18 old files)

### 1:1 moves (12 files) - copy, rename, update imports if needed

| Old path | New path |
|----------|----------|
| `misc/test_traces.py` | `observability/test_traces.py` |
| `promise/test_await_children.py` | `resolution/test_await_children_async.py` |
| `promise/test_start_soon_setups.py` | `configuration/test_start_soon.py` |
| `promise/sync/test_promise_sync.py` | `resolution/test_promise_sync_api.py` |
| `promise/sync/test_await_children_sync.py` | `resolution/test_await_children_sync.py` |
| `promise/sync/test_concurrent_future_deadlock_safeguard.py` | `resolution/test_deadlock_safeguards.py` |
| `promising_context/test_context_manager.py` | `hierarchy/test_context_manager.py` |
| `promising_context/test_namespaces.py` | `observability/test_namespaces.py` |
| `promising_context/sync/test_sync_nested_contexts_and_promises.py` | `hierarchy/test_nesting_sync.py` |
| `promising_function/test_call_config_override.py` | `configuration/test_call_overrides_async.py` |
| `promising_function/sync/test_config_with_sync_funcs.py` | `configuration/test_call_overrides_sync.py` |
| `promising_function/sync/test_thread_pool.py` | `configuration/test_thread_pool.py` |
| `promising_function/sync/test_use_thread_pool.py` | `configuration/test_use_thread_pool.py` |

### Splits (1 file)

**`misc/test_decorator_asyncio_run.py`** -> split into 2 destinations:
- `test_async_context_decorator_resolves_parent_at_call_site` + `test_async_context_decorator_no_parent_when_called_outside_context` -> `hierarchy/test_parent_resolution.py`

### Merges (4 files -> 2 targets)

**`hierarchy/test_parent_resolution.py`** = merge of:
- `promising_function/test_promising_function.py` (2 tests - basic parent/no-parent)
- `promising_function/sync/test_sync_functions.py` (2 tests - sync parent/active-promise)
- 2 tests from `misc/test_decorator_asyncio_run.py` (call-site vs await-site parent resolution)
- Total: 6 tests covering parent resolution from all angles

## Steps

1. Create folders: `tests/hierarchy/`, `tests/configuration/`, `tests/observability/`
2. Do the 12 straight moves (copy content, adjust imports if needed)
3. Create `resolution/test_run.py` from the 2 `.run()` tests in `misc/test_decorator_asyncio_run.py`
4. Create `hierarchy/test_nesting_async.py` by merging `test_nested_contexts.py` + `test_nested_contexts_and_promises.py`
5. Create `hierarchy/test_parent_resolution.py` by merging 3 source files (6 tests total)
6. Run full test suite: `pytest tests/ -v` to verify everything passes
7. Verify test count matches expectations (~161 new tests from old files + existing tests)

## Verification

```bash
# Run new tests only
pytest tests/hierarchy/ tests/configuration/ tests/observability/ tests/resolution/test_run.py tests/resolution/test_promise_sync_api.py tests/resolution/test_deadlock_safeguards.py tests/resolution/test_await_children_async.py tests/resolution/test_await_children_sync.py -v

# Run full suite to check nothing broke
pytest tests/ -v

# Compare test counts
pytest tests/ --co -q | tail -1
pytest tests_old/ --co -q | tail -1
```
