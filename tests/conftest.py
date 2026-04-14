from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _disable_qualnames_in_namespaces(request):
    if "do_not_patch_qualnames" in request.keywords:
        yield
    else:
        with patch("promising.Defaults.QUALNAMES_IN_NAMESPACES", False):
            yield
