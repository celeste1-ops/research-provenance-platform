"""Draw the picture behind the icons in the macOS disk image window (DECISIONS D-052).

It tells people what to do after opening the downloaded .dmg — drag the app onto Applications,
then open it from there — in English and Chinese, with an arrow between the two icons. The
images are checked in (packaging/macos/dmg-background.png and @2x), so building the app needs
no Chinese font; to draw them again, give a font with Chinese characters:

    uv run python tools/dmg_background.py /usr/share/fonts/truetype/wqy/wqy-zenhei.ttc
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent.parent / "packaging" / "macos"
WIDTH, HEIGHT = 660, 400  # the window's content area; packaging/macos/dmg_settings.py matches it
APP_X, APPS_X, ICON_Y = 170, 490, 190  # icon centres
BLUE, INK, MUTED = (47, 91, 211), (30, 34, 40), (110, 116, 126)

LINES_TOP = [
    ("Drag Research History onto Applications", 21, INK),
    ("把 Research History 拖到 Applications（应用程序）上", 18, INK),
]
LINES_BOTTOM = [
    ("Then open it from Applications or Launchpad.", 15, INK),
    ("然后在「应用程序」或启动台里打开它。", 15, INK),
    ("The first time: System Settings → Privacy & Security → Open Anyway", 12, MUTED),
    ("第一次打开：系统设置 → 隐私与安全性 → 仍要打开", 12, MUTED),
]


def draw(font_path: str, scale: int) -> Image.Image:
    img = Image.new("RGB", (WIDTH * scale, HEIGHT * scale), (250, 251, 253))
    d = ImageDraw.Draw(img)

    def text_lines(lines, top, gap):
        y = top * scale
        for text, size, colour in lines:
            font = ImageFont.truetype(font_path, size * scale)
            w = d.textlength(text, font=font)
            d.text(((WIDTH * scale - w) / 2, y), text, font=font, fill=colour)
            y += (size + gap) * scale

    text_lines(LINES_TOP, 26, 10)
    # The arrow from the app to Applications.
    y = ICON_Y * scale
    x0, x1 = (APP_X + 82) * scale, (APPS_X - 82) * scale
    d.line((x0, y, x1 - 18 * scale, y), fill=BLUE, width=7 * scale)
    d.polygon([(x1, y), (x1 - 26 * scale, y - 16 * scale), (x1 - 26 * scale, y + 16 * scale)], fill=BLUE)
    text_lines(LINES_BOTTOM, 296, 7)
    return img


def main(font_path: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    draw(font_path, 1).save(OUT / "dmg-background.png", optimize=True)
    draw(font_path, 2).save(OUT / "dmg-background@2x.png", optimize=True)
    print("written:", OUT / "dmg-background.png", OUT / "dmg-background@2x.png")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
