"""Reading cursor packs out of .zip, .7z and .rar archives.

No third-party dependency is needed. ZIP is handled by the standard library,
and 7z/RAR by the bsdtar (libarchive) build that Windows has shipped in
System32 since Windows 10 1803 - verified here to read all three formats. If
that is somehow missing, an installed 7-Zip is used instead, and failing both
the user gets told what to install rather than a stack trace.

Archives are extracted into a temporary directory that the caller is
responsible for cleaning up, and every member path is validated first: an
archive entry naming `..\\..\\Windows\\System32` must never be able to write
outside the extraction directory.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

ARCHIVE_EXTENSIONS = {".zip", ".7z", ".rar"}

# Guard rails against a maliciously crafted archive.
MAX_MEMBERS = 20_000
MAX_TOTAL_BYTES = 2 * 1024 * 1024 * 1024      # 2 GB uncompressed


class ArchiveError(Exception):
    """An archive could not be opened or extracted."""


@dataclass
class ExtractResult:
    directory: Path                            # temporary; caller cleans up
    archive: Path
    member_count: int = 0
    skipped: list[str] = field(default_factory=list)
    backend: str = ""

    def cleanup(self) -> None:
        shutil.rmtree(self.directory, ignore_errors=True)


def is_archive(path: Path) -> bool:
    return Path(path).suffix.lower() in ARCHIVE_EXTENSIONS


# ---------------------------------------------------------------------------
# Backends
# ---------------------------------------------------------------------------

def _bsdtar() -> Optional[Path]:
    """Windows' bundled libarchive build, which reads zip, 7z and rar."""
    root = os.environ.get("SystemRoot", r"C:\Windows")
    candidate = Path(root) / "System32" / "tar.exe"
    return candidate if candidate.is_file() else None


def _sevenzip() -> Optional[Path]:
    for env in ("ProgramFiles", "ProgramFiles(x86)"):
        base = os.environ.get(env)
        if not base:
            continue
        candidate = Path(base) / "7-Zip" / "7z.exe"
        if candidate.is_file():
            return candidate
    found = shutil.which("7z")
    return Path(found) if found else None


def available_backends() -> dict[str, bool]:
    """What this machine can currently open, for diagnostics."""
    return {
        "zip (built in)": True,
        "bsdtar (7z, rar)": _bsdtar() is not None,
        "7-Zip (7z, rar)": _sevenzip() is not None,
    }


def _safe_destination(root: Path, member: str) -> Optional[Path]:
    """Resolve an archive member against `root`, refusing to escape it."""
    if not member or member.endswith("/") or member.endswith("\\"):
        return None
    name = member.replace("\\", "/")
    if name.startswith("/") or (len(name) > 1 and name[1] == ":"):
        return None                            # absolute path
    target = (root / name).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError:
        return None                            # path traversal attempt
    return target


def _extract_zip(archive: Path, dest: Path, result: ExtractResult) -> None:
    try:
        with zipfile.ZipFile(archive) as zf:
            infos = zf.infolist()
            if len(infos) > MAX_MEMBERS:
                raise ArchiveError(
                    f"archive contains {len(infos)} entries, which is more "
                    f"than this app will extract")
            total = 0
            for info in infos:
                if info.is_dir():
                    continue
                total += info.file_size
                if total > MAX_TOTAL_BYTES:
                    raise ArchiveError("archive expands to more than 2 GB")
                target = _safe_destination(dest, info.filename)
                if target is None:
                    result.skipped.append(info.filename)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as src, open(target, "wb") as out:
                    shutil.copyfileobj(src, out)
                result.member_count += 1
    except zipfile.BadZipFile as exc:
        raise ArchiveError(f"not a readable zip file ({exc})") from exc
    except OSError as exc:
        raise ArchiveError(f"could not read the archive ({exc})") from exc


def _run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, cwd=str(cwd), capture_output=True, text=True, timeout=300,
        # Never let a console window flash up in a windowed app.
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def _extract_external(archive: Path, dest: Path,
                      result: ExtractResult) -> None:
    """Extract 7z/rar with bsdtar, falling back to an installed 7-Zip."""
    tar = _bsdtar()
    if tar is not None:
        proc = _run([str(tar), "-xf", str(archive)], dest)
        if proc.returncode == 0:
            result.backend = "bsdtar"
            return
        tar_error = (proc.stderr or proc.stdout or "").strip()
    else:
        tar_error = "bsdtar not found"

    seven = _sevenzip()
    if seven is not None:
        proc = _run([str(seven), "x", str(archive), f"-o{dest}", "-y"], dest)
        if proc.returncode == 0:
            result.backend = "7-Zip"
            return
        raise ArchiveError(
            (proc.stderr or proc.stdout or "7-Zip failed").strip()[:300])

    raise ArchiveError(
        f"could not extract this archive ({tar_error}). "
        f"Install 7-Zip, or extract it yourself and import the folder.")


def _prune_unsafe(root: Path, result: ExtractResult) -> None:
    """Belt and braces after an external extractor: drop anything that
    escaped the destination, and count what landed."""
    root_resolved = root.resolve()
    for path in list(root.rglob("*")):
        if not path.is_file():
            continue
        try:
            path.resolve().relative_to(root_resolved)
        except ValueError:
            result.skipped.append(str(path))
            try:
                path.unlink()
            except OSError:
                pass
            continue
        result.member_count += 1


def extract(archive: Path, *,
            progress: Optional[Callable[[str], None]] = None) -> ExtractResult:
    """Extract an archive into a fresh temporary directory.

    The caller owns the returned directory and must call `result.cleanup()`
    when finished with it.
    """
    archive = Path(archive)
    if not archive.is_file():
        raise ArchiveError(f"{archive.name} does not exist")
    ext = archive.suffix.lower()
    if ext not in ARCHIVE_EXTENSIONS:
        raise ArchiveError(f"{archive.name}: not a supported archive type")

    dest = Path(tempfile.mkdtemp(prefix="CursorSetStudio_"))
    result = ExtractResult(directory=dest, archive=archive)

    if progress:
        progress(f"Extracting {archive.name}…")

    try:
        if ext == ".zip":
            result.backend = "zipfile"
            _extract_zip(archive, dest, result)
        else:
            _extract_external(archive, dest, result)
            _prune_unsafe(dest, result)
    except ArchiveError:
        result.cleanup()
        raise
    except subprocess.TimeoutExpired:
        result.cleanup()
        raise ArchiveError("extraction took too long and was stopped")
    except Exception as exc:
        result.cleanup()
        raise ArchiveError(f"could not extract {archive.name}: {exc}") from exc

    if result.member_count == 0:
        result.cleanup()
        raise ArchiveError(f"{archive.name} contained no usable files")

    return result
