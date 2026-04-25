from collections.abc import Iterator
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _disable_qualnames_in_namespaces(request: pytest.FixtureRequest) -> Iterator[None]:
    if "do_not_patch_qualnames" in request.keywords:
        yield
    else:
        with patch("promising.Defaults.QUALNAMES_IN_NAMESPACES", new=False):
            yield


def pytest_runtest_setup(item: pytest.Item) -> None:
    if "cycle_detection_github_issue_66" in item.keywords:
        pytest.skip("cycle detection not implemented yet (issue #66)")
    if "feature_possibly_obsolete" in item.keywords:
        pytest.skip("feature possibly obsolete")
