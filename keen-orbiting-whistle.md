# Test Reorganization Plan

## Context

The current test structure mirrors the library's module layout (`promise/`, `promising_function/`, `promising_context/`, each with `sync/` subfolders). This doesn't work because most tests exercise multiple modules simultaneously — e.g., parent chain tests use both `@promising.function` and `@promising.context`, thread pool tests combine `@promising.function` + `promising.context()` + threading. The new structure organizes tests by **behavioral concern** instead.

## New Directory Structure

```
tests/
├── utils_for_tests.py                 (unchanged)
├── decoration/                        # How decorators are applied
│   ├── test_function_decorator.py     # @promising.function on standalone functions
│   ├── test_context_decorator.py      # @promising.context on standalone functions
│   ├── test_method_decorators.py      # Both decorators on methods (instance/static/class)
│   ├── test_decorator_robustness.py   # Stacking, attribute independence, error baselines
│   └── test_call_args_flow.py         # Spy-based arg flow through __call__
├── resolution/                        # How promise values are accessed
│   ├── test_async_resolution.py       # await, unpack_once, nested unpacking
│   ├── test_sync_resolution.py        # sync(), unpack_once_sync(), nested sync unpacking
│   ├── test_sync_timeout.py           # Timeout behavior for sync access
│   └── test_concurrent_future.py      # as_concurrent_future(), deadlock safeguards
├── context/                           # Context management & hierarchy
│   ├── test_context_manager.py        # with promising.context() basics + context propagation
│   ├── test_parent_chains.py          # Parent chain resolution (call-site vs await-site)
│   └── test_await_children.py         # await_children / await_children_sync
├── config/                            # Configuration system
│   ├── test_start_soon.py             # start_soon, children_start_soon, start_soon_default
│   ├── test_config_overrides.py       # Call-time config overrides (async + sync)
│   ├── test_use_thread_pool.py        # use_thread_pool parameter, errors, deadlock
│   └── test_thread_pool.py            # thread_pool param: types, inheritance, context override
├── display/                           # Namespace, repr, tracing
│   ├── test_namespaces.py             # resolve_namespace, repr/str, qualname
│   └── test_traces.py                 # get_trace(), format_trace()
└── integration/
    └── test_asyncio_run.py            # PromisingFunction.run() with asyncio.run()
```

## Complete Test-by-Test Mapping

Each test function listed below with its source → destination.

---

### `resolution/test_async_resolution.py`

**From `promise/test_promise.py` (all):**
- `test_promise`
- `test_promise_with_exception`
- `test_from_concurrent_tasks`
- `test_parallel_await`
- `_promise_expected_incomplete` (helper function)

**From `promise/test_unpack.py` (all):**
- `test_single_promise_no_nesting`
- `test_prefilled_promise_no_nesting`
- `test_two_levels_await_unpacks_all`
- `test_two_levels_unpack_once_stops_at_inner`
- `test_three_levels_await_unpacks_all`
- `test_three_levels_unpack_once_returns_second_level`
- `test_custom_coroutine_await_unpacks`
- `test_custom_coroutine_unpack_once_stops`
- `test_mixed_chain_await_unpacks_all`
- `test_mixed_chain_unpack_once`
- `test_asyncio_future_await_unpacks`
- `test_asyncio_future_unpack_once_stops`
- `test_coroutine_with_sleep_await_unpacks`
- `test_coroutine_with_sleep_unpack_once_stops`
- `test_five_levels_await_unpacks_all`
- `test_five_levels_sequential_unpack_once`
- `test_nested_with_start_soon`
- `test_non_awaitable_returned_as_is`
- `test_exception_in_inner_promise_await`
- `test_exception_in_inner_promise_unpack_once`
- `test_coro_exception_at_depth_5_with_promising_context_and_functions`

---

### `resolution/test_sync_resolution.py`

**From `promise/sync/test_promise_sync.py` (all):**
- `test_sync_returns_result_from_thread`
- `test_sync_with_start_soon_false`
- `test_sync_with_prefilled_promise`
- `test_sync_propagates_exception`
- `test_sync_propagates_prefilled_exception`
- `test_sync_raises_on_event_loop_thread`
- `test_sync_raises_on_event_loop_thread_prefilled`
- `test_sync_inside_sync_promising_function`
- `test_sync_exception_inside_sync_promising_function`

**From `promise/sync/test_unpack_sync.py` (all):**
- `test_single_promise_no_nesting`
- `test_prefilled_promise_no_nesting`
- `test_two_levels_sync_unpacks_all`
- `test_two_levels_unpack_once_sync_stops_at_inner`
- `test_three_levels_sync_unpacks_all`
- `test_three_levels_unpack_once_sync_returns_second_level`
- `test_custom_coroutine_sync_unpacks`
- `test_custom_coroutine_unpack_once_sync_stops`
- `test_mixed_chain_sync_unpacks_all`
- `test_mixed_chain_unpack_once_sync`
- `test_asyncio_future_sync_unpacks`
- `test_asyncio_future_unpack_once_sync_stops`
- `test_coroutine_with_sleep_sync_unpacks`
- `test_coroutine_with_sleep_unpack_once_sync_stops`
- `test_five_levels_sync_unpacks_all`
- `test_five_levels_sequential_unpack_once_sync`
- `test_nested_with_start_soon`
- `test_non_awaitable_returned_as_is`
- `test_exception_in_inner_promise_sync`
- `test_exception_in_inner_promise_unpack_once_sync`
- `test_coro_exception_at_depth_5_with_promising_context_and_functions`

---

### `resolution/test_sync_timeout.py`

**From `promise/sync/test_unpack_sync_timeout.py` (all — moved as-is):**
- `test_unpack_once_sync_times_out_on_slow_promise`
- `test_unpack_once_sync_succeeds_within_timeout`
- `test_sync_times_out_on_slow_promise`
- `test_sync_succeeds_within_timeout`
- `test_sync_times_out_on_slow_inner_promise`
- `test_sync_nested_succeeds_within_timeout`
- `test_sync_timeout_spans_multiple_levels`
- `test_sync_timeout_spans_multiple_levels_succeeds`
- `test_sync_times_out_on_slow_coroutine_result`
- `test_sync_coroutine_result_succeeds_within_timeout`
- `test_sync_no_timeout_waits_indefinitely`
- `test_unpack_once_sync_no_timeout_waits_indefinitely`
- `test_sync_zero_timeout_on_prefilled_promise`
- `test_unpack_once_sync_zero_timeout_on_prefilled_promise`
- `test_sync_zero_timeout_on_slow_promise`
- `test_unpack_once_sync_zero_timeout_on_slow_promise`
- `test_sync_zero_timeout_nested_prefilled`
- `test_sync_zero_timeout_nested_slow_inner`

---

### `resolution/test_concurrent_future.py`

**From `promise/sync/test_concurrent_future.py` (all):**
- `test_as_concurrent_future`
- `test_with_exception`
- `test_from_threads`
- `_promise_expected_incomplete` (helper)

**From `promise/sync/test_concurrent_future_deadlock_safeguard.py` (all):**
- `test_raises_sync_usage_error_from_event_loop_thread_with_prefilled_result`
- `test_raises_sync_usage_error_even_when_done`
- `test_raises_sync_usage_error_with_prefilled_exception`
- `test_from_separate_thread` (multiple sub-scenarios)

---

### `context/test_context_manager.py`

**From `promising_context/test_context_manager.py` (all):**
- `test_context_manager_activates_context`
- `test_context_manager_deactivates_on_exception`
- `test_nested_context_managers`
- `test_nested_context_parent_relationship`
- `test_context_manager_reuse_raises`
- `test_context_manager_with_explicit_parent_none`
- `test_context_manager_inside_promising_function_run` (parametrized)

**From `promising_function/test_promising_function.py` (parent-related tests):**
- `test_promise_has_parent_when_created_in_context`
- `test_promise_has_no_parent_outside_context`

**From `promising_function/sync/test_sync_functions.py` (context propagation tests):**
- `test_active_promise_accessible_inside_sync_function`
- `test_sync_parent_child_relationship`

---

### `context/test_parent_chains.py`

**From `promising_context/test_nested_contexts.py` (all):**
- `test_contexted_function_inside_outer_context`
- `test_contexted_function_outside_outer_context`
- `test_contexted_function_await_outside_outer_context`

**From `promising_context/test_nested_contexts_and_promises.py` (all):**
- `test_promise_inside_outer_context`
- `test_promise_outside_outer_context`
- `test_promise_await_outside_outer_context`

**From `promising_context/sync/test_sync_nested_contexts_and_promises.py` (all):**
- `test_sync_promise_inside_outer_context`
- `test_sync_promise_outside_outer_context`
- `test_sync_promise_await_outside_outer_context`
- `test_sync_contexted_function_inside_outer_context`

**From `misc/test_decorator_asyncio_run.py` (parent-resolution tests only):**
- `test_async_context_decorator_resolves_parent_at_call_site`
- `test_async_context_decorator_no_parent_when_called_outside_context`

---

### `context/test_await_children.py`

**From `promise/test_await_children.py` (all):**
- `test_await_children`
- `test_await_children_recursively`
- `test_await_children_recursively_sync_children`

**From `promise/sync/test_await_children_sync.py` (all):**
- `test_await_children_sync`
- `test_await_children_sync_recursively`
- `test_await_children_sync_recursively_all_sync`
- `test_await_children_sync_raises_on_event_loop_thread`

---

### `config/test_start_soon.py`

**From `promise/test_start_soon_setups.py` (all — moved as-is):**
- `test_config_forwarding`
- `test_start_soon_behavior`
- `test_start_soon_default_inherits_from_parent`
- `test_start_soon_default_global_default_ignores_parent`
- `test_children_start_soon_enforced_on_children`

---

### `config/test_config_overrides.py`

**From `promising_function/test_call_config_override.py` (all):**
- `test_call_overrides_start_soon`
- `test_call_without_start_soon_uses_constructor_value`
- `test_call_start_soon_none_overrides_constructor`
- `test_call_overrides_children_start_soon`
- `test_call_without_children_start_soon_uses_constructor_value`
- `test_call_overrides_start_soon_default`
- `test_call_without_start_soon_default_uses_constructor_value`
- `test_call_overrides_all_three`
- `test_config_kwargs_do_not_leak_into_function`
- `test_config_kwargs_alongside_function_kwargs`
- `test_call_override_with_inherit`
- `test_call_override_with_global_default`

**From `promising_function/sync/test_config_with_sync_funcs.py` (all):**
- `test_config_params_work_with_sync_functions`
- `test_call_time_config_overrides_work_with_sync_functions`
- `test_config_kwargs_do_not_leak_into_sync_function`

---

### `config/test_use_thread_pool.py`

**From `promising_function/sync/test_use_thread_pool.py` (all — moved as-is):**
- `test_use_thread_pool_true_runs_in_different_thread`
- `test_use_thread_pool_false_runs_on_event_loop_thread`
- `test_use_thread_pool_false_returns_correct_result`
- `test_use_thread_pool_false_exception_propagates`
- `test_use_thread_pool_false_context_propagation`
- `test_sync_raises_sync_usage_error_with_no_thread_pool` (parametrized)
- `test_await_children_sync_raises_sync_usage_error_with_no_thread_pool`
- `test_sync_works_with_thread_pool` (parametrized)
- `test_await_children_sync_works_with_thread_pool`
- `test_use_thread_pool_raises_for_async_functions` (parametrized)
- `test_use_thread_pool_at_call_site_raises_for_async_functions`
- `test_use_thread_pool_required_for_sync_functions`
- `test_use_thread_pool_override_at_call_site`
- `test_use_thread_pool_call_site_false_to_true`
- `test_use_thread_pool_call_site_not_forwarded`

---

### `config/test_thread_pool.py`

**From `promising_function/sync/test_thread_pool.py` (all — moved as-is):**
- `test_global_default_runs_off_main_thread`
- `test_asyncio_default_runs_off_main_thread`
- `test_asyncio_default_returns_correct_result`
- `test_custom_thread_pool_is_used`
- `test_custom_thread_pool_returns_correct_result`
- `test_custom_thread_pool_exception_propagates`
- `test_inherit_from_context`
- `test_inherit_from_parent_promise`
- `test_inherit_falls_back_to_global_default`
- `test_thread_pool_override_at_call_site`
- `test_call_site_override_takes_precedence_over_decorator`
- `test_context_thread_pool_overrides_global_default`
- `test_nested_context_inner_overrides_outer`
- `test_nested_context_inner_inherits_outer`
- `test_asyncio_default_via_context_runs_off_main_thread`
- `test_thread_pool_ignored_for_async_functions`
- `test_inner_thread_pool_overrides_outer`

---

### `display/test_namespaces.py`

**From `promising_context/test_namespaces.py` (all — moved as-is):**
- `test_explicit_namespace_wins_over_fallback`
- `test_explicit_namespace_wins_even_with_none_fallback`
- `test_none_when_both_are_none`
- `test_qualname_from_function`
- `test_qualname_from_sync_function`
- `test_qualname_from_async_generator_object`
- `test_qualname_from_class`
- `test_qualname_from_method_of_class`
- `test_name_fallback_when_no_qualname`
- `test_name_fallback_with_module_but_no_qualname`
- `test_promise_repr_with_explicit_namespace` (parametrized)
- `test_promise_repr_without_namespace` (parametrized)
- `test_promise_repr_auto_resolves_from_coroutine` (parametrized)
- `test_promise_repr_explicit_overrides_coroutine_name` (parametrized)
- `test_promising_function_auto_namespace`
- `test_promising_function_explicit_namespace`
- `test_promising_function_promise_inherits_namespace` (parametrized)
- `test_promising_function_auto_namespace_in_promise_repr` (parametrized)
- `test_promising_function_namespace_override_at_call_time` (parametrized)
- `test_promising_function_call_unchanged_namespace_uses_decorator_ns` (parametrized)
- `test_context_manager_explicit_namespace` (parametrized)
- `test_context_manager_no_namespace` (parametrized)
- `test_context_decorator_auto_namespace` (parametrized)
- `test_context_decorator_explicit_namespace` (parametrized)
- `test_promising_function_on_instance_method_qualname` (parametrized)
- `test_promising_function_on_static_method_qualname` (parametrized)
- `test_promising_function_on_class_method_qualname` (parametrized)
- `test_plain_instance_inherits_module_from_class`
- `test_instance_with_name_inherits_module_from_class`
- `test_callable_instance_inherits_module_from_class`
- `test_builtin_type_has_no_inherited_module`

---

### `display/test_traces.py`

**From `misc/test_traces.py` (all — moved as-is):**
- `test_get_trace_single_context`
- `test_get_trace_with_promise`
- `test_format_trace_nested_contexts`
- `test_format_trace_no_namespace`
- `test_format_trace_nested_promising_functions`
- `normalize_object_repr` (helper — imported from utils_for_tests)

---

### `integration/test_asyncio_run.py`

**From `misc/test_decorator_asyncio_run.py` (.run() tests only):**
- `test_async_function_decorator_with_run` (parametrized)
- `test_async_function_decorator_with_run_and_child_promise` (parametrized)

---

## Implementation Steps

1. **Create directory structure**: Create 7 new directories (`decoration/`, `resolution/`, `context/`, `config/`, `display/`, `integration/`) with `__init__.py` files.

2. **Move "as-is" files first** (no splitting needed — just copy to new location):
   - `test_decorator_robustness.py` → `decoration/`
   - `test_call_args_flow.py` → `decoration/`
   - `test_unpack_sync_timeout.py` → `resolution/test_sync_timeout.py`
   - `test_start_soon_setups.py` → `config/test_start_soon.py`
   - `test_use_thread_pool.py` → `config/`
   - `test_thread_pool.py` → `config/`
   - `test_namespaces.py` → `display/`
   - `test_traces.py` → `display/`

3. **Merge files** (two+ sources into one destination, no splitting):
   - `test_concurrent_future.py` + `test_concurrent_future_deadlock_safeguard.py` → `resolution/test_concurrent_future.py`
   - `test_call_config_override.py` + `test_config_with_sync_funcs.py` → `config/test_config_overrides.py`
   - `test_await_children.py` + `test_await_children_sync.py` → `context/test_await_children.py`
   - `test_nested_contexts.py` + `test_nested_contexts_and_promises.py` + `test_sync_nested_contexts_and_promises.py` → `context/test_parent_chains.py` (+ 2 tests from `test_decorator_asyncio_run.py`)
   - `test_promise.py` + `test_unpack.py` → `resolution/test_async_resolution.py`
   - `test_promise_sync.py` + `test_unpack_sync.py` → `resolution/test_sync_resolution.py`

4. **Split and reassemble** (source tests go to multiple destinations):
   - `test_promising_function.py`: 13 tests → `decoration/test_function_decorator.py`, 2 tests → `context/test_context_manager.py`
   - `test_sync_functions.py`: 13 tests → `decoration/test_function_decorator.py`, 2 tests → `context/test_context_manager.py`
   - `test_context_decorator.py`: 7+1 function tests → `decoration/test_context_decorator.py`, 16 method tests → `decoration/test_method_decorators.py`
   - `test_sync_context_decorator.py`: 6 function tests → `decoration/test_context_decorator.py`, 9 method tests → `decoration/test_method_decorators.py`
   - `test_method_decorators.py` (all 23) + `test_sync_method_decorators.py` (all 13) + method sections from context decorators → `decoration/test_method_decorators.py`
   - `test_decorator_asyncio_run.py`: 2 .run() tests → `integration/test_asyncio_run.py`, 2 parent-resolution tests → `context/test_parent_chains.py`
   - `test_context_manager.py` (all 7) + parent tests from other files → `context/test_context_manager.py`

5. **Remove old directories**: Delete `misc/`, `promise/`, `promising_context/`, `promising_function/` and their contents.

6. **Verify**: Run full test suite to confirm all tests pass.

## Verification

```bash
# Run the full test suite
pytest tests/ -v

# Verify test count matches before/after
pytest tests/ --co -q | tail -1
```
