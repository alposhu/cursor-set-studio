"""Scheme library: everything built with this app, ready to reapply."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QFileDialog, QFrame, QHBoxLayout, QLabel,
                               QPushButton, QScrollArea, QVBoxLayout, QWidget)

from ..core import library, registry
from ..core.models import SchemeRecord
from . import theme
from .dialogs import ConfirmDialog, TextPromptDialog
from .util import clear_layout
from .widgets.badges import Pill


class SchemeRow(QFrame):
    """One saved scheme."""

    reapply = Signal(object)
    rename = Signal(object)
    export = Signal(object)
    delete = Signal(object)

    def __init__(self, rec: SchemeRecord, active: bool, parent=None):
        super().__init__(parent)
        self.rec = rec
        self.setObjectName("Card")
        self.setFixedHeight(78)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 11, 12, 11)
        lay.setSpacing(13)

        thumb = QLabel()
        thumb.setFixedSize(46, 46)
        thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        thumb.setStyleSheet(
            f"background:{theme.BG_INPUT}; border:1px solid {theme.BORDER};"
            f"border-radius:8px;")
        if rec.thumbnail and Path(rec.thumbnail).is_file():
            pm = QPixmap(rec.thumbnail)
            if not pm.isNull():
                thumb.setPixmap(pm.scaled(
                    34, 34, Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation))
        lay.addWidget(thumb)

        col = QVBoxLayout()
        col.setSpacing(3)
        row1 = QHBoxLayout()
        row1.setSpacing(7)
        name = QLabel(rec.name)
        name.setStyleSheet("font-size:13px; font-weight:600;")
        row1.addWidget(name)
        if active:
            row1.addWidget(Pill("ACTIVE", theme.OK, theme.OK_WASH))
        row1.addStretch(1)
        col.addLayout(row1)

        missing = sum(1 for p in rec.roles.values() if not Path(p).is_file())
        detail = (f"{len(rec.roles)} roles  ·  "
                  f"{rec.created.replace('T', ' ')}")
        if missing:
            detail += f"  ·  {missing} file(s) missing"
        meta = QLabel(detail)
        meta.setObjectName("Dim")
        col.addWidget(meta)
        lay.addLayout(col, 1)

        for label, signal, obj in (
            ("Apply", self.reapply, "Primary"),
            ("Rename", self.rename, "Ghost"),
            ("Export", self.export, "Ghost"),
            ("Delete", self.delete, "Danger"),
        ):
            b = QPushButton(label)
            b.setObjectName(obj)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, s=signal: s.emit(self.rec))
            if label == "Apply" and missing == len(rec.roles) and rec.roles:
                b.setEnabled(False)
                b.setToolTip("The files for this scheme are no longer on disk.")
            lay.addWidget(b)


class LibraryScreen(QWidget):
    """Reapply, rename, export, or delete any scheme built here."""

    toast = Signal(str, str)
    back = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Screen")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 22, 28, 20)
        outer.setSpacing(13)

        head = QHBoxLayout()
        col = QVBoxLayout()
        col.setSpacing(2)
        t = QLabel("Scheme library")
        t.setObjectName("H1")
        col.addWidget(t)
        s = QLabel("Every set you have built here. Reapply one at any time.")
        s.setObjectName("Sub")
        col.addWidget(s)
        head.addLayout(col, 1)

        restore = QPushButton("Restore original cursors")
        restore.setObjectName("Ghost")
        restore.setCursor(Qt.CursorShape.PointingHandCursor)
        restore.clicked.connect(self._restore_original)
        head.addWidget(restore)

        back = QPushButton("←  Back")
        back.setObjectName("Ghost")
        back.setCursor(Qt.CursorShape.PointingHandCursor)
        back.clicked.connect(self.back.emit)
        head.addWidget(back)
        outer.addLayout(head)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QWidget()
        self.list_lay = QVBoxLayout(inner)
        self.list_lay.setContentsMargins(0, 0, 8, 0)
        self.list_lay.setSpacing(8)
        self.list_lay.addStretch(1)
        scroll.setWidget(inner)
        outer.addWidget(scroll, 1)

        self.empty = QLabel(
            "No schemes yet.\n\nBuild one from the Import screen and it will "
            "appear here, ready to reapply whenever you want it back.")
        self.empty.setObjectName("Dim")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setWordWrap(True)
        outer.addWidget(self.empty)

        self.refresh()

    def refresh(self) -> None:
        clear_layout(self.list_lay, keep_trailing=1)

        records = library.load_library()
        try:
            active = registry.read_current().scheme_name
        except Exception:
            active = ""

        for rec in records:
            row = SchemeRow(rec, active == rec.name)
            row.reapply.connect(self._reapply)
            row.rename.connect(self._rename)
            row.export.connect(self._export)
            row.delete.connect(self._delete)
            self.list_lay.insertWidget(self.list_lay.count() - 1, row)

        self.empty.setVisible(not records)

    # -- actions ------------------------------------------------------------
    def _reapply(self, rec: SchemeRecord) -> None:
        live = {k: v for k, v in rec.roles.items() if Path(v).is_file()}
        if not live:
            self.toast.emit(
                "None of this scheme's files are on disk any more.", "error")
            return
        missing = len(rec.roles) - len(live)
        try:
            registry.apply_cursors(live, scheme_name=rec.name)
            msg = f"“{rec.name}” applied."
            if missing:
                msg += f" {missing} missing file(s) were skipped."
            self.toast.emit(msg, "success" if not missing else "warn")
        except registry.RegistryError as exc:
            self.toast.emit(f"Could not apply: {exc}", "error")
        self.refresh()

    def _rename(self, rec: SchemeRecord) -> None:
        taken = [r.name for r in library.load_library() if r.name != rec.name]
        d = TextPromptDialog("Rename scheme", "New name for this scheme:",
                             self, rec.name, taken=taken)
        if not d.exec() or not d.value or d.value == rec.name:
            return
        new = d.value
        try:
            registry.delete_scheme(rec.name)
            registry.save_scheme(new, rec.roles)
        except registry.RegistryError:
            pass
        library.rename_scheme_record(rec.name, new)
        self.toast.emit(f"Renamed to “{new}”.", "success")
        self.refresh()

    def _export(self, rec: SchemeRecord) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "Choose where to export", str(Path.home()))
        if not folder:
            return
        try:
            dest = library.export_scheme(
                rec.name, rec.roles,
                Path(folder) / library.safe_dir_name(rec.name))
            self.toast.emit(f"Exported to {dest.name}.", "success")
        except Exception as exc:
            self.toast.emit(f"Export failed: {exc}", "error")

    def _delete(self, rec: SchemeRecord) -> None:
        if not ConfirmDialog.ask(
                self, "Delete this scheme",
                f"“{rec.name}” will be removed from the library, and its "
                f"copied cursor files deleted.\n\nIf it is the scheme you are "
                f"using right now, your cursors will keep working until you "
                f"apply a different one, then fall back to the Windows "
                f"default.\n\nYour original cursors stay restorable.",
                "Delete", danger=True):
            return
        try:
            registry.delete_scheme(rec.name)
        except registry.RegistryError:
            pass
        library.delete_scheme_record(rec.name)
        self.toast.emit(f"“{rec.name}” deleted.", "info")
        self.refresh()

    def _restore_original(self) -> None:
        backup = registry.load_backup(original=True)
        if backup is None:
            self.toast.emit("Nothing backed up yet — install a set first.", "info")
            return
        if not ConfirmDialog.ask(
                self, "Restore original cursors",
                f"Put back the configuration saved on "
                f"{backup.captured.replace('T', ' ')}, before this app changed "
                f"anything?", "Restore"):
            return
        try:
            registry.restore_backup(original=True)
            self.toast.emit("Original cursors restored.", "success")
        except registry.RegistryError as exc:
            self.toast.emit(f"Restore failed: {exc}", "error")
        self.refresh()

    def showEvent(self, e):
        super().showEvent(e)
        self.refresh()
