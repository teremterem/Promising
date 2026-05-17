"""
Race-condition stress tests use threads and high iteration counts to
surface unsynchronized state in the framework.

We force a very short GIL switch interval (1µs) so the interpreter
preempts between almost every bytecode, dramatically widening the race
windows that the framework's unprotected read-then-act sequences
expose. Without this, CPython's default ~5ms switch interval often
hides the bugs.
"""

import sys
from collections.abc import Iterator

import pytest

# Apply a longer per-test timeout to every test in this directory.
pytestmark = pytest.mark.timeout(30)

_ORIGINAL_SWITCH_INTERVAL = sys.getswitchinterval()
_RACE_SWITCH_INTERVAL = 1e-6  # 1 microsecond


@pytest.fixture(autouse=True)
def _aggressive_gil_switching() -> Iterator[None]:
    """Force frequent GIL hand-offs so reader/writer races surface."""
    sys.setswitchinterval(_RACE_SWITCH_INTERVAL)
    try:
        yield
    finally:
        sys.setswitchinterval(_ORIGINAL_SWITCH_INTERVAL)


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    for item in items:
        if "race_conditions" in str(item.fspath):
            item.add_marker(pytest.mark.timeout(30))
