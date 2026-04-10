import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from promising.promising_context import PromisingContext


class PromisingHierarchyLogger:
    def __init__(self, logger: logging.Logger | None = None):
        self.logger = logger or logging.getLogger(type(self).__name__)

    @staticmethod
    def _fmt(label: str, ctx: "PromisingContext") -> str:
        status = "OPEN" if ctx.is_still_open() else "CLOSED"
        return f"  {label}: [{status}] {ctx}"

    def _log_awaiting_children(self, children: "set[PromisingContext]") -> None:
        if not logger.isEnabledFor(logging.DEBUG):
            return

        lines = ["AWAITING CHILDREN", self._fmt("parent", self)]
        for child in self._active_children:
            lines.append(self._fmt("direct child", child))
        for child in children:
            lines.append(self._fmt("awaiting", child))
        log_message = "\n".join(lines)

        logger.debug(f"\n{log_message}\n")

    def _log_children_awaited(self) -> None:
        if not logger.isEnabledFor(logging.DEBUG):
            return

        lines = ["CHILDREN AWAITED", self._fmt("parent", self)]
        for child in self._active_children:
            lines.append(self._fmt("(!)outstanding direct child", child))
        log_message = "\n".join(lines)

        logger.debug(f"\n{log_message}\n")

    def _log_unregistering_from_parent(self) -> None:
        if not logger.isEnabledFor(logging.DEBUG):
            return

        lines = ["UNREGISTERING FROM PARENT", self._fmt("parent", self._parent), self._fmt("child", self)]
        log_message = "\n".join(lines)

        logger.debug(f"\n{log_message}\n")

    def _log_children_registered(self, children: "tuple[PromisingContext, ...]") -> None:
        if not logger.isEnabledFor(logging.DEBUG):
            return

        lines = ["CHILDREN REGISTERED", self._fmt("parent", self)]
        for child in children:
            lines.append(self._fmt("child", child))
        log_message = "\n".join(lines)

        logger.debug(f"\n{log_message}\n")

    def _log_children_unregistered(self, children: "tuple[PromisingContext, ...]") -> None:
        if not logger.isEnabledFor(logging.DEBUG):
            return

        lines = ["CHILDREN UNREGISTERED", self._fmt("parent", self)]
        for child in children:
            lines.append(self._fmt("child", child))
        log_message = "\n".join(lines)

        logger.debug(f"\n{log_message}\n")
