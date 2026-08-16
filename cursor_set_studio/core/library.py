"""Managed storage, the scheme library, and export.

Cursor files are copied into this app's own storage before the registry is
ever pointed at them. That is what makes an applied scheme durable: if the
user later moves, renames, or deletes the folder they imported from, the
scheme keeps working because the registry points at our copy, not theirs.
"""
from __future__ import annotations

import json
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable, Optional

from PIL import Image

from . import cursor_io, registry
from .models import Assignment, FileKind, HotspotDefault, SchemeRecord

INDEX_NAME = "library.json"
_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def schemes_root() -> Path:
    d = registry.app_data_dir() / "schemes"
    d.mkdir(parents=True, exist_ok=True)
    return d


def safe_dir_name(name: str) -> str:
    """Turn a scheme name into something usable as a folder name."""
    cleaned = _UNSAFE.sub("_", name).strip(" .")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned[:80] or "scheme"


def unique_dir(name: str) -> Path:
    base = schemes_root() / safe_dir_name(name)
    if not base.exists():
        return base
    for i in range(2, 1000):
        candidate = base.parent / f"{base.name} ({i})"
        if not candidate.exists():
            return candidate
    raise OSError("could not find a free directory name")


# ---------------------------------------------------------------------------
# Staging
# ---------------------------------------------------------------------------

def stage_scheme(
    name: str,
    assignments: Iterable[Assignment],
    *,
    target_dir: Optional[Path] = None,
    frame_jiffies: int = cursor_io.DEFAULT_JIFFIES,
    progress: Optional[Callable[[int, int], None]] = None,
) -> tuple[dict[str, str], list[str]]:
    """Copy every assigned cursor into managed storage, named by its role.

    Existing .cur/.ani files are copied byte-for-byte so their hotspots
    survive exactly. Numbered frame runs are assembled into a single .ani,
    and raw images are converted to .cur using the assignment's hotspot.

    Returns (role -> absolute path, warnings).
    """
    filled = [a for a in assignments if a.filled]
    if not filled:
        raise ValueError("nothing to stage: no roles are assigned")

    directory = Path(target_dir) if target_dir else unique_dir(name)
    directory.mkdir(parents=True, exist_ok=True)

    mapping: dict[str, str] = {}
    warnings: list[str] = []

    for i, a in enumerate(filled):
        src = a.file.path
        role_key = a.role.registry_name
        try:
            if a.file.is_sequence:
                dest = directory / f"{role_key}.ani"
                cursor_io.build_ani_from_frames(
                    a.file.sequence_paths, dest,
                    jiffies=frame_jiffies, name=f"{name} {role_key}")

            elif a.file.kind is FileKind.CONVERTIBLE:
                dest = directory / f"{role_key}.cur"
                with Image.open(src) as im:
                    rgba = im.convert("RGBA")
                hotspot = a.hotspot_override or cursor_io.default_hotspot_for(
                    rgba, a.role.hotspot_default)
                cursor_io.image_to_cur(rgba, hotspot, dest)

            else:
                # Copy verbatim: re-encoding would risk the hotspot and any
                # extra resolutions bundled in the file.
                dest = directory / f"{role_key}{src.suffix.lower()}"
                shutil.copy2(src, dest)

            mapping[role_key] = str(dest.resolve())

        except Exception as exc:
            warnings.append(f"{a.role.display_name}: {exc}")

        if progress:
            progress(i + 1, len(filled))

    if not mapping:
        raise ValueError("no cursors could be staged: " + "; ".join(warnings[:3]))

    return mapping, warnings


def write_thumbnail(mapping: dict[str, str], directory: Path,
                    size: int = 64) -> Optional[str]:
    """Render a small PNG of the scheme's Normal Select cursor."""
    source = mapping.get("Arrow") or next(iter(mapping.values()), None)
    if not source:
        return None
    try:
        frames = cursor_io.load_frames(Path(source), target=size)
        img = frames[0][0]
        canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        img.thumbnail((size, size), Image.Resampling.LANCZOS)
        canvas.paste(img, ((size - img.width) // 2, (size - img.height) // 2))
        dest = Path(directory) / "thumbnail.png"
        canvas.save(dest)
        return str(dest)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# The library index
# ---------------------------------------------------------------------------

def index_path() -> Path:
    return registry.app_data_dir() / INDEX_NAME


def load_library() -> list[SchemeRecord]:
    p = index_path()
    if not p.is_file():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return [SchemeRecord.from_json(d) for d in data]
    except (OSError, ValueError):
        return []                  # a corrupt index must not block the app


def save_library(records: list[SchemeRecord]) -> None:
    try:
        index_path().write_text(
            json.dumps([r.to_json() for r in records], indent=2),
            encoding="utf-8")
    except OSError:
        pass


def record_scheme(name: str, directory: Path, mapping: dict[str, str],
                  thumbnail: Optional[str] = None) -> SchemeRecord:
    """Add or replace a scheme in the library index."""
    rec = SchemeRecord(
        name=name,
        created=datetime.now().isoformat(timespec="seconds"),
        directory=str(Path(directory).resolve()),
        roles=dict(mapping),
        thumbnail=thumbnail,
    )
    records = [r for r in load_library() if r.name != name]
    records.insert(0, rec)
    save_library(records)
    return rec


def delete_scheme_record(name: str, *, remove_files: bool = True) -> None:
    records = load_library()
    keep = [r for r in records if r.name != name]
    for r in records:
        if r.name == name and remove_files and r.directory:
            d = Path(r.directory)
            # Only ever delete inside our own storage.
            try:
                if d.is_dir() and schemes_root() in d.parents:
                    shutil.rmtree(d, ignore_errors=True)
            except OSError:
                pass
    save_library(keep)


def rename_scheme_record(old: str, new: str) -> None:
    records = load_library()
    for r in records:
        if r.name == old:
            r.name = new
    save_library(records)


def prune_orphans() -> int:
    """Delete staged scheme folders that no library record points at.

    Staging happens before the registry write, so an install that fails
    part-way (or an export the user cancels) can leave a folder behind with
    nothing referencing it. Sweeping them on startup keeps managed storage
    from growing without bound.
    """
    try:
        root = schemes_root()
    except OSError:
        return 0

    keep = {Path(r.directory).resolve() for r in load_library() if r.directory}
    removed = 0
    for entry in root.iterdir():
        if not entry.is_dir():
            continue
        if entry.resolve() in keep:
            continue
        try:
            shutil.rmtree(entry, ignore_errors=True)
            removed += 1
        except OSError:
            pass
    return removed


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

_INSTALL_BAT = r"""@echo off
setlocal
rem Cursor Set Studio - portable installer for the "{name}" scheme.
rem Installs for the current user only; no admin rights required.

set "DIR=%~dp0"
set "KEY=HKCU\Control Panel\Cursors"

echo Installing cursor scheme "{name}"...

{lines}
reg add "%KEY%" /ve /t REG_SZ /d "{name}" /f >nul
reg add "%KEY%" /v "Scheme Source" /t REG_DWORD /d 2 /f >nul

rem Apply immediately, without signing out.
rundll32.exe user32.dll,UpdatePerUserSystemParameters

echo Done. The "{name}" cursors are now active.
pause
"""


def export_scheme(name: str, mapping: dict[str, str], dest_dir: Path) -> Path:
    """Write a shareable folder: role-named cursors plus an installer."""
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)

    exported: dict[str, str] = {}
    for role_key, src in mapping.items():
        src_path = Path(src)
        if not src_path.is_file():
            continue
        target = dest / f"{role_key}{src_path.suffix.lower()}"
        shutil.copy2(src_path, target)
        exported[role_key] = target.name

    lines = "\n".join(
        f'reg add "%KEY%" /v "{k}" /t REG_EXPAND_SZ /d "%DIR%{v}" /f >nul'
        for k, v in exported.items())

    (dest / "Install.bat").write_text(
        _INSTALL_BAT.format(name=name, lines=lines),
        encoding="utf-8")

    (dest / "scheme.json").write_text(
        json.dumps({"name": name, "roles": exported}, indent=2),
        encoding="utf-8")

    (dest / "README.txt").write_text(
        f'Cursor scheme: {name}\n'
        f'{"-" * (len(name) + 16)}\n\n'
        f'Exported by Cursor Set Studio.\n\n'
        f'To install: run Install.bat.\n'
        f'It writes to HKEY_CURRENT_USER only, applies immediately, and does\n'
        f'not need administrator rights. Keep this folder where it is after\n'
        f'installing - the cursors are loaded from these files.\n\n'
        f'Roles included ({len(exported)}):\n'
        + "".join(f'  {k:<12} {v}\n' for k, v in sorted(exported.items())),
        encoding="utf-8")

    return dest
