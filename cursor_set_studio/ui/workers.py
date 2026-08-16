"""Background workers, so the window never freezes on a big folder."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, QThread, Signal

from ..core import library, scanner
from ..core.scanner import ScanResult


class ScanWorker(QThread):
    """Scans a folder off the UI thread."""

    progress = Signal(int, int)          # done, total
    finished_ok = Signal(object, object)  # ScanResult, Path
    failed = Signal(str)

    def __init__(self, folder: Path, parent=None):
        super().__init__(parent)
        self.folder = Path(folder)
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        try:
            result: ScanResult = scanner.scan_folder(
                self.folder,
                progress=lambda d, t: self.progress.emit(d, t),
                cancelled=lambda: self._cancel,
            )
            if not self._cancel:
                self.finished_ok.emit(result, self.folder)
        except Exception as exc:
            self.failed.emit(str(exc))


class StageWorker(QThread):
    """Copies the chosen cursors into managed storage off the UI thread."""

    progress = Signal(int, int)
    finished_ok = Signal(object, object, object)   # mapping, warnings, directory
    failed = Signal(str)

    def __init__(self, name: str, assignments, frame_jiffies: int = 6, parent=None):
        super().__init__(parent)
        self.name = name
        self.assignments = list(assignments)
        self.frame_jiffies = frame_jiffies

    def run(self) -> None:
        try:
            directory = library.unique_dir(self.name)
            mapping, warnings = library.stage_scheme(
                self.name, self.assignments,
                target_dir=directory,
                frame_jiffies=self.frame_jiffies,
                progress=lambda d, t: self.progress.emit(d, t),
            )
            self.finished_ok.emit(mapping, warnings, directory)
        except Exception as exc:
            self.failed.emit(str(exc))
