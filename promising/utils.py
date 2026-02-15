# ruff: noqa: PLC0415 (import-outside-top-level)
import typing
from typing import Any

if typing.TYPE_CHECKING:
    from promising.sentinels import Sentinel


def get_concrete_value(value: Any | "Sentinel", default_value: Any) -> Any:
    from promising.sentinels import INHERIT, NOT_SET

    if value in (NOT_SET, INHERIT):
        return default_value
    return value
