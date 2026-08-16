"""Frameless-window chrome: a custom title bar plus edge resizing."""
from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from .. import theme
from ..resources import logo_pixmap

RESIZE_MARGIN = 6


class TitleBar(QWidget):
    """Drag to move, double-click to maximise, with the usual three buttons."""

    minimise_clicked = Signal()
    maximise_clicked = Signal()
    close_clicked = Signal()

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setObjectName("TitleBar")
        self.setFixedHeight(42)
        self._drag_offset: QPoint | None = None

        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 0, 8, 0)
        lay.setSpacing(9)

        mark = QLabel()
        mark.setFixedSize(22, 22)
        mark.setScaledContents(True)
        pm = logo_pixmap(44)                 # 2x, so it stays sharp on hidpi
        if not pm.isNull():
            mark.setPixmap(pm)
        else:
            mark.setObjectName("TitleDot")   # fall back if the asset is gone
            mark.setText("◆")
        lay.addWidget(mark)

        self.title = QLabel(title)
        self.title.setObjectName("TitleText")
        lay.addWidget(self.title)

        self.subtitle = QLabel("")
        self.subtitle.setObjectName("Dim")
        lay.addWidget(self.subtitle)

        lay.addStretch(1)

        for glyph, name, signal in (
            ("–", "WinBtn", self.minimise_clicked),
            ("□", "WinBtn", self.maximise_clicked),
            ("✕", "WinBtnClose", self.close_clicked),
        ):
            b = QPushButton(glyph)
            b.setObjectName(name)
            b.setFixedSize(34, 26)
            b.setCursor(Qt.CursorShape.ArrowCursor)
            b.clicked.connect(signal.emit)
            lay.addWidget(b)

    def set_subtitle(self, text: str) -> None:
        self.subtitle.setText(f"  {text}" if text else "")

    # The window is frameless, so moving it is our job.
    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            win = self.window()
            self._drag_offset = (e.globalPosition().toPoint()
                                 - win.frameGeometry().topLeft())
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._drag_offset is None:
            return
        win = self.window()
        if win.isMaximized():
            # Un-maximise and continue the drag under the pointer.
            ratio = e.globalPosition().toPoint().x() / max(win.width(), 1)
            win.showNormal()
            self._drag_offset = QPoint(int(win.width() * ratio), self.height() // 2)
        win.move(e.globalPosition().toPoint() - self._drag_offset)

    def mouseReleaseEvent(self, e):
        self._drag_offset = None
        super().mouseReleaseEvent(e)

    def mouseDoubleClickEvent(self, e):
        self.maximise_clicked.emit()
        super().mouseDoubleClickEvent(e)


class ResizeMixin:
    """Edge resizing for a frameless top-level window.

    Mixed into the main window; expects `self` to be a QWidget with mouse
    tracking enabled.
    """

    _resize_edge: str = ""
    _resize_start = None
    _resize_geom = None

    def _edge_at(self, pos: QPoint) -> str:
        m = RESIZE_MARGIN
        w, h = self.width(), self.height()
        left, right = pos.x() <= m, pos.x() >= w - m
        top, bottom = pos.y() <= m, pos.y() >= h - m
        return ("topleft" if top and left else
                "topright" if top and right else
                "bottomleft" if bottom and left else
                "bottomright" if bottom and right else
                "left" if left else "right" if right else
                "top" if top else "bottom" if bottom else "")

    @staticmethod
    def _cursor_for(edge: str):
        return {
            "left": Qt.CursorShape.SizeHorCursor,
            "right": Qt.CursorShape.SizeHorCursor,
            "top": Qt.CursorShape.SizeVerCursor,
            "bottom": Qt.CursorShape.SizeVerCursor,
            "topleft": Qt.CursorShape.SizeFDiagCursor,
            "bottomright": Qt.CursorShape.SizeFDiagCursor,
            "topright": Qt.CursorShape.SizeBDiagCursor,
            "bottomleft": Qt.CursorShape.SizeBDiagCursor,
        }.get(edge, Qt.CursorShape.ArrowCursor)

    def handle_resize_press(self, e) -> bool:
        if self.isMaximized():
            return False
        edge = self._edge_at(e.position().toPoint())
        if not edge:
            return False
        self._resize_edge = edge
        self._resize_start = e.globalPosition().toPoint()
        self._resize_geom = self.geometry()
        return True

    def handle_resize_move(self, e) -> bool:
        if not self._resize_edge:
            if not self.isMaximized():
                self.setCursor(self._cursor_for(self._edge_at(e.position().toPoint())))
            return False

        delta = e.globalPosition().toPoint() - self._resize_start
        g = self._resize_geom
        x, y, w, h = g.x(), g.y(), g.width(), g.height()
        mw = self.minimumWidth() or 900
        mh = self.minimumHeight() or 600

        if "left" in self._resize_edge:
            nw = max(w - delta.x(), mw)
            x += w - nw
            w = nw
        if "right" in self._resize_edge:
            w = max(w + delta.x(), mw)
        if "top" in self._resize_edge:
            nh = max(h - delta.y(), mh)
            y += h - nh
            h = nh
        if "bottom" in self._resize_edge:
            h = max(h + delta.y(), mh)

        self.setGeometry(x, y, w, h)
        return True

    def handle_resize_release(self) -> None:
        self._resize_edge = ""
        self.unsetCursor()
