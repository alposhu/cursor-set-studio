"""Convert screen: a standalone tool for moving between the four formats."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QFileDialog,
                               QFrame, QHBoxLayout, QLabel, QProgressBar,
                               QPushButton, QScrollArea, QSlider, QVBoxLayout,
                               QWidget)

from ..core import cursor_io
from ..core.converter import ConvertOptions, Target
from ..core.models import CursorFile, FileKind
from . import theme
from .util import clear_layout
from .widgets.badges import KindPill, Pill
from .widgets.cursor_preview import AnimatedCursorLabel

SIZE_PRESETS = {
    "Keep original": None,
    "32 px": (32,),
    "48 px": (48,),
    "64 px": (64,),
    "All sizes (16-128)": (16, 24, 32, 48, 64, 96, 128),
}

HOTSPOT_PRESETS = {
    "Centre": "centre",
    "Top-left": "topleft",
}


def _as_cursor_file(path: Path) -> CursorFile:
    """Wrap a plain path so the preview widgets can render it."""
    ext = path.suffix.lower()
    kind = (FileKind.ANIMATED if ext == ".ani"
            else FileKind.CONVERTIBLE if ext in (".png", ".ico")
            else FileKind.STATIC)
    cf = CursorFile(path=path, kind=kind)
    try:
        info = cursor_io.probe(path)
        cf.width, cf.height = info.width, info.height
        cf.hotspot = info.hotspot
        cf.frame_count = info.frame_count
    except Exception as exc:
        cf.error = str(exc)
    return cf


class InputRow(QFrame):
    """One file queued for conversion."""

    removed = Signal(object)

    def __init__(self, cf: CursorFile, parent=None):
        super().__init__(parent)
        self.cf = cf
        self.setObjectName("Card")
        self.setFixedHeight(56)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 7, 8, 7)
        lay.setSpacing(11)

        preview = AnimatedCursorLabel(36)
        preview.set_file(cf)
        lay.addWidget(preview)

        col = QVBoxLayout()
        col.setSpacing(2)
        name = QLabel(cf.stem)
        name.setStyleSheet(f"font-size:12px; font-weight:550; color:{theme.TEXT};")
        name.setToolTip(str(cf.path))
        col.addWidget(name)

        meta = QHBoxLayout()
        meta.setSpacing(5)
        meta.addWidget(KindPill(cf.path.suffix.lower().lstrip(".").upper(),
                                "error" if not cf.ok else "info"))
        if cf.ok and cf.frame_count > 1:
            meta.addWidget(KindPill(f"{cf.frame_count} FRAMES", "anim"))
        detail = QLabel(f"{cf.width}x{cf.height}" if cf.width else "unreadable")
        detail.setObjectName("Dim")
        meta.addWidget(detail)
        meta.addStretch(1)
        col.addLayout(meta)
        lay.addLayout(col, 1)

        remove = QPushButton("✕")
        remove.setObjectName("Ghost")
        remove.setFixedSize(26, 26)
        remove.setCursor(Qt.CursorShape.PointingHandCursor)
        remove.setToolTip("Remove from the list")
        remove.clicked.connect(lambda: self.removed.emit(self.cf))
        lay.addWidget(remove)


class ConvertScreen(QWidget):
    """Convert between PNG, ICO, CUR and ANI."""

    toast = Signal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Screen")
        self.setAcceptDrops(True)
        self.inputs: list[CursorFile] = []
        self.target = Target.CUR
        self.out_dir: Path | None = None
        self._worker = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 22, 28, 20)
        outer.setSpacing(14)

        head = QVBoxLayout()
        head.setSpacing(2)
        title = QLabel("Convert")
        title.setObjectName("H1")
        head.addWidget(title)
        sub = QLabel("Turn PNG, ICO, CUR and ANI files into one another. "
                     "Drop files anywhere on this screen.")
        sub.setObjectName("Sub")
        head.addWidget(sub)
        outer.addLayout(head)

        body = QHBoxLayout()
        body.setSpacing(14)

        # -- left: the input queue -------------------------------------------
        left = QFrame()
        left.setObjectName("Panel")
        ll = QVBoxLayout(left)
        ll.setContentsMargins(13, 13, 13, 13)
        ll.setSpacing(9)

        lh = QHBoxLayout()
        lt = QLabel("Files to convert")
        lt.setObjectName("H2")
        lh.addWidget(lt)
        lh.addStretch(1)
        self.count_pill = Pill("0", theme.TEXT_MUTED, theme.IDLE_WASH)
        lh.addWidget(self.count_pill)
        ll.addLayout(lh)

        buttons = QHBoxLayout()
        buttons.setSpacing(7)
        add = QPushButton("Add files…")
        add.setCursor(Qt.CursorShape.PointingHandCursor)
        add.clicked.connect(self._browse_files)
        buttons.addWidget(add)
        add_folder = QPushButton("Add a folder…")
        add_folder.setObjectName("Ghost")
        add_folder.setCursor(Qt.CursorShape.PointingHandCursor)
        add_folder.clicked.connect(self._browse_folder)
        buttons.addWidget(add_folder)
        buttons.addStretch(1)
        self.clear_btn = QPushButton("Clear")
        self.clear_btn.setObjectName("Ghost")
        self.clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clear_btn.clicked.connect(self._clear)
        buttons.addWidget(self.clear_btn)
        ll.addLayout(buttons)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QWidget()
        self.list_lay = QVBoxLayout(inner)
        self.list_lay.setContentsMargins(0, 0, 6, 0)
        self.list_lay.setSpacing(6)
        self.list_lay.addStretch(1)
        scroll.setWidget(inner)
        ll.addWidget(scroll, 1)

        self.empty = QLabel("Drop PNG, ICO, CUR or ANI files here,\nor use "
                            "the buttons above.")
        self.empty.setObjectName("Dim")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ll.addWidget(self.empty)

        body.addWidget(left, 1)

        # -- right: options ---------------------------------------------------
        right = QFrame()
        right.setObjectName("Panel")
        right.setFixedWidth(318)
        rl = QVBoxLayout(right)
        rl.setContentsMargins(15, 15, 15, 15)
        rl.setSpacing(11)

        fmt_label = QLabel("Convert to")
        fmt_label.setObjectName("H2")
        rl.addWidget(fmt_label)

        fmt_row = QHBoxLayout()
        fmt_row.setSpacing(6)
        self.fmt_group = QButtonGroup(self)
        self.fmt_group.setExclusive(True)
        for t in Target:
            b = QPushButton(t.label)
            b.setCheckable(True)
            b.setObjectName("NavItem")
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setStyleSheet(
                f"QPushButton{{background:{theme.BG_ELEVATED};"
                f"border:1px solid {theme.BORDER};border-radius:7px;"
                f"padding:8px 0;font-size:12px;font-weight:600;"
                f"color:{theme.TEXT_MUTED};}}"
                f"QPushButton:hover{{background:{theme.BG_HOVER};}}"
                f"QPushButton:checked{{background:{theme.ACCENT};"
                f"border-color:{theme.ACCENT};color:#fff;}}")
            b.clicked.connect(lambda _=False, tt=t: self._set_target(tt))
            self.fmt_group.addButton(b)
            fmt_row.addWidget(b, 1)
            if t is self.target:
                b.setChecked(True)
        rl.addLayout(fmt_row)

        self.explain = QLabel("")
        self.explain.setObjectName("Dim")
        self.explain.setWordWrap(True)
        rl.addWidget(self.explain)

        # Size
        self.size_box = QWidget()
        sb = QVBoxLayout(self.size_box)
        sb.setContentsMargins(0, 0, 0, 0)
        sb.setSpacing(5)
        sl = QLabel("Output size")
        sl.setStyleSheet("font-size:12px; font-weight:600;")
        sb.addWidget(sl)
        self.size_combo = QComboBox()
        self.size_combo.addItems(SIZE_PRESETS.keys())
        sb.addWidget(self.size_combo)
        rl.addWidget(self.size_box)

        # Hotspot
        self.hotspot_box = QWidget()
        hb = QVBoxLayout(self.hotspot_box)
        hb.setContentsMargins(0, 0, 0, 0)
        hb.setSpacing(5)
        hl = QLabel("Hotspot for files without one")
        hl.setStyleSheet("font-size:12px; font-weight:600;")
        hb.addWidget(hl)
        self.hotspot_combo = QComboBox()
        self.hotspot_combo.addItems(HOTSPOT_PRESETS.keys())
        hb.addWidget(self.hotspot_combo)
        note = QLabel("Files that already carry a hotspot keep theirs.")
        note.setObjectName("Dim")
        note.setWordWrap(True)
        hb.addWidget(note)
        rl.addWidget(self.hotspot_box)

        # Animation
        self.anim_box = QWidget()
        ab = QVBoxLayout(self.anim_box)
        ab.setContentsMargins(0, 0, 0, 0)
        ab.setSpacing(5)
        arow = QHBoxLayout()
        al = QLabel("Frame rate")
        al.setStyleSheet("font-size:12px; font-weight:600;")
        arow.addWidget(al)
        arow.addStretch(1)
        self.rate_value = QLabel("")
        self.rate_value.setObjectName("Mono")
        arow.addWidget(self.rate_value)
        ab.addLayout(arow)
        self.rate = QSlider(Qt.Orientation.Horizontal)
        self.rate.setRange(1, 30)
        self.rate.setValue(cursor_io.DEFAULT_JIFFIES)
        self.rate.valueChanged.connect(self._update_rate)
        ab.addWidget(self.rate)
        self.combine_cb = QCheckBox("Combine all files into one animation")
        self.combine_cb.setToolTip(
            "Treat every file in the list as a frame of a single .ani, "
            "instead of converting each one separately.")
        ab.addWidget(self.combine_cb)
        rl.addWidget(self.anim_box)

        # PNG
        self.png_box = QWidget()
        pb = QVBoxLayout(self.png_box)
        pb.setContentsMargins(0, 0, 0, 0)
        self.all_frames_cb = QCheckBox("Write every frame and size")
        self.all_frames_cb.setChecked(True)
        self.all_frames_cb.setToolTip(
            "Animations become one PNG per frame, and multi-resolution "
            "cursors one PNG per size. Off writes a single image.")
        pb.addWidget(self.all_frames_cb)
        rl.addWidget(self.png_box)

        rl.addStretch(1)

        self.dest_label = QLabel("")
        self.dest_label.setObjectName("Dim")
        self.dest_label.setWordWrap(True)
        rl.addWidget(self.dest_label)

        dest_btn = QPushButton("Choose output folder…")
        dest_btn.setObjectName("Ghost")
        dest_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        dest_btn.clicked.connect(self._choose_dest)
        rl.addWidget(dest_btn)

        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.hide()
        rl.addWidget(self.progress)

        self.convert_btn = QPushButton("Convert")
        self.convert_btn.setObjectName("Primary")
        self.convert_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.convert_btn.clicked.connect(self._convert)
        rl.addWidget(self.convert_btn)

        body.addWidget(right)
        outer.addLayout(body, 1)

        self._update_rate(self.rate.value())
        self._refresh()

    # -- input handling -----------------------------------------------------
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        paths: list[Path] = []
        for url in e.mimeData().urls():
            p = Path(url.toLocalFile())
            if p.is_dir():
                paths += [q for q in p.rglob("*")
                          if q.suffix.lower() in (".png", ".ico", ".cur", ".ani")]
            elif p.suffix.lower() in (".png", ".ico", ".cur", ".ani"):
                paths.append(p)
        self._add(paths)
        e.acceptProposedAction()

    def _browse_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self, "Choose files to convert", str(Path.home()),
            "Cursors and images (*.png *.ico *.cur *.ani);;All files (*)")
        self._add([Path(f) for f in files])

    def _browse_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "Choose a folder", str(Path.home()))
        if folder:
            self._add([p for p in Path(folder).rglob("*")
                       if p.suffix.lower() in (".png", ".ico", ".cur", ".ani")])

    def _add(self, paths: list[Path]) -> None:
        known = {str(cf.path) for cf in self.inputs}
        added = 0
        for p in paths:
            if str(p) in known:
                continue
            self.inputs.append(_as_cursor_file(p))
            known.add(str(p))
            added += 1
        if added:
            if self.out_dir is None and self.inputs:
                self.out_dir = self.inputs[0].path.parent / "converted"
            self._refresh()
            self.toast.emit(f"Added {added} file{'s' if added != 1 else ''}.",
                            "info")
        elif paths:
            self.toast.emit("Those files are already in the list.", "info")

    def _remove(self, cf: CursorFile) -> None:
        self.inputs = [c for c in self.inputs if c.path != cf.path]
        self._refresh()

    def _clear(self) -> None:
        self.inputs = []
        self._refresh()

    # -- options ------------------------------------------------------------
    def _set_target(self, target: Target) -> None:
        self.target = target
        self._refresh()

    def _update_rate(self, jiffies: int) -> None:
        self.rate_value.setText(
            f"{jiffies} jiffies · {jiffies * cursor_io.JIFFY_MS:.0f} ms")

    def _choose_dest(self) -> None:
        start = str(self.out_dir or Path.home())
        folder = QFileDialog.getExistingDirectory(
            self, "Choose where to save the converted files", start)
        if folder:
            self.out_dir = Path(folder)
            self._refresh()

    def _options(self) -> ConvertOptions:
        return ConvertOptions(
            sizes=SIZE_PRESETS[self.size_combo.currentText()],
            centre_hotspot=HOTSPOT_PRESETS[
                self.hotspot_combo.currentText()] == "centre",
            jiffies=self.rate.value(),
            combine=self.combine_cb.isChecked(),
            all_frames=self.all_frames_cb.isChecked(),
        )

    # -- rendering ----------------------------------------------------------
    def _refresh(self) -> None:
        clear_layout(self.list_lay, keep_trailing=1)
        for cf in self.inputs:
            row = InputRow(cf)
            row.removed.connect(self._remove)
            self.list_lay.insertWidget(self.list_lay.count() - 1, row)

        n = len(self.inputs)
        self.count_pill.apply(str(n), theme.TEXT_MUTED, theme.IDLE_WASH)
        self.empty.setVisible(n == 0)
        self.clear_btn.setEnabled(n > 0)

        from ..core import converter
        convertible = [cf.path for cf in self.inputs
                       if cf.ok and cf.path.suffix.lower() != self.target.extension]
        self.explain.setText(converter.describe(self.target,
                                                [cf.path for cf in self.inputs]))

        self.size_box.setVisible(self.target in (Target.ICO, Target.CUR,
                                                 Target.ANI))
        self.hotspot_box.setVisible(self.target.carries_hotspot)
        self.anim_box.setVisible(self.target is Target.ANI)
        self.png_box.setVisible(self.target is Target.PNG)

        self.dest_label.setText(
            f"Saving to  {self.out_dir}" if self.out_dir
            else "Output folder: a 'converted' folder beside the first input.")

        skipped = n - len(convertible)
        ready = bool(convertible) and self._worker is None
        self.convert_btn.setEnabled(ready)
        if skipped and convertible:
            self.convert_btn.setText(
                f"Convert {len(convertible)} file"
                f"{'s' if len(convertible) != 1 else ''}")
        else:
            self.convert_btn.setText("Convert")

    # -- running ------------------------------------------------------------
    def _convert(self) -> None:
        from .workers import ConvertWorker

        paths = [cf.path for cf in self.inputs
                 if cf.ok and cf.path.suffix.lower() != self.target.extension]
        if not paths:
            return
        out_dir = self.out_dir or (paths[0].parent / "converted")
        self.out_dir = out_dir

        self.progress.setRange(0, len(paths))
        self.progress.setValue(0)
        self.progress.show()
        self.convert_btn.setEnabled(False)

        self._worker = ConvertWorker(paths, self.target, out_dir,
                                     self._options(), self)
        self._worker.progress.connect(
            lambda d, t: self.progress.setValue(d))
        self._worker.finished_ok.connect(self._done)
        self._worker.failed.connect(self._failed)
        self._worker.start()

    def _failed(self, message: str) -> None:
        self._worker = None
        self.progress.hide()
        self.toast.emit(f"Conversion failed: {message}", "error")
        self._refresh()

    def _done(self, report) -> None:
        self._worker = None
        self.progress.hide()

        written = len(report.written)
        failures = report.failures
        if written and not failures:
            self.toast.emit(
                f"Wrote {written} file{'s' if written != 1 else ''} "
                f"to {self.out_dir.name}.", "success")
        elif written and failures:
            self.toast.emit(
                f"Wrote {written} file{'s' if written != 1 else ''}; "
                f"{len(failures)} could not be converted.", "warn")
        else:
            first = failures[0].error if failures else "nothing to do"
            self.toast.emit(f"Nothing was converted — {first}", "error")

        for f in failures[:2]:
            self.toast.emit(f"{Path(f.source).name}: {f.error}", "warn")
        self._refresh()
