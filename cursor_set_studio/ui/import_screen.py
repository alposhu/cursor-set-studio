"""Import screen: the first-run empty state and the folder drop target."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import (QEasingCurve, QPropertyAnimation, Qt, Signal)
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QFileDialog, QFrame, QHBoxLayout, QLabel,
                               QProgressBar, QPushButton, QVBoxLayout, QWidget)

from . import theme
from .resources import logo_pixmap


class DropZone(QFrame):
    """A large dashed target that accepts a dropped folder."""

    folder_chosen = Signal(object)       # Path

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setMinimumHeight(230)
        self._hover = False
        self._glow = 0.0

        lay = QVBoxLayout(self)
        lay.setContentsMargins(30, 30, 30, 30)
        lay.setSpacing(11)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.icon = QLabel("↓")
        self.icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon.setStyleSheet(
            f"font-size:38px; color:{theme.ACCENT}; font-weight:300;")
        lay.addWidget(self.icon)

        title = QLabel("Drop a cursor folder here")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size:16px; font-weight:600;")
        lay.addWidget(title)

        sub = QLabel("A folder, or a .zip, .7z or .rar archive. "
                     "Subfolders are included.")
        sub.setObjectName("Sub")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(sub)

        lay.addSpacing(6)
        row = QHBoxLayout()
        row.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row.setSpacing(8)
        browse = QPushButton("Browse for a folder…")
        browse.setObjectName("Primary")
        browse.setCursor(Qt.CursorShape.PointingHandCursor)
        browse.clicked.connect(self._browse)
        row.addWidget(browse)
        archive = QPushButton("Open an archive…")
        archive.setObjectName("Ghost")
        archive.setCursor(Qt.CursorShape.PointingHandCursor)
        archive.clicked.connect(self._browse_archive)
        row.addWidget(archive)
        lay.addLayout(row)

    def _browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "Choose a folder of cursor files", str(Path.home()))
        if folder:
            self.folder_chosen.emit(Path(folder))

    def _browse_archive(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose a cursor pack archive", str(Path.home()),
            "Archives (*.zip *.7z *.rar);;All files (*)")
        if path:
            self.folder_chosen.emit(Path(path))

    # -- drag and drop ------------------------------------------------------
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls() and any(
                Path(u.toLocalFile()).is_dir() or
                Path(u.toLocalFile()).suffix.lower()
                in (".cur", ".ani", ".zip", ".7z", ".rar")
                for u in e.mimeData().urls()):
            self._set_hover(True)
            e.acceptProposedAction()

    def dragLeaveEvent(self, e):
        self._set_hover(False)

    def dropEvent(self, e):
        self._set_hover(False)
        for url in e.mimeData().urls():
            p = Path(url.toLocalFile())
            if p.is_dir():
                self.folder_chosen.emit(p)
                e.acceptProposedAction()
                return
            if p.is_file() and p.suffix.lower() in (".zip", ".7z", ".rar"):
                self.folder_chosen.emit(p)      # the window extracts it
                e.acceptProposedAction()
                return
            if p.is_file() and p.suffix.lower() in (".cur", ".ani"):
                # Dropping a file is a reasonable way to mean "this folder".
                self.folder_chosen.emit(p.parent)
                e.acceptProposedAction()
                return
        e.ignore()

    def _set_hover(self, on: bool) -> None:
        if self._hover == on:
            return
        self._hover = on
        self.icon.setText("↓" if not on else "⤓")
        anim = QPropertyAnimation(self, b"glow", self)
        anim.setDuration(180)
        anim.setStartValue(self._glow)
        anim.setEndValue(1.0 if on else 0.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.start()
        self._anim = anim

    def get_glow(self) -> float:
        return self._glow

    def set_glow(self, v: float) -> None:
        self._glow = v
        self.update()

    glow = property(get_glow, set_glow)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(2, 2, -2, -2)

        path = QPainterPath()
        path.addRoundedRect(rect, 14, 14)

        base = QColor(theme.BG_SURFACE)
        if self._glow > 0:
            accent = QColor(theme.ACCENT)
            accent.setAlphaF(0.10 * self._glow)
            p.fillPath(path, base)
            p.fillPath(path, accent)
        else:
            p.fillPath(path, base)

        col = QColor(theme.ACCENT) if self._glow > 0.5 else QColor(theme.BORDER_STRONG)
        pen = QPen(col, 1.6 + self._glow, Qt.PenStyle.DashLine)
        pen.setDashPattern([7, 5])
        p.setPen(pen)
        p.drawPath(path)


class ImportScreen(QWidget):
    """Choose a folder, watch it scan."""

    folder_chosen = Signal(object)
    cancel_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Screen")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(38, 30, 38, 30)
        outer.setSpacing(6)

        hero = QHBoxLayout()
        hero.setSpacing(16)

        mark = QLabel()
        mark.setFixedSize(64, 64)
        mark.setScaledContents(True)
        pm = logo_pixmap(128)
        if not pm.isNull():
            mark.setPixmap(pm)
        hero.addWidget(mark, 0, Qt.AlignmentFlag.AlignTop)

        heading = QVBoxLayout()
        heading.setSpacing(4)
        title = QLabel("Build a cursor set")
        title.setObjectName("H1")
        heading.addWidget(title)

        sub = QLabel("Point Cursor Set Studio at a folder of cursor files. "
                     "It works out which file belongs to which role, and you "
                     "correct anything it gets wrong before installing.")
        sub.setObjectName("Sub")
        sub.setWordWrap(True)
        sub.setMaximumWidth(620)
        heading.addWidget(sub)
        hero.addLayout(heading, 1)
        # The heading is capped at 620px, so without a stretch to absorb it
        # the leftover width gets spread as padding and the row drifts right.
        hero.addStretch(1)
        outer.addLayout(hero)
        outer.addSpacing(18)

        self.zone = DropZone()
        self.zone.folder_chosen.connect(self.folder_chosen.emit)
        outer.addWidget(self.zone, 1)

        # Scan progress, hidden until a scan starts.
        self.progress_box = QFrame()
        self.progress_box.setObjectName("Panel")
        pb = QVBoxLayout(self.progress_box)
        pb.setContentsMargins(16, 13, 16, 15)
        pb.setSpacing(9)

        row = QHBoxLayout()
        self.progress_label = QLabel("Scanning…")
        self.progress_label.setStyleSheet("font-size:12.5px; font-weight:550;")
        row.addWidget(self.progress_label)
        row.addStretch(1)
        self.progress_count = QLabel("")
        self.progress_count.setObjectName("Mono")
        row.addWidget(self.progress_count)
        cancel = QPushButton("Cancel")
        cancel.setObjectName("Ghost")
        cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel.clicked.connect(self.cancel_requested.emit)
        row.addWidget(cancel)
        pb.addLayout(row)

        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setRange(0, 0)          # indeterminate until the count is known
        pb.addWidget(self.bar)

        self.progress_box.hide()
        outer.addWidget(self.progress_box)

        outer.addSpacing(16)

        # What happens next - orients a first-run user without a wall of text.
        steps = QHBoxLayout()
        steps.setSpacing(12)
        for num, head, detail in (
            ("1", "Matched by name",
             "Every file is scored against the 15 Windows cursor roles. "
             "Weak or ambiguous matches are flagged, never forced."),
            ("2", "You have the last word",
             "Drag anything into place. Files that were not matched wait in "
             "a pool — nothing is discarded."),
            ("3", "Installed safely",
             "Cursors are copied into managed storage and applied to your "
             "account. Your current set is backed up first."),
        ):
            steps.addWidget(self._step_card(num, head, detail), 1)
        outer.addLayout(steps)
        outer.addSpacing(10)

        tips = QLabel(
            "Nothing is written to your system at this stage. Files are only "
            "read, and your current cursors are backed up before anything is "
            "applied.")
        tips.setObjectName("Dim")
        tips.setWordWrap(True)
        outer.addWidget(tips)


    @staticmethod
    def _step_card(num: str, head: str, detail: str) -> QFrame:
        card = QFrame()
        card.setObjectName("Card")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(15, 13, 15, 14)
        lay.setSpacing(5)

        n = QLabel(num)
        n.setStyleSheet(
            f"color:{theme.ACCENT_BRIGHT}; font-size:11px; font-weight:800;"
            f"letter-spacing:1px;")
        lay.addWidget(n)

        h = QLabel(head)
        h.setStyleSheet("font-size:12.5px; font-weight:600;")
        lay.addWidget(h)

        d = QLabel(detail)
        d.setObjectName("Dim")
        d.setWordWrap(True)
        lay.addWidget(d)
        return card

    # -- progress -----------------------------------------------------------
    def start_progress(self, folder: Path) -> None:
        verb = "Opening" if folder.is_file() else "Scanning"
        self.progress_label.setText(f"{verb} {folder.name}…")
        self.progress_count.setText("")
        self.bar.setRange(0, 0)
        self.progress_box.show()
        self.zone.setEnabled(False)

    def set_status(self, text: str) -> None:
        self.progress_label.setText(text)

    def update_progress(self, done: int, total: int) -> None:
        if total > 0:
            self.bar.setRange(0, total)
            self.bar.setValue(done)
            self.progress_count.setText(f"{done} / {total}")

    def stop_progress(self) -> None:
        self.progress_box.hide()
        self.zone.setEnabled(True)
