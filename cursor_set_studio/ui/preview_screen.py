"""Preview screen: a small mock desktop that uses the real assigned cursors.

Hovering an element sets the actual Qt cursor to the file assigned to that
role, at its real hotspot, animating if it is an .ani. Nothing here touches
the system settings - it is the same bytes Windows would load, shown inside
the app first.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QPushButton, QScrollArea, QSizePolicy,
                               QVBoxLayout, QWidget)

from ..core.models import ALL_ROLES
from . import theme
from .state import AppState
from .widgets.badges import Pill
from .widgets.cursor_preview import AnimatedCursorLabel, LiveCursor


class HoverZone(QFrame):
    """A mock-UI element that shows one role's cursor while hovered."""

    hovered = Signal(str)                 # role key

    def __init__(self, role_key: str, live: LiveCursor, parent=None,
                 *, style: str = "", label: str = "", tag: bool = True):
        super().__init__(parent)
        self.role_key = role_key
        self._live = live
        self._base_style = style
        self.setStyleSheet(style)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        if label:
            lay = QVBoxLayout(self)
            lay.setContentsMargins(10, 8, 10, 8)
            lab = QLabel(label)
            lab.setStyleSheet("background:transparent; border:none;")
            lab.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lay.addWidget(lab)

        if tag:
            self.setToolTip(role_key)

    def enterEvent(self, e):
        self._live.enter(self)
        self.hovered.emit(self.role_key)
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._live.leave(self)
        super().leaveEvent(e)


class MockDesktop(QFrame):
    """A miniature application window, wired so each part exercises a role."""

    hovered = Signal(str)

    def __init__(self, live: LiveCursor, parent=None):
        super().__init__(parent)
        self.live = live
        self.zones: dict[str, HoverZone] = {}
        self.setObjectName("Mock")
        self.setStyleSheet(
            f"QFrame#Mock {{ background:{theme.BG_DEEP};"
            f"border:1px solid {theme.BORDER_STRONG}; border-radius:10px; }}")

        root = QVBoxLayout(self)
        root.setContentsMargins(1, 1, 1, 1)
        root.setSpacing(0)

        # --- title bar: Move ------------------------------------------------
        titlebar = self._zone(
            "SizeAll", height=34,
            style=f"background:{theme.BG_SURFACE};"
                  f"border-top-left-radius:9px; border-top-right-radius:9px;"
                  f"border-bottom:1px solid {theme.BORDER};")
        tb = QHBoxLayout(titlebar)
        tb.setContentsMargins(11, 0, 8, 0)
        tb.setSpacing(7)
        dot = QLabel("●  Sample window")
        dot.setStyleSheet(
            f"color:{theme.TEXT_MUTED}; font-size:11.5px; background:transparent;")
        tb.addWidget(dot)
        tb.addStretch(1)

        help_btn = self._zone("Help", parent_layout=None, width=22, height=22,
                              style=f"background:{theme.BG_ELEVATED};"
                                    f"border:1px solid {theme.BORDER};"
                                    f"border-radius:11px; color:{theme.TEXT_MUTED};"
                                    f"font-size:11px;", label="?")
        tb.addWidget(help_btn)
        root.addWidget(titlebar)

        # --- top resize edge: Vertical --------------------------------------
        root.addWidget(self._zone(
            "SizeNS", height=7,
            style=f"background:{theme.BG_SURFACE};"))

        # --- middle row ------------------------------------------------------
        mid = QHBoxLayout()
        mid.setContentsMargins(0, 0, 0, 0)
        mid.setSpacing(0)

        # Sidebar with a link and a disabled item
        side = QFrame()
        side.setFixedWidth(146)
        side.setStyleSheet(
            f"background:{theme.BG_SURFACE};"
            f"border-right:1px solid {theme.BORDER};")
        sl = QVBoxLayout(side)
        sl.setContentsMargins(11, 12, 11, 12)
        sl.setSpacing(8)

        link = self._zone(
            "Hand", height=26,
            style=f"background:transparent; color:{theme.ACCENT_BRIGHT};"
                  f"font-size:12px; text-decoration:underline;",
            label="A hyperlink")
        sl.addWidget(link)

        alt = self._zone(
            "UpArrow", height=26,
            style=f"background:{theme.BG_ELEVATED}; border:1px solid {theme.BORDER};"
                  f"border-radius:6px; color:{theme.TEXT_MUTED}; font-size:11.5px;",
            label="Alternate select")
        sl.addWidget(alt)

        disabled = self._zone(
            "No", height=26,
            style=f"background:{theme.BG_INPUT}; border:1px solid {theme.BORDER};"
                  f"border-radius:6px; color:{theme.TEXT_DIM}; font-size:11.5px;",
            label="Disabled action")
        sl.addWidget(disabled)

        pin = self._zone(
            "Pin", height=26,
            style=f"background:transparent; color:{theme.TEXT_DIM}; font-size:11.5px;",
            label="Location")
        sl.addWidget(pin)

        person = self._zone(
            "Person", height=26,
            style=f"background:transparent; color:{theme.TEXT_DIM}; font-size:11.5px;",
            label="Person")
        sl.addWidget(person)

        sl.addStretch(1)

        busy = self._zone(
            "Wait", height=32,
            style=f"background:{theme.ACCENT_WASH}; border-radius:6px;"
                  f"color:{theme.ACCENT_BRIGHT}; font-size:11px;",
            label="Busy area")
        sl.addWidget(busy)

        working = self._zone(
            "AppStarting", height=32,
            style=f"background:{theme.BG_ELEVATED}; border-radius:6px;"
                  f"color:{theme.TEXT_MUTED}; font-size:11px;",
            label="Launching…")
        sl.addWidget(working)

        mid.addWidget(side)

        # Vertical splitter: Horizontal resize
        mid.addWidget(self._zone(
            "SizeWE", width=7,
            style=f"background:{theme.BORDER};"))

        # Main content
        content = QFrame()
        content.setStyleSheet(f"background:{theme.BG_DEEP};")
        cl = QVBoxLayout(content)
        cl.setContentsMargins(15, 14, 15, 14)
        cl.setSpacing(11)

        text = self._zone(
            "IBeam", height=74,
            style=f"background:{theme.BG_INPUT}; border:1px solid {theme.BORDER};"
                  f"border-radius:7px; color:{theme.TEXT_MUTED};"
                  f"font-size:11.5px;",
            label="A text field — hover for Text Select")
        cl.addWidget(text)

        canvas = self._zone(
            "Crosshair", height=74,
            style=f"background:{theme.BG_SURFACE};"
                  f"border:1px dashed {theme.BORDER_STRONG};"
                  f"border-radius:7px; color:{theme.TEXT_DIM}; font-size:11.5px;",
            label="A drawing canvas — Precision Select")
        cl.addWidget(canvas)

        pen = self._zone(
            "NWPen", height=44,
            style=f"background:{theme.BG_SURFACE}; border:1px solid {theme.BORDER};"
                  f"border-radius:7px; color:{theme.TEXT_DIM}; font-size:11.5px;",
            label="Handwriting area")
        cl.addWidget(pen)

        row = QHBoxLayout()
        row.setSpacing(9)
        btn = self._zone(
            "Arrow", height=32, width=118,
            style=f"background:{theme.ACCENT}; border-radius:7px;"
                  f"color:#fff; font-size:12px; font-weight:600;",
            label="Normal Select")
        row.addWidget(btn)

        ghost = self._zone(
            "Arrow", height=32, width=92,
            style=f"background:{theme.BG_ELEVATED}; border:1px solid {theme.BORDER};"
                  f"border-radius:7px; color:{theme.TEXT}; font-size:12px;",
            label="Button", tag=False)
        row.addWidget(ghost)
        row.addStretch(1)
        cl.addLayout(row)
        cl.addStretch(1)

        mid.addWidget(content, 1)
        root.addLayout(mid, 1)

        # --- bottom edges: diagonals ----------------------------------------
        bottom = QHBoxLayout()
        bottom.setContentsMargins(0, 0, 0, 0)
        bottom.setSpacing(0)
        bottom.addWidget(self._zone(
            "SizeNESW", width=64, height=13,
            style=f"background:{theme.BG_SURFACE};"
                  f"border-bottom-left-radius:9px;"))
        bottom.addWidget(self._zone(
            "SizeNS", height=13, style=f"background:{theme.BG_SURFACE};"), 1)
        bottom.addWidget(self._zone(
            "SizeNWSE", width=64, height=13,
            style=f"background:{theme.BG_SURFACE};"
                  f"border-bottom-right-radius:9px;"))
        root.addLayout(bottom)

    def _zone(self, role_key: str, *, width: int = 0, height: int = 0,
              style: str = "", label: str = "", tag: bool = True,
              parent_layout=None) -> HoverZone:
        z = HoverZone(role_key, self.live, style=style, label=label, tag=tag)
        if width:
            z.setFixedWidth(width)
        if height:
            z.setFixedHeight(height)
        z.hovered.connect(self.hovered.emit)
        # Several zones can share a role (two buttons both use Arrow); keep
        # the first for the legend, but bind them all.
        self.zones.setdefault(role_key, z)
        self._all_zones = getattr(self, "_all_zones", [])
        self._all_zones.append(z)
        return z

    def bind_all(self, state: AppState) -> None:
        for z in getattr(self, "_all_zones", []):
            slot = state.assignments.get(z.role_key)
            self.live.bind(z, slot.file if slot and slot.filled else None)


class PreviewScreen(QWidget):
    """Try the set before installing it."""

    proceed = Signal()
    back = Signal()

    def __init__(self, state: AppState, parent=None):
        super().__init__(parent)
        self.state = state
        self.setObjectName("Screen")
        self.live = LiveCursor(self)
        self._role_rows: dict[str, tuple[AnimatedCursorLabel, QLabel, Pill]] = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 22, 28, 20)
        outer.setSpacing(14)

        head = QHBoxLayout()
        col = QVBoxLayout()
        col.setSpacing(2)
        t = QLabel("Try it out")
        t.setObjectName("H1")
        col.addWidget(t)
        s = QLabel("Hover the mock window below. Each element uses the cursor "
                   "you assigned to that role, at its real hotspot — nothing "
                   "has been installed yet.")
        s.setObjectName("Sub")
        s.setWordWrap(True)
        col.addWidget(s)
        head.addLayout(col, 1)

        back = QPushButton("←  Back to review")
        back.setObjectName("Ghost")
        back.setCursor(Qt.CursorShape.PointingHandCursor)
        back.clicked.connect(self.back.emit)
        head.addWidget(back)

        nxt = QPushButton("Install  →")
        nxt.setObjectName("Primary")
        nxt.setCursor(Qt.CursorShape.PointingHandCursor)
        nxt.clicked.connect(self.proceed.emit)
        head.addWidget(nxt)
        outer.addLayout(head)

        body = QHBoxLayout()
        body.setSpacing(14)

        self.mock = MockDesktop(self.live)
        self.mock.hovered.connect(self._on_hover)
        self.mock.setMinimumWidth(430)
        body.addWidget(self.mock, 1)

        # Legend: every role, its cursor, and whether it is covered.
        legend = QFrame()
        legend.setObjectName("Panel")
        legend.setFixedWidth(258)
        ll = QVBoxLayout(legend)
        ll.setContentsMargins(13, 13, 13, 13)
        ll.setSpacing(8)

        lh = QLabel("The full set")
        lh.setObjectName("H2")
        ll.addWidget(lh)

        self.hover_label = QLabel("Hover the mock window →")
        self.hover_label.setObjectName("Dim")
        self.hover_label.setWordWrap(True)
        ll.addWidget(self.hover_label)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QWidget()
        self.legend_lay = QVBoxLayout(inner)
        self.legend_lay.setContentsMargins(0, 0, 6, 0)
        self.legend_lay.setSpacing(4)

        for r in ALL_ROLES:
            row = QFrame()
            rl = QHBoxLayout(row)
            rl.setContentsMargins(4, 3, 4, 3)
            rl.setSpacing(9)
            prev = AnimatedCursorLabel(28)
            rl.addWidget(prev)
            name = QLabel(r.display_name)
            name.setStyleSheet(f"font-size:11.5px; color:{theme.TEXT};")
            rl.addWidget(name, 1)
            pill = Pill("—", theme.IDLE, theme.IDLE_WASH)
            rl.addWidget(pill)
            self.legend_lay.addWidget(row)
            self._role_rows[r.registry_name] = (prev, name, pill)

        self.legend_lay.addStretch(1)
        scroll.setWidget(inner)
        ll.addWidget(scroll, 1)
        body.addWidget(legend)

        outer.addLayout(body, 1)
        state.assignments_changed.connect(self.refresh)

    def refresh(self) -> None:
        self.mock.bind_all(self.state)
        for key, (prev, name, pill) in self._role_rows.items():
            slot = self.state.assignments[key]
            prev.set_file(slot.file)
            if slot.filled:
                pill.apply("SET", theme.OK, theme.OK_WASH)
                name.setStyleSheet(f"font-size:11.5px; color:{theme.TEXT};")
            else:
                pill.apply("—", theme.IDLE, theme.IDLE_WASH)
                name.setStyleSheet(f"font-size:11.5px; color:{theme.TEXT_DIM};")

    def _on_hover(self, role_key: str) -> None:
        slot = self.state.assignments.get(role_key)
        if slot and slot.filled:
            self.hover_label.setText(
                f"{slot.role.display_name}  ·  {slot.file.name}")
        else:
            self.hover_label.setText(
                f"{role_key} — not assigned, so Windows keeps its current cursor here.")

    def showEvent(self, e):
        super().showEvent(e)
        self.refresh()
