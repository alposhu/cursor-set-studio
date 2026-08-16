"""Draggable entries in the unassigned pool."""
from __future__ import annotations

import json

from PySide6.QtCore import QMimeData, QPoint, Qt, Signal
from PySide6.QtGui import QDrag, QPainter, QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ...core.models import CursorFile, FileKind
from .. import theme
from .badges import KindPill
from .cursor_preview import AnimatedCursorLabel

# Payload passed between the pool and the role grid.
MIME_CURSOR = "application/x-css-cursor"
POOL_SOURCE = "@pool"


def make_payload(path: str, source: str) -> QMimeData:
    """`source` is either POOL_SOURCE or the registry name of a role slot."""
    md = QMimeData()
    md.setData(MIME_CURSOR, json.dumps({"path": path, "source": source}).encode())
    md.setText(path)
    return md


def read_payload(md: QMimeData) -> tuple[str, str] | None:
    if not md.hasFormat(MIME_CURSOR):
        return None
    try:
        d = json.loads(bytes(md.data(MIME_CURSOR)).decode())
        return d["path"], d["source"]
    except (ValueError, KeyError):
        return None


class FileChip(QFrame):
    """One unassigned file: preview, name, and what kind of file it is."""

    assign_requested = Signal(object)     # CursorFile - the click-to-assign path
    double_clicked = Signal(object)

    def __init__(self, cf: CursorFile, parent=None):
        super().__init__(parent)
        self.cf = cf
        self._press: QPoint | None = None

        self.setObjectName("Chip")
        self.setFixedHeight(52)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self._style(False)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 6, 10, 6)
        lay.setSpacing(10)

        self.preview = AnimatedCursorLabel(36)
        self.preview.set_file(cf)
        lay.addWidget(self.preview)

        col = QVBoxLayout()
        col.setSpacing(2)
        col.setContentsMargins(0, 0, 0, 0)

        name = QLabel(cf.stem if not cf.is_sequence else cf.stem)
        name.setStyleSheet(f"font-size:12px; font-weight:550; color:{theme.TEXT};")
        name.setToolTip(str(cf.path))
        col.addWidget(name)

        meta = QHBoxLayout()
        meta.setSpacing(5)
        meta.setContentsMargins(0, 0, 0, 0)

        if not cf.ok:
            meta.addWidget(KindPill("UNREADABLE", "error"))
        elif cf.is_sequence:
            meta.addWidget(KindPill(f"{cf.frame_count} FRAMES", "anim"))
        elif cf.kind is FileKind.ANIMATED:
            meta.addWidget(KindPill(f"ANI {cf.frame_count}F", "anim"))
        elif cf.kind is FileKind.CONVERTIBLE:
            meta.addWidget(KindPill("CONVERT", "convert"))

        size = QLabel(f"{cf.width}x{cf.height}" if cf.width else cf.path.suffix.lower())
        size.setObjectName("Dim")
        meta.addWidget(size)
        meta.addStretch(1)
        col.addLayout(meta)

        lay.addLayout(col, 1)
        self.setToolTip(str(cf.path) + (f"\n\n{cf.error}" if cf.error else ""))

    def _style(self, hover: bool) -> None:
        bg = theme.BG_HOVER if hover else theme.BG_ELEVATED
        border = theme.BORDER_STRONG if hover else theme.BORDER
        self.setStyleSheet(
            f"QFrame#Chip {{ background:{bg}; border:1px solid {border};"
            f"border-radius:{theme.RADIUS_SM}px; }}")

    def enterEvent(self, e):
        self._style(True)
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._style(False)
        super().leaveEvent(e)

    # -- drag ---------------------------------------------------------------
    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._press = e.position().toPoint()
        super().mousePressEvent(e)

    def mouseDoubleClickEvent(self, e):
        self.double_clicked.emit(self.cf)
        super().mouseDoubleClickEvent(e)

    def mouseMoveEvent(self, e):
        if self._press is None:
            return
        if (e.position().toPoint() - self._press).manhattanLength() < 12:
            return
        if not self.cf.ok:
            return                       # an unreadable file cannot be assigned

        drag = QDrag(self)
        drag.setMimeData(make_payload(str(self.cf.path), POOL_SOURCE))
        drag.setPixmap(self._drag_pixmap())
        drag.setHotSpot(QPoint(26, 26))
        self.setCursor(Qt.CursorShape.ClosedHandCursor)
        drag.exec(Qt.DropAction.MoveAction)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self._press = None

    def _drag_pixmap(self) -> QPixmap:
        pm = QPixmap(52, 52)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setOpacity(0.95)
        p.setBrush(Qt.GlobalColor.transparent)
        self.preview.render(p, QPoint(8, 8))
        p.end()
        return pm


class PoolPlaceholder(QWidget):
    """Shown when the pool is empty."""

    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 26, 16, 26)
        lab = QLabel(text)
        lab.setObjectName("Dim")
        lab.setWordWrap(True)
        lab.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(lab)
