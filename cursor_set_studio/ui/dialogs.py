"""Dialogs, reserved for decisions that genuinely need one."""
from __future__ import annotations

from typing import Optional, Sequence

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QPushButton,
                               QVBoxLayout, QWidget)

from ..core import cursor_io, matcher
from ..core.models import CursorFile, CursorRole
from . import theme
from .widgets.cursor_preview import AnimatedCursorLabel, load_frames


class BaseDialog(QDialog):
    """Shared chrome: no OS title bar, matching the rest of the app."""

    def __init__(self, title: str, parent=None, width: int = 420):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Dialog |
                            Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setModal(True)

        self._root = QFrame(self)
        self._root.setObjectName("Panel")
        self._root.setStyleSheet(
            f"QFrame#Panel {{ background:{theme.BG_SURFACE};"
            f"border:1px solid {theme.BORDER_STRONG}; border-radius:12px; }}")

        shell = QVBoxLayout(self)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.addWidget(self._root)

        self.body = QVBoxLayout(self._root)
        self.body.setContentsMargins(20, 17, 20, 17)
        self.body.setSpacing(12)

        head = QLabel(title)
        head.setObjectName("H2")
        self.body.addWidget(head)

        self.setMinimumWidth(width)
        self._drag: Optional[QPoint] = None

    def mousePressEvent(self, e):
        self._drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self._drag is not None:
            self.move(e.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, e):
        self._drag = None

    def add_buttons(self, ok_text: str = "OK", cancel_text: str = "Cancel",
                    danger: bool = False) -> QPushButton:
        row = QHBoxLayout()
        row.addStretch(1)
        cancel = QPushButton(cancel_text)
        cancel.setObjectName("Ghost")
        cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)
        ok = QPushButton(ok_text)
        ok.setObjectName("Danger" if danger else "Primary")
        ok.setCursor(Qt.CursorShape.PointingHandCursor)
        ok.setDefault(True)
        ok.clicked.connect(self.accept)
        row.addWidget(ok)
        self.body.addLayout(row)
        return ok


class ConfirmDialog(BaseDialog):
    """A yes/no decision."""

    def __init__(self, title: str, message: str, parent=None,
                 ok_text: str = "Continue", danger: bool = False):
        super().__init__(title, parent, 420)
        msg = QLabel(message)
        msg.setObjectName("Sub")
        msg.setWordWrap(True)
        self.body.addWidget(msg)
        self.add_buttons(ok_text, "Cancel", danger)

    @staticmethod
    def ask(parent, title: str, message: str, ok_text: str = "Continue",
            danger: bool = False) -> bool:
        d = ConfirmDialog(title, message, parent, ok_text, danger)
        return d.exec() == QDialog.DialogCode.Accepted


class TextPromptDialog(BaseDialog):
    """Ask for a single line of text, with live validation."""

    def __init__(self, title: str, label: str, parent=None,
                 default: str = "", placeholder: str = "",
                 taken: Sequence[str] = ()):
        super().__init__(title, parent, 430)
        self._taken = {t.lower() for t in taken}

        lab = QLabel(label)
        lab.setObjectName("Sub")
        lab.setWordWrap(True)
        self.body.addWidget(lab)

        self.edit = QLineEdit(default)
        self.edit.setPlaceholderText(placeholder)
        self.edit.selectAll()
        self.body.addWidget(self.edit)

        self.warning = QLabel("")
        self.warning.setStyleSheet(f"color:{theme.WARN}; font-size:11px;")
        self.warning.hide()
        self.body.addWidget(self.warning)

        self.ok = self.add_buttons("Save")
        self.edit.textChanged.connect(self._validate)
        self.edit.returnPressed.connect(
            lambda: self.accept() if self.ok.isEnabled() else None)
        self._validate(default)

    def _validate(self, text: str) -> None:
        text = text.strip()
        problem = ""
        if not text:
            problem = ""
            self.ok.setEnabled(False)
        elif "," in text:
            problem = "A scheme name cannot contain a comma."
            self.ok.setEnabled(False)
        elif text.lower() in self._taken:
            problem = "A scheme with this name already exists; it will be replaced."
            self.ok.setEnabled(True)
        else:
            self.ok.setEnabled(True)
        self.warning.setText(problem)
        self.warning.setVisible(bool(problem))

    @property
    def value(self) -> str:
        return self.edit.text().strip()


class FilePickerDialog(BaseDialog):
    """Pick a file for a role without dragging - the accessible path."""

    def __init__(self, role: CursorRole, candidates: Sequence[CursorFile],
                 parent=None, current: Optional[CursorFile] = None):
        super().__init__(f"Choose a cursor for {role.display_name}", parent, 470)
        self.selected: Optional[CursorFile] = None
        self._role = role

        hint = QLabel(role.description + "  Ranked by how well each filename "
                                         "matches this role.")
        hint.setObjectName("Sub")
        hint.setWordWrap(True)
        self.body.addWidget(hint)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter by filename…")
        self.body.addWidget(self.search)

        self.list = QListWidget()
        self.list.setStyleSheet(
            f"QListWidget {{ background:{theme.BG_INPUT};"
            f"border:1px solid {theme.BORDER}; border-radius:8px; padding:4px;"
            f"outline:none; }}"
            f"QListWidget::item {{ padding:7px 9px; border-radius:6px; }}"
            f"QListWidget::item:selected {{ background:{theme.ACCENT_WASH};"
            f"color:{theme.ACCENT_BRIGHT}; }}"
            f"QListWidget::item:hover {{ background:{theme.BG_HOVER}; }}")
        self.list.setMinimumHeight(260)
        self.body.addWidget(self.list)

        # Rank by match score so the likely answer is at the top.
        ranked = sorted(
            ((matcher.score_role(c, role), c) for c in candidates),
            key=lambda p: (-p[0], p[1].name.lower()))

        self._items: list[tuple[float, CursorFile]] = ranked
        self._populate("")

        self.search.textChanged.connect(self._populate)
        self.list.itemDoubleClicked.connect(lambda _: self._accept())

        ok = self.add_buttons("Assign")
        ok.clicked.disconnect()
        ok.clicked.connect(self._accept)
        self._ok = ok

        if current is not None:
            for i in range(self.list.count()):
                if self.list.item(i).data(Qt.ItemDataRole.UserRole) == str(current.path):
                    self.list.setCurrentRow(i)
                    break

    def _populate(self, needle: str) -> None:
        needle = needle.lower().strip()
        self.list.clear()
        for score, cf in self._items:
            if needle and needle not in cf.name.lower():
                continue
            label = cf.display_label
            if not cf.ok:
                label += "   (unreadable)"
            elif score > 0:
                label += f"   ·  match {score:.0f}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, str(cf.path))
            if not cf.ok:
                item.setForeground(QColor(theme.TEXT_DIM))
            elif score >= matcher.HIGH_CONFIDENCE:
                item.setForeground(QColor(theme.OK))
            self.list.addItem(item)

    def _accept(self) -> None:
        item = self.list.currentItem()
        if item is None:
            return
        path = item.data(Qt.ItemDataRole.UserRole)
        for _, cf in self._items:
            if str(cf.path) == path:
                if not cf.ok:
                    return               # never assign a file we cannot read
                self.selected = cf
                break
        self.accept()


class HotspotCanvas(QWidget):
    """Enlarged cursor with a click-to-set hotspot crosshair."""

    changed = Signal(int, int)

    def __init__(self, cf: CursorFile, hotspot: tuple[int, int], parent=None):
        super().__init__(parent)
        self.cf = cf
        self.hotspot = hotspot
        self.scale = 8
        frames, native_hs, error = load_frames(cf)
        self._pm = frames[0][0] if frames else None
        self._error = error
        if self._pm:
            self.scale = max(min(320 // max(self._pm.width(), 1), 12), 3)
            self.setFixedSize(self._pm.width() * self.scale,
                              self._pm.height() * self.scale)
        else:
            self.setFixedSize(240, 240)
        self.setCursor(Qt.CursorShape.CrossCursor)

    def mousePressEvent(self, e):
        if self._pm is None:
            return
        x = max(0, min(int(e.position().x()) // self.scale, self._pm.width() - 1))
        y = max(0, min(int(e.position().y()) // self.scale, self._pm.height() - 1))
        self.hotspot = (x, y)
        self.changed.emit(x, y)
        self.update()

    def mouseMoveEvent(self, e):
        # Dragging keeps adjusting the hotspot, which is easier to aim than
        # a single click.
        if e.buttons() & Qt.MouseButton.LeftButton:
            self.mousePressEvent(e)

    def paintEvent(self, _e):
        p = QPainter(self)
        if self._pm is None:
            p.setPen(QColor(theme.DANGER))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                       self._error or "No preview")
            return

        # Checkerboard, so transparency is obvious.
        s = self.scale * 2
        light, dark = QColor("#20242C"), QColor("#191C22")
        for y in range(0, self.height(), s):
            for x in range(0, self.width(), s):
                p.fillRect(x, y, s, s, light if (x // s + y // s) % 2 else dark)

        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        p.drawPixmap(self.rect(), self._pm)

        # Pixel grid, only when zoomed enough for it to read as a grid.
        if self.scale >= 6:
            p.setPen(QPen(QColor(255, 255, 255, 16), 1))
            for i in range(0, self._pm.width() + 1):
                p.drawLine(i * self.scale, 0, i * self.scale, self.height())
            for i in range(0, self._pm.height() + 1):
                p.drawLine(0, i * self.scale, self.width(), i * self.scale)

        hx = self.hotspot[0] * self.scale + self.scale // 2
        hy = self.hotspot[1] * self.scale + self.scale // 2
        p.setPen(QPen(QColor(0, 0, 0, 170), 3))
        p.drawLine(hx - 12, hy, hx + 12, hy)
        p.drawLine(hx, hy - 12, hx, hy + 12)
        p.setPen(QPen(QColor(theme.ACCENT_BRIGHT), 1.5))
        p.drawLine(hx - 12, hy, hx + 12, hy)
        p.drawLine(hx, hy - 12, hx, hy + 12)
        p.drawEllipse(QPoint(hx, hy), 3, 3)


class HotspotDialog(BaseDialog):
    """Set the hotspot of a converted image."""

    def __init__(self, cf: CursorFile, role: CursorRole,
                 hotspot: Optional[tuple[int, int]], parent=None):
        super().__init__(f"Hotspot · {role.display_name}", parent, 400)

        frames, native, _ = load_frames(cf)
        start = hotspot or native or (0, 0)

        note = QLabel(
            "Click the pixel that should count as the tip of this cursor."
            if cf.kind.name == "CONVERTIBLE" else
            "This file already carries a hotspot from its own format. It is "
            "shown here for reference and is preserved exactly on install.")
        note.setObjectName("Sub")
        note.setWordWrap(True)
        self.body.addWidget(note)

        wrap = QHBoxLayout()
        wrap.addStretch(1)
        self.canvas = HotspotCanvas(cf, start)
        self.canvas.setEnabled(cf.kind.name == "CONVERTIBLE")
        wrap.addWidget(self.canvas)
        wrap.addStretch(1)
        self.body.addLayout(wrap)

        self.readout = QLabel()
        self.readout.setObjectName("Mono")
        self.readout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.body.addWidget(self.readout)
        self._update_readout(*start)

        self.canvas.changed.connect(self._update_readout)

        if cf.kind.name == "CONVERTIBLE":
            self.add_buttons("Set hotspot")
        else:
            row = QHBoxLayout()
            row.addStretch(1)
            close = QPushButton("Close")
            close.setObjectName("Ghost")
            close.clicked.connect(self.reject)
            row.addWidget(close)
            self.body.addLayout(row)

    def _update_readout(self, x: int, y: int) -> None:
        self.readout.setText(f"hotspot  x={x}  y={y}")

    @property
    def hotspot(self) -> tuple[int, int]:
        return self.canvas.hotspot
