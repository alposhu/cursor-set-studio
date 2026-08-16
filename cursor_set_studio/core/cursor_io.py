"""Reading and writing Windows cursor files.

The two community packages usually recommended for this (Iconolatry and
ani_file) are not usable here: Iconolatry was never published to PyPI, and
ani_file imports the stdlib `chunk` module, which PEP 594 removed in Python
3.13. Both formats are stable and well documented, so this module implements
them directly with `struct` and Pillow.

Formats implemented
-------------------
.cur  ICONDIR + ICONDIRENTRY records. Structurally an .ico, except that the
      wPlanes/wBitCount fields of each directory entry carry the hotspot
      (x, y) instead. Image payloads are either a PNG blob or a packed DIB
      (BITMAPINFOHEADER with a doubled height: a colour XOR bitmap followed
      by a 1-bpp AND transparency mask).

.ani  A RIFF container with form type ACON, holding an `anih` header chunk
      (36-byte ANIHEADER), a `LIST`/`fram` chunk of embedded .cur/.ico blobs
      one per frame, and optional `rate` (per-step duration in 1/60s jiffies)
      and `seq ` (playback order) chunks.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Optional, Sequence

from PIL import Image

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
JIFFY_MS = 1000.0 / 60.0          # one jiffy, in milliseconds
DEFAULT_JIFFIES = 6               # ~100ms, a sane default frame duration

# ANIHEADER.bfAttributes flags
AF_ICON = 0x0001                  # frames are .ico/.cur blobs, not raw DIBs
AF_SEQUENCE = 0x0002              # a `seq ` chunk is present


class CursorFormatError(Exception):
    """Raised when a file is not a readable cursor. Always caught by callers -
    one bad file must never take down a whole scan."""


@dataclass
class CursorImage:
    """One image inside a cursor file, at one resolution."""

    image: Image.Image             # always RGBA
    hotspot: tuple[int, int]

    @property
    def width(self) -> int:
        return self.image.width

    @property
    def height(self) -> int:
        return self.image.height


@dataclass
class AniData:
    """The decoded contents of an .ani file."""

    frames: list[bytes] = field(default_factory=list)   # raw .cur/.ico blobs
    rates: list[int] = field(default_factory=list)      # jiffies, per step
    sequence: list[int] = field(default_factory=list)   # frame index, per step
    width: int = 0
    height: int = 0
    display_rate: int = DEFAULT_JIFFIES
    name: str = ""
    artist: str = ""

    @property
    def step_count(self) -> int:
        return len(self.sequence) if self.sequence else len(self.frames)


# ---------------------------------------------------------------------------
# DIB decoding
# ---------------------------------------------------------------------------

def _decode_dib(data: bytes) -> Image.Image:
    """Decode a packed DIB (XOR colour bitmap + AND mask) into RGBA."""
    if len(data) < 40:
        raise CursorFormatError("DIB header truncated")

    (hdr_size, width, height_doubled, planes, bpp, compression,
     _size_image, _xppm, _yppm, clr_used, _clr_important) = struct.unpack_from(
        "<IiiHHIIiiII", data, 0)

    if hdr_size < 40:
        raise CursorFormatError(f"unsupported DIB header size {hdr_size}")
    if compression not in (0, 3):
        raise CursorFormatError(f"unsupported DIB compression {compression}")

    height = height_doubled // 2
    if width <= 0 or height <= 0:
        raise CursorFormatError(f"bad DIB dimensions {width}x{height}")
    if width > 1024 or height > 1024:
        raise CursorFormatError(f"implausible DIB dimensions {width}x{height}")

    offset = hdr_size

    # Palette, for the indexed depths.
    palette: list[tuple[int, int, int]] = []
    if bpp <= 8:
        count = clr_used or (1 << bpp)
        need = count * 4
        if len(data) < offset + need:
            raise CursorFormatError("DIB palette truncated")
        for i in range(count):
            b, g, r, _a = data[offset + i * 4: offset + i * 4 + 4]
            palette.append((r, g, b))
        offset += need

    xor_stride = ((width * bpp + 31) // 32) * 4
    and_stride = ((width + 31) // 32) * 4
    xor_size = xor_stride * height

    if len(data) < offset + xor_size:
        raise CursorFormatError("DIB pixel data truncated")

    xor = data[offset: offset + xor_size]
    and_off = offset + xor_size
    and_mask = data[and_off: and_off + and_stride * height]
    has_and = len(and_mask) >= and_stride * height

    # Fast path: let Pillow's C raw decoder do the unpacking. Orientation -1
    # handles the bottom-up row order. Falls back to a pure-Python loop for
    # anything the raw decoder will not take.
    RAW = {32: "BGRA", 24: "BGR", 8: "P", 4: "P;4", 1: "P;1"}
    if bpp not in RAW:
        raise CursorFormatError(f"unsupported bit depth {bpp}")

    try:
        if bpp == 32:
            img = Image.frombytes("RGBA", (width, height), xor,
                                  "raw", ("BGRA", xor_stride, -1))
        elif bpp == 24:
            img = Image.frombytes("RGB", (width, height), xor,
                                  "raw", ("BGR", xor_stride, -1)).convert("RGBA")
        else:
            pal = Image.frombytes("P", (width, height), xor,
                                  "raw", (RAW[bpp], xor_stride, -1))
            flat: list[int] = []
            for r, g, b in palette:
                flat += [r, g, b]
            flat += [0] * (768 - len(flat))
            pal.putpalette(flat)
            img = pal.convert("RGBA")
    except Exception:
        img = _decode_dib_slow(width, height, bpp, xor, xor_stride, palette)

    # A 32-bpp image whose alpha channel is entirely zero is really an opaque
    # image relying on the AND mask, so only trust alpha when some is set.
    use_alpha = bpp == 32 and img.getextrema()[3][1] > 0

    if has_and and not use_alpha:
        try:
            # 1 in the AND mask means transparent, so invert it into an alpha
            # channel: opaque (255) wherever the mask bit is 0.
            mask = Image.frombytes("1", (width, height), and_mask,
                                   "raw", ("1;I", and_stride, -1)).convert("L")
        except Exception:
            mask = _and_mask_slow(width, height, and_mask, and_stride)
        img.putalpha(mask)
    elif not use_alpha:
        img.putalpha(255)                    # no mask and no alpha: opaque

    return img


def _decode_dib_slow(width, height, bpp, xor, xor_stride, palette) -> Image.Image:
    """Per-pixel fallback for DIB layouts Pillow's raw decoder rejects."""
    img = Image.new("RGBA", (width, height))
    px = img.load()
    for y in range(height):
        row = (height - 1 - y) * xor_stride  # rows are stored bottom-up
        for x in range(width):
            if bpp == 32:
                i = row + x * 4
                b, g, r, a = xor[i], xor[i + 1], xor[i + 2], xor[i + 3]
            elif bpp == 24:
                i = row + x * 3
                b, g, r, a = xor[i], xor[i + 1], xor[i + 2], 255
            elif bpp == 8:
                idx = xor[row + x]
                r, g, b = palette[idx] if idx < len(palette) else (0, 0, 0)
                a = 255
            elif bpp == 4:
                byte = xor[row + (x >> 1)]
                idx = (byte >> 4) if (x & 1) == 0 else (byte & 0x0F)
                r, g, b = palette[idx] if idx < len(palette) else (0, 0, 0)
                a = 255
            else:
                byte = xor[row + (x >> 3)]
                idx = (byte >> (7 - (x & 7))) & 1
                r, g, b = palette[idx] if idx < len(palette) else (0, 0, 0)
                a = 255
            px[x, y] = (r, g, b, a)
    return img


def _and_mask_slow(width, height, and_mask, and_stride) -> Image.Image:
    """Per-pixel fallback that turns an AND mask into an alpha channel."""
    mask = Image.new("L", (width, height), 255)
    mp = mask.load()
    for y in range(height):
        row = (height - 1 - y) * and_stride
        for x in range(width):
            if (and_mask[row + (x >> 3)] >> (7 - (x & 7))) & 1:
                mp[x, y] = 0
    return mask


def _encode_dib(img: Image.Image) -> bytes:
    """Encode an RGBA image as a 32-bpp packed DIB with an AND mask."""
    img = img.convert("RGBA")
    w, h = img.size
    flipped = img.transpose(Image.Transpose.FLIP_TOP_BOTTOM)   # DIBs are bottom-up

    xor = flipped.tobytes("raw", "BGRA")

    # AND mask: one bit per pixel, set where the pixel is fully transparent,
    # rows padded out to a 4-byte boundary.
    transparent = flipped.getchannel("A").point(
        lambda a: 255 if a == 0 else 0).convert("1", dither=Image.Dither.NONE)
    packed = transparent.tobytes("raw", "1")
    row_bytes = (w + 7) // 8
    and_stride = ((w + 31) // 32) * 4
    and_mask = b"".join(
        packed[i * row_bytes:(i + 1) * row_bytes].ljust(and_stride, bytes(1))
        for i in range(h))

    header = struct.pack(
        "<IiiHHIIiiII",
        40, w, h * 2, 1, 32, 0,
        len(xor) + len(and_mask), 0, 0, 0, 0)
    return bytes(header + xor + and_mask)


# ---------------------------------------------------------------------------
# .cur / .ico
# ---------------------------------------------------------------------------

def read_cur_bytes(data: bytes, *, source: str = "<bytes>") -> list[CursorImage]:
    """Decode every image in a .cur/.ico blob."""
    if len(data) < 6:
        raise CursorFormatError(f"{source}: file too small to be a cursor")

    reserved, ftype, count = struct.unpack_from("<HHH", data, 0)
    if reserved != 0 or ftype not in (1, 2):
        raise CursorFormatError(f"{source}: not an .ico/.cur (type={ftype})")
    if count == 0:
        raise CursorFormatError(f"{source}: contains no images")
    if len(data) < 6 + count * 16:
        raise CursorFormatError(f"{source}: directory truncated")

    out: list[CursorImage] = []
    for i in range(count):
        off = 6 + i * 16
        (bw, bh, _colors, _res, planes, bits, size, data_off) = struct.unpack_from(
            "<BBBBHHII", data, off)

        width = bw or 256
        height = bh or 256

        if data_off + size > len(data) or size == 0:
            continue                         # skip this entry, keep the rest

        blob = data[data_off: data_off + size]

        # For .cur the planes/bits fields hold the hotspot; for .ico they are
        # genuinely planes/bits, and a sensible hotspot is the top-left.
        hotspot = (planes, bits) if ftype == 2 else (0, 0)

        try:
            if blob.startswith(PNG_MAGIC):
                image = Image.open(BytesIO(blob)).convert("RGBA")
            else:
                image = _decode_dib(blob)
        except CursorFormatError:
            continue
        except Exception as exc:
            raise CursorFormatError(f"{source}: image {i} unreadable ({exc})") from exc

        # Clamp a nonsense hotspot rather than rejecting the whole file.
        hx = min(max(hotspot[0], 0), max(image.width - 1, 0))
        hy = min(max(hotspot[1], 0), max(image.height - 1, 0))
        out.append(CursorImage(image=image, hotspot=(hx, hy)))

    if not out:
        raise CursorFormatError(f"{source}: no decodable images")
    return out


def read_cur(path: Path) -> list[CursorImage]:
    try:
        data = Path(path).read_bytes()
    except OSError as exc:
        raise CursorFormatError(f"{Path(path).name}: cannot read ({exc})") from exc
    return read_cur_bytes(data, source=Path(path).name)


def write_cur_bytes(images: Sequence[CursorImage]) -> bytes:
    """Build a .cur blob holding one entry per supplied image."""
    if not images:
        raise CursorFormatError("cannot write a cursor with no images")

    blobs = [_encode_dib(ci.image) for ci in images]

    header = struct.pack("<HHH", 0, 2, len(images))
    entries = bytearray()
    offset = 6 + len(images) * 16
    for ci, blob in zip(images, blobs):
        w = 0 if ci.width >= 256 else ci.width
        h = 0 if ci.height >= 256 else ci.height
        hx = min(max(ci.hotspot[0], 0), max(ci.width - 1, 0))
        hy = min(max(ci.hotspot[1], 0), max(ci.height - 1, 0))
        entries += struct.pack("<BBBBHHII", w, h, 0, 0, hx, hy, len(blob), offset)
        offset += len(blob)

    return bytes(header + entries + b"".join(blobs))


def write_cur(images: Sequence[CursorImage], path: Path) -> None:
    Path(path).write_bytes(write_cur_bytes(images))


# ---------------------------------------------------------------------------
# .ani
# ---------------------------------------------------------------------------

def _riff_chunks(data: bytes, start: int, end: int):
    """Yield (fourcc, payload_start, payload_len) over a RIFF chunk list."""
    pos = start
    while pos + 8 <= end:
        fourcc = data[pos: pos + 4]
        (size,) = struct.unpack_from("<I", data, pos + 4)
        body = pos + 8
        if body + size > end:
            size = end - body                # tolerate a truncated final chunk
            if size <= 0:
                return
        yield fourcc, body, size
        pos = body + size + (size & 1)       # chunks are padded to even length


def read_ani(path: Path) -> AniData:
    p = Path(path)
    try:
        data = p.read_bytes()
    except OSError as exc:
        raise CursorFormatError(f"{p.name}: cannot read ({exc})") from exc

    if len(data) < 12 or data[0:4] != b"RIFF" or data[8:12] != b"ACON":
        raise CursorFormatError(f"{p.name}: not a RIFF/ACON animated cursor")

    (riff_size,) = struct.unpack_from("<I", data, 4)
    end = min(len(data), 8 + riff_size)

    ani = AniData()
    seen_anih = False

    for fourcc, body, size in _riff_chunks(data, 12, end):
        if fourcc == b"anih":
            if size < 36:
                raise CursorFormatError(f"{p.name}: anih chunk truncated")
            (_cb, _n_frames, _n_steps, width, height, _bits, _planes,
             disp_rate, _attrs) = struct.unpack_from("<9I", data, body)
            ani.width, ani.height = width, height
            ani.display_rate = disp_rate or DEFAULT_JIFFIES
            seen_anih = True

        elif fourcc == b"rate":
            ani.rates = list(struct.unpack_from(f"<{size // 4}I", data, body))

        elif fourcc == b"seq ":
            ani.sequence = list(struct.unpack_from(f"<{size // 4}I", data, body))

        elif fourcc == b"LIST":
            list_type = data[body: body + 4]
            if list_type == b"fram":
                for sub, sbody, ssize in _riff_chunks(data, body + 4, body + size):
                    if sub == b"icon":
                        ani.frames.append(data[sbody: sbody + ssize])
            elif list_type == b"INFO":
                for sub, sbody, ssize in _riff_chunks(data, body + 4, body + size):
                    text = data[sbody: sbody + ssize].split(b"\x00")[0]
                    decoded = text.decode("utf-8", "replace")
                    if sub == b"INAM":
                        ani.name = decoded
                    elif sub == b"IART":
                        ani.artist = decoded

    if not seen_anih:
        raise CursorFormatError(f"{p.name}: missing anih header chunk")
    if not ani.frames:
        raise CursorFormatError(f"{p.name}: contains no frames")

    # Drop a sequence that points outside the frame list rather than trusting it.
    if ani.sequence and any(i >= len(ani.frames) for i in ani.sequence):
        ani.sequence = []

    if not ani.width or not ani.height:
        try:
            first = read_cur_bytes(ani.frames[0], source=p.name)[0]
            ani.width, ani.height = first.width, first.height
        except CursorFormatError:
            pass

    return ani


def _riff_chunk(fourcc: bytes, payload: bytes) -> bytes:
    out = fourcc + struct.pack("<I", len(payload)) + payload
    if len(payload) & 1:
        out += b"\x00"                       # pad to even
    return out


def write_ani(
    frames: Sequence[bytes],
    path: Path,
    *,
    rates: Optional[Sequence[int]] = None,
    sequence: Optional[Sequence[int]] = None,
    width: int = 0,
    height: int = 0,
    name: str = "",
    artist: str = "",
) -> None:
    """Assemble an .ani from a list of .cur/.ico blobs, one per frame."""
    if not frames:
        raise CursorFormatError("cannot write an animated cursor with no frames")

    n_frames = len(frames)
    steps = list(sequence) if sequence else []
    n_steps = len(steps) if steps else n_frames

    if not width or not height:
        try:
            first = read_cur_bytes(frames[0])[0]
            width, height = first.width, first.height
        except CursorFormatError:
            width = height = 32

    rate_list = list(rates) if rates else [DEFAULT_JIFFIES] * n_steps
    if len(rate_list) != n_steps:            # normalise a mismatched rate list
        rate_list = (rate_list + [DEFAULT_JIFFIES] * n_steps)[:n_steps]

    attrs = AF_ICON | (AF_SEQUENCE if steps else 0)
    anih = struct.pack(
        "<9I", 36, n_frames, n_steps, width, height, 32, 1,
        rate_list[0] if rate_list else DEFAULT_JIFFIES, attrs)

    body = bytearray(b"ACON")

    if name or artist:
        info = bytearray(b"INFO")
        if name:
            info += _riff_chunk(b"INAM", name.encode("utf-8") + b"\x00")
        if artist:
            info += _riff_chunk(b"IART", artist.encode("utf-8") + b"\x00")
        body += _riff_chunk(b"LIST", bytes(info))

    body += _riff_chunk(b"anih", anih)
    body += _riff_chunk(b"rate", struct.pack(f"<{n_steps}I", *rate_list))
    if steps:
        body += _riff_chunk(b"seq ", struct.pack(f"<{n_steps}I", *steps))

    fram = bytearray(b"fram")
    for blob in frames:
        fram += _riff_chunk(b"icon", blob)
    body += _riff_chunk(b"LIST", bytes(fram))

    Path(path).write_bytes(_riff_chunk(b"RIFF", bytes(body)))


# ---------------------------------------------------------------------------
# High-level helpers used by the rest of the app
# ---------------------------------------------------------------------------

@dataclass
class Probe:
    """Cheap metadata about a cursor file, for the scan pass."""

    width: int
    height: int
    hotspot: tuple[int, int]
    frame_count: int


def probe(path: Path) -> Probe:
    """Read just enough of a file to describe it. Raises CursorFormatError."""
    p = Path(path)
    ext = p.suffix.lower()

    if ext == ".ani":
        ani = read_ani(p)
        hotspot = (0, 0)
        try:
            hotspot = read_cur_bytes(ani.frames[0], source=p.name)[0].hotspot
        except CursorFormatError:
            pass
        return Probe(ani.width, ani.height, hotspot, len(ani.frames))

    if ext in (".cur", ".ico"):
        images = read_cur(p)
        best = _pick_best(images)
        return Probe(best.width, best.height, best.hotspot, 1)

    if ext == ".png":
        try:
            with Image.open(p) as im:
                w, h = im.size
        except Exception as exc:
            raise CursorFormatError(f"{p.name}: unreadable image ({exc})") from exc
        return Probe(w, h, (0, 0), 1)

    raise CursorFormatError(f"{p.name}: unsupported extension {ext}")


def _pick_best(images: Sequence[CursorImage], target: int = 32) -> CursorImage:
    """Pick the image closest to `target`, preferring the larger on a tie."""
    return min(images, key=lambda ci: (abs(ci.width - target), -ci.width))


def load_frames(path: Path, target: int = 32) -> list[tuple[Image.Image, int]]:
    """Load a file as animation frames: a list of (RGBA image, duration_ms).

    Static cursors come back as a single frame with a duration of 0.
    """
    p = Path(path)
    ext = p.suffix.lower()

    if ext == ".ani":
        ani = read_ani(p)
        decoded: list[Optional[Image.Image]] = []
        for blob in ani.frames:
            try:
                decoded.append(_pick_best(read_cur_bytes(blob, source=p.name), target).image)
            except CursorFormatError:
                decoded.append(None)

        steps = ani.sequence or list(range(len(ani.frames)))
        out: list[tuple[Image.Image, int]] = []
        for step, frame_index in enumerate(steps):
            img = decoded[frame_index] if frame_index < len(decoded) else None
            if img is None:
                continue
            jiffies = ani.rates[step] if step < len(ani.rates) else ani.display_rate
            out.append((img, max(int(jiffies * JIFFY_MS), 10)))
        if not out:
            raise CursorFormatError(f"{p.name}: no decodable frames")
        return out

    if ext in (".cur", ".ico"):
        return [(_pick_best(read_cur(p), target).image, 0)]

    if ext == ".png":
        with Image.open(p) as im:
            return [(im.convert("RGBA"), 0)]

    raise CursorFormatError(f"{p.name}: unsupported extension {ext}")


def default_hotspot_for(img: Image.Image, mode) -> tuple[int, int]:
    """Pick a starting hotspot for an image that carries no metadata."""
    from .models import HotspotDefault
    if mode is HotspotDefault.TOP_LEFT:
        # Not exactly (0,0): art is usually inset a little from the corner.
        return (max(img.width // 16, 0), max(img.height // 16, 0))
    return (img.width // 2, img.height // 2)


def image_to_cur(
    img: Image.Image,
    hotspot: tuple[int, int],
    path: Path,
    *,
    sizes: Sequence[int] = (32,),
) -> None:
    """Convert a raw image into a .cur, scaling the hotspot with each size."""
    img = img.convert("RGBA")
    base_w, base_h = img.size

    images: list[CursorImage] = []
    for size in sizes:
        scaled = img if (base_w, base_h) == (size, size) else img.resize(
            (size, size), Image.Resampling.LANCZOS)
        hx = round(hotspot[0] * size / base_w) if base_w else 0
        hy = round(hotspot[1] * size / base_h) if base_h else 0
        images.append(CursorImage(scaled, (min(hx, size - 1), min(hy, size - 1))))

    write_cur(images, path)


def build_ani_from_frames(
    frame_paths: Sequence[Path],
    path: Path,
    *,
    jiffies: int = DEFAULT_JIFFIES,
    name: str = "",
) -> None:
    """Combine numbered .cur/.png frame files into one .ani.

    Existing .cur frames are embedded byte-for-byte so their hotspots survive
    exactly; images are converted first, taking the hotspot of the first
    already-cursor frame if there is one.
    """
    if not frame_paths:
        raise CursorFormatError("no frames supplied")

    blobs: list[bytes] = []
    errors: list[str] = []
    hotspot: Optional[tuple[int, int]] = None

    for fp in frame_paths:
        fp = Path(fp)
        try:
            if fp.suffix.lower() in (".cur", ".ico"):
                data = fp.read_bytes()
                images = read_cur_bytes(data, source=fp.name)
                if hotspot is None:
                    hotspot = _pick_best(images).hotspot
                blobs.append(data)
            else:
                with Image.open(fp) as im:
                    rgba = im.convert("RGBA")
                spot = hotspot or (rgba.width // 2, rgba.height // 2)
                blobs.append(write_cur_bytes([CursorImage(rgba, spot)]))
        except (CursorFormatError, OSError, ValueError) as exc:
            errors.append(f"{fp.name}: {exc}")

    if not blobs:
        raise CursorFormatError(
            "no frames could be read: " + "; ".join(errors[:3]))

    write_ani(blobs, path, rates=[jiffies] * len(blobs), name=name)
