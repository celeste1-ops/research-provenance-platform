"""Files the installers need that are generated, not checked in (DECISIONS D-044):

* build/prebuilt/verify.py — the checker every evidence bundle carries, assembled from the
  core library now, because the frozen app has no core sources on disk to assemble it from;
* build/icons/ — the app icon as PNGs (macOS iconset, for iconutil) and as a Windows .ico.

    uv run python packaging/prepare.py
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
sys.path.insert(0, str(ROOT))


def write_verify_py() -> Path:
    spec = importlib.util.spec_from_file_location("rprov_build_verify", ROOT / "tools" / "build_verify.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    out = BUILD / "prebuilt" / "verify.py"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(module.build_verify_source(), encoding="utf-8")
    return out


def app_icon(size: int):
    """Blue rounded square with a white stamp ring — the same mark as the menu bar icon."""
    from PIL import Image, ImageDraw

    scale = 4  # draw large, then shrink: smooth edges
    s = size * scale
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    pad = s // 10
    d.rounded_rectangle((pad, pad, s - pad, s - pad), radius=s // 5, fill=(47, 91, 211, 255))
    ring = s * 3 // 10
    d.ellipse((ring, ring, s - ring, s - ring), outline=(255, 255, 255, 255), width=max(2, s // 18))
    dot = s * 9 // 20
    d.ellipse((dot, dot, s - dot, s - dot), fill=(255, 255, 255, 255))
    return img.resize((size, size), Image.LANCZOS)


def write_icons() -> Path:
    icons = BUILD / "icons"
    iconset = icons / "app.iconset"
    iconset.mkdir(parents=True, exist_ok=True)
    for base in (16, 32, 128, 256, 512):  # names iconutil expects
        app_icon(base).save(iconset / f"icon_{base}x{base}.png")
        app_icon(base * 2).save(iconset / f"icon_{base}x{base}@2x.png")
    big = app_icon(256)
    big.save(icons / "app.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    app_icon(1024).save(icons / "app-1024.png")
    return icons


if __name__ == "__main__":
    print("verify.py:", write_verify_py())
    print("icons:", write_icons())
