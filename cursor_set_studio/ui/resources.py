"""Locating bundled assets, both from source and from a frozen build."""
from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path

from PySide6.QtGui import QIcon, QPixmap


def asset_dir() -> Path:
    """Where the bundled assets live.

    PyInstaller unpacks a one-file build into a temporary directory exposed as
    sys._MEIPASS, so the path differs between running from source and running
    the built .exe.
    """
    bundled = getattr(sys, "_MEIPASS", None)
    if bundled:
        return Path(bundled) / "assets"
    return Path(__file__).resolve().parent.parent / "assets"


def asset(name: str) -> Path:
    return asset_dir() / name


@lru_cache(maxsize=16)
def logo_pixmap(size: int) -> QPixmap:
    """The app mark, scaled for a given box. Empty pixmap if it is missing."""
    path = asset("logo.png")
    if not path.is_file():
        return QPixmap()
    pm = QPixmap(str(path))
    if pm.isNull():
        return QPixmap()
    from PySide6.QtCore import Qt
    return pm.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio,
                     Qt.TransformationMode.SmoothTransformation)


@lru_cache(maxsize=1)
def app_icon() -> QIcon:
    """Multi-resolution window and taskbar icon."""
    ico = asset("logo.ico")
    if ico.is_file():
        return QIcon(str(ico))
    png = asset("logo.png")
    if png.is_file():
        return QIcon(str(png))
    return QIcon()
