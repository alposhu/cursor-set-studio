"""The role slot card: a drop target, a drag source, and a live preview."""
from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QAction, QDrag, QPainter, QPixmap
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QMenu,
                               QSizePolicy, QVBoxLayout)

from ...core.models import Assignment, Confidence, CursorFile, FileKind
from .. import theme
from .badges import ConfidenceBadge, KindPill
from .cursor_preview import AnimatedCursorLabel
from ..util import clear_layout
from .file_chip import POOL_SOURCE, make_payload, read_payload


class RoleCard(QFrame):
    """One of the 15+ cursor roles, and whatever fills it."""

    # (target role key, source path, source role key or POOL_SOURCE)
    file_dropped = Signal(str, str, str)
    cleared = Signal(str)                 # role key
    reassign_requested = Signal(str)      # role key - open the picker
    hotspot_requested = Signal(str)       # role key - open hotspot editor

    def __init__(self, assignment: Assignment, parent=None):
        super().__init__(parent)
        self.assignment = assignment
        self._press: QPoint | None = None
        self._drag_over = False

        self.setObjectName("RoleCard")
        self.setAcceptDrops(True)
        self.setMinimumWidth(212)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(126)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(13, 11, 13, 11)
        lay.setSpacing(8)

        # Header: role name + confidence badge
        head = QHBoxLayout()
        head.setSpacing(6)
        self.title = QLabel(assignment.role.display_name)
        self.title.setStyleSheet(
            f"font-size:12.5px; font-weight:600; color:{theme.TEXT};")
        self.title.setToolTip(assignment.role.display_name)
        self.title.setSizePolicy(QSizePolicy.Policy.Ignored,
                                 QSizePolicy.Policy.Preferred)
        head.addWidget(self.title, 1)
        self.badge = ConfidenceBadge()
        head.addWidget(self.badge)
        lay.addLayout(head)

        # Body: preview + filename
        body = QHBoxLayout()
        body.setSpacing(11)
        self.preview = AnimatedCursorLabel(44, interactive=True)
        self.preview.clicked.connect(
            lambda: self.hotspot_requested.emit(self.role_key))
        body.addWidget(self.preview, 0, Qt.AlignmentFlag.AlignTop)

        col = QVBoxLayout()
        col.setSpacing(3)
        self.filename = QLabel()
        self.filename.setWordWrap(False)
        self.filename.setStyleSheet(f"font-size:11px; color:{theme.TEXT_MUTED};")
        col.addWidget(self.filename)

        self.meta = QHBoxLayout()
        self.meta.setSpacing(5)
        self.meta.setContentsMargins(0, 0, 0, 0)
        col.addLayout(self.meta)
        col.addStretch(1)
        body.addLayout(col, 1)
        lay.addLayout(body)

        # Footer: registry name, so power users can see what is being written
        self.regname = QLabel(assignment.role.registry_name)
        self.regname.setObjectName("Mono")
        lay.addWidget(self.regname)

        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)
        self.refresh()

    @property
    def role_key(self) -> str:
        return self.assignment.role.registry_name

    # -- appearance ---------------------------------------------------------
    def refresh(self) -> None:
        a = self.assignment
        self.preview.set_file(a.file)
        self.badge.set_confidence(a.confidence, rivals=len(a.rivals))

        clear_layout(self.meta)

        if a.filled:
            self.filename.setText(self._elide(a.file.stem, 22))
            self.filename.setToolTip(str(a.file.path))
            if a.file.is_sequence:
                self.meta.addWidget(KindPill(f"{a.file.frame_count} FRAMES", "anim"))
            elif a.file.kind is FileKind.ANIMATED:
                self.meta.addWidget(KindPill(f"ANI {a.file.frame_count}F", "anim"))
            elif a.file.kind is FileKind.CONVERTIBLE:
                self.meta.addWidget(KindPill("CONVERT", "convert"))
            if a.rivals:
                self.meta.addWidget(KindPill(f"+{len(a.rivals)} SIMILAR", "info"))
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        else:
            self.filename.setText("Drop a cursor here")
            self.filename.setToolTip(a.role.description)
            self.unsetCursor()

        self.meta.addStretch(1)
        self._style()

    def _style(self) -> None:
        a = self.assignment
        if self._drag_over:
            border, bg, width = theme.ACCENT, theme.ACCENT_WASH, 2
        elif not a.filled:
            border, bg, width = theme.BORDER, "transparent", 1
        elif a.confidence is Confidence.LOW:
            border, bg, width = f"{theme.WARN}55", theme.BG_ELEVATED, 1
        else:
            border, bg, width = theme.BORDER, theme.BG_ELEVATED, 1

        dashed = "dashed" if not a.filled and not self._drag_over else "solid"
        self.setStyleSheet(
            f"QFrame#RoleCard {{ background:{bg};"
            f"border:{width}px {dashed} {border};"
            f"border-radius:{theme.RADIUS}px; }}")

    @staticmethod
    def _elide(text: str, n: int) -> str:
        return text if len(text) <= n else text[:n - 1] + "…"

    # -- drag out -----------------------------------------------------------
    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._press = e.position().toPoint()
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._press is None or not self.assignment.filled:
            return
        if (e.position().toPoint() - self._press).manhattanLength() < 12:
            return
        drag = QDrag(self)
        drag.setMimeData(make_payload(str(self.assignment.file.path), self.role_key))
        pm = QPixmap(52, 52)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        self.preview.render(p, QPoint(4, 4))
        p.end()
        drag.setPixmap(pm)
        drag.setHotSpot(QPoint(26, 26))
        drag.exec(Qt.DropAction.MoveAction)
        self._press = None

    # -- drop in ------------------------------------------------------------
    def dragEnterEvent(self, e):
        payload = read_payload(e.mimeData())
        if payload and payload[1] != self.role_key:
            self._drag_over = True
            self._style()
            e.acceptProposedAction()
        else:
            e.ignore()

    def dragLeaveEvent(self, e):
        self._drag_over = False
        self._style()
        super().dragLeaveEvent(e)

    def dropEvent(self, e):
        self._drag_over = False
        self._style()
        payload = read_payload(e.mimeData())
        if not payload:
            e.ignore()
            return
        path, source = payload
        self.file_dropped.emit(self.role_key, path, source)
        e.acceptProposedAction()

    # -- context menu -------------------------------------------------------
    def _menu(self, pos):
        m = QMenu(self)
        act = QAction("Choose a file for this role…", m)
        act.triggered.connect(lambda: self.reassign_requested.emit(self.role_key))
        m.addAction(act)

        if self.assignment.filled:
            if self.assignment.file.kind is FileKind.CONVERTIBLE:
                hs = QAction("Set hotspot…", m)
                hs.triggered.connect(
                    lambda: self.hotspot_requested.emit(self.role_key))
                m.addAction(hs)
            m.addSeparator()
            clear = QAction("Return to unassigned pool", m)
            clear.triggered.connect(lambda: self.cleared.emit(self.role_key))
            m.addAction(clear)

        m.exec(self.mapToGlobal(pos))
