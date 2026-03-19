import re
from typing import Any

import promising


def normalize_object_repr(s: str) -> str:
    """
    Replace hex addresses and digit sequences with X for stable comparisons.
    """
    assert isinstance(s, str)
    s = re.sub(r"\d+", "999", s)
    # After the previous sub, hex addresses like "0x7f3a" have become
    # "999x999f999a". This pattern matches that mangled form and normalizes
    # it to "0xfff".
    # After the previous sub, hex addresses like "0x7f3a" have become
    # "999x999f999a". This pattern matches "999x" followed by any mix of
    # digits-turned-999 and hex letters, normalizing to "0xfff".
    return re.sub(r"999x[9a-f]+", "0xfff", s)


def collect_parent_contexts(ctx: promising.PromisingContext) -> list[promising.PromisingContext]:
    result = []
    while (parent := ctx.get_parent_context(raise_if_none=False)) is not None:
        result.append(parent)
        ctx = parent
    return result


def collect_parent_promises(ctx: promising.PromisingContext) -> list[promising.Promise[Any]]:
    result = []
    while (parent := ctx.get_parent_promise(raise_if_none=False)) is not None:
        result.append(parent)
        ctx = parent
    return result
