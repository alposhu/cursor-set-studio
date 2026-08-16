"""Regenerate the bundled icon assets from the source artwork.

    .venv\\Scripts\\python build_assets\\make_icons.py

Reads logo.png in the repository root and writes:

    cursor_set_studio/assets/logo.png   512px, used in the title bar and
                                        on the import screen
    cursor_set_studio/assets/logo.ico   16-256px, the window, taskbar and
                                        executable icon

Only needs re-running if the source artwork changes.
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "logo.png"
ASSETS = ROOT / "cursor_set_studio" / "assets"

ICO_SIZES = [16, 24, 32, 48, 64, 128, 256]


def main() -> int:
    if not SRC.is_file():
        print(f"source artwork not found: {SRC}", file=sys.stderr)
        return 1

    ASSETS.mkdir(parents=True, exist_ok=True)
    src = Image.open(SRC).convert("RGBA")

    # The artwork is a rounded square wrapped in a soft glow. Crop to the solid
    # body: downscaling the glow turns a 16px icon into a blue smudge.
    solid = src.getchannel("A").point(lambda a: 255 if a > 235 else 0)
    box = solid.getbbox()
    if box is None:
        print("artwork appears to be fully transparent", file=sys.stderr)
        return 1

    pad = int(min(src.size) * 0.02)          # keep a hint of the glow
    box = (max(box[0] - pad, 0), max(box[1] - pad, 0),
           min(box[2] + pad, src.width), min(box[3] + pad, src.height))
    body = src.crop(box)

    # Square it so nothing is distorted when resized.
    side = max(body.size)
    square = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    square.paste(body, ((side - body.width) // 2, (side - body.height) // 2))

    square.resize((512, 512), Image.Resampling.LANCZOS).save(ASSETS / "logo.png")

    # Save from a full-resolution frame: Pillow downsamples to each requested
    # size and cannot invent detail if handed a small one to start from.
    square.resize((256, 256), Image.Resampling.LANCZOS).save(
        ASSETS / "logo.ico", format="ICO", sizes=[(s, s) for s in ICO_SIZES])

    with Image.open(ASSETS / "logo.ico") as ico:
        got = sorted(s[0] for s in ico.ico.sizes())
    print(f"logo.png  512px")
    print(f"logo.ico  {got}")
    if got != sorted(ICO_SIZES):
        print("warning: not every requested size was embedded", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
