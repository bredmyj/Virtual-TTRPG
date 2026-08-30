"""Adventuring Journal - a separate window for notes, cast and quest threads.

Opens from Tools > Adventuring Journal. Three sections:

  * Notes (big, middle)   - a drawing surface with a tool bar down the right
                            and an optional grid overlay to guide it
  * Cast (left column)    - important people and places
  * Threads (bottom)      - quests and vows, each with ten four-tick progress
                            boxes, resolved against two challenge dice

Everything here belongs to the campaign that is currently open, so each save
file has its own journal.

The file is still journal.py so that journals saved before the rename keep
loading - a mod's save file is named after its .py file.
"""

import math
import tkinter as tk
from tkinter import colorchooser, font as tkfont, messagebox, simpledialog

PLUGIN = {
    "name": "Adventuring Journal",
    "version": "2.0",
    "description": "Notes canvas, cast list and quest threads with vow checks, in their own window.",
    "author": "bundled",
}

TOOLS = [
    ("select", "Select"),
    ("pen", "Pen"),
    ("eraser", "Erase"),
    ("line", "Line"),
    ("ruler", "Ruler"),
    ("box", "Box"),
    ("oval", "Circle"),
    ("fill", "Fill"),
    ("text", "Text"),
]

SWATCHES = ["#e6e8ee", "#8b90a0", "#c8a24a", "#e2585f",
            "#5fd38d", "#5aa9e6", "#b98cff", "#1b1d23"]

BOXES_PER_THREAD = 10
TICKS_PER_BOX = 4
BOX_SIZE = 22
UNDO_LIMIT = 60

# The fill layer is a fixed, generously sized image sitting under the drawing.
FILL_W, FILL_H = 2400, 1600
ERASE_R = 6        # half-width of the eraser, in pixels
MAX_PEN = 20

# A note on the page can be resized by its corner, between these.
SHIFT = 0x0001      # the bit Tk sets on an event while Shift is held

MIN_TEXT, MAX_TEXT = 6, 96
SIZER = 9          # the grab handle, in pixels
TEXT_STEPS = [10, 12, 14, 18, 24, 32, 48, 64]

# Grid overlay: a guide drawn under the artwork, never part of it. The sizes
# are the cell edge in pixels, smallest first.
GRID_SIZES = [12, 16, 24, 32, 48, 64, 96]
GRID_DEFAULT = 3          # index into the above - 32px
GRID_BLEND = 0.45         # how far the line colour sits from the page toward muted


def setup(api):
    holder = {"journal": None}

    def open_journal():
        journal = holder["journal"]
        if journal is not None and journal.alive():
            journal.win.deiconify()
            journal.win.lift()
            journal.win.focus_force()
            return
        holder["journal"] = Journal(api)

    def flush(_name=None):
        journal = holder["journal"]
        if journal is not None and journal.alive():
            journal.save()

    api.add_menu_command("Tools", "Adventuring Journal...", open_journal)
    api.on("save", flush)


class Journal:
    def __init__(self, api):
        self.api = api
        self.t = api.theme
        self.f = api.fonts

        self.tool = "pen"
        self.color = self.t["fg"]
        self.pen_width = 2
        self.items = []       # drawn shapes, each a dict + a live canvas id
        self.fills = []       # [{"color", "runs"}] - the pixels each fill covered
        self.entries = []     # left column strings
        self.threads = []     # [{"name", "boxes", "result"}]
        self.completed = []   # archived vows
        self.partial = []     # archived half-finished vows
        self.canvas_bg = self.t["bg"]
        self.grid_on = False
        self.grid_index = GRID_DEFAULT
        self._grid_extent = (0, 0)

        self.selected = []
        self.drag_mode = None
        self.resize_from = None     # (x, y, size) while a corner is dragged
        self._text_fonts = {}
        self.start = (0, 0)
        self.last = (0, 0)
        self.stroke = []
        self.current = None
        self.preview = None
        self.preview_text = None
        self._save_job = None
        self._fill_job = None
        self._pending = None
        self.undo_stack = []
        self.redo_stack = []

        self._load()
        self._build()
        self._restore_canvas()
        self._render_entries()
        self._render_threads()
        self._render_archives()
        # Fills are replayed once the canvas knows how big it is.
        self._fill_job = self.win.after(80, self._repaint_fills)

    # -- data -------------------------------------------------------------
    def alive(self):
        try:
            return bool(self.win.winfo_exists())
        except tk.TclError:
            return False

    def _load(self):
        store = self.api.storage
        self.entries = [str(e) for e in store.get("entries", [])]
        for thread in store.get("threads", []):
            boxes = list(thread.get("boxes", []))[:BOXES_PER_THREAD]
            boxes += [0] * (BOXES_PER_THREAD - len(boxes))
            self.threads.append({"name": thread.get("name", ""), "boxes": boxes,
                                 "result": thread.get("result")})
        self.completed = [dict(c) for c in store.get("completed", [])]
        self.partial = [dict(c) for c in store.get("partial", [])]
        self.items = [dict(item) for item in store.get("canvas", [])]
        self.fills = [dict(f) for f in store.get("fills", [])]
        self.canvas_bg = store.get("canvas_bg", self.t["bg"])
        self.color = store.get("color", self.t["fg"])
        self.pen_width = max(1, min(MAX_PEN, int(store.get("pen_width", 2))))
        self.grid_on = bool(store.get("grid_on", False))
        self.grid_index = max(0, min(len(GRID_SIZES) - 1,
                                     int(store.get("grid_index", GRID_DEFAULT))))

    def _plain_threads(self):
        """Threads without the live widget references hung off them."""
        return [{k: v for k, v in t.items() if not k.startswith("_")}
                for t in self.threads]

    def save(self):
        store = self.api.storage
        store["entries"] = self.entries
        store["threads"] = self._plain_threads()
        store["completed"] = self.completed
        store["partial"] = self.partial
        store["canvas"] = [{k: v for k, v in item.items() if k != "id"}
                           for item in self.items]
        store["fills"] = self.fills
        store["canvas_bg"] = self.canvas_bg
        store["color"] = self.color
        store["pen_width"] = self.pen_width
        store["grid_on"] = self.grid_on
        store["grid_index"] = self.grid_index
        self.api.save()

    def schedule_save(self):
        """Coalesce the flurry of edits from typing into one write."""
        if self._save_job is not None:
            self.win.after_cancel(self._save_job)
        self._save_job = self.win.after(600, self._do_save)

    def _do_save(self):
        self._save_job = None
        if self.alive():   # the window may have gone since this was scheduled
            self.save()

    def _cancel_jobs(self):
        for attribute in ("_save_job", "_fill_job"):
            job = getattr(self, attribute, None)
            if job is not None:
                try:
                    self.win.after_cancel(job)
                except tk.TclError:
                    pass
                setattr(self, attribute, None)

    def _on_destroy(self, event):
        """However the window goes, don't leave timers pointing at it."""
        if event.widget is self.win:
            self._cancel_jobs()

    def _close(self):
        self._cancel_jobs()
        self.save()
        self.win.destroy()

    # -- undo / redo -------------------------------------------------------
    def _snapshot(self):
        return {
            "entries": list(self.entries),
            "threads": [{"name": t["name"], "boxes": list(t["boxes"]),
                         "result": dict(t["result"]) if t.get("result") else None}
                        for t in self.threads],
            "completed": [dict(c) for c in self.completed],
            "partial": [dict(c) for c in self.partial],
            "canvas": [{k: v for k, v in i.items() if k != "id"}
                       for i in self.items],
            "fills": [dict(f) for f in self.fills],
            "canvas_bg": self.canvas_bg,
        }

    def _push_undo(self, snapshot=None):
        """Call this immediately BEFORE changing anything."""
        snapshot = snapshot if snapshot is not None else self._snapshot()
        if self.undo_stack and self.undo_stack[-1] == snapshot:
            return  # nothing actually changed since the last step
        self.undo_stack.append(snapshot)
        if len(self.undo_stack) > UNDO_LIMIT:
            del self.undo_stack[0]
        self.redo_stack.clear()

    def _commit_pending(self):
        """Typing is one undo step, taken from when the field got focus."""
        if self._pending is not None:
            self._push_undo(self._pending)
            self._pending = None

    def undo(self, _event=None):
        if not self.undo_stack:
            return "break"
        self.redo_stack.append(self._snapshot())
        self._apply(self.undo_stack.pop())
        return "break"

    def redo(self, _event=None):
        if not self.redo_stack:
            return "break"
        self.undo_stack.append(self._snapshot())
        self._apply(self.redo_stack.pop())
        return "break"

    def _apply(self, snap):
        self._clear_selection()
        for item in self.items:
            self.canvas.delete(item["id"])
        self.items = [dict(i) for i in snap["canvas"]]
        self._restore_canvas()
        self.fills = [dict(f) for f in snap.get("fills", [])]
        self._repaint_fills()
        self.canvas_bg = snap["canvas_bg"]
        self.canvas.configure(bg=self.canvas_bg)
        self._draw_grid()
        self.entries = list(snap["entries"])
        self.threads = [dict(t) for t in snap["threads"]]
        self.completed = [dict(c) for c in snap["completed"]]
        self.partial = [dict(c) for c in snap["partial"]]
        self._render_entries()
        self._render_threads()
        self._render_archives()
        self.save()

    # -- widget helpers ----------------------------------------------------
    def _heading(self, parent, text):
        return tk.Label(parent, text=text, font=self.f["label"],
                        bg=self.t["panel"], fg=self.t["muted"], anchor="w")

    def _entry(self, parent, width, value=""):
        widget = tk.Entry(parent, width=width, font=self.f["label"],
                          bg=self.t["bg"], fg=self.t["fg"],
                          insertbackground=self.t["fg"], relief="flat", bd=0,
                          highlightthickness=1,
                          highlightbackground=self.t["panel"],
                          highlightcolor=self.t["accent"])
        if value:
            widget.insert(0, value)
        # Hold a snapshot from when the field got focus; it only becomes an
        # undo step if the user actually types something.
        widget.bind("<FocusIn>", lambda _e: setattr(self, "_pending",
                                                    self._snapshot()))
        return widget

    def _button(self, parent, text, command, fg=None, width=None, font=None):
        return tk.Button(parent, text=text, font=font or self.f["label"],
                         bg=self.t["bg"], fg=fg or self.t["fg"],
                         activebackground=self.t["accent"],
                         activeforeground=self.t["bg"], relief="flat", bd=0,
                         cursor="hand2", command=command,
                         **({"width": width} if width else {}))

    def _scroller(self, parent, height=None):
        outer = tk.Frame(parent, bg=self.t["panel"])
        canvas = tk.Canvas(outer, bg=self.t["panel"], highlightthickness=0,
                           bd=0, **({"height": height} if height else {}))
        bar = tk.Scrollbar(outer, orient="vertical", command=canvas.yview,
                           bg=self.t["panel"], troughcolor=self.t["bg"],
                           activebackground=self.t["accent"], relief="flat",
                           bd=0, width=10)
        canvas.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        inner = tk.Frame(canvas, bg=self.t["panel"])
        window = canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>",
                   lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>",
                    lambda e: canvas.itemconfigure(window, width=e.width))
        return outer, inner, canvas

    def _bind_wheel(self, widget, canvas):
        def scroll(event):
            canvas.yview_scroll(-int(event.delta / 120), "units")
            return "break"
        widget.bind("<MouseWheel>", scroll)
        for child in widget.winfo_children():
            self._bind_wheel(child, canvas)

    # -- window ------------------------------------------------------------
    def _apply_pointer(self):
        """Your own colour on the pointer, away from the drawing canvas -
        that keeps the crosshair and the grab hand its tools need."""
        try:
            import pointer
        except ImportError:
            return
        pointer.apply_profile(self.win, getattr(self.api, "session", None))

    def _build(self):
        self.win = tk.Toplevel(self.api.app)
        self.win.title(f"Adventuring Journal - {self.api.save_name}")
        self.win.configure(bg=self.t["bg"])
        self.win.geometry("1240x820")
        self.win.minsize(980, 660)
        self.win.protocol("WM_DELETE_WINDOW", self._close)
        self.win.bind("<Destroy>", self._on_destroy)

        self.win.columnconfigure(1, weight=1)
        self.win.rowconfigure(0, weight=1)

        self._build_cast()
        self._build_notes()
        self._build_tools()
        self._apply_pointer()
        self._build_threads()
        self._draw_size_dot()

        self.win.bind("<Control-z>", self.undo)
        self.win.bind("<Control-Z>", self.redo)      # ctrl+shift+z
        self.win.bind("<Control-y>", self.redo)
        self.win.bind("<Delete>", self._delete_selected)
        self.win.bind("<Escape>", lambda _e: self._clear_selection())

    # -- section 2: the cast column ---------------------------------------
    def _build_cast(self):
        box = tk.Frame(self.win, bg=self.t["panel"], width=240)
        box.grid(row=0, column=0, sticky="nsew", padx=(8, 4), pady=8)
        box.pack_propagate(False)
        self._heading(box, "PLACES & CHARACTERS").pack(fill="x", padx=10,
                                                       pady=(8, 6))
        outer, self.cast_rows, self.cast_canvas = self._scroller(box)
        outer.pack(fill="both", expand=True, padx=6)

        adder = tk.Frame(box, bg=self.t["panel"])
        adder.pack(fill="x", padx=10, pady=8)
        self.cast_entry = self._entry(adder, 16)
        self.cast_entry.pack(side="left", fill="x", expand=True, ipady=3)
        self.cast_entry.bind("<Return>", lambda _e: self._add_cast())
        self._button(adder, "+", self._add_cast, fg=self.t["accent"],
                     width=2).pack(side="left", padx=(6, 0), ipady=2)

    def _add_cast(self):
        text = self.cast_entry.get().strip()
        if not text:
            return
        self._push_undo()
        self.entries.append(text)
        self.cast_entry.delete(0, "end")
        self._render_entries()
        self.save()

    def _render_entries(self):
        for child in self.cast_rows.winfo_children():
            child.destroy()
        if not self.entries:
            tk.Label(self.cast_rows, text="Nobody noted down yet.",
                     font=self.f["label"], bg=self.t["panel"],
                     fg=self.t["muted"], anchor="w", wraplength=180,
                     justify="left").pack(fill="x", padx=4, pady=4)
        for index, text in enumerate(self.entries):
            row = tk.Frame(self.cast_rows, bg=self.t["panel"])
            row.pack(fill="x", pady=1)
            field = self._entry(row, 1, text)
            field.pack(side="left", fill="x", expand=True, ipady=2)
            field.bind("<KeyRelease>",
                       lambda _e, i=index, w=field: self._edit_cast(i, w))
            self._button(row, "x", lambda i=index: self._drop_cast(i),
                         fg=self.t["muted"], width=2).pack(side="left",
                                                           padx=(4, 0))
        self._bind_wheel(self.cast_rows, self.cast_canvas)

    def _edit_cast(self, index, widget):
        self._commit_pending()
        self.entries[index] = widget.get()
        self.schedule_save()

    def _drop_cast(self, index):
        self._push_undo()
        del self.entries[index]
        self._render_entries()
        self.save()

    # -- section 1: the notes canvas --------------------------------------
    def _build_notes(self):
        wrap = tk.Frame(self.win, bg=self.t["panel"])
        wrap.grid(row=0, column=1, sticky="nsew", padx=4, pady=8)
        header = tk.Frame(wrap, bg=self.t["panel"])
        header.pack(fill="x", padx=10, pady=(8, 4))
        self._heading(header, "NOTES").pack(side="left")
        self._button(header, "↺", self.undo, width=2,
                     font=self.f["die"]).pack(side="left", padx=(12, 2))
        self._button(header, "↻", self.redo, width=2,
                     font=self.f["die"]).pack(side="left", padx=2)

        # Grid overlay: toggle, then coarser / finer cells.
        self.grid_button = self._button(header, "▦", self._toggle_grid,
                                        width=2, font=self.f["die"])
        self.grid_button.pack(side="left", padx=(12, 2))
        self._button(header, "−", lambda: self._step_grid(-1),
                     width=2).pack(side="left", padx=1)
        self._button(header, "+", lambda: self._step_grid(1),
                     width=2).pack(side="left", padx=1)

        # Pen size: a dot showing the current width, click it for a slider.
        size_box = tk.Frame(header, bg=self.t["panel"], cursor="hand2")
        size_box.pack(side="right", padx=(10, 0))
        self.size_dot = tk.Canvas(size_box, width=28, height=24,
                                  bg=self.t["panel"], highlightthickness=0,
                                  bd=0, cursor="hand2")
        self.size_dot.pack()
        size_word = tk.Label(size_box, text="size", font=self.f["label"],
                             bg=self.t["panel"], fg=self.t["muted"],
                             cursor="hand2")
        size_word.pack()
        for widget in (size_box, self.size_dot, size_word):
            widget.bind("<Button-1>", lambda _e: self._toggle_size())

        self.hint = tk.Label(header, text="", font=self.f["label"],
                             bg=self.t["panel"], fg=self.t["muted"])
        self.hint.pack(side="right")

        # The slider drops down over the canvas, under the dot.
        self.size_popup = tk.Frame(wrap, bg=self.t["panel"],
                                   highlightthickness=1,
                                   highlightbackground=self.t["muted"])
        self.size_scale = tk.Scale(
            self.size_popup, from_=MAX_PEN, to=1, orient="vertical",
            length=130, width=14, font=self.f["label"], bg=self.t["panel"],
            fg=self.t["fg"], troughcolor=self.t["bg"],
            activebackground=self.t["accent"], highlightthickness=0, bd=0,
            relief="flat", sliderrelief="flat", showvalue=True,
            command=self._set_pen_width)
        self.size_scale.set(self.pen_width)
        self.size_scale.pack(padx=6, pady=6)

        self.canvas = tk.Canvas(wrap, bg=self.canvas_bg, highlightthickness=0,
                                bd=0, cursor="crosshair")
        self.canvas.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.canvas.bind("<Button-1>", self._press)
        self.canvas.bind("<B1-Motion>", self._drag)
        self.canvas.bind("<ButtonRelease-1>", self._release)
        self.canvas.bind("<Button-3>", self._canvas_menu)
        self.canvas.bind("<Double-Button-1>", self._double_click)
        self.canvas.bind("<Configure>", self._on_canvas_resize)

        # Flood fills live on their own image layer underneath every shape.
        self.fill_layer = tk.PhotoImage(width=FILL_W, height=FILL_H)
        self.fill_item = self.canvas.create_image(0, 0, anchor="nw",
                                                  image=self.fill_layer)
        self.canvas.tag_lower(self.fill_item)
        self._sync_grid_button()

    # -- the grid overlay --------------------------------------------------
    def _toggle_grid(self):
        self.grid_on = not self.grid_on
        self._sync_grid_button()
        self._draw_grid()
        self.schedule_save()

    def _step_grid(self, delta):
        """delta +1 goes coarser, -1 finer. Reaching for a size turns it on."""
        index = max(0, min(len(GRID_SIZES) - 1, self.grid_index + delta))
        changed = index != self.grid_index
        self.grid_index = index
        if not self.grid_on:
            self.grid_on = True
            self._sync_grid_button()
        elif not changed:
            return
        self._draw_grid()
        self.hint.config(text="grid %dpx" % GRID_SIZES[self.grid_index])
        self.schedule_save()

    def _sync_grid_button(self):
        on = self.grid_on
        self.grid_button.config(bg=self.t["accent"] if on else self.t["bg"],
                                fg=self.t["bg"] if on else self.t["fg"])

    def _grid_color(self):
        """A faint line - muted blended most of the way into the page colour."""
        try:
            back = self.canvas.winfo_rgb(self.canvas_bg)
            line = self.canvas.winfo_rgb(self.t["muted"])
        except tk.TclError:
            return self.t["muted"]
        mixed = [int((b + (l - b) * GRID_BLEND) / 256) for b, l in zip(back, line)]
        return "#%02x%02x%02x" % tuple(max(0, min(255, c)) for c in mixed)

    def _draw_grid(self):
        """Repaint the overlay. The lines carry no record, so every scan the
        canvas does (select, erase, fill walls) looks straight through them."""
        self.canvas.delete("grid")
        if not self.grid_on:
            self._grid_extent = (0, 0)
            return
        width = max(1, self.canvas.winfo_width())
        height = max(1, self.canvas.winfo_height())
        step = GRID_SIZES[self.grid_index]
        colour = self._grid_color()
        for x in range(step, width, step):
            self.canvas.create_line(x, 0, x, height, fill=colour, tags="grid")
        for y in range(step, height, step):
            self.canvas.create_line(0, y, width, y, fill=colour, tags="grid")
        # Under the artwork, over the fills.
        self.canvas.tag_lower("grid")
        self.canvas.tag_lower(self.fill_item)
        self._grid_extent = (width, height)

    def _on_canvas_resize(self, event):
        if self.grid_on and (event.width, event.height) != self._grid_extent:
            self._draw_grid()

    # -- the tool bar ------------------------------------------------------
    def _build_tools(self):
        # Fixed-width column holding a scrollable strip, so a short window
        # still reaches everything down to Clear.
        column = tk.Frame(self.win, bg=self.t["panel"], width=100)
        column.grid(row=0, column=2, sticky="ns", padx=(4, 8), pady=8)
        # The contents are packed, so it's pack propagation that has to be off
        # for the width above to stick.
        column.pack_propagate(False)
        outer, bar, self.tool_scroll = self._scroller(column)
        outer.pack(fill="both", expand=True)

        self._heading(bar, "TOOLS").pack(fill="x", padx=8, pady=(8, 6))

        self.tool_buttons = {}
        for key, label in TOOLS:
            button = self._button(bar, label, lambda k=key: self._pick_tool(k),
                                  width=7)
            button.pack(padx=8, pady=1, ipady=3)
            self.tool_buttons[key] = button

        tk.Frame(bar, bg=self.t["bg"], height=1).pack(fill="x", padx=8,
                                                      pady=(10, 6))
        self._heading(bar, "COLOR").pack(fill="x", padx=8)
        grid = tk.Frame(bar, bg=self.t["panel"])
        grid.pack(padx=8, pady=(4, 6))
        for i, colour in enumerate(SWATCHES):
            chip = tk.Frame(grid, bg=colour, width=20, height=20,
                            highlightthickness=1,
                            highlightbackground=self.t["muted"], cursor="hand2")
            chip.grid(row=i // 2, column=i % 2, padx=2, pady=1)
            chip.bind("<Button-1>", lambda _e, c=colour: self._pick_color(c))
        self._button(bar, "Custom...", self._choose_color,
                     fg=self.t["muted"]).pack(padx=8, pady=(0, 6))

        self.color_preview = tk.Frame(bar, bg=self.color, height=6)
        self.color_preview.pack(fill="x", padx=8, pady=(0, 10))

        self._button(bar, "Clear", self._clear_canvas,
                     fg=self.t["fumble"]).pack(fill="x", padx=8, pady=(0, 10))
        self._pick_tool(self.tool)
        self._bind_wheel(bar, self.tool_scroll)

    def _pick_tool(self, key):
        if key != "select":
            self._clear_selection()
        self.tool = key
        for name, button in self.tool_buttons.items():
            on = name == key
            button.config(bg=self.t["accent"] if on else self.t["bg"],
                          fg=self.t["bg"] if on else self.t["fg"])
        self.canvas.config(cursor="fleur" if key == "select" else "crosshair")
        hints = {
            "select": "drag a box around things, then drag them to move - Delete removes",
            "pen": "click and drag to draw",
            "eraser": "rub out marks and filled colour",
            "line": "drag for a straight line",
            "ruler": "drag to measure, nothing is drawn",
            "box": "drag to draw a rectangle",
            "oval": "drag to draw a circle - hold Shift to keep it round",
            "fill": "click a shape to fill it, empty space for the background",
            "text": "click where the note should go",
        }
        self.hint.config(text=hints.get(key, ""))

    # -- pen size ----------------------------------------------------------
    def _toggle_size(self):
        if self.size_popup.winfo_ismapped():
            self.size_popup.place_forget()
        else:
            self.size_popup.place(relx=1.0, y=54, anchor="ne", x=-12)
            self.size_popup.lift()

    def _set_pen_width(self, value):
        self.pen_width = max(1, min(MAX_PEN, int(float(value))))
        self._draw_size_dot()
        self.schedule_save()

    def _draw_size_dot(self):
        self.size_dot.delete("all")
        radius = min(10, 1.5 + self.pen_width * 0.45)
        self.size_dot.create_oval(14 - radius, 12 - radius,
                                  14 + radius, 12 + radius,
                                  fill=self.color, outline=self.color)

    def _pick_color(self, colour):
        self.color = colour
        self.color_preview.config(bg=colour)
        self._draw_size_dot()
        self.schedule_save()

    def _choose_color(self):
        chosen = colorchooser.askcolor(color=self.color, parent=self.win)
        if chosen and chosen[1]:
            self._pick_color(chosen[1])

    def _clear_canvas(self):
        if not self.items and not self.fills:
            return
        if not messagebox.askyesno("Clear notes",
                                   "Erase everything drawn on the notes page?",
                                   parent=self.win, icon="warning"):
            return
        self._push_undo()
        self._clear_selection()
        for item in self.items:
            self.canvas.delete(item["id"])
        self.items = []
        self.fills = []
        self.fill_layer.blank()
        self.save()

    # -- drawing -----------------------------------------------------------
    def _create(self, record):
        kind = record["kind"]
        coords = record["coords"]
        colour = record.get("color", self.t["fg"])
        width = record.get("width", 2)
        if kind == "line":
            if len(coords) < 4:
                coords = list(coords) + list(coords[-2:])
            item = self.canvas.create_line(*coords, fill=colour, width=width,
                                           capstyle="round", joinstyle="round",
                                           smooth=True)
        elif kind == "rect":
            item = self.canvas.create_rectangle(*coords, outline=colour,
                                                width=width,
                                                fill=record.get("fill", ""))
        elif kind == "oval":
            item = self.canvas.create_oval(*coords, outline=colour, width=width,
                                           fill=record.get("fill", ""))
        elif kind == "text":
            item = self.canvas.create_text(coords[0], coords[1],
                                           text=record.get("text", ""),
                                           fill=colour, anchor="nw",
                                           font=self._text_font(
                                               self._text_size(record)))
        else:
            return None
        record["id"] = item
        return item

    def _base_text_size(self):
        return abs(tkfont.Font(font=self.f["result"]).cget("size")) or 11

    def _text_size(self, record):
        return int(record.get("size") or self._base_text_size())

    def _text_font(self, size):
        """One font object per size, kept - Tk wants a real font, and making
        a fresh one on every redraw is wasteful."""
        made = self._text_fonts.get(size)
        if made is None:
            base = tkfont.Font(font=self.f["result"])
            made = tkfont.Font(family=base.cget("family"), size=size,
                               weight=base.cget("weight"))
            self._text_fonts[size] = made
        return made

    def _restore_canvas(self):
        for record in self.items:
            self._create(record)

    def _record_for(self, item_id):
        for record in self.items:
            if record.get("id") == item_id:
                return record
        return None

    def _item_at(self, x, y):
        for item_id in reversed(self.canvas.find_overlapping(x - 3, y - 3,
                                                             x + 3, y + 3)):
            record = self._record_for(item_id)
            if record is not None:
                return record
        return None

    # -- selecting and moving ---------------------------------------------
    def _set_selection(self, records):
        self.selected = list(records)
        self._draw_selection()

    def _clear_selection(self):
        self.selected = []
        self.canvas.delete("selection")

    def _draw_selection(self):
        self.canvas.delete("selection")
        for record in self.selected:
            bounds = self.canvas.bbox(record["id"])
            if not bounds:
                continue
            x0, y0, x1, y1 = bounds
            self.canvas.create_rectangle(x0 - 3, y0 - 3, x1 + 3, y1 + 3,
                                         outline=self.t["accent"], dash=(3, 2),
                                         tags="selection")
        # One piece of text on its own gets a handle hanging off the corner
        # of the box: drag it to size the writing up or down.
        if len(self.selected) == 1 and self.selected[0]["kind"] == "text":
            bounds = self.canvas.bbox(self.selected[0]["id"])
            if bounds:
                x1, y1 = bounds[2] + 3, bounds[3] + 3
                self.canvas.create_rectangle(x1, y1, x1 + SIZER, y1 + SIZER,
                                             fill=self.t["accent"],
                                             outline=self.t["bg"],
                                             tags=("selection", "sizer"))

    def _handle_at(self, x, y):
        for item in self.canvas.find_withtag("sizer"):
            x0, y0, x1, y1 = self.canvas.coords(item)
            if x0 - 3 <= x <= x1 + 3 and y0 - 3 <= y <= y1 + 3:
                return True
        return False

    def _shift_record(self, record, dx, dy):
        record["coords"] = [c + (dx if i % 2 == 0 else dy)
                            for i, c in enumerate(record["coords"])]

    def _delete_selected(self, _event=None):
        if isinstance(self.win.focus_get(), tk.Entry):
            return  # the Delete key belongs to whatever is being typed in
        if not self.selected:
            return
        self._push_undo()
        for record in self.selected:
            self.canvas.delete(record["id"])
            if record in self.items:
                self.items.remove(record)
        self._clear_selection()
        self.save()

    # -- canvas events -----------------------------------------------------
    def _press(self, event):
        self.start = (event.x, event.y)
        self.last = (event.x, event.y)

        if self.tool == "select":
            if (len(self.selected) == 1
                    and self.selected[0]["kind"] == "text"
                    and self._handle_at(event.x, event.y)):
                self.drag_mode = "resize"
                self._push_undo()
                self.resize_from = (event.x, event.y,
                                    self._text_size(self.selected[0]))
                return
            hit = self._item_at(event.x, event.y)
            if hit is not None:
                if hit not in self.selected:
                    self._set_selection([hit])
                self.drag_mode = "move"
                self._push_undo()   # one snapshot for the whole drag
            else:
                self._clear_selection()
                self.drag_mode = "marquee"
            return

        if self.tool == "pen":
            self._push_undo()
            self.stroke = [event.x, event.y]
            self.current = self.canvas.create_line(
                event.x, event.y, event.x, event.y, fill=self.color,
                width=self.pen_width, capstyle="round", joinstyle="round")
        elif self.tool == "eraser":
            self._push_undo()
            self._erase_at(event.x, event.y)
        elif self.tool == "fill":
            self._push_undo()
            self._fill_at(event.x, event.y)
        elif self.tool == "text":
            self._add_text(event.x, event.y)

    def _drag(self, event):
        if self.tool == "select":
            if self.drag_mode == "move" and self.selected:
                dx = event.x - self.last[0]
                dy = event.y - self.last[1]
                for record in self.selected:
                    self.canvas.move(record["id"], dx, dy)
                    self._shift_record(record, dx, dy)
                self.last = (event.x, event.y)
                self._draw_selection()
            elif self.drag_mode == "resize" and self.selected:
                self._resize_text(event)
            elif self.drag_mode == "marquee":
                if self.preview is not None:
                    self.canvas.delete(self.preview)
                self.preview = self.canvas.create_rectangle(
                    self.start[0], self.start[1], event.x, event.y,
                    outline=self.t["accent"], dash=(3, 2))
            return

        if self.tool == "pen" and self.current is not None:
            self.stroke.extend([event.x, event.y])
            self.canvas.coords(self.current, *self.stroke)
        elif self.tool == "eraser":
            self._erase_at(event.x, event.y)
        elif self.tool in ("line", "ruler", "box", "oval"):
            self._preview(event)

    def _held_shift(self, event):
        return bool(getattr(event, "state", 0) & SHIFT)

    def _corner(self, event):
        """Where the shape ends.

        Holding Shift squares off the drag, which for the circle tool is the
        difference between an oval and a true circle. Let go of Shift and it
        is freehand again.
        """
        x0, y0 = self.start
        if self.tool != "oval" or not self._held_shift(event):
            return event.x, event.y
        dx, dy = event.x - x0, event.y - y0
        # The longer side wins, so the circle follows the hand rather than
        # collapsing to whichever way was moved less.
        reach = max(abs(dx), abs(dy))
        return (x0 + (reach if dx >= 0 else -reach),
                y0 + (reach if dy >= 0 else -reach))

    def _preview(self, event):
        x0, y0 = self.start
        if self.preview is not None:
            self.canvas.delete(self.preview)
        if self.preview_text is not None:
            self.canvas.delete(self.preview_text)
            self.preview_text = None

        stroke = 2 if self.tool == "ruler" else self.pen_width
        if self.tool == "box":
            self.preview = self.canvas.create_rectangle(
                x0, y0, event.x, event.y, outline=self.color, width=stroke,
                dash=(4, 2))
        elif self.tool == "oval":
            ex, ey = self._corner(event)
            self.preview = self.canvas.create_oval(
                x0, y0, ex, ey, outline=self.color, width=stroke,
                dash=(4, 2))
        else:
            dash = (6, 3) if self.tool == "ruler" else None
            self.preview = self.canvas.create_line(
                x0, y0, event.x, event.y, fill=self.color, width=stroke,
                **({"dash": dash} if dash else {}))
            if self.tool == "ruler":
                length = ((event.x - x0) ** 2 + (event.y - y0) ** 2) ** 0.5
                self.preview_text = self.canvas.create_text(
                    (x0 + event.x) / 2, (y0 + event.y) / 2 - 12,
                    text=f"{length:.0f} px", fill=self.color,
                    font=self.f["label"])

    def _release(self, event):
        if self.tool == "select":
            if self.drag_mode == "marquee":
                if self.preview is not None:
                    self.canvas.delete(self.preview)
                    self.preview = None
                x0, y0 = self.start
                found = []
                for item_id in self.canvas.find_overlapping(
                        min(x0, event.x), min(y0, event.y),
                        max(x0, event.x), max(y0, event.y)):
                    record = self._record_for(item_id)
                    if record is not None:
                        found.append(record)
                self._set_selection(found)
            elif self.drag_mode in ("move", "resize"):
                self.save()
            self.drag_mode = None
            self.resize_from = None
            return

        if self.tool == "pen" and self.current is not None:
            if len(self.stroke) >= 4:
                self.items.append({"kind": "line", "coords": list(self.stroke),
                                   "color": self.color,
                                   "width": self.pen_width,
                                   "id": self.current})
            else:
                self.canvas.delete(self.current)
            self.current = None
            self.stroke = []
            self.save()
            return

        if self.tool in ("line", "box", "oval", "ruler"):
            if self.preview is not None:
                self.canvas.delete(self.preview)
                self.preview = None
            if self.preview_text is not None:
                self.canvas.delete(self.preview_text)
                self.preview_text = None
            if self.tool == "ruler":
                return  # a ruler measures, it doesn't leave a mark
            x0, y0 = self.start
            ex, ey = self._corner(event)
            if abs(ex - x0) < 3 and abs(ey - y0) < 3:
                return  # a stray click, not a shape
            self._push_undo()
            kind = {"line": "line", "box": "rect", "oval": "oval"}[self.tool]
            record = {"kind": kind, "coords": [x0, y0, ex, ey],
                      "color": self.color, "width": self.pen_width}
            if kind in ("rect", "oval"):
                record["fill"] = ""
            self._create(record)
            self.items.append(record)
            self.save()

        if self.tool == "eraser":
            self.save()

    def _erase_at(self, x, y):
        for item_id in self.canvas.find_overlapping(x - ERASE_R, y - ERASE_R,
                                                    x + ERASE_R, y + ERASE_R):
            record = self._record_for(item_id)
            if record is not None:
                self.canvas.delete(item_id)
                self.items.remove(record)
        self._erase_fill_at(x, y)

    def _erase_fill_at(self, x, y):
        """Rub filled pixels out of the fill layer as well as off the record."""
        left, right = int(x) - ERASE_R, int(x) + ERASE_R
        top, bottom = int(y) - ERASE_R, int(y) + ERASE_R
        hit = False
        for fill in self.fills:
            kept = []
            for run_left, run_right, row in fill.get("runs", []):
                if not top <= row <= bottom or run_right < left or run_left > right:
                    kept.append([run_left, run_right, row])
                    continue
                hit = True
                if run_left < left:               # piece to the left survives
                    kept.append([run_left, min(run_right, left - 1), row])
                if run_right > right:             # piece to the right survives
                    kept.append([max(run_left, right + 1), run_right, row])
            fill["runs"] = kept
        if not hit:
            return
        for row in range(max(0, top), min(FILL_H, bottom + 1)):
            for column in range(max(0, left), min(FILL_W, right + 1)):
                try:
                    self.fill_layer.transparency_set(column, row, True)
                except tk.TclError:
                    pass
        self.fills = [f for f in self.fills if f.get("runs")]

    # -- flood fill --------------------------------------------------------
    def _wall_grid(self, width, height):
        """A 1-per-pixel map of everything drawn, used as fill boundaries.

        Whatever is drawn acts as a wall. A shape with a gap in it isn't a
        wall all the way round, so the fill escapes through the gap - same as
        a paint bucket in any drawing program.
        """
        walls = bytearray(width * height)
        for record in self.items:
            radius = max(1, (record.get("width", 2) + 1) // 2)
            coords = record["coords"]
            kind = record["kind"]
            if kind == "line":
                for i in range(0, len(coords) - 3, 2):
                    self._wall_line(walls, width, height, coords[i],
                                    coords[i + 1], coords[i + 2],
                                    coords[i + 3], radius)
            elif kind == "rect":
                x0, y0, x1, y1 = coords
                for a, b, c, d in ((x0, y0, x1, y0), (x1, y0, x1, y1),
                                   (x1, y1, x0, y1), (x0, y1, x0, y0)):
                    self._wall_line(walls, width, height, a, b, c, d, radius)
            elif kind == "oval":
                self._wall_oval(walls, width, height, coords, radius)
            # Text is left out on purpose - a fill flows around lettering
            # rather than being stopped by its bounding box.
        return walls

    def _wall_dot(self, walls, width, height, x, y, radius):
        for yy in range(max(0, y - radius), min(height, y + radius + 1)):
            row = yy * width
            for xx in range(max(0, x - radius), min(width, x + radius + 1)):
                walls[row + xx] = 1

    def _wall_line(self, walls, width, height, x0, y0, x1, y1, radius):
        x0, y0, x1, y1 = int(x0), int(y0), int(x1), int(y1)
        dx, dy = abs(x1 - x0), abs(y1 - y0)
        step_x = 1 if x0 < x1 else -1
        step_y = 1 if y0 < y1 else -1
        error = dx - dy
        while True:
            self._wall_dot(walls, width, height, x0, y0, radius)
            if x0 == x1 and y0 == y1:
                return
            doubled = 2 * error
            if doubled > -dy:
                error -= dy
                x0 += step_x
            if doubled < dx:
                error += dx
                y0 += step_y

    def _wall_oval(self, walls, width, height, coords, radius):
        x0, y0, x1, y1 = coords
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        rx, ry = abs(x1 - x0) / 2, abs(y1 - y0) / 2
        steps = max(32, int((rx + ry) * 2))
        previous = None
        for i in range(steps + 1):
            angle = 2 * math.pi * i / steps
            point = (cx + rx * math.cos(angle), cy + ry * math.sin(angle))
            if previous is not None:
                self._wall_line(walls, width, height, previous[0], previous[1],
                                point[0], point[1], radius)
            previous = point

    def _flood_runs(self, seed_x, seed_y, walls, width, height):
        """Scanline flood from a point, returned as (x0, x1, y) runs."""
        if not (0 <= seed_x < width and 0 <= seed_y < height):
            return []
        if walls[seed_y * width + seed_x]:
            return []
        seen = bytearray(width * height)
        runs = []
        stack = [(seed_x, seed_y)]
        while stack:
            x, y = stack.pop()
            row = y * width
            if seen[row + x] or walls[row + x]:
                continue
            left = x
            while left > 0 and not walls[row + left - 1] and not seen[row + left - 1]:
                left -= 1
            right = x
            while right < width - 1 and not walls[row + right + 1] \
                    and not seen[row + right + 1]:
                right += 1
            for xi in range(left, right + 1):
                seen[row + xi] = 1
            runs.append((left, right, y))
            for neighbour in (y - 1, y + 1):
                if not 0 <= neighbour < height:
                    continue
                nrow = neighbour * width
                xi = left
                while xi <= right:
                    if not walls[nrow + xi] and not seen[nrow + xi]:
                        stack.append((xi, neighbour))
                        while xi <= right and not walls[nrow + xi] \
                                and not seen[nrow + xi]:
                            xi += 1
                    else:
                        xi += 1
        return runs

    def _paint_runs(self, runs, colour):
        for left, right, y in runs:
            self.fill_layer.put(colour, to=(left, y, right + 1, y + 1))

    def _repaint_fills(self):
        """Redraw the layer from the pixels each fill actually covered.

        Fills are stored as the runs of pixels they painted, not as a seed
        point to be flooded again. That means rubbing out part of a shape
        leaves its fill exactly where it was instead of letting the colour
        escape across the page.
        """
        if not self.alive():
            return
        self.fill_layer.blank()
        legacy = [f for f in self.fills if "runs" not in f]
        if legacy:
            self._convert_legacy_fills(legacy)
        for fill in self.fills:
            self._paint_runs(fill.get("runs", []), fill["color"])

    def _convert_legacy_fills(self, legacy):
        """Journals saved before fills recorded their pixels."""
        width = min(max(1, self.canvas.winfo_width()), FILL_W)
        height = min(max(1, self.canvas.winfo_height()), FILL_H)
        walls = self._wall_grid(width, height)
        for fill in legacy:
            fill["runs"] = [list(r) for r in self._flood_runs(
                int(fill.get("x", 0)), int(fill.get("y", 0)), walls, width,
                height)]
            fill.pop("x", None)
            fill.pop("y", None)

    def _fill_at(self, x, y):
        self.canvas.config(cursor="watch")
        self.canvas.update_idletasks()
        try:
            width = min(max(1, self.canvas.winfo_width()), FILL_W)
            height = min(max(1, self.canvas.winfo_height()), FILL_H)
            walls = self._wall_grid(width, height)
            runs = self._flood_runs(int(x), int(y), walls, width, height)
        finally:
            self.canvas.config(cursor="fleur" if self.tool == "select"
                               else "crosshair")
        if not runs:
            return  # clicked straight onto a line
        self._paint_runs(runs, self.color)
        self.fills.append({"color": self.color,
                           "runs": [list(r) for r in runs]})
        self.save()

    def _resize_text(self, event):
        """Away from the corner grows it, back towards it shrinks."""
        px, py, base = self.resize_from
        step = int(((event.x - px) + (event.y - py)) / 6)
        self._apply_text_size(self.selected[0],
                              max(MIN_TEXT, min(MAX_TEXT, base + step)))

    def _apply_text_size(self, record, size):
        if size == self._text_size(record):
            return
        record["size"] = size
        self.canvas.itemconfigure(record["id"], font=self._text_font(size))
        self._draw_selection()

    def _set_text_size(self, record, size):
        self._push_undo()
        self._apply_text_size(record, size)
        self.save()

    def _edit_text(self, record):
        said = self._ask_text(record.get("text", ""), "Edit text")
        if said is None:
            return                      # they backed out
        self._push_undo()
        if not said.strip():
            # Emptying it would leave an invisible thing on the page that
            # could still be bumped into, so take it off instead.
            self.canvas.delete(record["id"])
            if record in self.items:
                self.items.remove(record)
            self._clear_selection()
        else:
            record["text"] = said
            self.canvas.itemconfigure(record["id"], text=said)
            self._draw_selection()
        self.save()

    def _remove_record(self, record):
        self._push_undo()
        self.canvas.delete(record["id"])
        if record in self.items:
            self.items.remove(record)
        self._clear_selection()
        self.save()

    def _canvas_menu(self, event):
        """Right-click something on the page to work on it."""
        hit = self._item_at(event.x, event.y)
        if hit is None:
            return
        self._set_selection([hit])
        menu = tk.Menu(self.win, tearoff=0, bg=self.t["panel"],
                       fg=self.t["fg"], activebackground=self.t["accent"],
                       activeforeground=self.t["bg"], bd=0,
                       font=self.f["label"])
        if hit["kind"] == "text":
            menu.add_command(label="Edit Text...",
                             command=lambda: self._edit_text(hit))
            sizes = tk.Menu(menu, tearoff=0, bg=self.t["panel"],
                            fg=self.t["fg"],
                            activebackground=self.t["accent"],
                            activeforeground=self.t["bg"], bd=0,
                            font=self.f["label"])
            current = self._text_size(hit)
            for size in TEXT_STEPS:
                sizes.add_command(
                    label=("* " if size == current else "   ") + str(size),
                    command=lambda s=size: self._set_text_size(hit, s))
            menu.add_cascade(label="Text Size", menu=sizes)
            menu.add_separator()
        menu.add_command(label="Delete",
                         command=lambda: self._remove_record(hit))
        menu.tk_popup(event.x_root, event.y_root)

    def _double_click(self, event):
        """Double-clicking a note is the quick way into editing it."""
        hit = self._item_at(event.x, event.y)
        if hit is not None and hit["kind"] == "text":
            self._set_selection([hit])
            self._edit_text(hit)

    def _ask_text(self, initial="", title="Note"):
        """The writing window. Returns the text, or None if they backed out."""
        return TextDialog(self.win, self.t, self.f, initial, title).result

    def _add_text(self, x, y):
        text = self._ask_text(title="Note")
        if not text or not text.strip():
            return
        self._push_undo()
        record = {"kind": "text", "coords": [x, y], "color": self.color,
                  "text": text, "size": self._base_text_size()}
        self._create(record)
        self.items.append(record)
        self.save()

    # -- section 3: threads ------------------------------------------------
    def _build_threads(self):
        box = tk.Frame(self.win, bg=self.t["panel"])
        box.grid(row=1, column=0, columnspan=3, sticky="nsew", padx=8,
                 pady=(0, 8))
        box.columnconfigure(0, weight=1)

        left = tk.Frame(box, bg=self.t["panel"])
        left.grid(row=0, column=0, sticky="nsew")
        header = tk.Frame(left, bg=self.t["panel"])
        header.pack(fill="x", padx=10, pady=(8, 4))
        self._heading(header, "THREADS  ·  QUESTS  ·  VOWS").pack(side="left")
        tk.Label(header,
                 text="left click a box to tick, right click to take one back  ·  "
                      "Check rolls 2d10 against your progress",
                 font=self.f["label"], bg=self.t["panel"],
                 fg=self.t["muted"]).pack(side="left", padx=12)
        self._button(header, "+", self._add_thread, fg=self.t["accent"],
                     width=2, font=self.f["die"]).pack(side="right", ipady=2)
        outer, self.thread_rows, self.thread_canvas = self._scroller(left,
                                                                     height=176)
        outer.pack(fill="both", expand=True, padx=6, pady=(0, 8))

        right = tk.Frame(box, bg=self.t["panel"], width=300)
        right.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        right.pack_propagate(False)
        self._heading(right, "COMPLETED").pack(fill="x", padx=10, pady=(8, 2))
        done_outer, self.done_rows, self.done_canvas = self._scroller(right,
                                                                      height=70)
        done_outer.pack(fill="x", padx=6)
        self._heading(right, "HALF COMPLETED").pack(fill="x", padx=10,
                                                    pady=(8, 2))
        half_outer, self.half_rows, self.half_canvas = self._scroller(right,
                                                                      height=70)
        half_outer.pack(fill="x", padx=6, pady=(0, 8))

    def _add_thread(self):
        self._push_undo()
        self.threads.append({"name": "", "boxes": [0] * BOXES_PER_THREAD,
                             "result": None})
        self._render_threads()
        self.save()

    def _drop_thread(self, index):
        self._push_undo()
        del self.threads[index]
        self._render_threads()
        self.save()

    def _render_threads(self):
        for child in self.thread_rows.winfo_children():
            child.destroy()
        if not self.threads:
            tk.Label(self.thread_rows,
                     text="No threads yet - add one to start tracking a quest.",
                     font=self.f["label"], bg=self.t["panel"],
                     fg=self.t["muted"], anchor="w").pack(fill="x", padx=4,
                                                          pady=6)
        for index, thread in enumerate(self.threads):
            row = tk.Frame(self.thread_rows, bg=self.t["panel"])
            row.pack(fill="x", pady=3, padx=4)

            name = self._entry(row, 24, thread["name"])
            name.pack(side="left", ipady=3)
            name.bind("<KeyRelease>",
                      lambda _e, i=index, w=name: self._rename_thread(i, w))

            boxes = []
            for slot in range(BOXES_PER_THREAD):
                cell = tk.Canvas(row, width=BOX_SIZE, height=BOX_SIZE,
                                 bg=self.t["panel"], highlightthickness=0,
                                 bd=0, cursor="hand2")
                cell.pack(side="left", padx=2)
                cell.bind("<Button-1>",
                          lambda _e, i=index, s=slot: self._tick(i, s, 1))
                cell.bind("<Button-3>",
                          lambda _e, i=index, s=slot: self._tick(i, s, -1))
                boxes.append(cell)
                self._draw_box(cell, thread["boxes"][slot])
            thread["_cells"] = boxes

            done = tk.Label(row, text="", font=self.f["label"],
                            bg=self.t["panel"], fg=self.t["accent"], width=6)
            done.pack(side="left", padx=(10, 0))
            thread["_done"] = done

            self._button(row, "Check", lambda i=index: self._check_thread(i),
                         fg=self.t["accent"]).pack(side="left", padx=(6, 0),
                                                   ipadx=4)

            mark = tk.Label(row, text="", font=self.f["die"],
                            bg=self.t["panel"], fg=self.t["accent"],
                            cursor="hand2")
            mark.pack(side="left", padx=(8, 0))
            mark.bind("<Button-1>", lambda _e, i=index: self._claim(i))
            thread["_mark"] = mark

            outcome = tk.Label(row, text="", font=self.f["label"],
                               bg=self.t["panel"], fg=self.t["muted"])
            outcome.pack(side="left", padx=(6, 0))
            thread["_outcome"] = outcome

            self._button(row, "x", lambda i=index: self._drop_thread(i),
                         fg=self.t["muted"], width=2).pack(side="right",
                                                           padx=(8, 6))
            self._update_row(thread)
        self._bind_wheel(self.thread_rows, self.thread_canvas)

    def _rename_thread(self, index, widget):
        self._commit_pending()
        self.threads[index]["name"] = widget.get()
        self.schedule_save()

    def _tick(self, index, slot, delta):
        thread = self.threads[index]
        self._push_undo()
        thread["boxes"][slot] = max(0, min(TICKS_PER_BOX,
                                           thread["boxes"][slot] + delta))
        self._draw_box(thread["_cells"][slot], thread["boxes"][slot])
        self._update_row(thread)
        self.schedule_save()

    def _progress(self, thread):
        return sum(1 for b in thread["boxes"] if b == TICKS_PER_BOX)

    def _update_row(self, thread):
        thread["_done"].config(
            text=f"{self._progress(thread)}/{BOXES_PER_THREAD}")
        result = thread.get("result")
        if not result:
            thread["_mark"].config(text="")
            thread["_outcome"].config(text="")
            return
        dice = result.get("dice", [0, 0])
        detail = f"{result.get('progress', 0)} vs {dice[0]} and {dice[1]}"
        if result["kind"] == "full":
            thread["_mark"].config(text="✓", fg=self.t["crit"], cursor="hand2")
            thread["_outcome"].config(text=f"{detail}  ·  completed",
                                      fg=self.t["crit"])
        elif result["kind"] == "partial":
            thread["_mark"].config(text="✓/✗", fg=self.t["accent"],
                                   cursor="hand2")
            thread["_outcome"].config(text=f"{detail}  ·  half done",
                                      fg=self.t["accent"])
        else:
            thread["_mark"].config(text="✗", fg=self.t["fumble"], cursor="arrow")
            thread["_outcome"].config(text=f"{detail}  ·  not yet",
                                      fg=self.t["fumble"])

    def _check_thread(self, index):
        """Progress score against two d10 challenge dice."""
        thread = self.threads[index]
        progress = self._progress(thread)
        first = self.api.roll_die("d10")
        second = self.api.roll_die("d10")
        beaten = (progress > first) + (progress > second)
        kind = {2: "full", 1: "partial"}.get(beaten, "miss")

        self._push_undo()
        thread["result"] = {"kind": kind, "progress": progress,
                            "dice": [first, second]}
        self._update_row(thread)
        self.save()

        title = thread["name"] or "This thread"
        words = {"full": "COMPLETED", "partial": "HALF COMPLETED",
                 "miss": "NOT COMPLETED"}
        group = self.api.make_group("d10", [first, second])
        group.note = "challenge dice"
        self.api.present(
            [group],
            notes=[f"{title}: progress {progress} vs {first} and {second}"
                   f" - {words[kind]}"],
            label=words[kind], hooks=False)

        # The verdict shows inline beside the thread - no popup to dismiss.

    def _claim(self, index):
        """Click the mark to move a resolved thread into its archive."""
        thread = self.threads[index]
        result = thread.get("result")
        if not result or result["kind"] not in ("full", "partial"):
            return
        dice = result.get("dice", [0, 0])
        record = {"name": thread["name"] or "(unnamed thread)",
                  "detail": f"{result['progress']} vs {dice[0]} and {dice[1]}"}
        self._push_undo()
        if result["kind"] == "full":
            self.completed.append(record)
        else:
            self.partial.append(record)
        del self.threads[index]
        self._render_threads()
        self._render_archives()
        self.save()

    def _render_archives(self):
        for rows, canvas, store, empty in (
                (self.done_rows, self.done_canvas, self.completed,
                 "Nothing finished yet."),
                (self.half_rows, self.half_canvas, self.partial,
                 "Nothing half done yet.")):
            for child in rows.winfo_children():
                child.destroy()
            if not store:
                tk.Label(rows, text=empty, font=self.f["label"],
                         bg=self.t["panel"], fg=self.t["muted"],
                         anchor="w").pack(fill="x", padx=4, pady=2)
            for index, record in enumerate(list(store)):
                row = tk.Frame(rows, bg=self.t["panel"])
                row.pack(fill="x", padx=4, pady=1)
                tk.Label(row, text=record["name"], font=self.f["label"],
                         bg=self.t["panel"], fg=self.t["fg"],
                         anchor="w").pack(side="left")
                tk.Label(row, text=record.get("detail", ""),
                         font=self.f["label"], bg=self.t["panel"],
                         fg=self.t["muted"]).pack(side="left", padx=6)
                self._button(row, "x",
                             lambda s=store, i=index: self._drop_archive(s, i),
                             fg=self.t["muted"], width=2).pack(side="right")
            self._bind_wheel(rows, canvas)

    def _drop_archive(self, store, index):
        self._push_undo()
        del store[index]
        self._render_archives()
        self.save()

    def _draw_box(self, cell, ticks):
        """Four ticks fill a box: | then - then / then \\."""
        cell.delete("all")
        edge = self.t["accent"] if ticks >= TICKS_PER_BOX else self.t["muted"]
        cell.create_rectangle(2, 2, BOX_SIZE - 2, BOX_SIZE - 2, outline=edge)
        mark = self.t["accent"]
        low, high, mid = 5, BOX_SIZE - 5, BOX_SIZE // 2
        if ticks >= 1:
            cell.create_line(mid, low, mid, high, fill=mark, width=2)
        if ticks >= 2:
            cell.create_line(low, mid, high, mid, fill=mark, width=2)
        if ticks >= 3:
            cell.create_line(low, high, high, low, fill=mark, width=2)
        if ticks >= 4:
            cell.create_line(low, low, high, high, fill=mark, width=2)


class TextDialog:
    """Writing a note for the page.

    Deliberately roomy: notes on a map are rarely one line, and the old
    one-line box meant opening a fresh note every time you wanted a second
    one. Enter is Done, because that is the button you are reaching for;
    Shift+Enter is what starts a new line.
    """

    WIDE, TALL = 54, 10         # in characters and lines

    def __init__(self, parent, theme, fonts, initial="", title="Note"):
        self.t = theme
        self.f = fonts
        self.result = None

        self.win = tk.Toplevel(parent)
        self.win.title(title)
        self.win.configure(bg=self.t["bg"])
        self.win.transient(parent)
        self.win.minsize(430, 260)
        self._build(initial)
        self.win.update_idletasks()
        x = parent.winfo_rootx() + (parent.winfo_width()
                                    - self.win.winfo_width()) // 2
        y = parent.winfo_rooty() + 90
        self.win.geometry("+%d+%d" % (max(0, x), max(0, y)))
        try:
            self.win.grab_set()
        except tk.TclError:
            pass
        self.box.focus_set()
        self.win.wait_window(self.win)

    def _build(self, initial):
        pad = tk.Frame(self.win, bg=self.t["bg"])
        pad.pack(fill="both", expand=True, padx=14, pady=12)

        tk.Label(pad, text="Enter to finish  ·  Shift+Enter for a new line",
                 font=self.f["label"], bg=self.t["bg"],
                 fg=self.t["muted"]).pack(anchor="w", pady=(0, 6))

        frame = tk.Frame(pad, bg=self.t["panel"])
        frame.pack(fill="both", expand=True)
        self.box = tk.Text(frame, width=self.WIDE, height=self.TALL,
                           bg=self.t["panel"], fg=self.t["fg"],
                           insertbackground=self.t["fg"], relief="flat", bd=0,
                           wrap="word", undo=True, font=self.f["result"],
                           padx=8, pady=6)
        bar = tk.Scrollbar(frame, orient="vertical", command=self.box.yview,
                           bg=self.t["panel"], troughcolor=self.t["bg"],
                           activebackground=self.t["accent"], relief="flat",
                           bd=0, width=10)
        self.box.configure(yscrollcommand=bar.set)
        self.box.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")
        if initial:
            self.box.insert("1.0", initial)

        # Bound on the Text itself and returning "break", so Tk's own newline
        # handling never runs for a bare Enter.
        self.box.bind("<Return>", self._accept)
        self.box.bind("<Shift-Return>", self._newline)
        self.box.bind("<KP_Enter>", self._accept)
        self.win.bind("<Escape>", lambda _e: self.win.destroy())

        buttons = tk.Frame(pad, bg=self.t["bg"])
        buttons.pack(fill="x", pady=(10, 0))
        tk.Button(buttons, text="Done", font=self.f["label"],
                  bg=self.t["accent"], fg=self.t["bg"],
                  activebackground=self.t["accent_hot"],
                  activeforeground=self.t["bg"], relief="flat", bd=0,
                  cursor="hand2", command=self._accept).pack(side="right",
                                                             ipadx=14, ipady=4)
        tk.Button(buttons, text="Cancel", font=self.f["label"],
                  bg=self.t["bg"], fg=self.t["muted"],
                  activebackground=self.t["panel"],
                  activeforeground=self.t["fg"], relief="flat", bd=0,
                  cursor="hand2", command=self.win.destroy).pack(side="right",
                                                                 padx=(0, 8))

    def _newline(self, _event=None):
        self.box.insert("insert", "\n")
        self.box.see("insert")
        return "break"

    def _accept(self, _event=None):
        # Trailing blank lines are almost always a stray Shift+Enter, and
        # they would push the note's box down the page for nothing.
        self.result = self.box.get("1.0", "end-1c").rstrip()
        self.win.destroy()
        return "break"
