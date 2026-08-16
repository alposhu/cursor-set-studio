"""Conversion matrix and archive extraction tests.

Covers all twelve cross-format conversions, what each one preserves, and
the three archive types. Anything the machine cannot provide (7-Zip, a
sample .rar) is skipped rather than failed, so this is safe to run in CI.
"""
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image
from cursor_set_studio.core import archives, converter, cursor_io
from cursor_set_studio.core.converter import ConvertOptions, Target

WIN = Path(r"C:\Windows\Cursors")
passed, failed = 0, []


def check(label, cond, detail=""):
    global passed
    if cond:
        passed += 1
    else:
        failed.append(label)
    print(f"  {'ok  ' if cond else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


print("=" * 60)
print("CONVERSION MATRIX")
print("=" * 60)

tmp = Path(tempfile.mkdtemp(prefix="convtest_"))
src = tmp / "src"; src.mkdir()

# Build one real source of each type.
png = src / "sample.png"
im = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
for i in range(50):
    im.putpixel((i, i), (255, 40, 40, 255))
    im.putpixel((i, 50 - i), (40, 120, 255, 255))
im.save(png)

cur = src / "sample.cur"
cursor_io.image_to_cur(im, (7, 3), cur, sizes=(32, 48))

ico = src / "sample.ico"
cursor_io.write_ico([cursor_io.CursorImage(im, (0, 0))], ico)

ani = src / "sample.ani"
blobs = []
for k in range(4):
    f = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
    for x in range(32):
        f.putpixel((x, (k * 8) % 32), (0, 255, 0, 255))
    blobs.append(cursor_io.write_cur_bytes([cursor_io.CursorImage(f, (5, 9))]))
cursor_io.write_ani(blobs, ani, rates=[8] * 4)

SOURCES = {"PNG": png, "ICO": ico, "CUR": cur, "ANI": ani}

# Every one of the 12 cross-format conversions.
for sname, spath in SOURCES.items():
    for target in Target:
        if target.label == sname:
            continue
        out = tmp / f"{sname}_to_{target.label}"
        rep = converter.convert_files([spath], target, out, ConvertOptions())
        r = rep.results[0]
        ok = r.ok and r.outputs and all(p.is_file() for p in r.outputs)
        detail = (f"{len(r.outputs)} file(s)" + (f", {r.note}" if r.note else "")) if ok else str(r.error)
        check(f"{sname} -> {target.label}", ok, detail)
        # Anything we wrote must be readable back.
        if ok:
            for p in r.outputs:
                try:
                    if p.suffix.lower() == ".png":
                        Image.open(p).verify()
                    elif p.suffix.lower() == ".ani":
                        cursor_io.read_ani(p)
                    else:
                        cursor_io.read_cur(p)
                except Exception as exc:
                    check(f"   {sname}->{target.label} output valid", False, str(exc))

print()
print("=" * 60)
print("SEMANTICS")
print("=" * 60)

# Hotspot must survive CUR -> ANI.
out = tmp / "hs1"
converter.convert_files([cur], Target.ANI, out, ConvertOptions())
a = cursor_io.read_ani(out / "sample.ani")
hs = cursor_io.read_cur_bytes(a.frames[0])[0].hotspot
expected = cursor_io._pick_best(cursor_io.read_cur(cur)).hotspot
check("CUR -> ANI preserves the hotspot", hs == expected,
      f"got {hs}, source entry has {expected}")

# ANI -> CUR keeps the frame's hotspot.
out = tmp / "hs2"
converter.convert_files([ani], Target.CUR, out, ConvertOptions())
got = cursor_io.read_cur(out / "sample.cur")[0]
check("ANI -> CUR preserves the hotspot", got.hotspot == (5, 9), str(got.hotspot))

# PNG -> CUR uses the supplied hotspot, scaled per size.
out = tmp / "hs3"
converter.convert_files([png], Target.CUR, out,
                        ConvertOptions(sizes=(32,), hotspot=(16, 16)))
got = cursor_io.read_cur(out / "sample.cur")[0]
check("PNG -> CUR applies the given hotspot", got.hotspot == (8, 8), str(got.hotspot))

# ICO output must be type 1 and carry no hotspot.
out = tmp / "ico1"
converter.convert_files([cur], Target.ICO, out, ConvertOptions())
import struct
blob = (out / "sample.ico").read_bytes()
check("CUR -> ICO writes a real icon (type 1)",
      struct.unpack_from("<HHH", blob)[1] == 1)

# Multi-size .cur keeps both resolutions through to .ico.
sizes = [c.width for c in cursor_io.read_cur(out / "sample.ico")]
check("CUR -> ICO keeps every resolution", sorted(sizes) == [32, 48], str(sizes))

# ANI -> PNG writes one file per frame.
out = tmp / "png1"
rep = converter.convert_files([ani], Target.PNG, out, ConvertOptions(all_frames=True))
check("ANI -> PNG writes every frame", len(rep.results[0].outputs) == 4,
      f"{len(rep.results[0].outputs)} files")

# ANI -> PNG first-frame-only mode.
out = tmp / "png2"
rep = converter.convert_files([ani], Target.PNG, out, ConvertOptions(all_frames=False))
check("ANI -> PNG can write just one frame", len(rep.results[0].outputs) == 1)

# Combine several stills into one animation.
out = tmp / "comb"
frames = []
for i in range(5):
    f = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
    f.putpixel((i, i), (255, 255, 255, 255))
    fp = src / f"walk_{i+1:02d}.png"
    f.save(fp)
    frames.append(fp)
rep = converter.convert_files(frames, Target.ANI, out,
                              ConvertOptions(combine=True, jiffies=5))
built = rep.results[0].outputs
ok = len(built) == 1 and built[0].name == "walk.ani"
check("combine mode makes one .ani named from the run", ok,
      str([p.name for p in built]))
if ok:
    fr = cursor_io.load_frames(built[0])
    check("  combined animation has every frame", len(fr) == 5, f"{len(fr)}")
    check("  frame rate honoured", abs(fr[0][1] - 83) < 6, f"{fr[0][1]}ms")

# Animation timing survives ANI -> ANI-style rebuild via combine of one ani.
out = tmp / "retime"
converter.convert_files([ani], Target.ANI, out, ConvertOptions())
# (ani -> ani is refused as a no-op; verify that)
rep = converter.convert_files([ani], Target.ANI, tmp / "noop", ConvertOptions())
check("same-format conversion is refused as a no-op",
      not rep.results[0].ok, str(rep.results[0].error))

# A bad file must not stop the batch.
bad = src / "broken.cur"
bad.write_bytes(b"definitely not a cursor")
rep = converter.convert_files([bad, png], Target.ICO, tmp / "batch", ConvertOptions())
check("one bad input does not stop the batch",
      rep.succeeded == 1 and len(rep.failures) == 1,
      f"{rep.succeeded} ok, {len(rep.failures)} failed")

# Existing files are not silently clobbered.
out = tmp / "dup"
converter.convert_files([png], Target.ICO, out, ConvertOptions())
converter.convert_files([png], Target.ICO, out, ConvertOptions())
names = sorted(p.name for p in out.iterdir())
check("a second conversion does not overwrite the first",
      names == ["sample (2).ico", "sample.ico"], str(names))

# Real Windows cursors through the matrix.
if WIN.is_dir():
    for t in (Target.PNG, Target.ICO, Target.ANI):
        # Exclude inputs already in the target format; that is refused by
        # design and tested separately.
        real = [p for p in (WIN / "aero_arrow.cur", WIN / "aero_busy.ani")
                if p.suffix.lower() != t.extension]
        rep = converter.convert_files(real, t, tmp / f"real_{t.label}",
                                      ConvertOptions())
        check(f"real Windows cursors -> {t.label}",
              rep.succeeded == len(real),
              f"{rep.succeeded}/{len(real)}; {[r.error for r in rep.failures]}")

print()
print("=" * 60)
print("ARCHIVES")
print("=" * 60)
print("  backends:", archives.available_backends())

arc = tmp / "arc"; arc.mkdir()
pack = tmp / "pack"; pack.mkdir()
(pack / "sub").mkdir()
if WIN.is_dir():
    for n in ("aero_arrow.cur", "aero_busy.ani"):
        (pack / n).write_bytes((WIN / n).read_bytes())
    (pack / "sub" / "aero_link.cur").write_bytes((WIN / "aero_link.cur").read_bytes())
(pack / "readme.txt").write_text("hi")

zpath = arc / "pack.zip"
with zipfile.ZipFile(zpath, "w") as zf:
    for p in pack.rglob("*"):
        if p.is_file():
            zf.write(p, p.relative_to(pack).as_posix())

res = archives.extract(zpath)
try:
    found = list(res.directory.rglob("*.cur")) + list(res.directory.rglob("*.ani"))
    check("zip extracts (stdlib)", len(found) == 3, f"{len(found)} cursors, backend={res.backend}")
    check("zip preserves subfolders",
          any(p.parent.name == "sub" for p in found))
finally:
    res.cleanup()
check("temp dir cleaned up", not res.directory.exists())

# 7z via bsdtar
seven = archives._sevenzip()
if seven:
    s7 = arc / "pack.7z"
    subprocess.run([str(seven), "a", "-t7z", str(s7), str(pack / "*")],
                   capture_output=True)
    if s7.is_file():
        res = archives.extract(s7)
        try:
            found = list(res.directory.rglob("*.cur")) + list(res.directory.rglob("*.ani"))
            check("7z extracts", len(found) >= 2, f"{len(found)} cursors, backend={res.backend}")
        finally:
            res.cleanup()
else:
    print("  (7-Zip not installed; skipping 7z creation test)")

# Real .rar from the user's machine
rar = next((p for p in Path.home().glob("Downloads/*.rar")), None)
if rar is not None:
    res = archives.extract(rar)
    try:
        files = [p for p in res.directory.rglob("*") if p.is_file()]
        check("real .rar extracts", len(files) > 0,
              f"{len(files)} files, backend={res.backend}")
    finally:
        res.cleanup()
else:
    print("  (no .rar available to test)")

# Path traversal must be refused.
eviluser = arc / "evil.zip"
with zipfile.ZipFile(eviluser, "w") as zf:
    zf.writestr("../../../ESCAPED.txt", "should never be written")
    zf.writestr("good.cur", b"x" * 10)
res = archives.extract(eviluser)
try:
    escaped = (res.directory.parent.parent.parent / "ESCAPED.txt")
    check("path traversal is blocked", not escaped.exists() and len(res.skipped) == 1,
          f"skipped={res.skipped}")
finally:
    res.cleanup()

# Non-archive and corrupt archive handling.
for name, data, label in (
    ("notanarchive.zip", b"garbage", "corrupt zip reports an error"),
    ("nope.tar", b"x", "unsupported type reports an error"),
):
    p = arc / name
    p.write_bytes(data)
    try:
        r = archives.extract(p)
        r.cleanup()
        check(label, False, "no error raised")
    except archives.ArchiveError:
        check(label, True)

print()
print("=" * 60)
print(f"{passed} passed, {len(failed)} failed" +
      (": " + ", ".join(failed) if failed else ""))
print("=" * 60)

import shutil as sh
sh.rmtree(tmp, ignore_errors=True)
sys.exit(1 if failed else 0)
