"""The application shell: frameless window, navigation, screen transitions."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import (QEasingCurve, QPropertyAnimation, Qt, QTimer)
from PySide6.QtWidgets import (QApplication, QButtonGroup, QFrame,
                               QGraphicsOpacityEffect, QHBoxLayout, QLabel,
                               QPushButton, QStackedWidget, QVBoxLayout,
                               QWidget)

from ..core import registry
from . import theme
from .apply_screen import ApplyScreen
from .convert_screen import ConvertScreen
from .dialogs import ConfirmDialog
from .import_screen import ImportScreen
from .library_screen import LibraryScreen
from .preview_screen import PreviewScreen
from .review_screen import ReviewScreen
from .resources import app_icon
from .state import AppState
from .widgets.title_bar import ResizeMixin, TitleBar
from .widgets.toast import ToastHost
from .workers import ExtractWorker, ScanWorker

IMPORT, REVIEW, PREVIEW, APPLY, LIBRARY, CONVERT = range(6)

STEPS = [
    (IMPORT, "1", "Import"),
    (REVIEW, "2", "Review"),
    (PREVIEW, "3", "Preview"),
    (APPLY, "4", "Install"),
]


class MainWindow(QWidget, ResizeMixin):
    """Frameless main window holding the five screens."""

    def __init__(self):
        super().__init__()
        self.state = AppState()
        self._scan_worker: ScanWorker | None = None
        self._fade: QPropertyAnimation | None = None
        self._extracted = None      # temp dir from an archive import

        self.setWindowTitle("Cursor Set Studio")
        # Set on the window too, not just the application: the window is
        # frameless, and this is what the taskbar entry picks up.
        self.setWindowIcon(app_icon())
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint |
                            Qt.WindowType.Window)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMinimumSize(1000, 660)
        self.resize(1220, 780)
        self.setMouseTracking(True)

        shell = QVBoxLayout(self)
        shell.setContentsMargins(0, 0, 0, 0)

        self.root = QWidget()
        self.root.setObjectName("Root")
        self.root.setMouseTracking(True)
        shell.addWidget(self.root)

        root_lay = QVBoxLayout(self.root)
        root_lay.setContentsMargins(0, 0, 0, 0)
        root_lay.setSpacing(0)

        # -- title bar -------------------------------------------------------
        self.title_bar = TitleBar("Cursor Set Studio")
        self.title_bar.minimise_clicked.connect(self.showMinimized)
        self.title_bar.maximise_clicked.connect(self._toggle_max)
        self.title_bar.close_clicked.connect(self.close)
        root_lay.addWidget(self.title_bar)

        # -- body: nav rail + screens ----------------------------------------
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        self.nav = self._build_nav()
        body.addWidget(self.nav)

        self.stack = QStackedWidget()
        self.stack.setMouseTracking(True)

        self.import_screen = ImportScreen()
        self.review_screen = ReviewScreen(self.state)
        self.preview_screen = PreviewScreen(self.state)
        self.apply_screen = ApplyScreen(self.state)
        self.library_screen = LibraryScreen()
        self.convert_screen = ConvertScreen()

        for w in (self.import_screen, self.review_screen, self.preview_screen,
                  self.apply_screen, self.library_screen, self.convert_screen):
            self.stack.addWidget(w)

        body.addWidget(self.stack, 1)
        root_lay.addLayout(body, 1)

        self.toasts = ToastHost(self)

        # -- wiring ----------------------------------------------------------
        self.import_screen.folder_chosen.connect(self._begin_scan)
        self.import_screen.cancel_requested.connect(self._cancel_scan)

        self.review_screen.proceed.connect(lambda: self.go(PREVIEW))
        self.review_screen.rescan_requested.connect(self._reimport)

        self.preview_screen.back.connect(lambda: self.go(REVIEW))
        self.preview_screen.proceed.connect(lambda: self.go(APPLY))

        self.apply_screen.back.connect(lambda: self.go(PREVIEW))
        self.apply_screen.toast.connect(
            lambda msg, kind: self.toasts.show(msg, kind))
        self.apply_screen.applied.connect(self._on_applied)
        self.apply_screen.open_library.connect(lambda: self.go(LIBRARY))

        self.library_screen.toast.connect(
            lambda msg, kind: self.toasts.show(msg, kind))
        self.library_screen.back.connect(
            lambda: self.go(APPLY if self.state.has_work else IMPORT))
        self.convert_screen.toast.connect(
            lambda msg, kind: self.toasts.show(msg, kind))

        self.state.assignments_changed.connect(self._update_nav)

        self.go(IMPORT, animate=False)
        self._update_nav()

    # -- navigation ---------------------------------------------------------
    def _build_nav(self) -> QWidget:
        rail = QFrame()
        rail.setObjectName("NavRail")
        rail.setFixedWidth(178)
        lay = QVBoxLayout(rail)
        lay.setContentsMargins(11, 6, 11, 12)
        lay.setSpacing(3)

        head = QLabel("WORKFLOW")
        head.setObjectName("NavStep")
        lay.addWidget(head)

        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        self.nav_buttons: dict[int, QPushButton] = {}

        for index, num, label in STEPS:
            b = QPushButton(f"{num}   {label}")
            b.setObjectName("NavItem")
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, i=index: self.go(i))
            self.nav_group.addButton(b)
            self.nav_buttons[index] = b
            lay.addWidget(b)

        lay.addStretch(1)

        head2 = QLabel("LIBRARY")
        head2.setObjectName("NavStep")
        lay.addWidget(head2)

        lib = QPushButton("◆   Saved schemes")
        lib.setObjectName("NavItem")
        lib.setCheckable(True)
        lib.setCursor(Qt.CursorShape.PointingHandCursor)
        lib.clicked.connect(lambda: self.go(LIBRARY))
        self.nav_group.addButton(lib)
        self.nav_buttons[LIBRARY] = lib
        lay.addWidget(lib)

        conv = QPushButton("⇄   Convert files")
        conv.setObjectName("NavItem")
        conv.setCheckable(True)
        conv.setCursor(Qt.CursorShape.PointingHandCursor)
        conv.clicked.connect(lambda: self.go(CONVERT))
        self.nav_group.addButton(conv)
        self.nav_buttons[CONVERT] = conv
        lay.addWidget(conv)

        credit = QLabel("Cursor Set Studio v1.1<br>by Alperen Karabıyık")
        credit.setObjectName("Dim")
        credit.setTextFormat(Qt.TextFormat.RichText)
        credit.setStyleSheet(
            f"color:{theme.TEXT_DIM}; font-size:10px; padding:10px 4px 0 4px;")
        lay.addWidget(credit)

        return rail

    def go(self, index: int, *, animate: bool = True) -> None:
        if index in (REVIEW, PREVIEW, APPLY) and not self.state.has_work:
            # Fall back to Import rather than merely refusing: the user may
            # already be sitting on a screen whose data has just been cleared.
            if self.stack.currentIndex() != IMPORT:
                self.stack.setCurrentIndex(IMPORT)
                self.title_bar.set_subtitle("")
            self.toasts.show("Import a folder of cursors first.", "info")
            self._update_nav()
            return

        if self.stack.currentIndex() == index:
            self._update_nav()
            return

        self.stack.setCurrentIndex(index)
        if animate:
            self._fade_in(self.stack.currentWidget())
        self._update_nav()

        subtitle = {
            IMPORT: "", REVIEW: "Step 2 of 4", PREVIEW: "Step 3 of 4",
            APPLY: "Step 4 of 4", LIBRARY: "Library",
            CONVERT: "Converter",
        }[index]
        if index == REVIEW and self.state.source_folder:
            subtitle = f"Step 2 of 4  ·  {self.state.source_folder.name}"
        self.title_bar.set_subtitle(subtitle)

    def _fade_in(self, widget: QWidget) -> None:
        effect = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(effect)
        anim = QPropertyAnimation(effect, b"opacity", self)
        anim.setDuration(190)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        # Drop the effect afterwards so it never interferes with painting.
        anim.finished.connect(lambda: widget.setGraphicsEffect(None))
        anim.start()
        self._fade = anim

    def _update_nav(self) -> None:
        current = self.stack.currentIndex()
        if current in (REVIEW, PREVIEW, APPLY) and not self.state.has_work:
            self.stack.setCurrentIndex(IMPORT)
            self.title_bar.set_subtitle("")
            current = IMPORT
        for index, button in self.nav_buttons.items():
            button.setChecked(index == current)
            if index in (REVIEW, PREVIEW, APPLY):
                button.setEnabled(self.state.has_work)

        if self.state.has_work:
            self.nav_buttons[REVIEW].setText(
                f"2   Review   ({self.state.filled_count})")
        else:
            self.nav_buttons[REVIEW].setText("2   Review")

    # -- scanning -----------------------------------------------------------
    def _reimport(self) -> None:
        self.go(IMPORT)

    def _begin_scan(self, folder: Path) -> None:
        if self.state.has_work:
            if not ConfirmDialog.ask(
                    self, "Replace the current set?",
                    f"You have {self.state.filled_count} role(s) assigned from "
                    f"“{self.state.source_folder.name if self.state.source_folder else 'a previous scan'}”.\n\n"
                    f"Importing “{folder.name}” discards those assignments.",
                    "Import and replace"):
                return

        if self._scan_worker is not None:
            return

        from ..core import archives
        self.import_screen.start_progress(folder)

        if folder.is_file() and archives.is_archive(folder):
            worker = ExtractWorker(folder, self)
            worker.status.connect(self.import_screen.set_status)
            worker.progress.connect(self.import_screen.update_progress)
            worker.finished_ok.connect(self._on_archive_scanned)
            worker.failed.connect(self._on_scan_failed)
        else:
            worker = ScanWorker(folder, self)
            worker.progress.connect(self.import_screen.update_progress)
            worker.finished_ok.connect(self._on_scanned)
            worker.failed.connect(self._on_scan_failed)

        worker.finished.connect(self._clear_worker)
        self._scan_worker = worker
        worker.start()

    def _on_archive_scanned(self, result, archive, extracted) -> None:
        """An archive finished extracting and scanning.

        The scan points at files inside the extracted directory, so that
        directory has to outlive the import. It is released when the next
        import replaces it, or when the window closes.
        """
        self._release_extraction()
        self._extracted = extracted
        self._on_scanned(result, Path(archive))
        if result.is_empty:
            self._release_extraction()

    def _release_extraction(self) -> None:
        extracted = getattr(self, "_extracted", None)
        if extracted is not None:
            extracted.cleanup()
            self._extracted = None

    def _cancel_scan(self) -> None:
        if self._scan_worker is not None:
            self._scan_worker.cancel()
            self.import_screen.stop_progress()
            self.toasts.show("Scan cancelled.", "info")

    def _clear_worker(self) -> None:
        self._scan_worker = None
        self.import_screen.stop_progress()

    def _on_scan_failed(self, message: str) -> None:
        self.import_screen.stop_progress()
        self.toasts.show(f"Could not scan that folder: {message}", "error")

    def _on_scanned(self, result, folder: Path) -> None:
        from .widgets.cursor_preview import clear_cache
        clear_cache()
        self.import_screen.stop_progress()

        if result.is_empty:
            self.toasts.show(
                f"No cursor files found in “{folder.name}”. "
                f"Cursor Set Studio looks for .cur and .ani files.",
                "warn", duration=6000)
            return

        match = self.state.load_scan(result, folder)

        confident = match.confident_count
        total_roles = match.matched_count
        message = (f"{total_roles} of 17 roles matched automatically"
                   + (f", {confident} with high confidence" if confident else "")
                   + ".")
        kind = "success" if total_roles >= 10 else "info"

        if result.errors:
            self.toasts.show(
                f"{len(result.errors)} file(s) could not be read and are "
                f"marked in the pool.", "warn")
        if result.convertibles:
            self.toasts.show(
                f"{len(result.convertibles)} image file(s) found. They are in "
                f"the pool, ready to convert if you want them.", "info")

        self.toasts.show(message, kind)
        self.go(REVIEW)

    # -- apply --------------------------------------------------------------
    def _on_applied(self, name: str) -> None:
        self.toasts.show(
            f"“{name}” applied. Your cursors changed just now — no sign-out "
            f"needed.", "success",
            action=("Undo", self._undo_apply), duration=7000)

    def _undo_apply(self) -> None:
        try:
            registry.restore_backup(original=False)
            self.toasts.show("Reverted to your previous cursors.", "info")
        except registry.RegistryError as exc:
            self.toasts.show(f"Could not revert: {exc}", "error")

    # -- window chrome ------------------------------------------------------
    def _toggle_max(self) -> None:
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def mousePressEvent(self, e):
        if not self.handle_resize_press(e):
            super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if not self.handle_resize_move(e):
            super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        self.handle_resize_release()
        super().mouseReleaseEvent(e)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        # Keep the toast stack pinned to the bottom-right corner.
        if hasattr(self, "_toasts"):
            self._reflow()

    def closeEvent(self, e):
        if self._scan_worker is not None:
            self._scan_worker.cancel()
            self._scan_worker.wait(1500)
        self._release_extraction()
        super().closeEvent(e)
