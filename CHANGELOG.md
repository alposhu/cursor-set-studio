# Changelog

All notable changes to Cursor Set Studio are recorded here.

## [1.1.0] — 2026-08-16

### Added

**Format converter.** A new screen covering all twelve conversions between
PNG, ICO, CUR and ANI, in batches.

|  | → PNG | → ICO | → CUR | → ANI |
|---|---|---|---|---|
| **PNG →** | – | yes | yes | yes |
| **ICO →** | yes | – | yes | yes |
| **CUR →** | yes | yes | – | yes |
| **ANI →** | yes | yes | yes | – |

- Hotspots are carried through wherever the target format can store one, and
  the interface says plainly when it cannot — an ICO or PNG has nowhere to
  keep one. Converting the other way assigns a hotspot, centred by default or
  at the top-left.
- Every resolution embedded in a multi-size `.ico`/`.cur` is preserved, and can
  be written out as one PNG per size.
- Animations keep their own per-frame timing. Converting one to a static format
  keeps a single frame, except to PNG which can write every frame out.
- **Combine mode** turns several still images into one animation, with an
  adjustable frame rate.
- Output size, hotspot placement and frame rate are all adjustable, and
  existing files are never silently overwritten.

**Archive import.** Cursor packs can be opened directly from `.zip`, `.7z` and
`.rar` files, by drag and drop or through the file picker, without unpacking
them first. This adds no third-party dependency: ZIP is handled by the Python
standard library, and 7z/RAR by the bsdtar (libarchive) build that Windows has
shipped in `System32` since Windows 10 1803. An installed 7-Zip is used as a
fallback, and if neither is present the app says what to install rather than
failing obscurely.

Archives are extracted to a temporary directory that is cleaned up afterwards,
and every member path is validated first, so an entry named
`..\..\Windows\System32\...` cannot write outside the extraction folder.

### Changed

- `core/cursor_io.py` can now write real `.ico` files. An icon is type 1 with
  genuine colour-plane and bit-depth fields, where a cursor is type 2 with the
  hotspot packed into those same bytes.
- The application self-test (`--selftest`) now also exercises the converter and
  reports which archive backends are available, so a packaged build is checked
  for modules that are only imported lazily at runtime.

### Fixed

- Continuous integration reported every packaged build as failed. PowerShell's
  call operator does not wait for a GUI-subsystem process and leaves
  `$LASTEXITCODE` unset, so the verification step compared `$null` against `0`
  and threw on every run. The executable itself was never broken.
- The self-test asserted a fixed screen count, which broke when the converter
  screen was added. It is now derived from the navigation rail.

---

## [1.0.0] — 2026-08-16

First public release.

### Added

- Automatic filename-to-role matching across all 15 Windows cursor roles plus
  the Windows 10/11 `Pin` and `Person` extras, verified against four naming
  conventions.
- Weak or ambiguous matches are flagged rather than silently guessed, and
  anything unmatched waits in a visible pool — nothing is ever discarded.
- `.cur` and `.ani` codecs implemented directly against the file formats. All
  189 cursors Windows ships decode correctly, and re-encoding preserves
  hotspots and pixels exactly.
- Detection of numbered frame runs (`busy_01.cur`, `busy_02.cur`, …), combined
  into a single `.ani` with adjustable timing.
- Live preview on a mock desktop, using the real assigned cursors at their real
  hotspots before anything touches the system.
- Drag-and-drop review, with a picker as an alternative to dragging.
- One-click install to `HKEY_CURRENT_USER` with an immediate refresh — no
  administrator rights and no sign-out.
- Cursor files are copied into managed storage before the registry is pointed
  at them, so a scheme cannot break when the imported folder is moved.
- The previous cursor configuration is backed up before the first install and
  stays restorable in one click.
- Scheme library for reapplying, renaming, exporting or deleting any set.
- Export to a shareable folder with a self-contained installer script.
