"""
Generate the site's icons and link-preview image.

Writes three files that index.html references:
    favicon.ico    16/32/48 px, the browser tab icon
    icon-180.png   apple-touch-icon, for "add to home screen"
    og.png         1200x630, the card Discord/Twitter/iMessage show for a link

Run: python make_social.py

Only needs re-running if the artwork changes; the outputs are committed so a
plain `python build_web.py` deploy does not depend on Pillow being installed.
"""

import os
import random

from PIL import Image, ImageDraw, ImageFont

BG = (13, 17, 23)          # #0d1117, the page background
INK = (230, 237, 243)      # #e6edf3
MUTED = (139, 152, 168)    # #8b98a8
# the overview tab's accents: --a, --b, --c
WARM = [(255, 140, 66), (255, 89, 100), (255, 208, 123)]

FONT_BOLD = r"C:\Windows\Fonts\segoeuib.ttf"
FONT_REG = r"C:\Windows\Fonts\segoeui.ttf"


def font(path, size):
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        # Not on Windows, or the font moved. The image still builds, just plainer.
        return ImageFont.load_default()


def lerp(a, b, t):
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def heat(t):
    """0..1 -> the warm ramp, dark ember through to pale gold."""
    stops = [(22, 27, 34), WARM[1], WARM[0], WARM[2]]
    t = max(0.0, min(1.0, t)) * (len(stops) - 1)
    i = min(int(t), len(stops) - 2)
    return lerp(stops[i], stops[i + 1], t - i)


def rounded(d, box, r, fill):
    d.rounded_rectangle(box, radius=r, fill=fill)


def make_og(path):
    """A calendar heatmap fading out under the title — the same shape as the
    real first chart, so the preview looks like the thing it links to."""
    W, H = 1200, 630
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    rng = random.Random(7)              # fixed seed: rebuilds are identical
    cell, gap = 26, 6
    cols, rows = 34, 7
    x0, y0 = 96, 330
    for c in range(cols):
        # busier towards the right, so it reads as a history building up
        density = 0.20 + 0.75 * (c / cols) ** 1.4
        for r in range(rows):
            v = max(0.0, min(1.0, rng.random() * density * 1.5))
            if v < 0.06:
                v = 0.0
            x = x0 + c * (cell + gap)
            y = y0 + r * (cell + gap)
            rounded(d, [x, y, x + cell, y + cell], 5, heat(v))

    # Dissolve the last rows into the background. Held at 0 for the top half of
    # the grid: ramping from the very first row just makes every cell muddy.
    fade = Image.new("L", (W, H), 0)
    fd = ImageDraw.Draw(fade)
    span = H - y0
    for i in range(span):
        t = max(0.0, (i / span - 0.45) / 0.55)
        fd.line([(0, y0 + i), (W, y0 + i)], fill=int(255 * t ** 1.3))
    img = Image.composite(Image.new("RGB", (W, H), BG), img, fade)
    d = ImageDraw.Draw(img)

    # accent rule above the title, in the tab's three colours
    for i, col in enumerate(WARM):
        rounded(d, [96 + i * 46, 96, 96 + i * 46 + 34, 102], 3, col)

    d.text((92, 128), "you, in music", font=font(FONT_BOLD, 108), fill=INK)
    d.text((96, 258), "a full last.fm listening report, rendered in your browser",
           font=font(FONT_REG, 34), fill=MUTED)

    img.save(path)
    return img


def make_icons(ico_path, png_path):
    """A three-bar equaliser: the only motif that still reads at 16 px."""
    S = 512
    img = Image.new("RGBA", (S, S), BG + (255,))
    d = ImageDraw.Draw(img)
    rounded(d, [0, 0, S, S], 96, BG + (255,))

    bar_w, gap = 92, 42
    heights = [0.42, 0.74, 0.56]
    total = 3 * bar_w + 2 * gap
    x = (S - total) // 2
    base = S - 96
    for h, col in zip(heights, WARM):
        top = base - int(h * (S - 192))
        rounded(d, [x, top, x + bar_w, base], bar_w // 2, col + (255,))
        x += bar_w + gap

    img.resize((180, 180), Image.LANCZOS).save(png_path)
    img.save(ico_path, sizes=[(16, 16), (32, 32), (48, 48)])


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    make_og(os.path.join(here, "og.png"))
    make_icons(os.path.join(here, "favicon.ico"),
               os.path.join(here, "icon-180.png"))
    for f in ("og.png", "favicon.ico", "icon-180.png"):
        p = os.path.join(here, f)
        print(f"  {f:16} {os.path.getsize(p):>8,} bytes")


if __name__ == "__main__":
    main()
