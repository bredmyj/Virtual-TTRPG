"""Your own mouse pointer, in your own colour.

Everyone else already sees your cursor in your profile colour, drawn onto
their map. This is the other half: the pointer on your own screen, so the
arrow you are pushing around is the same one they are watching.

Tk cannot recolour a cursor, and it has no way to build one from scratch -
but on Windows it will load one from a file. So the arrow is drawn with
Pillow and written out as a real .cur, once per colour, and handed to Tk by
name. Without Pillow, or on a platform that will not take a file, everything
here quietly does nothing and you keep the ordinary arrow.
"""

import os
import struct
import tkinter as tk

try:
    from PIL import Image, ImageDraw
    HAVE_PIL = True
except ImportError:                                     # pragma: no cover
    HAVE_PIL = False

import paths

APP_DIR = paths.APP_DIR
CACHE = os.path.join(APP_DIR, "cursors")

SIZE = 32               # what Windows expects for a cursor
SCALE = 4               # drawn this much bigger, then shrunk, for a clean edge
HOTSPOT = (1, 1)        # the very tip of the arrow
OUTLINE = "#1b1d23"     # so it shows up on pale floors as well as dark ones

_made = {}              # colour -> path, so a file is written once per run
_broken = set()         # colours Tk would not take


def _arrow(size):
    """The same arrow the other players see, as points inside a box."""
    return [(0.00, 0.00), (0.00, 1.00), (0.30, 0.74), (0.46, 1.04),
            (0.62, 0.96), (0.46, 0.66), (0.78, 0.62)]


def _draw(colour):
    """The pointer as a picture with a see-through background."""
    big = SIZE * SCALE
    picture = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    pen = ImageDraw.Draw(picture)
    # Held just inside the edge: the outline needs somewhere to go, and a
    # shape touching the border comes out clipped.
    span = (SIZE - 2) * SCALE
    left, top = HOTSPOT[0] * SCALE, HOTSPOT[1] * SCALE
    points = [(left + x * span, top + y * span * 0.96) for x, y in _arrow(SIZE)]
    pen.polygon(points, fill=colour, outline=OUTLINE, width=SCALE)
    return picture.resize((SIZE, SIZE), Image.LANCZOS)


def _pack(picture):
    """A .cur file's bytes.

    A cursor is an icon with a hotspot: a small directory, a bitmap header,
    the pixels bottom-up, and a one-bit mask that modern Windows ignores in
    favour of the alpha channel but still insists on being given.
    """
    width, height = picture.size
    pixels = picture.load()

    colours = bytearray()
    mask = bytearray()
    mask_row = ((width + 31) // 32) * 4          # each row padded to 4 bytes
    for y in range(height - 1, -1, -1):          # bottom-up, as bitmaps are
        row = bytearray()
        bits = bytearray(mask_row)
        for x in range(width):
            red, green, blue, alpha = pixels[x, y]
            colours += bytes((blue, green, red, alpha))
            if alpha == 0:
                bits[x // 8] |= 0x80 >> (x % 8)  # 1 means "leave the screen"
            row.append(alpha)
        mask += bits

    header = struct.pack("<IiiHHIIiiII", 40, width, height * 2, 1, 32, 0,
                         len(colours) + len(mask), 0, 0, 0, 0)
    image = header + bytes(colours) + bytes(mask)
    entry = struct.pack("<BBBBHHII", width % 256, height % 256, 0, 0,
                        HOTSPOT[0], HOTSPOT[1], len(image), 6 + 16)
    return struct.pack("<HHH", 0, 2, 1) + entry + image


def cursor_file(colour):
    """Where the pointer for this colour lives, making it if need be."""
    if not HAVE_PIL:
        return None
    if colour in _made:
        return _made[colour]
    safe = "".join(c for c in colour if c.isalnum()) or "plain"
    path = os.path.join(CACHE, "pointer_%s.cur" % safe)
    try:
        os.makedirs(CACHE, exist_ok=True)
        if not os.path.exists(path):
            with open(path, "wb") as fh:
                fh.write(_pack(_draw(colour)))
    except (OSError, ValueError):
        return None
    _made[colour] = path
    return path


def spec(colour):
    """What to hand Tk, or None if there is nothing to hand it."""
    path = cursor_file(colour)
    if path is None or " " in path:
        # Tk reads a cursor setting as a list, so a space in the path would
        # be read as the start of a second word. Not worth the quoting.
        return None
    return "@" + path.replace("\\", "/")


def apply_profile(widget, session=None):
    """The pointer for whoever is sitting here."""
    colour = None
    if session is not None:
        profile = getattr(session, "profile", None)
        colour = getattr(profile, "colour", None)
    if colour is None:
        import netplay
        colour = netplay.Profile.load().colour
    return apply(widget, colour)


def apply(widget, colour):
    """Put this pointer on a window and everything inside it.

    Anything that sets its own cursor - a button saying it can be clicked,
    a text field - keeps it. This only fills in what has not been asked for.
    """
    if colour in _broken:
        return False
    wanted = spec(colour)
    if wanted is None:
        return False
    try:
        widget.configure(cursor=wanted)
    except tk.TclError:
        # Some builds will not load a cursor from a file. Nothing is broken;
        # you simply get the arrow everyone gets.
        _broken.add(colour)
        return False
    return True
