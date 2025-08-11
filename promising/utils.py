# pylint: disable=import-outside-toplevel
import typing
from typing import Any

if typing.TYPE_CHECKING:
    from promising.sentinels import Sentinel


def get_concrete_value(value: Any | "Sentinel", default_value: Any) -> Any:
    from promising.sentinels import NOT_SET

    if value is NOT_SET:
        return default_value
    return value
