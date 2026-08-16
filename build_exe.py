"""Build the standalone Cursor Set Studio executable.

    .venv\\Scripts\\python build_exe.py

Produces dist/Cursor Set Studio.exe - a single file that runs on a machine
with no Python installed.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
NAME = "Cursor Set Studio"

# Qt ships far more than this app uses. Excluding the unused modules keeps the
# one-file build from ballooning, and avoids pulling in WebEngine, which alone
# is larger than everything else combined.
EXCLUDES = [
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebEngineQuick", "PySide6.QtWebChannel", "PySide6.QtWebSockets",
    "PySide6.QtQuick", "PySide6.QtQuick3D", "PySide6.QtQml", "PySide6.QtQuickWidgets",
    "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets",
    "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.Qt3DAnimation",
    "PySide6.Qt3DExtras", "PySide6.Qt3DInput", "PySide6.Qt3DLogic",
    "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtGraphs",
    "PySide6.QtBluetooth", "PySide6.QtNfc", "PySide6.QtPositioning",
    "PySide6.QtLocation", "PySide6.QtSerialPort", "PySide6.QtSerialBus",
    "PySide6.QtTest", "PySide6.QtHelp", "PySide6.QtDesigner", "PySide6.QtUiTools",
    "PySide6.QtSql", "PySide6.QtPdf", "PySide6.QtPdfWidgets",
    "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets",
    "PySide6.QtNetworkAuth", "PySide6.QtRemoteObjects", "PySide6.QtScxml",
    "PySide6.QtSensors", "PySide6.QtSpatialAudio", "PySide6.QtStateMachine",
    "PySide6.QtSvgWidgets", "PySide6.QtTextToSpeech",
    "tkinter", "unittest", "pydoc", "doctest", "email", "http", "xmlrpc",
    "numpy", "scipy", "pytest",
]


def main() -> int:
    icon = ROOT / "cursor_set_studio" / "assets" / "logo.ico"
    if not icon.is_file():
        print(f"missing icon: {icon}", file=sys.stderr)
        return 1

    for stale in ("build", "dist"):
        shutil.rmtree(ROOT / stale, ignore_errors=True)

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--onefile",
        "--windowed",                       # no console window behind the app
        "--name", NAME,
        "--icon", str(icon),
        # resources.py reads these from sys._MEIPASS/assets at runtime.
        "--add-data", f"{ROOT / 'cursor_set_studio' / 'assets'}{os_sep()}assets",
        "--version-file", str(ROOT / "build_assets" / "version_info.txt"),
        "--paths", str(ROOT),
        "--clean",
    ]
    for mod in EXCLUDES:
        cmd += ["--exclude-module", mod]
    cmd.append(str(ROOT / "cursor_set_studio" / "main.py"))

    print("building...\n")
    result = subprocess.run(cmd, cwd=ROOT)
    if result.returncode != 0:
        return result.returncode

    exe = ROOT / "dist" / f"{NAME}.exe"
    if not exe.is_file():
        print("build reported success but produced no exe", file=sys.stderr)
        return 1

    print(f"\nbuilt {exe}")
    print(f"size  {exe.stat().st_size / 1024 / 1024:.1f} MB")
    return 0


def os_sep() -> str:
    """PyInstaller's --add-data separator: ';' on Windows, ':' elsewhere."""
    return ";" if sys.platform == "win32" else ":"


if __name__ == "__main__":
    raise SystemExit(main())
