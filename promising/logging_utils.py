import logging
from collections.abc import Iterable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from promising.promising_context import PromisingContext


class PromisingHierarchyLogger:
    def __init__(self, *, logger: logging.Logger | None = None, level: int) -> None:
        self.logger = logger or logging.getLogger(type(self).__name__)
        self.level = level

    def log_awaiting_children_started(self, *, parent: "PromisingContext") -> None:
        if not self.logger.isEnabledFor(self.level):
            return

        log_message = "\n".join(
            [
                "AWAITING CHILDREN STARTED",
                self._fmt("awaiter", parent),
                *self._lines_for_unsettled_children(parent=parent),
            ]
        )
        self.logger.log(self.level, f"\n{log_message}\n")

    def log_awaiting_children(self, *, parent: "PromisingContext", children: Iterable["PromisingContext"]) -> None:
        if not self.logger.isEnabledFor(self.level):
            return

        log_message = "\n".join(
            [
                "AWAITING CHILDREN...",
                self._fmt("awaiter", parent),
                *[self._fmt("awaiting", child) for child in children],
                *self._lines_for_unsettled_children(parent=parent),
            ]
        )
        self.logger.log(self.level, f"\n{log_message}\n")

    def log_children_awaited(self, *, parent: "PromisingContext") -> None:
        if not self.logger.isEnabledFor(self.level):
            return

        log_message = "\n".join(
            [
                "CHILDREN AWAITED",
                self._fmt("awaiter", parent),
                *self._lines_for_unsettled_children(parent=parent),
            ]
        )
        self.logger.log(self.level, f"\n{log_message}\n")

    def log_unregistering_from_parent(self, *, parent: "PromisingContext", child: "PromisingContext") -> None:
        if not self.logger.isEnabledFor(self.level):
            return

        log_message = "\n".join(
            [
                "UNREGISTERING FROM PARENT...",
                self._fmt("parent", parent),
                self._fmt("child", child),
                *self._lines_for_unsettled_children(parent=parent),
            ]
        )
        self.logger.log(self.level, f"\n{log_message}\n")

    def log_children_registered(self, *, parent: "PromisingContext", children: Iterable["PromisingContext"]) -> None:
        if not self.logger.isEnabledFor(self.level):
            return

        log_message = "\n".join(
            [
                "CHILDREN REGISTERED",
                self._fmt("parent", parent),
                *[self._fmt("registered", child) for child in children],
                *self._lines_for_unsettled_children(parent=parent),
            ]
        )
        self.logger.log(self.level, f"\n{log_message}\n")

    def log_children_unregistered(self, *, parent: "PromisingContext", children: Iterable["PromisingContext"]) -> None:
        if not self.logger.isEnabledFor(self.level):
            return

        log_message = "\n".join(
            [
                "CHILDREN UNREGISTERED",
                self._fmt("parent", parent),
                *[self._fmt("unregistered", child) for child in children],
                *self._lines_for_unsettled_children(parent=parent),
            ]
        )
        self.logger.log(self.level, f"\n{log_message}\n")

    def _lines_for_unsettled_children(self, *, parent: "PromisingContext") -> list[str]:
        unsettled_children = self._unsettled_children_snapshot(parent)
        if not unsettled_children:
            return []

        return ["CURRENT UNSETTLED STATE", *[self._fmt("direct child", child) for child in unsettled_children]]

    @staticmethod
    def _fmt(label: str, ctx: "PromisingContext") -> str:
        status = "OPEN" if ctx.is_still_open() else "CLOSED"
        return f"  {label}: [{status}] {ctx}"

    def _unsettled_children_snapshot(self, parent: "PromisingContext") -> tuple["PromisingContext", ...]:
        num_retries = 10

        for attempt in range(num_retries):
            try:
                return tuple(parent._unsettled_children)
            except RuntimeError:
                if attempt < num_retries - 1:
                    self.logger.log(
                        self.level, f"Retrying unsettled-children snapshot (attempt {attempt + 1}/{num_retries})"
                    )
        self.logger.warning("[MINOR] Failed to snapshot unsettled children for logging purposes after 10 attempts")
        return ()
