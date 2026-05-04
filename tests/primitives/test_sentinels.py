import pytest

from promising import PROMISING_DEFAULT
from promising.errors import SentinelUsageError
from promising.sentinels import Sentinel


def test_repr() -> None:
    assert repr(PROMISING_DEFAULT) == "PROMISING_DEFAULT"


def test_identity_comparison() -> None:
    assert PROMISING_DEFAULT is not None
    assert PROMISING_DEFAULT is not Sentinel("PROMISING_DEFAULT")
    assert PROMISING_DEFAULT is PROMISING_DEFAULT  # noqa: PLR0124 (comparison-with-itself)


def test_equality_uses_identity() -> None:
    assert PROMISING_DEFAULT != None  # noqa: E711 (none-comparison)
    assert PROMISING_DEFAULT != "PROMISING_DEFAULT"
    assert PROMISING_DEFAULT != Sentinel("PROMISING_DEFAULT")
    assert PROMISING_DEFAULT == PROMISING_DEFAULT  # noqa: PLR0124 (comparison-with-itself)


def test_hashable_as_dict_key() -> None:
    d = {PROMISING_DEFAULT: 1}
    assert d[PROMISING_DEFAULT] == 1


@pytest.mark.parametrize(
    "op",
    [
        bool,
        lambda s: not s,
        lambda s: bool(s and True),
        lambda s: bool(s or False),
        lambda s: True if s else False,
    ],
)
def test_truthiness_raises(op) -> None:
    with pytest.raises(SentinelUsageError, match="cannot be cast to boolean"):
        op(PROMISING_DEFAULT)


@pytest.mark.parametrize(
    "op",
    [
        len,
        iter,
        int,
        float,
        lambda s: s[0],
        lambda s: s(),
        lambda s: s + 1,
        lambda s: 1 in s,
        lambda s: s < s,  # noqa: PLR0124 (comparison-with-itself)
    ],
)
def test_non_value_operations_raise_type_error(op) -> None:
    with pytest.raises(TypeError):
        op(PROMISING_DEFAULT)
