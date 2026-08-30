"""Draw the app's icon.

    python make_icon.py

Writes `app.ico`, which is what the window corners, the taskbar, the built
program and the desktop shortcut all use. Kept as a script rather than a
loose image so the icon can be changed by editing numbers here and running
it again.

A twenty-sided die, because that is the one symbol every table recognises
from across the room. Drawn eight times larger than needed and shrunk, so
the edges stay clean all the way down to the sixteen-pixel version Windows
uses in the taskbar.
"""

import math
import os
import sys

try:
    from PIL import Image, ImageDraw
except ImportError:
    sys.exit("Drawing the icon needs Pillow:\n    python -m pip install pillow")

import paths

OUT = os.path.join(paths.APP_DIR, "app.ico")
SIZES = [16, 24, 32, 48, 64, 128, 256]
BIG = 1024              # drawn this large, then shrunk

BACK = (36, 39, 47, 255)        # the app's panel colour
EDGE = (58, 62, 74, 255)
GOLD = (200, 162, 74, 255)      # the app's accent
BRIGHT = (224, 187, 99, 255)    # the lit faces
SHADE = (150, 118, 48, 255)     # the ones turned away
LINE = (27, 29, 35, 255)        # the app's background, as the facet lines


def points(centre, radius, angles):
    return [(centre + radius * math.cos(math.radians(a)),
             centre - radius * math.sin(math.radians(a))) for a in angles]


def draw():
    picture = Image.new("RGBA", (BIG, BIG), (0, 0, 0, 0))
    pen = ImageDraw.Draw(picture)

    # A rounded square behind it, so the icon reads as an app rather than a
    # shape floating on the desktop.
    inset = BIG * 0.03
    pen.rounded_rectangle((inset, inset, BIG - inset, BIG - inset),
                          radius=BIG * 0.18, fill=BACK, outline=EDGE,
                          width=int(BIG * 0.012))

    centre = BIG / 2.0
    radius = BIG * 0.36

    # The die seen corner-on: a six-sided outline, with the face pointing at
    # you in the middle and the sloping faces filling the gaps.
    outer = points(centre, radius, [90, 150, 210, 270, 330, 30])
    inner = points(centre, radius * 0.46, [90, 210, 330])

    pen.polygon(outer, fill=GOLD)

    # The three faces that catch the light, between the middle face and the
    # outline - drawn brighter so the die looks solid rather than flat.
    for i, angle in enumerate([90, 210, 330]):
        here = outer[[90, 150, 210, 270, 330, 30].index(angle)]
        left = outer[([90, 150, 210, 270, 330, 30].index(angle) - 1) % 6]
        right = outer[([90, 150, 210, 270, 330, 30].index(angle) + 1) % 6]
        pen.polygon([here, left, inner[(i - 1) % 3]], fill=SHADE)
        pen.polygon([here, right, inner[i]], fill=BRIGHT)

    pen.polygon(inner, fill=BRIGHT)

    # The facets, in the app's own dark background colour.
    width = int(BIG * 0.022)
    pen.polygon(outer, outline=LINE, width=width)
    pen.polygon(inner, outline=LINE, width=width)
    for i, angle in enumerate([90, 210, 330]):
        corner = outer[[90, 150, 210, 270, 330, 30].index(angle)]
        pen.line([inner[i], corner], fill=LINE, width=width)

    return picture


def main():
    art = draw()
    frames = [art.resize((size, size), Image.LANCZOS) for size in SIZES]
    frames[-1].save(OUT, format="ICO",
                    sizes=[(size, size) for size in SIZES])
    print("wrote %s  (%s)" % (OUT, ", ".join("%dpx" % s for s in SIZES)))
    return art


if __name__ == "__main__":
    main()
