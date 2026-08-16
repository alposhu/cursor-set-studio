"""Toast notifications - routine feedback without a modal dialog."""
from __future__ import annotations

from PySide6.QtCore import (QEasingCurve, QPoint, QPropertyAnimation, Qt,
                            QTimer)
from PySide6.QtWidgets import (QGraphicsOpacityEffect, QHBoxLayout, QLabel,
                               QPushButton, QVBoxLayout, QWidget)

from .. import theme

KINDS = {
    "info": (theme.ACCENT_BRIGHT, "◆"),
    "success": (theme.OK, "✓"),
    "warn": (theme.WARN, "!"),
    "error": (theme.DANGER, "✕"),
}


class Toast(QWidget):
    """A single message. Fades in, waits, slides out."""

    def __init__(self, text: str, kind: str = "info", parent=None,
                 *, action: tuple[str, callable] | None = None,
                 duration: int = 3600):
        super().__init__(parent)
        color, glyph = KINDS.get(kind, KINDS["info"])

        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(
            f"background:{theme.BG_ELEVATED};"
            f"border:1px solid {theme.BORDER_STRONG};"
            f"border-left:3px solid {color};"
            f"border-radius:{theme.RADIUS_SM}px;")

        lay = QHBoxLayout(self)
        lay.setContentsMargins(13, 10, 12, 10)
        lay.setSpacing(10)

        icon = QLabel(glyph)
        icon.setStyleSheet(
            f"color:{color}; font-size:13px; font-weight:800; border:none;")
        lay.addWidget(icon, 0, Qt.AlignmentFlag.AlignTop)

        label = QLabel(text)
        label.setWordWrap(True)
        label.setStyleSheet(
            f"color:{theme.TEXT}; font-size:12px; border:none;")
        label.setMaximumWidth(330)
        lay.addWidget(label, 1)

        if action:
            btn = QPushButton(action[0])
            btn.setObjectName("Link")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(
                f"color:{color}; background:transparent; border:none;"
                f"font-size:11.5px; font-weight:650; padding:2px 4px;")
            btn.clicked.connect(action[1])
            btn.clicked.connect(self.dismiss)
            lay.addWidget(btn, 0, Qt.AlignmentFlag.AlignTop)

        self._effect = QGraphicsOpacityEffect(self)
        self._effect.setOpacity(0.0)
        self.setGraphicsEffect(self._effect)

        self.adjustSize()
        self._anim: QPropertyAnimation | None = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.dismiss)
        self._duration = duration

    def show_at(self, pos: QPoint) -> None:
        self.move(pos + QPoint(0, 10))
        self.show()
        self.raise_()

        fade = QPropertyAnimation(self._effect, b"opacity", self)
        fade.setDuration(200)
        fade.setStartValue(0.0)
        fade.setEndValue(1.0)
        fade.setEasingCurve(QEasingCurve.Type.OutCubic)

        slide = QPropertyAnimation(self, b"pos", self)
        slide.setDuration(240)
        slide.setStartValue(pos + QPoint(0, 10))
        slide.setEndValue(pos)
        slide.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._anim = fade
        self._slide = slide
        fade.start()
        slide.start()
        self._timer.start(self._duration)

    def dismiss(self) -> None:
        self._timer.stop()
        anim = QPropertyAnimation(self._effect, b"opacity", self)
        anim.setDuration(180)
        anim.setStartValue(self._effect.opacity())
        anim.setEndValue(0.0)
        anim.setEasingCurve(QEasingCurve.Type.InCubic)
        anim.finished.connect(self._finish)
        self._anim = anim
        anim.start()

    def _finish(self) -> None:
        parent = self.parent()
        self.hide()
        if isinstance(parent, QWidget) and hasattr(parent, "_toasts"):
            host = parent
            if self in host._toasts:
                host._toasts.remove(self)
            host._reflow()
        self.deleteLater()


class ToastHost:
    """Stacks toasts in the bottom-right corner of a host widget."""

    MARGIN = 20
    GAP = 9

    def __init__(self, host: QWidget):
        self.host = host
        host._toasts = []                  # type: ignore[attr-defined]
        host._reflow = self._reflow        # type: ignore[attr-defined]

    def show(self, text: str, kind: str = "info", *,
             action: tuple[str, callable] | None = None,
             duration: int = 3600) -> Toast:
        toast = Toast(text, kind, self.host, action=action, duration=duration)
        self.host._toasts.append(toast)    # type: ignore[attr-defined]
        toast.show_at(self._slot_pos(toast, len(self.host._toasts) - 1))
        # Keep the stack short so it never covers the whole window.
        while len(self.host._toasts) > 4:
            self.host._toasts[0].dismiss()
            break
        return toast

    def _slot_pos(self, toast: Toast, index: int) -> QPoint:
        x = self.host.width() - toast.width() - self.MARGIN
        y = self.host.height() - self.MARGIN
        for t in self.host._toasts[:index]:
            y -= t.height() + self.GAP
        y -= toast.height()
        return QPoint(x, y)

    def _reflow(self) -> None:
        y = self.host.height() - self.MARGIN
        for t in self.host._toasts:
            y -= t.height()
            anim = QPropertyAnimation(t, b"pos", t)
            anim.setDuration(160)
            anim.setStartValue(t.pos())
            anim.setEndValue(QPoint(self.host.width() - t.width() - self.MARGIN, y))
            anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            anim.start()
            t._reflow_anim = anim          # keep a reference alive
            y -= self.GAP
