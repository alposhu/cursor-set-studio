"""Core test suite for Cursor Set Studio.

Run it with:      .venv\\Scripts\\python tests\\test_core.py
Include the registry round-trip with:   --registry

No pytest dependency, no GUI. The registry test is opt-in because it
writes to HKEY_CURRENT_USER; it snapshots every value first and restores
the snapshot verbatim afterwards, leaving the machine byte-identical.
"""
from __future__ import annotations

import sys
import tempfile
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image

from cursor_set_studio.core import cursor_io, library, matcher, scanner
from cursor_set_studio.core.models import (ALL_ROLES, Confidence, CursorFile,
                                           FileKind)

WINDOWS_CURSORS = Path(r"C:\Windows\Cursors")

_passed = 0
_failed: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> bool:
    global _passed
    if cond:
        _passed += 1
    else:
        _failed.append(label)
    print(f"  {'ok  ' if cond else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    return cond


def section(name: str) -> None:
    print(f"\n--- {name} ---")


def mk(name: str, parent: str = "C:/pack") -> CursorFile:
    ext = Path(name).suffix.lower()
    kind = (FileKind.ANIMATED if ext == ".ani"
            else FileKind.CONVERTIBLE if ext in (".png", ".ico")
            else FileKind.STATIC)
    return CursorFile(path=Path(parent) / name, kind=kind)


# ---------------------------------------------------------------------------

def test_codec_against_real_cursors() -> None:
    section("Codec vs. the cursors Windows ships")
    if not WINDOWS_CURSORS.is_dir():
        check("Windows cursor folder present", False, "skipped")
        return

    files = sorted(p for p in WINDOWS_CURSORS.iterdir()
                   if p.suffix.lower() in (".cur", ".ani"))
    bad = []
    for p in files:
        try:
            cursor_io.probe(p)
            frames = cursor_io.load_frames(p)
            assert frames and all(im.mode == "RGBA" for im, _ in frames)
        except Exception as exc:
            bad.append(f"{p.name}: {exc}")
    check(f"read all {len(files)} system cursors", not bad, "; ".join(bad[:2]))


def test_cur_roundtrip() -> None:
    section("Round-trip .cur")
    if not WINDOWS_CURSORS.is_dir():
        return
    drift = []
    for p in [f for f in sorted(WINDOWS_CURSORS.iterdir())
              if f.suffix.lower() == ".cur"][:30]:
        try:
            best = cursor_io._pick_best(cursor_io.read_cur(p))
            back = cursor_io.read_cur_bytes(
                cursor_io.write_cur_bytes([best]), source="rt")[0]
            if back.hotspot != best.hotspot:
                drift.append(f"{p.name} hotspot")
            elif back.image.tobytes() != best.image.tobytes():
                drift.append(f"{p.name} pixels")
        except Exception as exc:
            drift.append(f"{p.name}: {exc}")
    check("hotspots and pixels survive a re-encode", not drift,
          "; ".join(drift[:2]))


def test_ani_roundtrip() -> None:
    section("Round-trip .ani")
    if not WINDOWS_CURSORS.is_dir():
        return
    with tempfile.TemporaryDirectory() as td:
        drift = []
        for p in [f for f in sorted(WINDOWS_CURSORS.iterdir())
                  if f.suffix.lower() == ".ani"][:8]:
            try:
                ani = cursor_io.read_ani(p)
                dest = Path(td) / p.name
                cursor_io.write_ani(ani.frames, dest,
                                    rates=ani.rates or None,
                                    sequence=ani.sequence or None,
                                    width=ani.width, height=ani.height)
                back = cursor_io.read_ani(dest)
                if len(back.frames) != len(ani.frames):
                    drift.append(f"{p.name} frame count")
                elif back.sequence != ani.sequence:
                    drift.append(f"{p.name} sequence")
            except Exception as exc:
                drift.append(f"{p.name}: {exc}")
        check("frames, rates and sequence survive", not drift,
              "; ".join(drift[:2]))


def test_conversion_and_assembly() -> None:
    section("Conversion and frame assembly")
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        for i in range(30):
            img.putpixel((i, i), (255, 0, 0, 255))

        dest = td / "converted.cur"
        cursor_io.image_to_cur(img, (8, 8), dest, sizes=(32, 48))
        got = cursor_io.read_cur(dest)
        check("hotspot scales with each size",
              [g.hotspot for g in got] == [(4, 4), (6, 6)],
              str([g.hotspot for g in got]))

        frames = []
        for i in range(4):
            fi = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
            for x in range(32):
                fi.putpixel((x, i * 8), (0, 255, 0, 255))
            fp = td / f"seq_{i + 1:02d}.cur"
            cursor_io.image_to_cur(fi, (16, 16), fp)
            frames.append(fp)

        out = td / "combined.ani"
        cursor_io.build_ani_from_frames(frames, out, jiffies=10)
        got_frames = cursor_io.load_frames(out)
        check("numbered frames combine into one .ani", len(got_frames) == 4,
              f"{len(got_frames)} frames")
        check("frame duration honours the jiffy rate",
              abs(got_frames[0][1] - 167) < 6, f"{got_frames[0][1]}ms")
        hs = cursor_io.read_cur_bytes(cursor_io.read_ani(out).frames[0])[0].hotspot
        check("embedded frame keeps its hotspot", hs == (16, 16), str(hs))


def test_corrupt_files() -> None:
    section("Corrupt and malformed files")
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        cases = {
            "empty.cur": b"",
            "garbage.cur": b"not a cursor at all" * 4,
            "badani.ani": b"RIFF\x10\x00\x00\x00ACONjunkjunk",
            "zerocount.cur": b"\x00\x00\x02\x00\x00\x00",
        }
        if WINDOWS_CURSORS.is_dir():
            cases["truncated.cur"] = (
                WINDOWS_CURSORS / "aero_arrow.cur").read_bytes()[:40]

        clean = True
        for name, data in cases.items():
            fp = td / name
            fp.write_bytes(data)
            try:
                cursor_io.probe(fp)
                clean = False
                print(f"      {name}: no error raised")
            except cursor_io.CursorFormatError:
                pass
            except Exception as exc:
                clean = False
                print(f"      {name}: wrong exception {type(exc).__name__}: {exc}")
        check("every bad file raises CursorFormatError", clean)

        # A bad file must not abort a whole scan.
        (td / "readme.txt").write_text("hi")
        result = scanner.scan_folder(td)
        check("scan survives a corrupt file", len(result.errors) >= 1,
              f"{len(result.errors)} errors recorded")
        check("unreadable files stay visible to the user",
              any(not f.ok for f in result.cursors))


def test_matching() -> None:
    section("Name matching")
    suites = {
        "Windows aero": [
            ("aero_arrow.cur", "Arrow"), ("aero_helpsel.cur", "Help"),
            ("aero_working.ani", "AppStarting"), ("aero_busy.ani", "Wait"),
            ("aero_pen.cur", "NWPen"), ("aero_unavail.cur", "No"),
            ("aero_ns.cur", "SizeNS"), ("aero_ew.cur", "SizeWE"),
            ("aero_nwse.cur", "SizeNWSE"), ("aero_nesw.cur", "SizeNESW"),
            ("aero_move.cur", "SizeAll"), ("aero_up.cur", "UpArrow"),
            ("aero_link.cur", "Hand"), ("aero_pin.cur", "Pin"),
            ("aero_person.cur", "Person"),
        ],
        "Mouse Properties names": [
            ("Normal Select.cur", "Arrow"), ("Help Select.cur", "Help"),
            ("Working In Background.ani", "AppStarting"), ("Busy.ani", "Wait"),
            ("Precision Select.cur", "Crosshair"), ("Text Select.cur", "IBeam"),
            ("Handwriting.cur", "NWPen"), ("Unavailable.cur", "No"),
            ("Vertical Resize.cur", "SizeNS"),
            ("Horizontal Resize.cur", "SizeWE"),
            ("Diagonal Resize 1.cur", "SizeNWSE"),
            ("Diagonal Resize 2.cur", "SizeNESW"),
            ("Move.cur", "SizeAll"), ("Alternate Select.cur", "UpArrow"),
            ("Link Select.cur", "Hand"),
        ],
        "Registry-style": [
            ("Arrow.cur", "Arrow"), ("Help.cur", "Help"),
            ("AppStarting.ani", "AppStarting"), ("Wait.ani", "Wait"),
            ("Crosshair.cur", "Crosshair"), ("IBeam.cur", "IBeam"),
            ("NWPen.cur", "NWPen"), ("No.cur", "No"),
            ("size_ns.cur", "SizeNS"), ("size-we.cur", "SizeWE"),
            ("SizeNWSE.cur", "SizeNWSE"), ("sizeNESW.cur", "SizeNESW"),
            ("size all.cur", "SizeAll"), ("UpArrow.cur", "UpArrow"),
            ("Hand.cur", "Hand"),
        ],
        "Cryptic pack names": [
            ("pointer.cur", "Arrow"), ("qmark.cur", "Help"),
            ("bgtask.ani", "AppStarting"), ("hourglass.ani", "Wait"),
            ("target.cur", "Crosshair"), ("caret.cur", "IBeam"),
            ("ink.cur", "NWPen"), ("forbidden.cur", "No"),
            ("updown.cur", "SizeNS"), ("leftright.cur", "SizeWE"),
            ("diag1.cur", "SizeNWSE"), ("diag2.cur", "SizeNESW"),
            ("fleur.cur", "SizeAll"), ("alternate.cur", "UpArrow"),
            ("hyperlink.cur", "Hand"),
        ],
    }

    for title, cases in suites.items():
        res = matcher.match_files([mk(n) for n, _ in cases])
        got = {a.file.name: k for k, a in res.assignments.items() if a.filled}
        wrong = [f"{n}->{got.get(n)}" for n, want in cases if got.get(n) != want]
        check(f"{title}: {len(cases) - len(wrong)}/{len(cases)}", not wrong,
              ", ".join(wrong[:3]))


def test_matching_guardrails() -> None:
    section("Matching guardrails")
    arrow = next(r for r in ALL_ROLES if r.key == "Arrow")
    no_role = next(r for r in ALL_ROLES if r.key == "No")
    f = mk("normal.cur")
    check("'normal' does not match the No role via substring",
          matcher.score_role(f, arrow) > 0 and matcher.score_role(f, no_role) == 0)

    res = matcher.match_files([mk("arrow.cur"), mk("uparrow.cur")])
    check("a more specific keyword wins",
          res.assignments["Arrow"].file.name == "arrow.cur"
          and res.assignments["UpArrow"].file.name == "uparrow.cur")

    res = matcher.match_files([mk("zzzz_qqq.cur"), mk("dsc00194.cur")])
    check("unrecognised names are never force-fitted",
          res.matched_count == 0 and len(res.unassigned) == 2)

    res = matcher.match_files([mk("arrow.cur"), mk("normal_select.cur"),
                               mk("default.cur")])
    slot = res.assignments["Arrow"]
    check("competing matches are surfaced, not silently chosen",
          bool(slot.rivals) and slot.confidence is Confidence.LOW,
          f"{len(slot.rivals)} rivals, {slot.confidence.label}")

    # A clean one-file-per-role pack should read as confident.
    clean = [mk(n) for n in (
        "Arrow.cur", "Help.cur", "AppStarting.ani", "Wait.ani",
        "Crosshair.cur", "IBeam.cur", "NWPen.cur", "No.cur", "SizeNS.cur",
        "SizeWE.cur", "SizeNWSE.cur", "SizeNESW.cur", "SizeAll.cur",
        "UpArrow.cur", "Hand.cur")]
    res = matcher.match_files(clean)
    check("a clean pack matches with high confidence",
          res.confident_count == 15, f"{res.confident_count}/15 confident")

    res = matcher.match_files([mk("arrow_xl.cur"), mk("arrow.cur")])
    check("the plain variant beats the size variant",
          res.assignments["Arrow"].file.name == "arrow.cur")

    files = [mk(f"f{i}.cur") for i in range(5)] + [mk("arrow.cur")]
    res = matcher.match_files(files)
    check("every file is accounted for",
          res.matched_count + len(res.unassigned) == len(files))


def test_sequences() -> None:
    section("Frame-sequence detection")
    grouped = scanner.group_sequences([mk(f"busy_{i:02d}.cur") for i in range(1, 9)])
    check("8 numbered frames collapse into one candidate",
          len(grouped) == 1 and grouped[0].frame_count == 8)

    grouped = scanner.group_sequences([mk("diagonal1.cur"), mk("diagonal2.cur")])
    check("diagonal1/diagonal2 stay two separate roles", len(grouped) == 2)
    res = matcher.match_files(grouped)
    check("  and map to the two diagonal roles",
          res.assignments["SizeNWSE"].filled and res.assignments["SizeNESW"].filled)

    grouped = scanner.group_sequences(
        [mk("cursor_2020.cur"), mk("shot_1999.cur"), mk("img_3.cur")])
    check("unrelated numbered files are not welded together", len(grouped) == 3)

    grouped = scanner.group_sequences([mk(f"busy_{i:02d}.cur") for i in range(1, 6)])
    res = matcher.match_files(grouped)
    check("a detected sequence still matches its role",
          res.assignments["Wait"].filled)


def test_scanner_filtering() -> None:
    section("Scanner filtering")
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        (td / "sub").mkdir()
        if WINDOWS_CURSORS.is_dir():
            real = (WINDOWS_CURSORS / "aero_arrow.cur").read_bytes()
            (td / "arrow.cur").write_bytes(real)
            (td / "sub" / "hand.cur").write_bytes(real)
        (td / "readme.txt").write_text("x")
        (td / "preview.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        (td / "license.md").write_text("x")

        res = scanner.scan_folder(td)
        check("subfolders are scanned", len(res.cursors) == 2,
              f"{len(res.cursors)} cursors")
        check("documentation files are ignored",
              all(c.path.suffix.lower() in (".cur", ".ani") for c in res.cursors))
        check("images are held separately as convertibles",
              all(c.kind is FileKind.CONVERTIBLE for c in res.convertibles))

        empty = td / "nothing"
        empty.mkdir()
        check("an empty folder yields an empty result, not a crash",
              scanner.scan_folder(empty).is_empty)


def test_registry_roundtrip() -> None:
    section("Registry apply / scheme / restore (opt-in)")
    import winreg
    from cursor_set_studio.core import registry

    KEY = r"Control Panel\Cursors"
    NAME = "CSS Selftest Scheme"

    snapshot = []
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, KEY) as k:
        i = 0
        while True:
            try:
                snapshot.append(winreg.EnumValue(k, i))
            except OSError:
                break
            i += 1
    print(f"      snapshot: {len(snapshot)} values")

    staged_dir = None
    try:
        res = scanner.scan_folder(WINDOWS_CURSORS)
        m = matcher.match_files(res.cursors)
        mapping, warnings = library.stage_scheme(NAME, m.assignments.values())
        staged_dir = Path(next(iter(mapping.values()))).parent

        check("files staged into managed storage",
              all(Path(p).is_file() for p in mapping.values()))
        check("staged files are named by role",
              all(Path(p).stem == k for k, p in mapping.items()))
        # Record it so the cleanup below removes the staged folder too.
        library.record_scheme(NAME, staged_dir, mapping,
                              library.write_thumbnail(mapping, staged_dir))

        registry.backup_current(original=True)
        check("backup written", registry.has_original_backup())

        check("live refresh succeeded",
              registry.apply_cursors(mapping, scheme_name=NAME))
        now = registry.read_current()
        check("registry points at the managed copy",
              now.roles.get("Arrow", "").lower() == mapping["Arrow"].lower())
        check("scheme name recorded", now.scheme_name == NAME)
        check("Scheme Source marked as user", now.scheme_source == 2)

        registry.save_scheme(NAME, mapping)
        schemes = registry.list_schemes()
        check("scheme registered for Mouse Properties", NAME in schemes)
        if NAME in schemes:
            check("scheme string has the 17 expected fields",
                  len(schemes[NAME]) == 17, str(len(schemes[NAME])))
            check("scheme string round-trips",
                  {k: v.lower() for k, v in
                   registry.scheme_to_roles(schemes[NAME]).items()}
                  == {k: v.lower() for k, v in mapping.items()})

        for bad, label in (
            ({}, "empty apply is blocked"),
            ({"Arrow": r"C:\does\not\exist.cur"}, "missing file is blocked"),
        ):
            try:
                registry.apply_cursors(bad)
                check(label, False)
            except registry.RegistryError:
                check(label, True)
        try:
            registry.save_scheme("bad,name", mapping)
            check("comma in a scheme name is blocked", False)
        except registry.RegistryError:
            check("comma in a scheme name is blocked", True)

    finally:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, KEY, 0,
                            winreg.KEY_SET_VALUE | winreg.KEY_READ) as k:
            existing = []
            i = 0
            while True:
                try:
                    existing.append(winreg.EnumValue(k, i)[0])
                except OSError:
                    break
                i += 1
            original = {n for n, _, _ in snapshot}
            for name in existing:
                if name not in original:
                    winreg.DeleteValue(k, name)
            for name, value, vtype in snapshot:
                winreg.SetValueEx(k, name, 0, vtype, value)

        try:
            registry.delete_scheme(NAME)
        except Exception:
            pass
        library.delete_scheme_record(NAME)
        registry.refresh_cursors()

        after = []
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, KEY) as k:
            i = 0
            while True:
                try:
                    after.append(winreg.EnumValue(k, i))
                except OSError:
                    break
                i += 1
        check("registry restored byte-identical",
              [(n, str(v), t) for n, v, t in snapshot]
              == [(n, str(v), t) for n, v, t in after])
        check("test scheme removed", NAME not in registry.list_schemes())


def main() -> int:
    print("Cursor Set Studio - core tests")
    tests = [
        test_codec_against_real_cursors,
        test_cur_roundtrip,
        test_ani_roundtrip,
        test_conversion_and_assembly,
        test_corrupt_files,
        test_matching,
        test_matching_guardrails,
        test_sequences,
        test_scanner_filtering,
    ]
    if "--registry" in sys.argv:
        tests.append(test_registry_roundtrip)
    else:
        print("\n(registry round-trip skipped; pass --registry to include it)")

    for t in tests:
        try:
            t()
        except Exception:
            _failed.append(t.__name__)
            print(f"  FAIL  {t.__name__} raised")
            traceback.print_exc()

    print("\n" + "=" * 58)
    if _failed:
        print(f"{_passed} passed, {len(_failed)} FAILED: {', '.join(_failed)}")
    else:
        print(f"All {_passed} checks passed.")
    print("=" * 58)
    return 1 if _failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
