"""Session state shared across screens.

Holds the current scan, the role assignments, and the unassigned pool. The
one invariant enforced here: every scanned file is either assigned to exactly
one role or sitting in the pool. Nothing is ever dropped on the floor.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, Signal

from ..core import matcher
from ..core.models import (ALL_ROLES, Assignment, Confidence, CursorFile,
                           FileKind)
from ..core.scanner import ScanResult


class AppState(QObject):
    """The in-progress cursor set."""

    assignments_changed = Signal()
    scan_loaded = Signal()

    def __init__(self):
        super().__init__()
        self.source_folder: Optional[Path] = None
        self.scan: Optional[ScanResult] = None
        self.assignments: dict[str, Assignment] = {
            r.registry_name: Assignment(role=r) for r in ALL_ROLES}
        self.pool: list[CursorFile] = []
        self.by_path: dict[str, CursorFile] = {}
        self.last_applied_scheme: Optional[str] = None

    # -- lifecycle ----------------------------------------------------------
    @property
    def has_work(self) -> bool:
        return bool(self.scan and not self.scan.is_empty)

    @property
    def filled_count(self) -> int:
        return sum(1 for a in self.assignments.values() if a.filled)

    @property
    def core_filled_count(self) -> int:
        return sum(1 for a in self.assignments.values()
                   if a.filled and a.role.core)

    def load_scan(self, result: ScanResult, folder: Path) -> matcher.MatchResult:
        """Replace the session with a fresh scan and auto-match it."""
        self.scan = result
        self.source_folder = folder
        self.by_path = {str(f.path): f for f in result.all_files}

        m = matcher.match_files(result.cursors)
        self.assignments = m.assignments
        # Roles the matcher did not know about (none today, but keeps the
        # dict complete if the role table grows).
        for r in ALL_ROLES:
            self.assignments.setdefault(r.registry_name, Assignment(role=r))

        # Convertibles are never auto-assigned; they wait in the pool until
        # the user opts into converting them.
        self.pool = list(m.unassigned) + list(result.convertibles)
        self._dedupe_pool()
        self.scan_loaded.emit()
        self.assignments_changed.emit()
        return m

    def reset(self) -> None:
        self.source_folder = None
        self.scan = None
        self.assignments = {r.registry_name: Assignment(role=r) for r in ALL_ROLES}
        self.pool = []
        self.by_path = {}
        self.assignments_changed.emit()

    # -- assignment ---------------------------------------------------------
    def file_for_path(self, path: str) -> Optional[CursorFile]:
        return self.by_path.get(path)

    def assign(self, role_key: str, cf: CursorFile, *, manual: bool = True) -> None:
        """Put `cf` in `role_key`, returning whatever was there to the pool."""
        slot = self.assignments.get(role_key)
        if slot is None:
            return

        # If the file currently fills another role, vacate that one.
        for key, other in self.assignments.items():
            if key != role_key and other.file is not None and other.file.path == cf.path:
                other.clear()

        if slot.file is not None and slot.file.path != cf.path:
            self._to_pool(slot.file)

        slot.file = cf
        slot.confidence = Confidence.MANUAL if manual else slot.confidence
        slot.rivals = []
        slot.hotspot_override = None
        if cf.kind is FileKind.CONVERTIBLE:
            cf.convert_opted_in = True

        self._remove_from_pool(cf)
        self._dedupe_pool()
        self.assignments_changed.emit()

    def clear_role(self, role_key: str) -> None:
        slot = self.assignments.get(role_key)
        if slot is None or not slot.filled:
            return
        self._to_pool(slot.file)
        slot.clear()
        self.assignments_changed.emit()

    def swap(self, role_a: str, role_b: str) -> None:
        a, b = self.assignments.get(role_a), self.assignments.get(role_b)
        if a is None or b is None:
            return
        a.file, b.file = b.file, a.file
        a.confidence = Confidence.MANUAL if a.filled else Confidence.UNASSIGNED
        b.confidence = Confidence.MANUAL if b.filled else Confidence.UNASSIGNED
        a.rivals, b.rivals = [], []
        self.assignments_changed.emit()

    def drop(self, target_role: str, path: str, source: str) -> None:
        """Handle a drag from the pool or from another role slot."""
        cf = self.file_for_path(path)
        if cf is None:
            return
        if source != "@pool" and source in self.assignments:
            if self.assignments[source].filled and self.assignments[target_role].filled:
                self.swap(source, target_role)
                return
            self.assignments[source].clear()
        self.assign(target_role, cf)

    def set_hotspot(self, role_key: str, hotspot: tuple[int, int]) -> None:
        slot = self.assignments.get(role_key)
        if slot and slot.filled:
            slot.hotspot_override = hotspot
            self.assignments_changed.emit()

    # -- pool ---------------------------------------------------------------
    def _to_pool(self, cf: CursorFile) -> None:
        if all(p.path != cf.path for p in self.pool):
            self.pool.append(cf)
            self.pool.sort(key=lambda f: (not f.ok, f.name.lower()))

    def _remove_from_pool(self, cf: CursorFile) -> None:
        self.pool = [p for p in self.pool if p.path != cf.path]

    def _dedupe_pool(self) -> None:
        assigned = {str(a.file.path) for a in self.assignments.values() if a.filled}
        seen: set[str] = set()
        out: list[CursorFile] = []
        for f in self.pool:
            key = str(f.path)
            if key in assigned or key in seen:
                continue
            seen.add(key)
            out.append(f)
        self.pool = out

    # -- readiness ----------------------------------------------------------
    def apply_blockers(self) -> list[str]:
        """Reasons the current set cannot be applied yet."""
        problems: list[str] = []
        if self.filled_count == 0:
            problems.append("No roles are assigned yet.")
        missing = [a.role.display_name for a in self.assignments.values()
                   if a.role.core and not a.filled]
        if len(missing) == len(
                [r for r in ALL_ROLES if r.core]):
            problems.append("None of the core roles are filled.")
        return problems

    def missing_core_roles(self) -> list[str]:
        return [a.role.display_name for a in self.assignments.values()
                if a.role.core and not a.filled]
