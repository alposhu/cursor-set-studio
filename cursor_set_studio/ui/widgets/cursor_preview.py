"""Animated cursor rendering.

Two consumers, one cache:

* AnimatedCursorLabel paints a cursor inside the UI (role cards, pool chips).
* make_qcursor / LiveCursor turn the same frames into a real QCursor, so the
  preview screen can show the actual cursor shape, at its real hotspot,
  following the mouse - without touching the system cursor settings.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (QColor, QCursor, QImage, QPainter, QPen, QPixmap)
from PySide6.QtWidgets import QWidget

from ...core import cursor_io
from ...core.models import CursorFile
from .. import theme

# path -> (frames, hotspot, error)
_CACHE: dict[str, tuple[list[tuple[QPixmap, int]], tuple[int, int], Optional[str]]] = {}
MAX_CACHE = 400


def pil_to_qpixmap(img) -> QPixmap:
    """Convert a Pillow RGBA image to a QPixmap."""
    img = img.convert("RGBA")
    data = img.tobytes("raw", "RGBA")
    qimg = QImage(data, img.width, img.height, img.width * 4,
                  QImage.Format.Format_RGBA8888)
    # copy() detaches from the Python buffer, which is about to be freed.
    return QPixmap.fromImage(qimg.copy())


def load_frames(cf: CursorFile) -> tuple[list[tuple[QPixmap, int]], tuple[int, int], Optional[str]]:
    """Load a scanned file as (frames, hotspot, error).

    Frames come back as (pixmap, duration_ms). A static cursor is a single
    frame with duration 0. On failure the frame list is empty and the error
    string explains why, so callers can render a placeholder instead.
    """
    key = str(cf.path)
    if key in _CACHE:
        return _CACHE[key]

    frames: list[tuple[QPixmap, int]] = []
    hotspot = (0, 0)
    error: Optional[str] = None

    try:
        if cf.is_sequence:
            # A numbered run has not been combined into an .ani yet, so play
            # the individual frames at the default rate.
            per_frame = int(cursor_io.DEFAULT_JIFFIES * cursor_io.JIFFY_MS)
            for fp in cf.sequence_paths:
                for img, _ in cursor_io.load_frames(fp):
                    frames.append((pil_to_qpixmap(img), per_frame))
                    break
            if frames:
                hotspot = cursor_io.probe(cf.sequence_paths[0]).hotspot
        else:
            for img, ms in cursor_io.load_frames(cf.path):
                frames.append((pil_to_qpixmap(img), ms))
            hotspot = cf.hotspot or cursor_io.probe(cf.path).hotspot
    except cursor_io.CursorFormatError as exc:
        error = str(exc)
    except Exception as exc:
        error = f"could not render: {exc}"

    if len(_CACHE) > MAX_CACHE:
        _CACHE.clear()
    _CACHE[key] = (frames, hotspot, error)
    return _CACHE[key]


def clear_cache() -> None:
    _CACHE.clear()


def make_qcursor(cf: CursorFile, frame_index: int = 0) -> Optional[QCursor]:
    """Build a real QCursor for one frame, honouring the hotspot."""
    frames, hotspot, error = load_frames(cf)
    if error or not frames:
        return None
    pm, _ = frames[frame_index % len(frames)]
    return QCursor(pm, hotspot[0], hotspot[1])


class AnimatedCursorLabel(QWidget):
    """Paints a cursor at a fixed box size, animating .ani frames in place."""

    clicked = Signal()

    def __init__(self, box: int = 40, parent=None, *, interactive: bool = False):
        super().__init__(parent)
        self._box = box
        self._frames: list[tuple[QPixmap, int]] = []
        self._hotspot = (0, 0)
        self._error: Optional[str] = None
        self._index = 0
        self._file: Optional[CursorFile] = None
        self._show_hotspot = False
        self._scale_to_box = False

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._advance)

        self.setFixedSize(box, box)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        if interactive:
            self.setCursor(Qt.CursorShape.PointingHandCursor)

    # -- content ------------------------------------------------------------
    def set_file(self, cf: Optional[CursorFile]) -> None:
        self._timer.stop()
        self._file = cf
        self._index = 0
        if cf is None:
            self._frames, self._hotspot, self._error = [], (0, 0), None
        else:
            self._frames, self._hotspot, self._error = load_frames(cf)
        self.update()
        self._schedule()

    def set_show_hotspot(self, on: bool) -> None:
        self._show_hotspot = on
        self.update()

    def set_scale_to_box(self, on: bool) -> None:
        self._scale_to_box = on
        self.update()

    @property
    def file(self) -> Optional[CursorFile]:
        return self._file

    @property
    def error(self) -> Optional[str]:
        return self._error

    @property
    def frame_count(self) -> int:
        return len(self._frames)

    # -- animation ----------------------------------------------------------
    def _schedule(self) -> None:
        if len(self._frames) > 1 and self.isVisible():
            self._timer.start(max(self._frames[self._index][1], 20))

    def _advance(self) -> None:
        if not self._frames:
            return
        self._index = (self._index + 1) % len(self._frames)
        self.update()
        self._schedule()

    def showEvent(self, e):
        super().showEvent(e)
        self._schedule()

    def hideEvent(self, e):
        super().hideEvent(e)
        self._timer.stop()          # never animate off-screen widgets

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(e)

    # -- painting -----------------------------------------------------------
    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        if self._error is not None:
            self._paint_placeholder(p, theme.DANGER, "!")
            return
        if not self._frames:
            self._paint_placeholder(p, theme.BORDER_STRONG, "")
            return

        pm, _ = self._frames[self._index % len(self._frames)]
        w, h = pm.width(), pm.height()

        # Draw at actual size when it fits, so the user sees true scale.
        if self._scale_to_box or w > self._box or h > self._box:
            ratio = min(self._box / max(w, 1), self._box / max(h, 1))
            w, h = max(int(w * ratio), 1), max(int(h * ratio), 1)
            drawn = pm.scaled(w, h, Qt.AspectRatioMode.KeepAspectRatio,
                              Qt.TransformationMode.SmoothTransformation)
        else:
            ratio = 1.0
            drawn = pm

        x = (self._box - w) // 2
        y = (self._box - h) // 2
        p.drawPixmap(x, y, drawn)

        if self._show_hotspot:
            hx = x + self._hotspot[0] * ratio
            hy = y + self._hotspot[1] * ratio
            p.setPen(QPen(QColor(theme.ACCENT_BRIGHT), 1.4))
            p.drawLine(int(hx) - 5, int(hy), int(hx) + 5, int(hy))
            p.drawLine(int(hx), int(hy) - 5, int(hx), int(hy) + 5)

    def _paint_placeholder(self, p: QPainter, color: str, glyph: str) -> None:
        rect = QRectF(3, 3, self._box - 6, self._box - 6)
        pen = QPen(QColor(color), 1.2, Qt.PenStyle.DashLine)
        p.setPen(pen)
        p.drawRoundedRect(rect, 6, 6)
        if glyph:
            p.setPen(QColor(color))
            f = p.font()
            f.setPointSize(max(self._box // 4, 7))
            f.setBold(True)
            p.setFont(f)
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter, glyph)


class LiveCursor:
    """Applies a cursor to widgets, animating it while the pointer is over them.

    Qt has no animated-cursor type, so an animated cursor is driven by
    swapping QCursor on a timer for as long as one of the registered widgets
    is hovered.
    """

    def __init__(self, parent: QWidget):
        self._parent = parent
        self._widgets: dict[QWidget, Optional[CursorFile]] = {}
        self._active: Optional[QWidget] = None
        self._index = 0
        self._timer = QTimer(parent)
        self._timer.timeout.connect(self._tick)

    def bind(self, widget: QWidget, cf: Optional[CursorFile]) -> None:
        """Give `widget` the cursor of `cf` (or the default arrow if None)."""
        self._widgets[widget] = cf
        if cf is None:
            widget.unsetCursor()
            return
        frames, hotspot, error = load_frames(cf)
        if error or not frames:
            widget.setCursor(Qt.CursorShape.ForbiddenCursor)
            return
        widget.setCursor(QCursor(frames[0][0], hotspot[0], hotspot[1]))

    def enter(self, widget: QWidget) -> None:
        cf = self._widgets.get(widget)
        self._active = widget
        self._index = 0
        if cf is None:
            self._timer.stop()
            return
        frames, _, error = load_frames(cf)
        if error or len(frames) <= 1:
            self._timer.stop()
            return
        self._timer.start(max(frames[0][1], 20))

    def leave(self, widget: QWidget) -> None:
        if self._active is widget:
            self._active = None
            self._timer.stop()

    def _tick(self) -> None:
        if self._active is None:
            self._timer.stop()
            return
        cf = self._widgets.get(self._active)
        if cf is None:
            return
        frames, hotspot, _ = load_frames(cf)
        if not frames:
            return
        self._index = (self._index + 1) % len(frames)
        pm, ms = frames[self._index]
        self._active.setCursor(QCursor(pm, hotspot[0], hotspot[1]))
        self._timer.start(max(ms, 20))

    def clear(self) -> None:
        self._timer.stop()
        self._active = None
        self._widgets.clear()
