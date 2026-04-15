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
