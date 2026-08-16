"""Review screen: the auto-match grid, and the pool of everything else."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QScrollArea, QSizePolicy,
                               QVBoxLayout, QWidget, QGridLayout)

from ..core.models import ALL_ROLES, Confidence, FileKind
from . import theme
from .dialogs import FilePickerDialog, HotspotDialog
from .state import AppState
from .util import clear_layout
from .widgets.badges import Pill
from .widgets.file_chip import FileChip, POOL_SOURCE, read_payload
from .widgets.role_card import RoleCard

CARD_MIN_WIDTH = 224
CARD_GAP = 12


class PoolPanel(QFrame):
    """Everything not currently assigned to a role."""

    file_activated = Signal(object)      # CursorFile

    def __init__(self, state: AppState, parent=None):
        super().__init__(parent)
        self.state = state
        self.setObjectName("Panel")
        self.setFixedWidth(272)
        self.setAcceptDrops(True)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(13, 13, 13, 13)
        lay.setSpacing(9)

        head = QHBoxLayout()
        title = QLabel("Unassigned")
        title.setObjectName("H2")
        head.addWidget(title)
        head.addStretch(1)
        self.count = Pill("0", theme.TEXT_MUTED, theme.IDLE_WASH)
        head.addWidget(self.count)
        lay.addLayout(head)

        note = QLabel("Every scanned file lives here until you place it. "
                      "Drag one onto a role, or drag a role back here.")
        note.setObjectName("Dim")
        note.setWordWrap(True)
        lay.addWidget(note)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter…")
        self.search.textChanged.connect(self.refresh)
        lay.addWidget(self.search)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.inner = QWidget()
        self.inner_lay = QVBoxLayout(self.inner)
        self.inner_lay.setContentsMargins(0, 0, 6, 0)
        self.inner_lay.setSpacing(6)
        self.inner_lay.addStretch(1)
        scroll.setWidget(self.inner)
        lay.addWidget(scroll, 1)

        self.empty = QLabel("Nothing left over — every file found a role.")
        self.empty.setObjectName("Dim")
        self.empty.setWordWrap(True)
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.empty)

    def refresh(self) -> None:
        needle = self.search.text().lower().strip()

        clear_layout(self.inner_lay, keep_trailing=1)

        shown = 0
        for cf in self.state.pool:
            if needle and needle not in cf.name.lower():
                continue
            chip = FileChip(cf)
            chip.double_clicked.connect(self.file_activated.emit)
            self.inner_lay.insertWidget(shown, chip)
            shown += 1

        total = len(self.state.pool)
        self.count.apply(str(total), theme.TEXT_MUTED, theme.IDLE_WASH)
        self.empty.setVisible(total == 0)
        if total and not shown:
            self.empty.setText("No file matches that filter.")
            self.empty.show()
        elif total == 0:
            self.empty.setText("Nothing left over — every file found a role.")

    # Dropping a role card here returns that cursor to the pool.
    def dragEnterEvent(self, e):
        payload = read_payload(e.mimeData())
        if payload and payload[1] != POOL_SOURCE:
            self.setStyleSheet(
                f"QFrame#Panel {{ background:{theme.BG_SURFACE};"
                f"border:1.5px solid {theme.ACCENT};"
                f"border-radius:{theme.RADIUS}px; }}")
            e.acceptProposedAction()

    def dragLeaveEvent(self, e):
        self.setStyleSheet("")

    def dropEvent(self, e):
        self.setStyleSheet("")
        payload = read_payload(e.mimeData())
        if payload and payload[1] != POOL_SOURCE:
            self.state.clear_role(payload[1])
            e.acceptProposedAction()


class ReviewScreen(QWidget):
    """The 15+ role slots, with everything the matcher could not place."""

    proceed = Signal()
    rescan_requested = Signal()

    def __init__(self, state: AppState, parent=None):
        super().__init__(parent)
        self.state = state
        self.setObjectName("Screen")
        self.cards: dict[str, RoleCard] = {}
        self._columns = 0

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 22, 28, 20)
        outer.setSpacing(14)

        # -- header ---------------------------------------------------------
        head = QHBoxLayout()
        col = QVBoxLayout()
        col.setSpacing(2)
        title = QLabel("Review the matches")
        title.setObjectName("H1")
        col.addWidget(title)
        self.summary = QLabel("")
        self.summary.setObjectName("Sub")
        col.addWidget(self.summary)
        head.addLayout(col)
        head.addStretch(1)

        self.stat_ok = Pill("0 matched", theme.OK, theme.OK_WASH)
        self.stat_warn = Pill("0 to check", theme.WARN, theme.WARN_WASH)
        self.stat_empty = Pill("0 empty", theme.IDLE, theme.IDLE_WASH)
        for s in (self.stat_ok, self.stat_warn, self.stat_empty):
            head.addWidget(s)

        head.addSpacing(8)
        rescan = QPushButton("Import another folder")
        rescan.setObjectName("Ghost")
        rescan.setCursor(Qt.CursorShape.PointingHandCursor)
        rescan.clicked.connect(self.rescan_requested.emit)
        head.addWidget(rescan)

        self.next_btn = QPushButton("Preview  →")
        self.next_btn.setObjectName("Primary")
        self.next_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.next_btn.clicked.connect(self.proceed.emit)
        head.addWidget(self.next_btn)
        outer.addLayout(head)

        # -- body -----------------------------------------------------------
        body = QHBoxLayout()
        body.setSpacing(14)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.grid_host = QWidget()
        self.grid = QGridLayout(self.grid_host)
        self.grid.setContentsMargins(0, 0, 8, 0)
        self.grid.setSpacing(CARD_GAP)
        self.scroll.setWidget(self.grid_host)
        body.addWidget(self.scroll, 1)

        self.pool = PoolPanel(state)
        self.pool.file_activated.connect(self._quick_assign)
        body.addWidget(self.pool)

        outer.addLayout(body, 1)

        self._build_cards()
        state.assignments_changed.connect(self.refresh)

    # -- construction -------------------------------------------------------
    def _build_cards(self) -> None:
        for r in ALL_ROLES:
            card = RoleCard(self.state.assignments[r.registry_name])
            card.file_dropped.connect(self._on_drop)
            card.cleared.connect(self.state.clear_role)
            card.reassign_requested.connect(self._open_picker)
            card.hotspot_requested.connect(self._open_hotspot)
            self.cards[r.registry_name] = card
        self._relayout(force=True)

    def _available_width(self) -> int:
        # Derived from the screen's own width rather than the scroll
        # viewport's: during __init__ the viewport has not been laid out yet
        # and reports a placeholder size.
        return (self.width() - 2 * 28            # screen margins
                - self.pool.width() - 14         # pool panel and its spacing
                - 16)                            # scrollbar gutter

    def _relayout(self, force: bool = False) -> None:
        width = max(self._available_width(), CARD_MIN_WIDTH)
        cols = max(1, (width + CARD_GAP) // (CARD_MIN_WIDTH + CARD_GAP))
        if cols == self._columns and not force:
            return
        self._columns = cols

        while self.grid.count():
            self.grid.takeAt(0)

        for i, r in enumerate(ALL_ROLES):
            self.grid.addWidget(self.cards[r.registry_name], i // cols, i % cols)
        for c in range(cols):
            self.grid.setColumnStretch(c, 1)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._relayout()

    def showEvent(self, e):
        super().showEvent(e)
        self._relayout(force=True)

    # -- state --------------------------------------------------------------
    def refresh(self) -> None:
        for key, card in self.cards.items():
            card.assignment = self.state.assignments[key]
            card.refresh()
        self.pool.refresh()

        ok = sum(1 for a in self.state.assignments.values()
                 if a.confidence in (Confidence.HIGH, Confidence.MANUAL))
        warn = sum(1 for a in self.state.assignments.values()
                   if a.confidence is Confidence.LOW)
        empty = sum(1 for a in self.state.assignments.values() if not a.filled)

        self.stat_ok.apply(f"{ok} SET",
                           theme.OK if ok else theme.IDLE,
                           theme.OK_WASH if ok else theme.IDLE_WASH)
        self.stat_warn.apply(f"{warn} TO CHECK",
                             theme.WARN if warn else theme.IDLE,
                             theme.WARN_WASH if warn else theme.IDLE_WASH)
        self.stat_empty.apply(f"{empty} EMPTY", theme.IDLE, theme.IDLE_WASH)

        core = self.state.core_filled_count
        total_files = len(self.state.scan.all_files) if self.state.scan else 0
        self.summary.setText(
            f"{core} of 15 core roles filled  ·  {total_files} files scanned")
        self.next_btn.setEnabled(self.state.filled_count > 0)

    # -- interactions -------------------------------------------------------
    def _on_drop(self, role_key: str, path: str, source: str) -> None:
        self.state.drop(role_key, path, source)

    def _open_picker(self, role_key: str) -> None:
        slot = self.state.assignments[role_key]
        candidates = list(self.state.pool)
        if slot.filled:
            candidates.insert(0, slot.file)
        # Files sitting in other roles are fair game too.
        for key, other in self.state.assignments.items():
            if key != role_key and other.filled:
                candidates.append(other.file)

        if not candidates:
            return
        d = FilePickerDialog(slot.role, candidates, self, slot.file)
        if d.exec() and d.selected is not None:
            self.state.assign(role_key, d.selected)

    def _open_hotspot(self, role_key: str) -> None:
        slot = self.state.assignments[role_key]
        if not slot.filled:
            self._open_picker(role_key)
            return
        d = HotspotDialog(slot.file, slot.role, slot.hotspot_override, self)
        if d.exec():
            self.state.set_hotspot(role_key, d.hotspot)

    def _quick_assign(self, cf) -> None:
        """Double-clicking a pool file offers it to its best-scoring role."""
        from ..core import matcher
        ranked = matcher.best_roles_for(cf, limit=1)
        if ranked:
            self.state.assign(ranked[0][0].registry_name, cf)
        else:
            # No opinion: let the user choose.
            empty = [k for k, a in self.state.assignments.items() if not a.filled]
            if empty:
                self._open_picker(empty[0])
