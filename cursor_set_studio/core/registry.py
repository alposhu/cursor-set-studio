"""Windows registry integration.

Everything here touches HKEY_CURRENT_USER only; nothing needs admin rights.

Layout, as verified against this machine's own registry:

  HKCU\\Control Panel\\Cursors
      Arrow, Help, AppStarting, ... (REG_EXPAND_SZ, one full path per role)
      (Default)        REG_SZ    name of the active scheme
      Scheme Source    REG_DWORD 0 = Windows default, 1 = system, 2 = user

  HKCU\\Control Panel\\Cursors\\Schemes
      <scheme name>    REG_EXPAND_SZ, comma-separated paths in SCHEME_ORDER

The scheme string order is not guesswork: it was read back from the built-in
schemes under HKLM (Windows Aero and friends), which list 17 role paths in
the order below. An empty entry means "leave this role at the system
default". Windows' own schemes append two more fields pointing at a string
resource for the localized display name; user schemes omit them.
"""
from __future__ import annotations

import ctypes
import json
import winreg
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

CURSORS_KEY = r"Control Panel\Cursors"
SCHEMES_KEY = r"Control Panel\Cursors\Schemes"

# The exact order Windows uses inside a scheme string.
SCHEME_ORDER: tuple[str, ...] = (
    "Arrow", "Help", "AppStarting", "Wait", "Crosshair", "IBeam", "NWPen",
    "No", "SizeNS", "SizeWE", "SizeNWSE", "SizeNESW", "SizeAll", "UpArrow",
    "Hand", "Pin", "Person",
)

# SystemParametersInfoW
SPI_SETCURSORS = 0x0057
SPIF_SENDCHANGE = 0x02

# Values under the Cursors key that are settings, not cursor paths.
NON_ROLE_VALUES = {
    "Scheme Source", "CursorBaseSize", "GestureVisualization",
    "ContactVisualization", "",
}

SCHEME_SOURCE_USER = 2


class RegistryError(Exception):
    """A registry operation failed."""


@dataclass
class CursorConfig:
    """A snapshot of the user's cursor configuration."""

    roles: dict[str, str] = field(default_factory=dict)   # role -> path
    scheme_name: str = ""
    scheme_source: Optional[int] = None
    captured: str = ""

    def to_json(self) -> dict:
        return {
            "roles": self.roles,
            "scheme_name": self.scheme_name,
            "scheme_source": self.scheme_source,
            "captured": self.captured,
        }

    @staticmethod
    def from_json(d: dict) -> "CursorConfig":
        return CursorConfig(
            roles=d.get("roles", {}),
            scheme_name=d.get("scheme_name", ""),
            scheme_source=d.get("scheme_source"),
            captured=d.get("captured", ""),
        )


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------

def read_current() -> CursorConfig:
    """Read the cursor configuration that is active right now."""
    cfg = CursorConfig(captured=datetime.now().isoformat(timespec="seconds"))
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, CURSORS_KEY) as key:
            i = 0
            while True:
                try:
                    name, value, vtype = winreg.EnumValue(key, i)
                except OSError:
                    break
                i += 1
                if name == "":
                    cfg.scheme_name = str(value)
                elif name == "Scheme Source":
                    cfg.scheme_source = int(value)
                elif name in NON_ROLE_VALUES:
                    continue
                elif vtype in (winreg.REG_SZ, winreg.REG_EXPAND_SZ):
                    cfg.roles[name] = str(value)
    except FileNotFoundError:
        pass                       # no Cursors key at all: everything default
    except OSError as exc:
        raise RegistryError(f"could not read cursor settings: {exc}") from exc
    return cfg


def list_schemes() -> dict[str, list[str]]:
    """Return every named scheme, as role-ordered path lists."""
    out: dict[str, list[str]] = {}
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, SCHEMES_KEY) as key:
            i = 0
            while True:
                try:
                    name, value, _ = winreg.EnumValue(key, i)
                except OSError:
                    break
                i += 1
                if name:
                    out[name] = str(value).split(",")
    except FileNotFoundError:
        pass                       # the Schemes key is created on first save
    except OSError as exc:
        raise RegistryError(f"could not list schemes: {exc}") from exc
    return out


def scheme_exists(name: str) -> bool:
    return name in list_schemes()


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------

def refresh_cursors() -> bool:
    """Make the change take effect immediately, with no logout.

    Returns False rather than raising if the call fails; the registry write
    has already happened and will apply at next sign-in regardless.
    """
    try:
        result = ctypes.windll.user32.SystemParametersInfoW(
            SPI_SETCURSORS, 0, None, SPIF_SENDCHANGE)
        return bool(result)
    except Exception:
        return False


def apply_cursors(roles: dict[str, str], *, scheme_name: str = "",
                  clear_missing: bool = True) -> bool:
    """Write role paths to the live cursor key and refresh.

    `roles` maps registry role names to absolute file paths. When
    `clear_missing` is set, roles absent from the mapping are blanked so the
    previous scheme does not show through the new one.
    """
    if not roles:
        raise RegistryError("refusing to apply an empty cursor set")

    for name, path in roles.items():
        if name not in SCHEME_ORDER:
            raise RegistryError(f"unknown cursor role {name!r}")
        if not Path(path).is_file():
            raise RegistryError(f"cursor file is missing: {path}")

    try:
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, CURSORS_KEY, 0,
                                winreg.KEY_SET_VALUE | winreg.KEY_READ) as key:
            for role_name in SCHEME_ORDER:
                path = roles.get(role_name, "")
                if not path and not clear_missing:
                    continue
                # REG_EXPAND_SZ matches what Windows itself writes.
                winreg.SetValueEx(key, role_name, 0, winreg.REG_EXPAND_SZ, path)

            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, scheme_name)
            winreg.SetValueEx(key, "Scheme Source", 0, winreg.REG_DWORD,
                              SCHEME_SOURCE_USER)
    except OSError as exc:
        raise RegistryError(f"could not write cursor settings: {exc}") from exc

    return refresh_cursors()


def save_scheme(name: str, roles: dict[str, str]) -> None:
    """Register a named scheme so Mouse Properties lists it."""
    name = name.strip()
    if not name:
        raise RegistryError("a scheme needs a name")
    if "," in name:
        # The scheme string itself is comma-separated, so a comma in the name
        # would corrupt the value.
        raise RegistryError("a scheme name cannot contain a comma")

    value = ",".join(roles.get(role_name, "") for role_name in SCHEME_ORDER)
    try:
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, SCHEMES_KEY, 0,
                                winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, name, 0, winreg.REG_EXPAND_SZ, value)
    except OSError as exc:
        raise RegistryError(f"could not save scheme {name!r}: {exc}") from exc


def delete_scheme(name: str) -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, SCHEMES_KEY, 0,
                            winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, name)
        return True
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise RegistryError(f"could not delete scheme {name!r}: {exc}") from exc


def scheme_to_roles(scheme_value: list[str] | str) -> dict[str, str]:
    """Turn a scheme string back into a role mapping."""
    parts = (scheme_value.split(",") if isinstance(scheme_value, str)
             else list(scheme_value))
    out: dict[str, str] = {}
    for i, role_name in enumerate(SCHEME_ORDER):
        if i < len(parts) and parts[i].strip():
            out[role_name] = parts[i].strip()
    return out


# ---------------------------------------------------------------------------
# Backup / restore
# ---------------------------------------------------------------------------

def app_data_dir() -> Path:
    import os
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    d = Path(base) / "CursorSetStudio"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _backup_path(original: bool) -> Path:
    name = "original_cursors.json" if original else "last_cursors.json"
    return app_data_dir() / name


def has_original_backup() -> bool:
    return _backup_path(True).is_file()


def backup_current(*, original: bool = False) -> CursorConfig:
    """Snapshot the live configuration to disk.

    The `original` snapshot is written once and never overwritten, so the very
    first state this app ever saw stays recoverable no matter how many schemes
    are applied afterwards.
    """
    cfg = read_current()
    path = _backup_path(original)
    if original and path.is_file():
        return load_backup(original=True) or cfg
    path.write_text(json.dumps(cfg.to_json(), indent=2), encoding="utf-8")
    return cfg


def load_backup(*, original: bool = False) -> Optional[CursorConfig]:
    path = _backup_path(original)
    if not path.is_file():
        return None
    try:
        return CursorConfig.from_json(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return None


def restore_backup(*, original: bool = False) -> bool:
    """Put a saved configuration back and refresh.

    Roles whose files have since disappeared are blanked rather than written,
    so a restore can never point the registry at a missing file.
    """
    cfg = load_backup(original=original)
    if cfg is None:
        raise RegistryError("there is no saved configuration to restore")

    roles = {k: v for k, v in cfg.roles.items()
             if v and Path(v).is_file() and k in SCHEME_ORDER}

    try:
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, CURSORS_KEY, 0,
                                winreg.KEY_SET_VALUE) as key:
            for role_name in SCHEME_ORDER:
                winreg.SetValueEx(key, role_name, 0, winreg.REG_EXPAND_SZ,
                                  roles.get(role_name, ""))
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, cfg.scheme_name)
            if cfg.scheme_source is not None:
                winreg.SetValueEx(key, "Scheme Source", 0, winreg.REG_DWORD,
                                  cfg.scheme_source)
    except OSError as exc:
        raise RegistryError(f"could not restore cursor settings: {exc}") from exc

    return refresh_cursors()
