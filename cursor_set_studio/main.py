"""Cursor Set Studio - entry point."""
from __future__ import annotations

import ctypes
import os
import sys
from pathlib import Path

# Allow running this file directly as well as via `python -m cursor_set_studio`.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication

from cursor_set_studio import AUTHOR, __version__
from cursor_set_studio.ui import theme
from cursor_set_studio.ui.main_window import MainWindow
from cursor_set_studio.ui.resources import app_icon, asset_dir, logo_pixmap

APP_ID = "CursorSetStudio.AlperenKarabiyik.1"


def _windows_setup() -> None:
    """Give the app its own taskbar identity and correct DPI handling."""
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:
        pass


def _ui_font() -> QFont:
    """Pick the best available UI font.

    Segoe UI Variable ships with Windows 11 only, so on Windows 10 fall back
    to Segoe UI, then to whatever the stylesheet font stack resolves.
    """
    try:
        families = set(QFontDatabase.families())
    except Exception:
        families = set()

    font = QFont()
    for name in ("Segoe UI Variable Display", "Segoe UI", "Tahoma"):
        if name in families:
            font = QFont(name)
            break
    font.setPointSize(9)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    return font


def _selftest() -> int:
    """Build the whole UI offscreen, verify assets, and exit.

    Used to check a packaged build without opening a window. A windowed .exe
    has no console, so the verdict is written to a file next to the report
    path as well as returned as the exit code.
    """
    import tempfile

    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    report: list[str] = []
    ok = True

    def note(label: str, passed: bool, detail: str = "") -> None:
        nonlocal ok
        ok = ok and passed
        report.append(f"{'PASS' if passed else 'FAIL'}  {label}"
                      + (f"  [{detail}]" if detail else ""))

    try:
        app = QApplication([])
        app.setStyleSheet(theme.STYLESHEET)
        app.setFont(_ui_font())

        icon = app_icon()
        note("app icon loaded", not icon.isNull(),
             ",".join(f"{s.width()}" for s in icon.availableSizes()))
        note("logo bitmap loaded", not logo_pixmap(64).isNull())
        note("frozen bundle" if getattr(sys, "frozen", False) else "source run",
             True, str(asset_dir()))

        window = MainWindow()
        window.resize(1280, 820)
        window.show()
        app.processEvents()
        # Derived from the navigation rail rather than hardcoded, so adding
        # a screen does not silently break this check.
        expected = len(window.nav_buttons)
        note("main window built", window.stack.count() == expected,
             f"{window.stack.count()} screens, {expected} nav entries")
        note("window icon set", not window.windowIcon().isNull())

        from cursor_set_studio.core import (archives, converter, cursor_io,
                                            registry)
        note("registry readable", isinstance(registry.read_current().roles, dict))
        probe_target = Path(r"C:\Windows\Cursors\aero_arrow.cur")
        if probe_target.is_file():
            note("cursor codec works",
                 cursor_io.probe(probe_target).width > 0)

        # These two are only imported lazily at runtime, so a frozen build
        # could plausibly ship without them. Exercise them for real.
        backends = archives.available_backends()
        note("archive backends present", any(backends.values()),
             ", ".join(k for k, v in backends.items() if v))

        if probe_target.is_file():
            with tempfile.TemporaryDirectory() as td:
                converted = converter.convert_files(
                    [probe_target], converter.Target.PNG, Path(td),
                    converter.ConvertOptions())
                note("converter works",
                     converted.succeeded == 1 and bool(converted.written),
                     f"{len(converted.written)} file(s)")

        window.close()
        app.processEvents()
    except Exception as exc:
        import traceback
        ok = False
        report.append(f"FAIL  exception: {exc}")
        report.append(traceback.format_exc())

    text = "\n".join(report) + f"\n\n{'ALL OK' if ok else 'FAILURES PRESENT'}\n"
    out = Path(tempfile.gettempdir()) / "cursor_set_studio_selftest.txt"
    try:
        out.write_text(text, encoding="utf-8")
    except OSError:
        pass
    print(text)
    print(f"(written to {out})")
    return 0 if ok else 1


def main() -> int:
    if sys.platform != "win32":
        print("Cursor Set Studio installs Windows cursor schemes and only "
              "runs on Windows 10/11.", file=sys.stderr)
        return 1

    if "--selftest" in sys.argv:
        return _selftest()

    _windows_setup()

    app = QApplication(sys.argv)
    app.setApplicationName("Cursor Set Studio")
    app.setApplicationDisplayName("Cursor Set Studio")
    app.setApplicationVersion(__version__)
    app.setOrganizationName(AUTHOR)
    app.setStyleSheet(theme.STYLESHEET)

    app.setFont(_ui_font())
    app.setWindowIcon(app_icon())

    # Clear any scheme folders left behind by an interrupted install.
    try:
        from cursor_set_studio.core import library
        library.prune_orphans()
    except Exception:
        pass                       # tidying is never worth blocking startup

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
