#!/usr/bin/env python3
"""
make_icon.py - generate swgo.ico for SWG-O.

Draws the mark procedurally at each size rather than downscaling one large
image, so the 16px and 20px entries stay legible instead of turning to mush.
Small sizes drop the inner detail and fatten the strokes.

    py -m pip install pillow
    py make_icon.py

Writes swgo.ico (multi-resolution) and swgo_256.png (for a readme or a
release page) next to this script.

The mark: two overlapping preview tiles, the front one carrying a live-view
accent dot. Reads as picture-in-picture at a glance and stays distinct in a
taskbar full of blue squares.
"""

import os
from PIL import Image, ImageDraw

OUT_ICO = "swgo.ico"
OUT_PNG = "swgo_256.png"
SIZES = [256, 128, 64, 48, 32, 24, 20, 16]

# Palette. Teal and amber, pulled from the SWG UI rather than a generic blue.
BG_TOP = (18, 26, 33)
BG_BOT = (11, 16, 21)
EDGE = (52, 74, 88)
BACK_FILL = (16, 38, 46)
BACK_LINE = (44, 108, 122)
FRONT_FILL = (13, 28, 35)
FRONT_LINE = (78, 199, 214)
ACCENT = (232, 163, 61)
BAR = (36, 62, 74)


def rr(draw, box, radius, fill=None, outline=None, width=1):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def draw_mark(size, ss=8):
    """Draw the icon at `size` px, supersampled by `ss` then reduced."""
    S = size * ss
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    tiny = size <= 20
    small = size <= 32

    # Rounded background plate with a vertical gradient.
    plate = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    grad = Image.new("RGBA", (1, S))
    gd = ImageDraw.Draw(grad)
    for y in range(S):
        t = y / max(1, S - 1)
        gd.point((0, y), fill=(
            int(BG_TOP[0] + (BG_BOT[0] - BG_TOP[0]) * t),
            int(BG_TOP[1] + (BG_BOT[1] - BG_TOP[1]) * t),
            int(BG_TOP[2] + (BG_BOT[2] - BG_TOP[2]) * t),
            255,
        ))
    plate.paste(grad.resize((S, S)), (0, 0))

    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, S - 1, S - 1],
                                           radius=int(S * 0.22), fill=255)
    img.paste(plate, (0, 0), mask)
    d = ImageDraw.Draw(img)

    # Plate edge, skipped at tiny sizes where it just muddies the silhouette.
    if not tiny:
        rr(d, [0, 0, S - 1, S - 1], int(S * 0.22),
           outline=EDGE, width=max(1, int(S * 0.012)))

    lw_back = max(1, int(S * (0.030 if small else 0.022)))
    lw_front = max(1, int(S * (0.040 if small else 0.028)))
    rad = int(S * 0.05)

    # Back tile, up and to the left, partly occluded.
    bx0, by0 = int(S * 0.135), int(S * 0.155)
    bx1, by1 = int(S * 0.665), int(S * 0.545)
    rr(d, [bx0, by0, bx1, by1], rad, fill=BACK_FILL, outline=BACK_LINE, width=lw_back)

    # Front tile, down and to the right, brighter.
    fx0, fy0 = int(S * 0.335), int(S * 0.435)
    fx1, fy1 = int(S * 0.875), int(S * 0.855)

    # Cut a gap so the front tile reads as sitting on top of the back one.
    gap = max(1, int(S * 0.022))
    rr(d, [fx0 - gap, fy0 - gap, fx1 + gap, fy1 + gap], rad + gap, fill=BG_BOT)
    rr(d, [fx0, fy0, fx1, fy1], rad, fill=FRONT_FILL, outline=FRONT_LINE, width=lw_front)

    if not tiny:
        # Title strips, the detail that makes them read as windows.
        inset = lw_front + max(1, int(S * 0.012))
        bar_h = max(1, int(S * 0.055))
        d.rectangle([fx0 + inset, fy0 + inset,
                     fx1 - inset, fy0 + inset + bar_h], fill=BAR)
        d.rectangle([bx0 + lw_back + int(S * 0.01), by0 + lw_back + int(S * 0.01),
                     bx1 - lw_back - int(S * 0.01),
                     by0 + lw_back + int(S * 0.01) + max(1, int(S * 0.045))],
                    fill=BAR)

    # Live-view accent dot on the front tile. Sits further inside at small
    # sizes, where a corner-hugging dot clips against the tile stroke.
    r = int(S * (0.070 if tiny else 0.055))
    off = 0.145 if tiny else (0.115 if small else 0.095)
    cx = fx1 - int(S * off)
    cy = fy1 - int(S * off)
    if not small:
        d.ellipse([cx - r * 1.9, cy - r * 1.9, cx + r * 1.9, cy + r * 1.9],
                  fill=(ACCENT[0], ACCENT[1], ACCENT[2], 55))
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=ACCENT)

    return img.resize((size, size), Image.LANCZOS)


def main():
    # This script lives in tools/. The .ico belongs at the repo root, where
    # build.bat and installer.iss look for it; the .png belongs in docs/.
    tools = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(tools)
    docs = os.path.join(root, "docs")
    os.makedirs(docs, exist_ok=True)

    frames = [draw_mark(s) for s in SIZES]
    big = frames[0]

    ico = os.path.join(root, OUT_ICO)
    png = os.path.join(docs, OUT_PNG)
    big.save(png)
    big.save(ico, format="ICO", sizes=[(s, s) for s in SIZES],
             append_images=frames[1:])

    print(f"wrote {ico} ({', '.join(f'{s}x{s}' for s in SIZES)})")
    print(f"wrote {png}")


if __name__ == "__main__":
    main()
