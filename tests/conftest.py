from collections.abc import Iterator
from unittest.mock import patch

import pytest

from tests.utils_for_tests import possibly_xfail


@pytest.fixture(autouse=True)
def _disable_qualnames_in_namespaces(request: pytest.FixtureRequest) -> Iterator[None]:
    if "do_not_patch_qualnames" in request.keywords:
        yield
    else:
        with patch("promising.Defaults.QUALNAMES_IN_NAMESPACES", new=False):
            yield


def pytest_runtest_setup(item: pytest.Item) -> None:
    # At the setup stage it is still not too late to just mark the test as
    # xfail rather than skipping the test entirely.
    possibly_xfail(*item.iter_markers(), item=item)
