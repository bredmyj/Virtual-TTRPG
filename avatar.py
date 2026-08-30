"""Round profile pictures, and something to show when there isn't one.

Tk can put an image on a canvas but it cannot cut a circle out of one, so
the round crop is done with Pillow and handed over as a finished picture.
Without Pillow you get a coloured disc with your initials on it, which is
enough to tell eight people apart at a glance.
"""

import os
import tkinter as tk

try:
    from PIL import Image, ImageDraw, ImageTk
    HAVE_PIL = True
except ImportError:                                     # pragma: no cover
    HAVE_PIL = False

STORED_SIZE = 256       # what a chosen picture is kept at


def initials(name):
    """One or two letters to stand in for a face."""
    parts = [p for p in (name or "").split() if p]
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()


def store_image(picture, destination):
    """Keep an already-framed square picture as the app's own copy."""
    if not HAVE_PIL or picture is None:
        return None
    picture = picture.convert("RGBA")
    if picture.size != (STORED_SIZE, STORED_SIZE):
        picture = picture.resize((STORED_SIZE, STORED_SIZE), Image.LANCZOS)
    try:
        picture.save(destination, "PNG")
    except OSError:
        return None
    return destination


def store_picture(source, destination):
    """Copy a chosen image into the app as a square PNG.

    Kept rather than pointed at, so moving or deleting the original later
    does not quietly blank somebody's face. Returns the path, or None.
    """
    if not HAVE_PIL or not source:
        return None
    try:
        picture = Image.open(source).convert("RGBA")
    except (OSError, ValueError):
        return None
    # Centre crop to a square first - a portrait squashed into a circle
    # looks worse than one with its edges trimmed.
    side = min(picture.size)
    left = (picture.width - side) // 2
    top = (picture.height - side) // 2
    picture = picture.crop((left, top, left + side, top + side))
    picture = picture.resize((STORED_SIZE, STORED_SIZE), Image.LANCZOS)
    try:
        picture.save(destination, "PNG")
    except OSError:
        return None
    return destination


def circular(path, size, ring=None, ring_width=2, master=None):
    """A round PhotoImage, or None if there is no usable picture.

    Keep a reference to what comes back - Tk drops images that nothing
    holds on to, and the picture silently disappears.

    `master` says which window the picture belongs to. Without it Tk hands
    it to whichever window happens to be the first one, which is the wrong
    one the moment there is more than one.
    """
    if not HAVE_PIL or not path or not os.path.exists(path):
        return None
    try:
        picture = Image.open(path).convert("RGBA")
    except (OSError, ValueError):
        return None

    side = min(picture.size)
    left = (picture.width - side) // 2
    top = (picture.height - side) // 2
    picture = picture.crop((left, top, left + side, top + side))

    # Work at four times the size and shrink at the end, so the edge of the
    # circle comes out smooth instead of stepped.
    scale = 4
    big = size * scale
    picture = picture.resize((big, big), Image.LANCZOS)

    mask = Image.new("L", (big, big), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, big - 1, big - 1), fill=255)
    picture.putalpha(mask)

    if ring:
        inset = max(1, ring_width * scale) // 2
        ImageDraw.Draw(picture).ellipse(
            (inset, inset, big - 1 - inset, big - 1 - inset),
            outline=ring, width=max(1, ring_width * scale))

    picture = picture.resize((size, size), Image.LANCZOS)
    return ImageTk.PhotoImage(picture, master=master)


def draw_face(canvas, x, y, size, name, colour, picture=None, tags=()):
    """A person on a canvas: their picture if there is one, initials if not.

    (x, y) is the top-left corner. Returns the PhotoImage used, if any, so
    the caller can keep hold of it.
    """
    photo = circular(picture, size, ring=colour, ring_width=2, master=canvas)
    if photo is not None:
        canvas.create_image(x, y, image=photo, anchor="nw", tags=tags)
        return photo

    canvas.create_oval(x, y, x + size, y + size, fill=colour, outline="",
                       tags=tags)
    canvas.create_text(x + size / 2, y + size / 2, text=initials(name),
                       fill="#1b1d23", tags=tags,
                       font=("Segoe UI", max(7, int(size * 0.38)), "bold"))
    return None


def swatch(parent, colour, size=20, **kwargs):
    """A small block of colour, for picking one."""
    return tk.Frame(parent, bg=colour, width=size, height=size,
                    highlightthickness=0, **kwargs)
