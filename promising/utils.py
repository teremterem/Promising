# pylint: disable=import-outside-toplevel
import os
import typing
from typing import Any

if typing.TYPE_CHECKING:
    from promising.sentinels import Sentinel


def get_bool_env(var_name: str, default: bool) -> bool:
    value = os.getenv(var_name)
    if value is None:
        return default
    lowered = value.lower()
    if lowered not in {"true", "false"}:
        raise ValueError(f"Invalid boolean for {var_name}: {value}. Expected 'true' or 'false'.")
    return lowered == "true"


def get_concrete_value(value: Any | "Sentinel", default_value: Any) -> Any:
    from promising.sentinels import NOT_SET

    if value is NOT_SET:
        return default_value
    return value
