"""
Process-global framework state under concurrent access.

``install_promising_tracebacks()`` mutates ``sys.excepthook`` /
``threading.excepthook`` and records the pre-existing hooks as the
fallback chain. It is called automatically by every Promise's first
unpacking step — so with multiple event loops in multiple threads (the
``run()``-in-parallel pattern) the *first* installation can genuinely be
raced. Currently protected by a double-checked ``threading.Lock``; this
is a regression net for the refactoring.

The catastrophic failure mode of a racy install is a **self-chained
hook**: a second concurrent install observing the promising hook already
in ``sys.excepthook`` and recording it as the "previous" hook — at crash
time the fallback path would then recurse into itself forever. That chain
is invisible from the public API until a crash, which is why this test
(exceptionally for this suite) asserts on the module's private
``_excepthook_state``.
"""

import sys
import threading

import pytest

from promising import install_promising_tracebacks
from promising.errors import (
    _excepthook_state,
    _promising_sys_excepthook,
    _promising_threading_excepthook,
)
from tests.race_conditions.utils_for_race_tests import (
    RACER_THREADS,
    assert_no_errors,
    run_racers_sync,
)

pytestmark = pytest.mark.timeout(30)


def test_concurrent_first_installation_of_promising_excepthooks() -> None:
    """
    N threads call ``install_promising_tracebacks()`` simultaneously while
    the hooks are NOT yet the promising ones (staged by planting dummy
    hooks first). Contract:

    - both hooks end up being the promising hooks;
    - exactly one caller reports ``True`` ("I actually installed");
    - the recorded previous hooks are the dummies — never the promising
      hooks themselves (the self-chain / infinite-recursion hazard).
    """

    def _dummy_sys_hook(exc_type, exc_value, exc_tb) -> None:  # pragma: no cover - never invoked
        pass

    def _dummy_threading_hook(args) -> None:  # pragma: no cover - never invoked
        pass

    # Save absolutely everything we are about to disturb, so the rest of
    # the test session keeps its normal excepthook behavior.
    original_sys_hook = sys.excepthook
    original_threading_hook = threading.excepthook
    original_previous_sys = _excepthook_state.previous_sys
    original_previous_threading = _excepthook_state.previous_threading

    try:
        for _ in range(20):
            # Stage a fresh "not yet installed" world.
            sys.excepthook = _dummy_sys_hook
            threading.excepthook = _dummy_threading_hook

            results, errors = run_racers_sync(*[install_promising_tracebacks] * RACER_THREADS)
            assert_no_errors(errors)

            assert sys.excepthook is _promising_sys_excepthook
            assert threading.excepthook is _promising_threading_excepthook

            assert results.count(True) == 1, (
                f"Expected exactly one racer to perform the installation, "
                f"but {results.count(True)} of them reported True"
            )

            # The fallback chain must point at the pre-existing (dummy)
            # hooks — a promising hook recorded as its own fallback would
            # recurse infinitely when an exception rendering fails.
            assert _excepthook_state.previous_sys is _dummy_sys_hook, (
                f"sys fallback hook is {_excepthook_state.previous_sys!r} instead of the pre-existing hook"
            )
            assert _excepthook_state.previous_threading is _dummy_threading_hook, (
                f"threading fallback hook is {_excepthook_state.previous_threading!r} instead of the pre-existing hook"
            )
    finally:
        sys.excepthook = original_sys_hook
        threading.excepthook = original_threading_hook
        _excepthook_state.previous_sys = original_previous_sys
        _excepthook_state.previous_threading = original_previous_threading
