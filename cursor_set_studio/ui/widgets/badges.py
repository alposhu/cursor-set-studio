"""Small status pills."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel

from ...core.models import Confidence
from .. import theme

_STYLES = {
    Confidence.HIGH: (theme.OK, theme.OK_WASH, "Matched"),
    Confidence.LOW: (theme.WARN, theme.WARN_WASH, "Check"),
    Confidence.MANUAL: (theme.ACCENT_BRIGHT, theme.ACCENT_WASH, "Manual"),
    Confidence.UNASSIGNED: (theme.IDLE, theme.IDLE_WASH, "Empty"),
}


class Pill(QLabel):
    """A compact coloured label."""

    def __init__(self, text: str = "", fg: str = theme.TEXT_MUTED,
                 bg: str = theme.IDLE_WASH, parent=None):
        super().__init__(text, parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.apply(text, fg, bg)

    def apply(self, text: str, fg: str, bg: str) -> None:
        self.setText(text)
        self.setStyleSheet(
            f"color:{fg}; background:{bg}; border:1px solid {fg}40;"
            f"border-radius:8px; padding:2px 8px;"
            f"font-size:10px; font-weight:700; letter-spacing:0.4px;")


class ConfidenceBadge(Pill):
    """Shows how a role slot was filled, and how much to trust it."""

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.set_confidence(Confidence.UNASSIGNED)

    def set_confidence(self, c: Confidence, *, rivals: int = 0) -> None:
        fg, bg, label = _STYLES[c]
        self.apply(label.upper(), fg, bg)
        self.setToolTip({
            Confidence.HIGH: "Matched with high confidence.",
            Confidence.LOW: ("More than one file could fit this role, or the "
                             "name only partly matched. Worth a look."),
            Confidence.MANUAL: "You assigned this one.",
            Confidence.UNASSIGNED: "No file assigned yet.",
        }[c])


class KindPill(Pill):
    """Marks animated and convertible files in the pool."""

    def __init__(self, text: str, kind: str = "info", parent=None):
        colors = {
            "anim": (theme.ACCENT_BRIGHT, theme.ACCENT_WASH),
            "convert": (theme.WARN, theme.WARN_WASH),
            "error": (theme.DANGER, theme.DANGER_WASH),
            "info": (theme.TEXT_DIM, theme.IDLE_WASH),
        }
        fg, bg = colors.get(kind, colors["info"])
        super().__init__(text, fg, bg, parent)
