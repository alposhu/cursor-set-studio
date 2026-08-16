<div align="center">

<img src="cursor_set_studio/assets/logo.png" width="120" alt="Cursor Set Studio">

# Cursor Set Studio

**Turn a messy folder of cursor files into an installed Windows cursor scheme.**

[![Build](https://github.com/alposhu/cursor-set-studio/actions/workflows/build.yml/badge.svg)](https://github.com/alposhu/cursor-set-studio/actions/workflows/build.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Windows](https://img.shields.io/badge/platform-Windows%2010%20%7C%2011-0078D6)](https://www.microsoft.com/windows)
[![Python](https://img.shields.io/badge/python-3.11%2B-3776AB)](https://www.python.org)

</div>

---

Windows makes you install cursors one file at a time, through the Mouse
Properties dialog, for each of 15+ roles. Cursor Set Studio replaces that:
point it at a folder, it works out which file belongs to which role from the
filenames, you correct anything it got wrong, preview the whole set live, and
install it with one click.

Everything is written to `HKEY_CURRENT_USER` only — **no administrator rights,
no sign-out.**

## Features

- **Automatic matching** — filenames are scored against all 15 Windows cursor
  roles plus the Windows 10/11 `Pin` and `Person` extras.
- **Nothing is guessed silently** — weak or ambiguous matches are flagged, and
  anything unmatched waits in a visible pool rather than being force-fitted.
- **Animated cursor support** — `.ani` files play in the UI, and runs of
  numbered frames (`busy_01.cur`, `busy_02.cur`, …) are detected and combined
  into a single `.ani` with adjustable timing.
- **Live preview** — a mock desktop where hovering each element shows the real
  cursor you assigned, at its real hotspot, before anything touches your system.
- **Drag and drop** — drag from the pool onto a role, or between roles to swap.
  A dropdown picker covers the same ground without dragging.
- **Safe install** — your current configuration is backed up first, and files
  are copied into managed storage so the scheme cannot break later.
- **Scheme library** — every set you build is kept, ready to reapply, rename,
  export, or delete.
- **Export** — produce a shareable folder with an installer script for another
  machine.

## Install

### Option 1 — the executable

Download `Cursor Set Studio.exe` from the
[Releases](https://github.com/alposhu/cursor-set-studio/releases) page and run
it. No Python needed.

> Windows SmartScreen may warn about an unrecognised publisher, since the
> executable is not code-signed. Choose **More info → Run anyway**.

### Option 2 — from source

```bash
git clone https://github.com/alposhu/cursor-set-studio.git
cd cursor-set-studio
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python cursor_set_studio\main.py
```

Requires Windows 10 or 11 and Python 3.11+ (developed on 3.14 / PySide6 6.11).

### Building the executable yourself

```bash
.venv\Scripts\python -m pip install pyinstaller
.venv\Scripts\python build_exe.py     # -> dist/Cursor Set Studio.exe
```

## Tests

```bash
.venv\Scripts\python tests\test_core.py              # 30 checks, read-only
.venv\Scripts\python tests\test_core.py --registry   # 45 checks, incl. registry
.venv\Scripts\python cursor_set_studio\main.py --selftest   # UI + assets
```

The `--registry` run applies a real scheme, verifies it, then restores a
byte-for-byte snapshot of your original registry values, leaving the machine
exactly as it found it. `--selftest` builds every screen offscreen — it never
opens a window, so it is safe in CI.

---

## How it works

### Matching

Filenames are normalised (lowercased, split on separators, camelCase, and
letter/digit boundaries) and scored against each role's keyword list. Adjacent
tokens are also joined, so `size_all` reaches the keyword `sizeall`.

Scoring tiers, highest first: exact token, exact joined n-gram, token prefix,
substring. A small per-character bonus makes a longer keyword win within a
tier, so `uparrow.cur` maps to Alternate Select rather than Normal Select.
Fuzzy matching is disabled below four characters — that is what stops `normal`
from matching the `No` role.

Anything below the threshold stays **unassigned** rather than being forced into
the nearest-sounding role. Where several unplaced files fit one role, all are
surfaced and the slot is flagged instead of one being silently chosen.

Verified against four naming conventions (60 cases, all passing): Windows' own
`aero_*` names, Mouse Properties display names, registry-style names, and
cryptic third-party pack names.

### Frame sequences

Runs of numbered files are detected and offered as one animation. A run needs
at least three files — which is what keeps `diagonal1.cur` and `diagonal2.cur`,
two genuinely different roles, from being welded into a two-frame animation.

### File formats

`core/cursor_io.py` implements `.cur` and `.ani` directly against the format
specifications:

- **`.cur`** — `ICONDIR` + `ICONDIRENTRY` records, where each entry's
  `wPlanes`/`wBitCount` fields carry the hotspot instead. Payloads are PNG
  blobs or packed DIBs (a colour XOR bitmap plus a 1-bpp AND mask, at
  1/4/8/24/32 bpp).
- **`.ani`** — a RIFF/`ACON` container with an `anih` header, a `LIST`/`fram`
  chunk of embedded cursor blobs, and optional `rate` and `seq ` chunks.

All 189 cursors Windows ships decode correctly, and re-encoding preserves
hotspots and pixels exactly. Decoding uses Pillow's C-level raw decoders with a
pure-Python fallback for layouts they reject.

Existing `.cur`/`.ani` files are **copied byte-for-byte** on install, so their
hotspots and bundled resolutions are never disturbed. Hotspots are only
computed when converting a raw `.png`/`.ico`, and that guess is editable with a
click-to-set control on an enlarged preview.

> **Why not use an existing library?** The two usual suggestions do not work:
> [Iconolatry](https://github.com/SystemRage/Iconolatry) was never published to
> PyPI, and [`ani_file`](https://pypi.org/project/ani_file/) imports the stdlib
> `chunk` module, which [PEP 594](https://peps.python.org/pep-0594/) removed in
> Python 3.13 — so it cannot even be imported on a current interpreter. Both
> formats are stable and well documented, so implementing them directly removes
> two fragile dependencies and gives exact control over hotspots and timing.

### Registry

| What | Where |
|---|---|
| Active cursors | `HKCU\Control Panel\Cursors`, one `REG_EXPAND_SZ` per role |
| Active scheme name | the `(Default)` value at that key |
| Scheme origin | `Scheme Source` = `2` (user scheme) |
| Named schemes | `HKCU\Control Panel\Cursors\Schemes` |

A scheme value is 17 comma-separated paths in a fixed order — the 15 core roles
plus `Pin` and `Person`. That order was read back from the built-in schemes
under `HKLM` rather than assumed:

```
Arrow, Help, AppStarting, Wait, Crosshair, IBeam, NWPen, No,
SizeNS, SizeWE, SizeNWSE, SizeNESW, SizeAll, UpArrow, Hand, Pin, Person
```

An empty entry means "leave this role at the Windows default". Windows' own
schemes append two more fields pointing at a string resource for the localized
name; user schemes omit them. Note the `Schemes` key does not necessarily
exist — on a machine that has never saved a custom scheme it is absent, so it
is created on first save.

Changes take effect immediately via
`SystemParametersInfoW(SPI_SETCURSORS, 0, None, SPIF_SENDCHANGE)`.

### Why files are copied into managed storage

Before any registry value is written, the chosen cursors are copied to
`%LOCALAPPDATA%\CursorSetStudio\schemes\<scheme name>\` and renamed to their
role. The registry then points at those copies.

This is not housekeeping. A registry pointing at whatever folder you happened
to import from breaks the moment you move, rename, or delete it — and Windows
gives no indication, it just quietly falls back to defaults. This is a common
real-world failure: cursor packs are typically installed straight out of a
`Downloads` folder that later gets cleaned up.

Folders left behind by an install that failed part-way are swept on next start.

### Backups

The configuration in place before the app first changed anything is written to
`%LOCALAPPDATA%\CursorSetStudio\original_cursors.json` and never overwritten,
so it stays restorable no matter how many schemes are applied afterwards. A
separate `last_cursors.json` backs the "Undo" on the toast shown after each
install. Restoring skips any path whose file has since disappeared, so a
restore can never point the registry at something that is not there.

---

## Project layout

```
cursor_set_studio/
├── main.py                 entry point, --selftest, font/DPI/icon setup
├── assets/                 logo.png, logo.ico
├── core/                   no Qt imports anywhere in here
│   ├── models.py           role table, CursorFile, Assignment, Confidence
│   ├── cursor_io.py        .cur / .ani read + write
│   ├── scanner.py          recursive scan, junk filter, sequence detection
│   ├── matcher.py          filename → role scoring
│   ├── registry.py         HKCU read/write, live refresh, backup/restore
│   └── library.py          managed storage, scheme index, export
└── ui/
    ├── theme.py            palette tokens + stylesheet
    ├── state.py            session state and the assignment invariant
    ├── workers.py          background scan/stage threads
    ├── resources.py        asset lookup, PyInstaller-aware
    ├── dialogs.py          picker, hotspot editor, confirmations
    ├── main_window.py      frameless shell, navigation
    ├── import_screen.py    1. Import
    ├── review_screen.py    2. Review
    ├── preview_screen.py   3. Preview
    ├── apply_screen.py     4. Install
    ├── library_screen.py   Saved schemes
    └── widgets/            role card, file chip, previews, toasts, title bar
```

`core/` imports no Qt and is testable on its own — the OS-integration logic was
built and validated before any UI existed.

## Scope

Windows 10/11 only. Cursor schemes as an OS-integrated concept are a Windows
idea; Linux (Xcursor) and macOS have no real equivalent. An Xcursor export
would be an addition to `core/`, not a rewrite.

## License

[MIT](LICENSE) © Alperen Karabıyık
