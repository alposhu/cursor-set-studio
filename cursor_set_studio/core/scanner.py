"""Folder scanning: find cursor files, filter junk, detect frame sequences."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Optional

from . import cursor_io
from .models import (CONVERTIBLE_EXTENSIONS, CURSOR_EXTENSIONS, CursorFile,
                     FileKind)

# Files whose names say they are documentation or packaging, not cursors.
JUNK_STEM_WORDS = {
    "readme", "read me", "license", "licence", "copying", "changelog",
    "preview", "screenshot", "screen shot", "banner", "thumbs", "thumb",
    "desktop", "folder", "install", "credits", "info", "about", "sample",
}
JUNK_EXACT_NAMES = {"desktop.ini", "thumbs.db", "folder.ico", "install.inf"}

# Directories never worth walking into.
SKIP_DIRS = {".git", ".svn", "__pycache__", "$recycle.bin",
             "system volume information", "node_modules"}

# A trailing frame number, with or without a separator: busy_01, busy-2, busy3.
_FRAME_RE = re.compile(r"^(?P<base>.*?)[ _\-.]?(?P<num>\d{1,4})$")

# Bases where a trailing digit distinguishes two different roles rather than
# two frames of one animation. Without this, diagonal1 + diagonal2 would be
# merged into a bogus two-frame animation instead of mapping to SizeNWSE and
# SizeNESW.
_NOT_SEQUENCE_BASES = {
    "diagonal", "diag", "diagonalresize", "resizediagonal", "d",
    "size", "sizediag", "arrow", "cursor",
}

# A real animation ships at least this many frames. Requiring three also keeps
# innocent pairs (foo1/foo2) from being merged.
MIN_SEQUENCE_FRAMES = 3


@dataclass
class ScanResult:
    cursors: list[CursorFile] = field(default_factory=list)      # .cur / .ani
    convertibles: list[CursorFile] = field(default_factory=list)  # .png / .ico
    errors: list[tuple[Path, str]] = field(default_factory=list)
    skipped_junk: int = 0
    total_seen: int = 0

    @property
    def all_files(self) -> list[CursorFile]:
        return self.cursors + self.convertibles

    @property
    def is_empty(self) -> bool:
        return not self.cursors and not self.convertibles


def _is_junk(path: Path) -> bool:
    if path.name.lower() in JUNK_EXACT_NAMES:
        return True
    stem = path.stem.lower().strip()
    if stem in JUNK_STEM_WORDS:
        return True
    # Only treat a junk word as decisive when it leads the name, so that a
    # legitimate cursor like "info_pointer.cur" survives.
    return any(stem.startswith(w) and len(stem) <= len(w) + 3
               for w in JUNK_STEM_WORDS)


def _walk(root: Path, cancelled: Optional[Callable[[], bool]] = None) -> Iterable[Path]:
    """Yield candidate files, skipping junk directories and unreadable ones."""
    stack = [root]
    while stack:
        if cancelled and cancelled():
            return
        current = stack.pop()
        try:
            entries = list(current.iterdir())
        except (OSError, PermissionError):
            continue
        for entry in entries:
            try:
                if entry.is_dir():
                    if entry.name.lower() not in SKIP_DIRS:
                        stack.append(entry)
                elif entry.is_file():
                    yield entry
            except OSError:
                continue


def _split_frame_number(stem: str) -> tuple[str, Optional[int]]:
    """Split 'busy_01' into ('busy', 1). Returns (stem, None) when there is
    no trailing number."""
    m = _FRAME_RE.match(stem)
    if not m:
        return stem, None
    base = m.group("base").rstrip(" _-.")
    if not base:
        return stem, None
    return base, int(m.group("num"))


def group_sequences(files: list[CursorFile]) -> list[CursorFile]:
    """Collapse runs of numbered frame files into single animation candidates.

    Returns a new list in which each detected run is represented by one
    CursorFile carrying the whole run in `sequence_paths`.
    """
    buckets: dict[tuple[Path, str, str], list[tuple[int, CursorFile]]] = {}
    loose: list[CursorFile] = []

    for f in files:
        base, num = _split_frame_number(f.stem)
        if num is None or base.lower() in _NOT_SEQUENCE_BASES:
            loose.append(f)
            continue
        key = (f.path.parent, base.lower(), f.path.suffix.lower())
        buckets.setdefault(key, []).append((num, f))

    out: list[CursorFile] = list(loose)

    for (parent, base, _ext), members in buckets.items():
        if len(members) < MIN_SEQUENCE_FRAMES:
            out.extend(f for _, f in members)      # too few: keep separate
            continue

        members.sort(key=lambda pair: pair[0])
        numbers = [n for n, _ in members]
        span = numbers[-1] - numbers[0] + 1
        # Require a mostly-contiguous run, so unrelated files that happen to
        # end in digits are not welded together.
        if span > len(numbers) * 2:
            out.extend(f for _, f in members)
            continue

        first = members[0][1]
        combined = CursorFile(
            path=first.path,
            kind=first.kind,
            width=first.width,
            height=first.height,
            hotspot=first.hotspot,
            frame_count=len(members),
            sequence_paths=[f.path for _, f in members],
        )
        # Present the run under its base name rather than the first frame's.
        combined.sequence_base = base                     # type: ignore[attr-defined]
        out.append(combined)

    return out


def scan_folder(
    root: Path,
    *,
    progress: Optional[Callable[[int, int], None]] = None,
    cancelled: Optional[Callable[[], bool]] = None,
    detect_sequences: bool = True,
) -> ScanResult:
    """Recursively scan `root` for cursor files.

    A file that fails to parse is recorded in `result.errors` and skipped;
    it never aborts the scan.
    """
    root = Path(root)
    result = ScanResult()

    candidates: list[Path] = []
    for path in _walk(root, cancelled):
        ext = path.suffix.lower()
        if ext not in CURSOR_EXTENSIONS and ext not in CONVERTIBLE_EXTENSIONS:
            continue
        result.total_seen += 1
        if _is_junk(path):
            result.skipped_junk += 1
            continue
        candidates.append(path)

    total = len(candidates)
    cursors: list[CursorFile] = []
    convertibles: list[CursorFile] = []

    for i, path in enumerate(candidates):
        if cancelled and cancelled():
            break
        ext = path.suffix.lower()
        kind = (FileKind.ANIMATED if ext == ".ani"
                else FileKind.STATIC if ext == ".cur"
                else FileKind.CONVERTIBLE)

        cf = CursorFile(path=path, kind=kind)
        try:
            info = cursor_io.probe(path)
            cf.width, cf.height = info.width, info.height
            cf.hotspot = info.hotspot
            cf.frame_count = info.frame_count
        except cursor_io.CursorFormatError as exc:
            cf.error = str(exc)
            result.errors.append((path, str(exc)))
        except Exception as exc:            # never let one odd file kill a scan
            cf.error = f"unexpected error: {exc}"
            result.errors.append((path, cf.error))

        (cursors if kind is not FileKind.CONVERTIBLE else convertibles).append(cf)

        if progress:
            progress(i + 1, total)

    if detect_sequences:
        cursors = group_sequences(cursors)
        convertibles = group_sequences(convertibles)

    # Files that failed to parse still belong in the pool so the user can see
    # them, but they sort last.
    result.cursors = sorted(cursors, key=lambda f: (not f.ok, f.path.name.lower()))
    result.convertibles = sorted(convertibles,
                                 key=lambda f: (not f.ok, f.path.name.lower()))
    return result
