"""Conversion between the four cursor-adjacent formats.

Every source is first decoded into a common intermediate - a list of frames,
each with an image, an optional hotspot and a duration - and every target is
then written from that. So the twelve conversions are four readers and four
writers rather than twelve special cases.

              PNG      ICO      CUR      ANI
    PNG        -        yes      yes      yes
    ICO       yes        -       yes      yes
    CUR       yes       yes       -       yes
    ANI       yes       yes      yes       -

What is preserved, and what cannot be:

* Hotspots survive CUR->CUR-like conversions and CUR/ANI->CUR. Icons and PNGs
  have nowhere to store one, so converting to those drops it; converting from
  them needs a hotspot to be supplied or defaulted.
* Multiple resolutions inside an .ico/.cur survive to .ico/.cur, and can be
  written out individually as PNGs.
* Animation frames survive to .ani. Converting an animation to a static format
  keeps one frame (the first by default), or every frame when writing PNGs.
"""
from __future__ import annotations

import enum
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Optional, Sequence

from PIL import Image

from . import cursor_io
from .cursor_io import CursorFormatError, CursorImage

SUPPORTED_INPUTS = {".png", ".ico", ".cur", ".ani"}


class Target(enum.Enum):
    PNG = "png"
    ICO = "ico"
    CUR = "cur"
    ANI = "ani"

    @property
    def extension(self) -> str:
        return f".{self.value}"

    @property
    def label(self) -> str:
        return self.value.upper()

    @property
    def animated(self) -> bool:
        return self is Target.ANI

    @property
    def carries_hotspot(self) -> bool:
        return self in (Target.CUR, Target.ANI)


@dataclass
class Frame:
    """One decoded image, with whatever metadata its source carried."""

    image: Image.Image
    hotspot: Optional[tuple[int, int]] = None
    duration_ms: int = 0


@dataclass
class Source:
    """A decoded input file."""

    path: Path
    frames: list[Frame]
    animated: bool
    # For .ico/.cur this holds every embedded resolution of the first frame.
    sizes: list[CursorImage] = field(default_factory=list)

    @property
    def native_hotspot(self) -> Optional[tuple[int, int]]:
        for f in self.frames:
            if f.hotspot is not None:
                return f.hotspot
        return None


@dataclass
class ConvertOptions:
    """How to perform a conversion."""

    # Output resolutions for .ico/.cur. None keeps whatever the source had
    # (or the source's own size, for a .png).
    sizes: Optional[tuple[int, ...]] = None
    # Hotspot for targets that carry one, when the source has none.
    hotspot: Optional[tuple[int, int]] = None
    centre_hotspot: bool = True          # used when `hotspot` is None
    # Frame duration for .ani output, in 1/60s jiffies.
    jiffies: int = cursor_io.DEFAULT_JIFFIES
    # Treat all inputs as frames of a single animation instead of converting
    # each one separately. Only meaningful for an .ani target.
    combine: bool = False
    # Write every frame of an animation / every embedded resolution, rather
    # than just the first. Only meaningful for a .png target.
    all_frames: bool = True
    overwrite: bool = False


@dataclass
class ConvertResult:
    source: Path
    outputs: list[Path] = field(default_factory=list)
    error: Optional[str] = None
    note: str = ""

    @property
    def ok(self) -> bool:
        return self.error is None


@dataclass
class ConvertReport:
    results: list[ConvertResult] = field(default_factory=list)

    @property
    def written(self) -> list[Path]:
        return [p for r in self.results for p in r.outputs]

    @property
    def failures(self) -> list[ConvertResult]:
        return [r for r in self.results if not r.ok]

    @property
    def succeeded(self) -> int:
        return sum(1 for r in self.results if r.ok)


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------

def load_source(path: Path) -> Source:
    """Decode any supported input into frames. Raises CursorFormatError."""
    path = Path(path)
    ext = path.suffix.lower()

    if ext == ".png":
        try:
            with Image.open(path) as im:
                frames = [Frame(im.convert("RGBA"))]
        except Exception as exc:
            raise CursorFormatError(f"{path.name}: unreadable image ({exc})") from exc
        return Source(path, frames, animated=False)

    if ext in (".ico", ".cur"):
        images = cursor_io.read_cur(path)
        best = cursor_io._pick_best(images)
        hotspot = best.hotspot if ext == ".cur" else None
        return Source(path, [Frame(best.image, hotspot)], animated=False,
                      sizes=list(images))

    if ext == ".ani":
        ani = cursor_io.read_ani(path)
        frames: list[Frame] = []
        steps = ani.sequence or list(range(len(ani.frames)))
        decoded: list[Optional[CursorImage]] = []
        for blob in ani.frames:
            try:
                decoded.append(cursor_io._pick_best(
                    cursor_io.read_cur_bytes(blob, source=path.name)))
            except CursorFormatError:
                decoded.append(None)

        for step, index in enumerate(steps):
            ci = decoded[index] if index < len(decoded) else None
            if ci is None:
                continue
            jiffies = (ani.rates[step] if step < len(ani.rates)
                       else ani.display_rate)
            frames.append(Frame(ci.image, ci.hotspot,
                                max(int(jiffies * cursor_io.JIFFY_MS), 10)))
        if not frames:
            raise CursorFormatError(f"{path.name}: no decodable frames")
        return Source(path, frames, animated=True)

    raise CursorFormatError(f"{path.name}: unsupported input type {ext}")


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------

def _resolve_hotspot(source: Source, frame: Frame,
                     options: ConvertOptions) -> tuple[int, int]:
    """Work out the hotspot for a target that needs one."""
    if frame.hotspot is not None:
        return frame.hotspot                 # the source carried a real one
    native = source.native_hotspot
    if native is not None:
        return native
    if options.hotspot is not None:
        return options.hotspot
    img = frame.image
    if options.centre_hotspot:
        return (img.width // 2, img.height // 2)
    return (0, 0)


def _scaled(image: Image.Image, size: int) -> Image.Image:
    if image.size == (size, size):
        return image
    return image.resize((size, size), Image.Resampling.LANCZOS)


def _build_images(source: Source, frame: Frame, options: ConvertOptions,
                  hotspot: Optional[tuple[int, int]]) -> list[CursorImage]:
    """Produce the per-resolution images for an .ico/.cur output."""
    if options.sizes:
        out: list[CursorImage] = []
        base_w = max(frame.image.width, 1)
        base_h = max(frame.image.height, 1)
        for size in options.sizes:
            scaled = _scaled(frame.image, size)
            if hotspot is None:
                spot = (0, 0)
            else:
                spot = (min(round(hotspot[0] * size / base_w), size - 1),
                        min(round(hotspot[1] * size / base_h), size - 1))
            out.append(CursorImage(scaled, spot))
        return out

    # No explicit sizes: keep every resolution the source already had.
    if source.sizes and not source.animated:
        return [CursorImage(ci.image, ci.hotspot if hotspot is None else hotspot)
                for ci in source.sizes]

    return [CursorImage(frame.image, hotspot or (0, 0))]


def _unique(path: Path, overwrite: bool) -> Path:
    if overwrite or not path.exists():
        return path
    for i in range(2, 1000):
        candidate = path.with_name(f"{path.stem} ({i}){path.suffix}")
        if not candidate.exists():
            return candidate
    raise CursorFormatError(f"could not find a free name near {path.name}")


def _write_png(source: Source, out_dir: Path, options: ConvertOptions,
               result: ConvertResult) -> None:
    stem = source.path.stem

    if source.animated and options.all_frames and len(source.frames) > 1:
        width = len(str(len(source.frames)))
        for i, frame in enumerate(source.frames, 1):
            dest = _unique(out_dir / f"{stem}_{i:0{width}d}.png", options.overwrite)
            frame.image.save(dest)
            result.outputs.append(dest)
        result.note = f"{len(source.frames)} frames"
        return

    # A multi-resolution icon or cursor: optionally write each size out.
    if source.sizes and len(source.sizes) > 1 and options.all_frames:
        for ci in source.sizes:
            dest = _unique(out_dir / f"{stem}_{ci.width}x{ci.height}.png",
                           options.overwrite)
            ci.image.save(dest)
            result.outputs.append(dest)
        result.note = f"{len(source.sizes)} sizes"
        return

    frame = source.frames[0]
    image = frame.image
    if options.sizes:
        image = _scaled(image, options.sizes[0])
    dest = _unique(out_dir / f"{stem}.png", options.overwrite)
    image.save(dest)
    result.outputs.append(dest)


def _write_static(source: Source, out_dir: Path, options: ConvertOptions,
                  result: ConvertResult, target: Target) -> None:
    frame = source.frames[0]
    hotspot = (_resolve_hotspot(source, frame, options)
               if target is Target.CUR else None)
    images = _build_images(source, frame, options, hotspot)

    dest = _unique(out_dir / f"{source.path.stem}{target.extension}",
                   options.overwrite)
    if target is Target.CUR:
        cursor_io.write_cur(images, dest)
    else:
        cursor_io.write_ico(images, dest)
    result.outputs.append(dest)

    if source.animated:
        result.note = "first frame"
    elif len(images) > 1:
        result.note = f"{len(images)} sizes"
    if target is Target.ICO and source.native_hotspot is not None:
        result.note = (result.note + ", hotspot dropped").lstrip(", ")


def _frames_to_ani(frames: Sequence[Frame], hotspots: Sequence[tuple[int, int]],
                   dest: Path, options: ConvertOptions, name: str) -> None:
    blobs: list[bytes] = []
    rates: list[int] = []
    for frame, hotspot in zip(frames, hotspots):
        image = frame.image
        if options.sizes:
            size = options.sizes[0]
            base_w, base_h = max(image.width, 1), max(image.height, 1)
            hotspot = (min(round(hotspot[0] * size / base_w), size - 1),
                       min(round(hotspot[1] * size / base_h), size - 1))
            image = _scaled(image, size)
        blobs.append(cursor_io.write_cur_bytes([CursorImage(image, hotspot)]))
        # Keep the source's own timing when it had some.
        if frame.duration_ms:
            rates.append(max(int(round(frame.duration_ms / cursor_io.JIFFY_MS)), 1))
        else:
            rates.append(options.jiffies)

    cursor_io.write_ani(blobs, dest, rates=rates, name=name)


def _write_ani(source: Source, out_dir: Path, options: ConvertOptions,
               result: ConvertResult) -> None:
    frames = source.frames
    hotspots = [_resolve_hotspot(source, f, options) for f in frames]
    dest = _unique(out_dir / f"{source.path.stem}.ani", options.overwrite)
    _frames_to_ani(frames, hotspots, dest, options, source.path.stem)
    result.outputs.append(dest)
    result.note = (f"{len(frames)} frames" if len(frames) > 1
                   else "single frame")


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------

def convert_files(
    paths: Iterable[Path],
    target: Target,
    out_dir: Path,
    options: Optional[ConvertOptions] = None,
    *,
    progress: Optional[Callable[[int, int], None]] = None,
) -> ConvertReport:
    """Convert each input to `target`, writing into `out_dir`.

    One bad input never stops the batch: it is recorded as a failed result and
    the rest continue.
    """
    options = options or ConvertOptions()
    paths = [Path(p) for p in paths]
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = ConvertReport()

    if target is Target.ANI and options.combine and len(paths) > 1:
        report.results.append(_combine_to_ani(paths, out_dir, options))
        if progress:
            progress(len(paths), len(paths))
        return report

    for i, path in enumerate(paths):
        result = ConvertResult(source=path)
        try:
            if path.suffix.lower() == target.extension:
                raise CursorFormatError(
                    f"already in {target.label} format")
            source = load_source(path)
            if target is Target.PNG:
                _write_png(source, out_dir, options, result)
            elif target is Target.ANI:
                _write_ani(source, out_dir, options, result)
            else:
                _write_static(source, out_dir, options, result, target)
        except CursorFormatError as exc:
            result.error = str(exc)
        except Exception as exc:
            result.error = f"unexpected error: {exc}"
        report.results.append(result)
        if progress:
            progress(i + 1, len(paths))

    return report


def _combine_to_ani(paths: Sequence[Path], out_dir: Path,
                    options: ConvertOptions) -> ConvertResult:
    """Treat several inputs as the frames of one animation."""
    result = ConvertResult(source=paths[0])
    frames: list[Frame] = []
    hotspots: list[tuple[int, int]] = []
    skipped: list[str] = []

    for path in paths:
        try:
            source = load_source(path)
            for frame in source.frames:
                frames.append(frame)
                hotspots.append(_resolve_hotspot(source, frame, options))
        except CursorFormatError as exc:
            skipped.append(f"{Path(path).name}: {exc}")

    if not frames:
        result.error = "no readable frames: " + "; ".join(skipped[:3])
        return result

    stem = Path(paths[0]).stem
    # Drop a trailing frame number so busy_01 + busy_02 becomes "busy.ani".
    import re
    stem = re.sub(r"[ _\-.]?\d+$", "", stem) or stem

    dest = _unique(out_dir / f"{stem}.ani", options.overwrite)
    try:
        _frames_to_ani(frames, hotspots, dest, options, stem)
    except CursorFormatError as exc:
        result.error = str(exc)
        return result

    result.outputs.append(dest)
    result.note = f"combined {len(frames)} frames"
    if skipped:
        result.note += f", skipped {len(skipped)}"
    return result


def describe(target: Target, sources: Sequence[Path]) -> str:
    """A short plain-language summary of what a conversion will do."""
    exts = {Path(p).suffix.lower().lstrip(".").upper() for p in sources}
    if not exts:
        return "Add files to convert."
    from_part = "/".join(sorted(exts))
    notes: list[str] = []
    if target is Target.ICO and {"CUR", "ANI"} & exts:
        notes.append("hotspots are dropped, icons cannot store one")
    if target in (Target.CUR, Target.ANI) and {"PNG", "ICO"} & exts:
        notes.append("a hotspot will be assigned")
    if target in (Target.PNG, Target.ICO, Target.CUR) and "ANI" in exts:
        notes.append("animations keep one frame"
                     if target is not Target.PNG else
                     "every animation frame is written out")
    tail = f" — {'; '.join(notes)}" if notes else ""
    return f"{from_part} → {target.label}{tail}"
