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


class ConvertWorker(QThread):
    """Runs a format conversion off the UI thread."""

    progress = Signal(int, int)
    finished_ok = Signal(object)         # ConvertReport
    failed = Signal(str)

    def __init__(self, paths, target, out_dir, options, parent=None):
        super().__init__(parent)
        self.paths = list(paths)
        self.target = target
        self.out_dir = out_dir
        self.options = options

    def run(self) -> None:
        try:
            from ..core import converter
            report = converter.convert_files(
                self.paths, self.target, self.out_dir, self.options,
                progress=lambda d, t: self.progress.emit(d, t))
            self.finished_ok.emit(report)
        except Exception as exc:
            self.failed.emit(str(exc))


class ExtractWorker(QThread):
    """Extracts an archive, then scans the result, off the UI thread."""

    status = Signal(str)
    progress = Signal(int, int)
    finished_ok = Signal(object, object, object)   # ScanResult, label, ExtractResult
    failed = Signal(str)

    def __init__(self, archive: Path, parent=None):
        super().__init__(parent)
        self.archive = Path(archive)
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        from ..core import archives
        extracted = None
        try:
            extracted = archives.extract(
                self.archive, progress=lambda m: self.status.emit(m))
            if self._cancel:
                extracted.cleanup()
                return
            self.status.emit(f"Scanning {self.archive.name}…")
            result = scanner.scan_folder(
                extracted.directory,
                progress=lambda d, t: self.progress.emit(d, t),
                cancelled=lambda: self._cancel,
            )
            if self._cancel:
                extracted.cleanup()
                return
            # The extracted directory must outlive this worker: the scan
            # results point into it, so the caller owns cleanup from here.
            self.finished_ok.emit(result, self.archive, extracted)
        except archives.ArchiveError as exc:
            if extracted:
                extracted.cleanup()
            self.failed.emit(str(exc))
        except Exception as exc:
            if extracted:
                extracted.cleanup()
            self.failed.emit(f"could not read {self.archive.name}: {exc}")
