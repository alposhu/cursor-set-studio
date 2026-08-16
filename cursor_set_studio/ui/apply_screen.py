"""Apply screen: back up, stage into managed storage, install, export."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QFileDialog, QFrame, QHBoxLayout,
                               QLabel, QLineEdit, QProgressBar, QPushButton,
                               QScrollArea, QSlider, QVBoxLayout, QWidget)

from ..core import cursor_io, library, registry
from . import theme
from .dialogs import ConfirmDialog
from .state import AppState
from .util import clear_layout
from .widgets.badges import Pill
from .widgets.cursor_preview import AnimatedCursorLabel


class InfoRow(QFrame):
    """A labelled fact with an optional action button."""

    def __init__(self, title: str, detail: str, parent=None,
                 action: tuple[str, callable] | None = None,
                 kind: str = "info"):
        super().__init__(parent)
        self.setObjectName("Card")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 11, 12, 11)
        lay.setSpacing(11)

        col = QVBoxLayout()
        col.setSpacing(2)
        self.title = QLabel(title)
        self.title.setStyleSheet("font-size:12.5px; font-weight:600;")
        col.addWidget(self.title)
        self.detail = QLabel(detail)
        self.detail.setObjectName("Dim")
        self.detail.setWordWrap(True)
        col.addWidget(self.detail)
        lay.addLayout(col, 1)

        self.button = None
        if action:
            self.button = QPushButton(action[0])
            self.button.setObjectName("Ghost")
            self.button.setCursor(Qt.CursorShape.PointingHandCursor)
            self.button.clicked.connect(action[1])
            lay.addWidget(self.button, 0, Qt.AlignmentFlag.AlignVCenter)

    def set_detail(self, text: str) -> None:
        self.detail.setText(text)


class ApplyScreen(QWidget):
    """The last step: write it to Windows."""

    back = Signal()
    applied = Signal(str)                 # scheme name
    toast = Signal(str, str)              # message, kind
    busy = Signal(bool)
    open_library = Signal()

    def __init__(self, state: AppState, parent=None):
        super().__init__(parent)
        self.state = state
        self.setObjectName("Screen")
        self._worker = None
        self._pending_action = "apply"

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 22, 28, 20)
        outer.setSpacing(13)

        head = QHBoxLayout()
        col = QVBoxLayout()
        col.setSpacing(2)
        t = QLabel("Install the set")
        t.setObjectName("H1")
        col.addWidget(t)
        self.sub = QLabel("")
        self.sub.setObjectName("Sub")
        col.addWidget(self.sub)
        head.addLayout(col, 1)
        back = QPushButton("←  Back to preview")
        back.setObjectName("Ghost")
        back.setCursor(Qt.CursorShape.PointingHandCursor)
        back.clicked.connect(self.back.emit)
        head.addWidget(back)
        outer.addLayout(head)

        body = QHBoxLayout()
        body.setSpacing(14)

        # -- left column: the settings --------------------------------------
        left = QVBoxLayout()
        left.setSpacing(11)

        name_card = QFrame()
        name_card.setObjectName("Card")
        nl = QVBoxLayout(name_card)
        nl.setContentsMargins(14, 13, 14, 14)
        nl.setSpacing(8)
        nlab = QLabel("Scheme name")
        nlab.setStyleSheet("font-size:12.5px; font-weight:600;")
        nl.addWidget(nlab)
        self.name_edit = QLineEdit("My Cursor Set")
        self.name_edit.setPlaceholderText("My Cursor Set")
        nl.addWidget(self.name_edit)
        self.save_scheme_cb = QCheckBox(
            "Also register it as a named scheme in Mouse Properties")
        self.save_scheme_cb.setChecked(True)
        nl.addWidget(self.save_scheme_cb)
        left.addWidget(name_card)

        # Frame timing, only meaningful when a numbered run was detected.
        self.timing_card = QFrame()
        self.timing_card.setObjectName("Card")
        tl = QVBoxLayout(self.timing_card)
        tl.setContentsMargins(14, 13, 14, 14)
        tl.setSpacing(7)
        trow = QHBoxLayout()
        tlab = QLabel("Animation frame rate")
        tlab.setStyleSheet("font-size:12.5px; font-weight:600;")
        trow.addWidget(tlab)
        trow.addStretch(1)
        self.timing_value = QLabel("")
        self.timing_value.setObjectName("Mono")
        trow.addWidget(self.timing_value)
        tl.addLayout(trow)
        self.timing_note = QLabel("")
        self.timing_note.setObjectName("Dim")
        self.timing_note.setWordWrap(True)
        tl.addWidget(self.timing_note)
        self.timing = QSlider(Qt.Orientation.Horizontal)
        self.timing.setRange(1, 30)
        self.timing.setValue(cursor_io.DEFAULT_JIFFIES)
        self.timing.valueChanged.connect(self._update_timing)
        tl.addWidget(self.timing)
        left.addWidget(self.timing_card)

        self.backup_row = InfoRow(
            "Your current cursors", "",
            action=("Restore", self._restore))
        left.addWidget(self.backup_row)

        self.storage_row = InfoRow(
            "Managed storage",
            "Cursor files are copied into this app's own folder before "
            "anything is installed, so the scheme keeps working even if you "
            "move or delete the folder you imported from.")
        left.addWidget(self.storage_row)

        manifest = QFrame()
        manifest.setObjectName("Card")
        ml = QVBoxLayout(manifest)
        ml.setContentsMargins(14, 13, 14, 13)
        ml.setSpacing(8)
        mh = QLabel("What will be written")
        mh.setStyleSheet("font-size:12.5px; font-weight:600;")
        ml.addWidget(mh)

        m_scroll = QScrollArea()
        m_scroll.setWidgetResizable(True)
        m_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        m_inner = QWidget()
        self.manifest_lay = QVBoxLayout(m_inner)
        self.manifest_lay.setContentsMargins(0, 0, 6, 0)
        self.manifest_lay.setSpacing(3)
        self.manifest_lay.addStretch(1)
        m_scroll.setWidget(m_inner)
        ml.addWidget(m_scroll, 1)
        left.addWidget(manifest, 1)

        body.addLayout(left, 1)

        # -- right column: readiness + actions -------------------------------
        right = QFrame()
        right.setObjectName("Panel")
        right.setFixedWidth(310)
        rl = QVBoxLayout(right)
        rl.setContentsMargins(15, 15, 15, 15)
        rl.setSpacing(10)

        rh = QLabel("Ready to install")
        rh.setObjectName("H2")
        rl.addWidget(rh)

        self.count_row = QHBoxLayout()
        self.count_pill = Pill("0 ROLES", theme.OK, theme.OK_WASH)
        self.count_row.addWidget(self.count_pill)
        self.count_row.addStretch(1)
        rl.addLayout(self.count_row)

        self.readiness = QLabel("")
        self.readiness.setObjectName("Sub")
        self.readiness.setWordWrap(True)
        rl.addWidget(self.readiness)

        self.blocker = QLabel("")
        self.blocker.setWordWrap(True)
        self.blocker.setStyleSheet(
            f"color:{theme.WARN}; font-size:11.5px;"
            f"background:{theme.WARN_WASH}; border-radius:7px; padding:9px 11px;")
        self.blocker.hide()
        rl.addWidget(self.blocker)

        rl.addStretch(1)

        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.hide()
        rl.addWidget(self.progress)

        self.apply_btn = QPushButton("Apply now")
        self.apply_btn.setObjectName("Primary")
        self.apply_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.apply_btn.clicked.connect(self._apply)
        rl.addWidget(self.apply_btn)

        self.export_btn = QPushButton("Export as a shareable folder…")
        self.export_btn.setObjectName("Ghost")
        self.export_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.export_btn.clicked.connect(self._export)
        rl.addWidget(self.export_btn)

        lib = QPushButton("Open scheme library")
        lib.setObjectName("Link")
        lib.setCursor(Qt.CursorShape.PointingHandCursor)
        lib.clicked.connect(self.open_library.emit)
        rl.addWidget(lib)

        note = QLabel("Applies to your account only. No administrator rights "
                      "are needed and you will not have to sign out.")
        note.setObjectName("Dim")
        note.setWordWrap(True)
        rl.addWidget(note)

        body.addWidget(right)
        outer.addLayout(body, 1)

        state.assignments_changed.connect(self.refresh)
        self._update_timing(self.timing.value())

    # -- state --------------------------------------------------------------
    def refresh(self) -> None:
        filled = self.state.filled_count
        missing = self.state.missing_core_roles()
        blockers = self.state.apply_blockers()

        self.count_pill.apply(f"{filled} ROLES", theme.OK if filled else theme.IDLE,
                              theme.OK_WASH if filled else theme.IDLE_WASH)
        self.sub.setText(
            f"{filled} cursor{'s' if filled != 1 else ''} will be written to "
            f"HKEY_CURRENT_USER\\Control Panel\\Cursors.")

        if missing:
            self.readiness.setText(
                f"{len(missing)} core role{'s' if len(missing) != 1 else ''} "
                f"will be left at the Windows default: " + ", ".join(missing[:6])
                + ("…" if len(missing) > 6 else ""))
        else:
            self.readiness.setText("All 15 core roles are assigned.")

        if blockers:
            self.blocker.setText("  ".join(blockers) +
                                 "  Assign at least one cursor before installing.")
            self.blocker.show()
        else:
            self.blocker.hide()

        self.apply_btn.setEnabled(not blockers and self._worker is None)
        self.export_btn.setEnabled(not blockers and self._worker is None)

        seqs = sum(1 for a in self.state.assignments.values()
                   if a.filled and a.file.is_sequence)
        self.timing_card.setVisible(seqs > 0)
        if seqs:
            self.timing_note.setText(
                f"{seqs} role{'s' if seqs != 1 else ''} came from numbered "
                f"frame files and will be combined into a single .ani.")

        backup = registry.load_backup(original=True)
        if backup:
            self.backup_row.set_detail(
                f"Backed up {backup.captured.replace('T', ' ')} — "
                f"scheme “{backup.scheme_name or 'unnamed'}”, "
                f"{len(backup.roles)} roles. One click puts it back.")
        else:
            self.backup_row.set_detail(
                "Not backed up yet. Your current configuration is saved "
                "automatically the first time you install a set.")
        if self.backup_row.button:
            self.backup_row.button.setEnabled(backup is not None)

        self._rebuild_manifest()

        self.storage_row.set_detail(
            "Cursor files are copied into this app's own folder before "
            "anything is installed, so the scheme keeps working even if you "
            f"move or delete the folder you imported from.\n{library.schemes_root()}")


    def _rebuild_manifest(self) -> None:
        """List each role and the file that will land in it."""
        clear_layout(self.manifest_lay, keep_trailing=1)

        index = 0
        for a in self.state.assignments.values():
            row = QWidget()
            rl = QHBoxLayout(row)
            rl.setContentsMargins(2, 2, 2, 2)
            rl.setSpacing(9)

            prev = AnimatedCursorLabel(24)
            prev.set_file(a.file)
            rl.addWidget(prev)

            name = QLabel(a.role.display_name)
            name.setStyleSheet(
                f"font-size:11.5px; color:"
                f"{theme.TEXT if a.filled else theme.TEXT_DIM};")
            name.setFixedWidth(132)
            rl.addWidget(name)

            if a.filled:
                target = QLabel(f"{a.role.registry_name}"
                                f"{'.ani' if a.file.is_animated else '.cur'}")
                target.setObjectName("Mono")
                rl.addWidget(target)
                rl.addStretch(1)
                src = QLabel(a.file.stem)
                src.setObjectName("Dim")
                src.setToolTip(str(a.file.path))
                rl.addWidget(src)
            else:
                skip = QLabel("left at the Windows default")
                skip.setObjectName("Dim")
                rl.addWidget(skip)
                rl.addStretch(1)

            self.manifest_lay.insertWidget(index, row)
            index += 1

    def _update_timing(self, jiffies: int) -> None:
        ms = jiffies * cursor_io.JIFFY_MS
        self.timing_value.setText(f"{jiffies} jiffies · {ms:.0f} ms/frame")

    # -- actions ------------------------------------------------------------
    def _scheme_name(self) -> str:
        return self.name_edit.text().strip() or "My Cursor Set"

    def _apply(self) -> None:
        if self.state.apply_blockers():
            return
        missing = self.state.missing_core_roles()
        if missing and not ConfirmDialog.ask(
                self, "Some roles are empty",
                f"{len(missing)} core role(s) have no cursor assigned:\n\n"
                + ", ".join(missing)
                + "\n\nWindows will keep its current cursor for those. "
                  "Install anyway?",
                "Install anyway"):
            return
        self._pending_action = "apply"
        self._stage()

    def _export(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "Choose where to export the set", str(Path.home()))
        if not folder:
            return
        self._export_target = Path(folder) / library.safe_dir_name(self._scheme_name())
        self._pending_action = "export"
        self._stage()

    def _stage(self) -> None:
        from .workers import StageWorker

        # Snapshot the current configuration before the first ever install.
        try:
            if not registry.has_original_backup():
                registry.backup_current(original=True)
            registry.backup_current(original=False)
        except Exception as exc:
            self.toast.emit(f"Could not back up current cursors: {exc}", "warn")

        self.progress.setRange(0, 0)
        self.progress.show()
        self.apply_btn.setEnabled(False)
        self.export_btn.setEnabled(False)
        self.busy.emit(True)

        self._worker = StageWorker(
            self._scheme_name(),
            [a for a in self.state.assignments.values() if a.filled],
            frame_jiffies=self.timing.value(),
            parent=self)
        self._worker.progress.connect(self._on_stage_progress)
        self._worker.finished_ok.connect(self._on_staged)
        self._worker.failed.connect(self._on_stage_failed)
        self._worker.start()

    def _on_stage_progress(self, done: int, total: int) -> None:
        self.progress.setRange(0, total)
        self.progress.setValue(done)

    def _on_stage_failed(self, message: str) -> None:
        self._worker = None
        self.progress.hide()
        self.busy.emit(False)
        self.toast.emit(f"Could not prepare the cursor files: {message}", "error")
        self.refresh()

    def _on_staged(self, mapping: dict, warnings: list, directory) -> None:
        self._worker = None
        self.progress.hide()
        self.busy.emit(False)
        name = self._scheme_name()

        for w in warnings[:2]:
            self.toast.emit(f"Skipped — {w}", "warn")

        if self._pending_action == "export":
            try:
                dest = library.export_scheme(name, mapping, self._export_target)
                self.toast.emit(
                    f"Exported {len(mapping)} cursors to {dest.name}", "success",)
            except Exception as exc:
                self.toast.emit(f"Export failed: {exc}", "error")
            self.refresh()
            return

        try:
            registry.apply_cursors(mapping, scheme_name=name)
        except registry.RegistryError as exc:
            self.toast.emit(f"Could not apply: {exc}", "error")
            self.refresh()
            return

        if self.save_scheme_cb.isChecked():
            try:
                registry.save_scheme(name, mapping)
            except registry.RegistryError as exc:
                self.toast.emit(f"Applied, but saving the scheme failed: {exc}",
                                "warn")

        thumb = library.write_thumbnail(mapping, directory)
        library.record_scheme(name, directory, mapping, thumb)
        self.state.last_applied_scheme = name

        self.applied.emit(name)
        self.refresh()

    def _restore(self) -> None:
        backup = registry.load_backup(original=True)
        if backup is None:
            return
        dead = sum(1 for v in backup.roles.values() if v and not Path(v).is_file())
        extra = ("\n\nNote: %d of the saved paths no longer exist on disk. "
                 "Those roles will go back to the Windows default." % dead
                 if dead else "")
        if not ConfirmDialog.ask(
                self, "Restore your previous cursors",
                f"This puts back the configuration saved on "
                f"{backup.captured.replace('T', ' ')} "
                f"(scheme “{backup.scheme_name or 'unnamed'}”).{extra}",
                "Restore"):
            return
        try:
            registry.restore_backup(original=True)
            self.toast.emit("Previous cursors restored.", "success")
        except registry.RegistryError as exc:
            self.toast.emit(f"Restore failed: {exc}", "error")
        self.refresh()

    def showEvent(self, e):
        super().showEvent(e)
        if self.state.source_folder and self.name_edit.text() == "My Cursor Set":
            self.name_edit.setText(self.state.source_folder.name[:60])
        self.refresh()
