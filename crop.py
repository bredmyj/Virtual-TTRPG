"""Framing a picture before it becomes a round portrait.

The circle on screen is exactly the crop that will be kept, so what you line
up is what you get. Drag to slide the picture about, zoom to decide how much
of it fits, then confirm.

The same window is used for the figures on the map and for your own profile
picture, so framing a face works the same way wherever you are doing it.
Whoever opens it says how big the circle is, how big to keep the result, and
what to do with the picture once it is settled.
"""

import tkinter as tk

try:
    from PIL import Image, ImageDraw, ImageTk
    HAVE_PIL = True
except ImportError:                                     # pragma: no cover
    HAVE_PIL = False

from dice_api import THEME

PREVIEW = 240           # the circle in the window, in pixels
STORE = 256             # what the finished picture is kept at
ZOOM_STEP = 1.25        # what one press of + or - does
ZOOM_MAX = 8.0
KINDS = [("Images", "*.png *.jpg *.jpeg *.gif *.bmp *.webp"),
         ("All files", "*.*")]

FONTS = {"label": ("Segoe UI", 9), "die": ("Segoe UI", 12, "bold"),
         "title": ("Segoe UI", 11, "bold")}


class CropDialog:
    """Line a picture up inside a circle.

    `on_accept` is handed the finished square picture when the window is
    confirmed - already cropped, not yet masked, so the caller can keep it
    however it likes.
    """

    def __init__(self, parent, path, title="Picture", theme=None, fonts=None,
                 on_accept=None, preview=PREVIEW, store=STORE):
        self.t = theme or THEME
        self.f = fonts or FONTS
        self.on_accept = on_accept
        self.preview = preview
        self.store = store
        self.source = Image.open(path).convert("RGBA")

        # scale 1.0 = the short side exactly fills the circle, so there is
        # never a gap to begin with and never one afterwards.
        self.base = self.preview / float(min(self.source.size))
        self.zoom = 1.0
        self.offset = [0.0, 0.0]
        self._centre()
        self._photo = None
        self._drag = None

        self.win = tk.Toplevel(parent)
        self.win.title(title)
        self.win.configure(bg=self.t["bg"])
        self.win.transient(parent)
        self.win.resizable(False, False)
        self._build()
        self._redraw()
        self.win.bind("<Escape>", lambda _e: self.win.destroy())
        self.win.bind("<Return>", lambda _e: self._accept())

    # -- geometry ----------------------------------------------------------
    def _shown_size(self):
        factor = self.base * self.zoom
        return (self.source.width * factor, self.source.height * factor)

    def _centre(self):
        wide, tall = self._shown_size()
        self.offset = [(self.preview - wide) / 2.0,
                       (self.preview - tall) / 2.0]

    def _clamp(self):
        """Never let the circle run off the edge of the picture."""
        wide, tall = self._shown_size()
        self.offset[0] = min(0.0, max(self.preview - wide, self.offset[0]))
        self.offset[1] = min(0.0, max(self.preview - tall, self.offset[1]))

    # -- layout ------------------------------------------------------------
    def _build(self):
        pad = tk.Frame(self.win, bg=self.t["bg"])
        pad.pack(padx=16, pady=14)

        tk.Label(pad, text="drag to move  -  zoom to fit", font=self.f["label"],
                 bg=self.t["bg"], fg=self.t["muted"]).pack(anchor="w",
                                                           pady=(0, 8))
        self.view = tk.Canvas(pad, width=self.preview, height=self.preview,
                              bg=self.t["panel"], highlightthickness=0, bd=0,
                              cursor="fleur")
        self.view.pack()
        self.view.bind("<Button-1>", self._grab)
        self.view.bind("<B1-Motion>", self._slide)
        self.view.bind("<ButtonRelease-1>",
                       lambda _e: setattr(self, "_drag", None))
        self.view.bind("<MouseWheel>",
                       lambda e: self._scale_by(ZOOM_STEP if e.delta > 0
                                                else 1 / ZOOM_STEP))

        row = tk.Frame(pad, bg=self.t["bg"])
        row.pack(fill="x", pady=(12, 0))
        self._step(row, "−", 1 / ZOOM_STEP).pack(side="left")
        self.zoom_label = tk.Label(row, text="", font=self.f["label"],
                                   bg=self.t["bg"], fg=self.t["muted"], width=6)
        self.zoom_label.pack(side="left", padx=6)
        self._step(row, "+", ZOOM_STEP).pack(side="left")
        tk.Button(row, text="Reset", font=self.f["label"], bg=self.t["bg"],
                  fg=self.t["muted"], activebackground=self.t["panel"],
                  activeforeground=self.t["fg"], relief="flat", bd=0,
                  cursor="hand2", command=self._reset).pack(side="left",
                                                            padx=(10, 0))

        buttons = tk.Frame(pad, bg=self.t["bg"])
        buttons.pack(fill="x", pady=(14, 0))
        tk.Button(buttons, text="Use This", font=self.f["title"],
                  bg=self.t["accent"], fg=self.t["bg"],
                  activebackground=self.t["accent_hot"],
                  activeforeground=self.t["bg"], relief="flat", bd=0,
                  cursor="hand2", command=self._accept).pack(side="right",
                                                             ipadx=14, ipady=6)
        tk.Button(buttons, text="Cancel", font=self.f["label"],
                  bg=self.t["bg"], fg=self.t["muted"],
                  activebackground=self.t["panel"],
                  activeforeground=self.t["fg"], relief="flat", bd=0,
                  cursor="hand2", command=self.win.destroy).pack(side="right",
                                                                 padx=(0, 10))

    def _step(self, parent, text, factor):
        return tk.Button(parent, text=text, font=self.f["die"], width=3,
                         bg=self.t["panel"], fg=self.t["fg"],
                         activebackground=self.t["accent"],
                         activeforeground=self.t["bg"], relief="flat", bd=0,
                         cursor="hand2",
                         command=lambda: self._scale_by(factor))

    # -- interaction -------------------------------------------------------
    def _grab(self, event):
        self._drag = (event.x, event.y, self.offset[0], self.offset[1])

    def _slide(self, event):
        if self._drag is None:
            return
        x, y, ox, oy = self._drag
        self.offset = [ox + (event.x - x), oy + (event.y - y)]
        self._clamp()
        self._redraw()

    def _scale_by(self, factor):
        """Zoom about the middle, so the framing does not lurch."""
        wanted = max(1.0, min(ZOOM_MAX, self.zoom * factor))
        if abs(wanted - self.zoom) < 1e-6:
            return
        middle = self.preview / 2.0
        grow = wanted / self.zoom
        self.offset = [middle - (middle - self.offset[0]) * grow,
                       middle - (middle - self.offset[1]) * grow]
        self.zoom = wanted
        self._clamp()
        self._redraw()

    def _reset(self):
        self.zoom = 1.0
        self._centre()
        self._redraw()

    # -- drawing -----------------------------------------------------------
    def _framed(self, size):
        """The circle's worth of picture, at whatever size is wanted."""
        factor = self.base * self.zoom
        left = -self.offset[0] / factor
        top = -self.offset[1] / factor
        side = self.preview / factor
        crop = self.source.crop((int(round(left)), int(round(top)),
                                 int(round(left + side)),
                                 int(round(top + side))))
        return crop.resize((size, size), Image.LANCZOS)

    def _redraw(self):
        picture = self._framed(self.preview)
        mask = Image.new("L", (self.preview, self.preview), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, self.preview - 1,
                                      self.preview - 1), fill=255)
        picture.putalpha(mask)
        self._photo = ImageTk.PhotoImage(picture, master=self.view)
        self.view.delete("all")
        self.view.create_image(self.preview // 2, self.preview // 2,
                               image=self._photo)
        self.view.create_oval(1, 1, self.preview - 2, self.preview - 2,
                              outline=self.t["accent"], width=2)
        self.zoom_label.config(text="%d%%" % round(self.zoom * 100))

    def _accept(self):
        picture = self._framed(self.store)
        self.win.destroy()
        if self.on_accept is not None:
            self.on_accept(picture)
