import logging
from collections.abc import Iterable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from promising.promising_context import PromisingContext


class PromisingHierarchyLogger:
    def __init__(self, *, logger: logging.Logger | None = None, level: int):
        self.logger = logger or logging.getLogger(type(self).__name__)
        self.level = level

    def _direct_children_snapshot(self, parent: "PromisingContext") -> tuple["PromisingContext", ...]:
        num_retries = 10

        for attempt in range(num_retries):
            try:
                return tuple(parent._unsettled_children)
            except RuntimeError:
                if attempt < num_retries - 1:
                    self.logger.log(
                        self.level, f"Retrying active-children snapshot (attempt {attempt + 1}/{num_retries})"
                    )
        self.logger.warning("[MINOR] Failed to snapshot active children after 10 attempts for logging purposes")
        return ()

    def log_awaiting_children_started(self, *, parent: "PromisingContext") -> None:
        if not self.logger.isEnabledFor(self.level):
            return

        lines = ["AWAITING CHILDREN", self._fmt("parent", parent), "CURRENT STATE"]
        for child in self._direct_children_snapshot(parent):
            lines.append(self._fmt("direct child", child))
        log_message = "\n".join(lines)

        self.logger.log(self.level, f"\n{log_message}\n")

    def log_awaiting_children(self, *, parent: "PromisingContext", children: Iterable["PromisingContext"]) -> None:
        if not self.logger.isEnabledFor(self.level):
            return

        lines = ["AWAITING CHILDREN", self._fmt("parent", parent)]
        for child in self._direct_children_snapshot(parent):
            lines.append(self._fmt("direct child", child))
        lines.append("CURRENT STATE")
        for child in children:
            lines.append(self._fmt("awaiting", child))
        log_message = "\n".join(lines)

        self.logger.log(self.level, f"\n{log_message}\n")

    def log_children_awaited(self, *, parent: "PromisingContext") -> None:
        if not self.logger.isEnabledFor(self.level):
            return

        lines = ["CHILDREN AWAITED", self._fmt("parent", parent), "CURRENT STATE"]
        for child in self._direct_children_snapshot(parent):
            lines.append(self._fmt("(!)outstanding direct child", child))
        log_message = "\n".join(lines)

        self.logger.log(self.level, f"\n{log_message}\n")

    def log_unregistering_from_parent(self, *, parent: "PromisingContext", child: "PromisingContext") -> None:
        if not self.logger.isEnabledFor(self.level):
            return

        lines = ["UNREGISTERING FROM PARENT", self._fmt("parent", parent), self._fmt("child", child)]
        log_message = "\n".join(lines)

        self.logger.log(self.level, f"\n{log_message}\n")

    def log_children_registered(self, *, parent: "PromisingContext", children: Iterable["PromisingContext"]) -> None:
        if not self.logger.isEnabledFor(self.level):
            return

        lines = ["CHILDREN REGISTERED", self._fmt("parent", parent)]
        for child in children:
            lines.append(self._fmt("registered", child))
        for child in self._direct_children_snapshot(parent):
            lines.append(self._fmt("direct child", child))
        log_message = "\n".join(lines)

        self.logger.log(self.level, f"\n{log_message}\n")

    def log_children_unregistered(self, *, parent: "PromisingContext", children: Iterable["PromisingContext"]) -> None:
        if not self.logger.isEnabledFor(self.level):
            return

        lines = ["CHILDREN UNREGISTERED", self._fmt("parent", parent)]
        for child in children:
            lines.append(self._fmt("unregistered", child))
        for child in self._direct_children_snapshot(parent):
            lines.append(self._fmt("direct child", child))
        log_message = "\n".join(lines)

        self.logger.log(self.level, f"\n{log_message}\n")

    def _fmt(self, label: str, ctx: "PromisingContext") -> str:
        status = "OPEN" if ctx.is_still_open() else "CLOSED"
        return f"  {label}: [{status}] {ctx}"
