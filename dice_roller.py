"""Dice Roller - a clickable dice rolling app for tabletop / solo RPGs.

Run with:  python dice_roller.py
Mods live in the plugins/ folder - see plugins/README.md
"""

import os
import subprocess
import sys
import tkinter as tk
import traceback
from tkinter import font as tkfont
from tkinter import messagebox, simpledialog

import core_panels
import dice_api
import paths
import pointer
import roster_bar
import session as session_module
from dice_api import THEME, Die, Group, RollRequest, RollResult

BG = THEME["bg"]
PANEL = THEME["panel"]
FG = THEME["fg"]
MUTED = THEME["muted"]
ACCENT = THEME["accent"]
CRIT = THEME["crit"]
FUMBLE = THEME["fumble"]

CORE_DICE = [2, 4, 6, 8, 10, 12, 20, 100]


class DiceRoller(tk.Tk):
    def __init__(self, plan=None):
        super().__init__()
        self.plan = plan or {"mode": "solo"}
        self.save_name = dice_api.current_save()
        self.title(f"{paths.APP_NAME} {paths.VERSION} - {self.save_name}")
        paths.apply_icon(self)
        self.configure(bg=BG)
        # Small enough to tuck beside something else. Anything that will
        # not fit is reached by scrolling rather than being cut off.
        self.minsize(260, 220)
        self.geometry("380x600")

        self.dice = {}          # key -> Die
        self.pool = {}          # key -> count queued for the next roll
        self.hooks = {}         # event -> [(mod name, callback)]
        self.die_buttons = {}
        self._die_cols = 4         # how many dice fit across, at this width
        self.last_result = None
        self.plugins = []

        # Who else is at the table. Started before the mods load, so a mod
        # can hook into it while it is setting itself up.
        self.session = session_module.Session(self, self.plan)
        self.session.start()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self._build_fonts()
        for i, sides in enumerate(CORE_DICE):
            # The d20 is weighted - see D20_WEIGHTS in dice_api.py.
            self.register_die(Die(key=f"d{sides}", label=f"d{sides}",
                                  sides=sides, order=i,
                                  roller=dice_api.roll_d20 if sides == 20
                                  else None))
        # Your own pointer, in your own colour - the same arrow the other
        # players see following you around the map.
        pointer.apply_profile(self, self.session)

        self._build_roster()
        self._build_scroll_shell()
        self._build_menubar()
        self._build_ui()

        # Which panels the user had minimised, and in what order, last time.
        self._config = dice_api.load_config()
        self._collapsed = set(self._config.get("collapsed", []))
        self.panels = []        # panel entries, in registration order
        self.panel_order = []   # the same entries, in the order shown
        self._drag = None

        # Built-in panels first, then mods register their dice / buttons /
        # panels on top.
        core_panels.install(self)
        self.plugins = dice_api.load_all(self)
        self._report_session()
        self._apply_saved_panel_order()
        self._build_die_grid()
        self._refresh_pool()
        self.emit("app_ready", self)

    def _build_roster(self):
        """The row of faces, pinned above the scrolling part so it stays put.

        Left out when playing alone - a strip showing only yourself would be
        taking up room to say nothing.
        """
        self.roster = None
        if self.session.is_solo:
            return
        self.roster = roster_bar.RosterBar(self, self.session)
        self.roster.pack(side="top", fill="x")
        tk.Frame(self, bg="#31353f", height=1).pack(side="top", fill="x")

    def _report_session(self):
        """Say what happened once there is a window to say it in."""
        if self.plan.get("mode") == "host" and self.session.error:
            messagebox.showwarning(
                "Could not host",
                f"The session could not be started, so this is a solo "
                f"game for now.\n\n{self.session.error}\n\n"
                f"Another copy of the app may still be hosting on "
                f"this machine.", parent=self)
        elif self.session.is_host:
            self.session.announce(
                f"Hosting - invite code {self.session.code}", colour="crit")
        elif not self.session.is_solo:
            host = (self.session.host_card or {}).get("name", "the host")
            self.session.announce(f"Joined {host}'s campaign.", colour="crit")

    def _on_close(self):
        self.emit("save", self.save_name)
        self.session.close()
        self.destroy()

    def open_main_menu(self):
        """Back out to the front door. The app restarts to get there."""
        self.emit("save", self.save_name)
        config = dice_api.load_config()
        config["force_menu"] = True
        dice_api.save_config(config)
        self.session.close()
        self.restart()

    def _build_fonts(self):
        # Deliberately small. This is meant to sit beside the map as a tool,
        # not to fill a quarter of the screen - and every mod draws with
        # these same fonts, so the panels come down with it.
        self.f_title = tkfont.Font(family="Segoe UI", size=11, weight="bold")
        self.f_label = tkfont.Font(family="Segoe UI", size=8)
        self.f_die = tkfont.Font(family="Segoe UI", size=10, weight="bold")
        self.f_roll = tkfont.Font(family="Segoe UI", size=12, weight="bold")
        self.f_result = tkfont.Font(family="Consolas", size=9)
        self.f_total = tkfont.Font(family="Segoe UI", size=22, weight="bold")
        self.fonts = {
            "title": self.f_title, "label": self.f_label, "die": self.f_die,
            "roll": self.f_roll, "result": self.f_result, "total": self.f_total,
        }

    # ------------------------------------------------------------------
    # Scrolling shell - everything else is built inside self.content
    # ------------------------------------------------------------------
    def _build_scroll_shell(self):
        self.canvas = tk.Canvas(self, bg=BG, highlightthickness=0, bd=0)
        self.vscroll = tk.Scrollbar(
            self, orient="vertical", command=self.canvas.yview,
            bg=PANEL, troughcolor=BG, activebackground=ACCENT,
            relief="flat", bd=0, highlightthickness=0, width=12)
        self.hscroll = tk.Scrollbar(
            self, orient="horizontal", command=self.canvas.xview,
            bg=PANEL, troughcolor=BG, activebackground=ACCENT,
            relief="flat", bd=0, highlightthickness=0, width=12)
        self.canvas.configure(yscrollcommand=self._sync_scrollbar,
                              xscrollcommand=self._sync_hscroll)
        # Along the foot first, so it spans the full width under both.
        self.hscroll.pack(side="bottom", fill="x")
        self.vscroll.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)

        self.content = tk.Frame(self.canvas, bg=BG)
        self._content_id = self.canvas.create_window(
            (0, 0), window=self.content, anchor="nw")
        # Content decides the scrollable height; the canvas decides the width.
        self.content.bind(
            "<Configure>",
            lambda _e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", self._fit_content)

        self.bind_all("<MouseWheel>", self._on_mousewheel)        # Windows / macOS
        # Shift and the wheel goes sideways, for when the window is narrow
        # enough that the page runs off the edge.
        self.bind_all("<Shift-MouseWheel>", self._on_shift_wheel)
        self.bind_all("<Button-4>", self._on_mousewheel)          # X11 up
        self.bind_all("<Button-5>", self._on_mousewheel)          # X11 down

    # ------------------------------------------------------------------
    # Menu bar and campaigns
    # ------------------------------------------------------------------
    def _build_menubar(self):
        self.menus = {}
        style = {"bg": PANEL, "fg": FG, "activebackground": ACCENT,
                 "activeforeground": BG, "relief": "flat", "bd": 0,
                 "tearoff": 0}
        self._menu_style = style
        self.menubar = tk.Menu(self, **style)

        self.file_menu = tk.Menu(self.menubar, **style)
        self.menubar.add_cascade(label="File", menu=self.file_menu)
        self.menus["File"] = self.file_menu
        self._rebuild_file_menu()

        # Mods hang their windows off Tools.
        tools = tk.Menu(self.menubar, **style)
        self.menubar.add_cascade(label="Tools", menu=tools)
        self.menus["Tools"] = tools
        tools.add_command(label="Mods...", command=self.open_mod_manager)
        tools.add_separator()

        self.configure(menu=self.menubar)

    def _rebuild_file_menu(self):
        """Redrawn whenever the list of campaigns changes."""
        menu = self.file_menu
        menu.delete(0, "end")
        menu.add_command(label="Save", command=self.save_all)
        menu.add_separator()

        opens = tk.Menu(menu, **self._menu_style)
        self._open_choice = tk.StringVar(value=self.save_name)
        for name in dice_api.list_saves():
            opens.add_radiobutton(label=name, value=name,
                                  variable=self._open_choice,
                                  command=lambda n=name: self.switch_save(n))
        menu.add_cascade(label="Open campaign", menu=opens)
        menu.add_command(label="New campaign...", command=self.new_save)
        menu.add_command(label="Save as new campaign...", command=self.save_as)
        menu.add_command(label="Delete campaign...", command=self.delete_save)
        menu.add_separator()
        menu.add_command(label="Main Menu...", command=self.open_main_menu)
        menu.add_command(label="Exit", command=self._on_close)

    def register_menu_command(self, menu_name, label, command):
        menu = self.menus.get(menu_name)
        if menu is None:
            menu = tk.Menu(self.menubar, **self._menu_style)
            self.menubar.add_cascade(label=menu_name, menu=menu)
            self.menus[menu_name] = menu
        menu.add_command(label=label, command=command)
        return menu

    def save_all(self):
        """Ask every mod to flush, then confirm in the title bar briefly."""
        self.emit("save", self.save_name)
        self.title(f"{paths.APP_NAME} {paths.VERSION} - {self.save_name}   (saved)")
        self.after(1200, lambda: self.title(f"{paths.APP_NAME} {paths.VERSION} - {self.save_name}"))

    def new_save(self, copy_current=False):
        name = simpledialog.askstring(
            "New campaign" if not copy_current else "Save as new campaign",
            "Name this campaign:", parent=self)
        if not name:
            return
        self.save_all()
        created = dice_api.create_save(
            name, copy_from=self.save_name if copy_current else None)
        if created is None:
            messagebox.showerror("Campaign exists",
                                 f"There is already a campaign called "
                                 f"{dice_api.clean_save_name(name)!r}.",
                                 parent=self)
            return
        self.switch_save(created)

    def save_as(self):
        self.new_save(copy_current=True)

    def delete_save(self):
        saves = dice_api.list_saves()
        if len(saves) < 2:
            messagebox.showinfo(
                "Delete campaign",
                "This is your only campaign, so there is nothing to switch to "
                "if it goes. Make another one first.", parent=self)
            return
        if not messagebox.askyesno(
                "Delete campaign",
                f"Delete {self.save_name!r} for good?\n\n"
                "Its dice history, initiative roster, journal and everything "
                "else in it will be gone.", parent=self, icon="warning"):
            return
        going = self.save_name
        dice_api.delete_save(going)
        self.switch_save(next(n for n in saves if n != going), flush=False)

    def switch_save(self, name, flush=True):
        """Load another campaign. Mods build from storage, so this restarts."""
        if flush:
            self.emit("save", self.save_name)
        dice_api.set_current_save(name)
        self.restart()

    def restart(self):
        if paths.FROZEN:
            # Built into a program: the program itself is the thing to run
            # again. There is no script to hand it.
            command = [sys.executable]
        else:
            command = [sys.executable, os.path.abspath(__file__)]
        try:
            subprocess.Popen(command, cwd=paths.APP_DIR)
        except OSError as exc:
            messagebox.showerror("Could not reopen",
                                 f"Restart failed: {exc}", parent=self)
            return
        self.destroy()

    def _fit_content(self, event):
        """Stretch the page to the window - but never squeeze it narrower
        than it needs to be.

        Forced narrower, the panels inside do not shrink politely; they get
        clipped. So below its natural width the page keeps that width and
        the bar along the foot appears instead.
        """
        wanted = max(event.width, self.content.winfo_reqwidth())
        self.canvas.itemconfigure(self._content_id, width=wanted)
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        self._reflow_dice(event.width)

    def _sync_scrollbar(self, first, last):
        """Only show the scrollbar when there is something to scroll to."""
        self.vscroll.set(first, last)
        needed = float(first) > 0.0 or float(last) < 1.0
        if needed and not self.vscroll.winfo_ismapped():
            self.vscroll.pack(side="right", fill="y", before=self.canvas)
        elif not needed and self.vscroll.winfo_ismapped():
            self.vscroll.pack_forget()

    def _on_shift_wheel(self, event):
        if event.widget.winfo_toplevel() is not self:
            return
        self.canvas.xview_scroll(-1 if event.delta > 0 else 1, "units")
        return "break"

    def _sync_hscroll(self, first, last):
        """The same, for the bar along the foot."""
        self.hscroll.set(first, last)
        needed = float(first) > 0.0 or float(last) < 1.0
        if needed and not self.hscroll.winfo_ismapped():
            self.hscroll.pack(side="bottom", fill="x", before=self.canvas)
        elif not needed and self.hscroll.winfo_ismapped():
            self.hscroll.pack_forget()

    def _on_mousewheel(self, event):
        if event.widget.winfo_toplevel() is not self:
            return  # a Toplevel (the Mods window) has its own scrolling
        # If the pointer is over a widget that can scroll itself (the roll
        # history), let that widget have the wheel instead.
        if isinstance(event.widget, (tk.Text, tk.Listbox)):
            try:
                first, last = event.widget.yview()
                if first > 0.0 or last < 1.0:
                    return
            except tk.TclError:
                pass
        if event.num == 4:
            steps = -1
        elif event.num == 5:
            steps = 1
        else:
            steps = -int(event.delta / 120) or (-1 if event.delta > 0 else 1)
        self.canvas.yview_scroll(steps, "units")

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build_ui(self):
        pad = {"padx": 8}
        parent = self.content

        tk.Label(parent, text="DICE ROLLER", font=self.f_title,
                 bg=BG, fg=ACCENT).pack(pady=(6, 0), **pad)
        tk.Label(parent, text="click dice, then ROLL",
                 font=self.f_label, bg=BG, fg=MUTED).pack(pady=(0, 6), **pad)

        self.grid_frame = tk.Frame(parent, bg=BG)
        self.grid_frame.pack(fill="x", **pad)

        # Sits between the dice and the pool - for the modifier, which gets
        # reached for constantly.
        self.dice_extras = tk.Frame(parent, bg=BG)
        self.dice_extras.pack(fill="x", pady=(6, 0), **pad)

        pool_row = tk.Frame(parent, bg=BG)
        pool_row.pack(fill="x", pady=(8, 3), **pad)
        self.pool_label = tk.Label(pool_row, text="", font=self.f_die,
                                   bg=BG, fg=FG, anchor="w")
        self.pool_label.pack(side="left")
        self._flat_button(pool_row, "Clear", self.clear_pool,
                          fg=MUTED, hot=FUMBLE).pack(side="right")

        roll_row = tk.Frame(parent, bg=BG)
        roll_row.pack(fill="x", pady=(4, 0), **pad)
        self.roll_button = tk.Button(
            roll_row, text="[ ROLL ]", font=self.f_roll, bg=ACCENT, fg=BG,
            activebackground=THEME["accent_hot"], activeforeground=BG,
            relief="flat", bd=0, cursor="hand2", command=self.roll)
        self.roll_button.pack(side="left", ipadx=8, ipady=8, fill="y")

        self.results = tk.Text(
            roll_row, font=self.f_result, bg=PANEL, fg=FG, relief="flat", bd=0,
            height=4, width=1, wrap="word", padx=6, pady=4,
            state="disabled", cursor="arrow")
        self.results.pack(side="left", fill="both", expand=True, padx=(6, 0))
        self.results.tag_configure("die", foreground=MUTED)
        self.results.tag_configure("val", foreground=FG)
        self.results.tag_configure("crit", foreground=CRIT)
        self.results.tag_configure("fumble", foreground=FUMBLE)
        self.results.tag_configure("drop", foreground=MUTED, overstrike=True)
        self.results.tag_configure("note", foreground=ACCENT)

        total_box = tk.Frame(parent, bg=BG)
        total_box.pack(fill="x", pady=(10, 8), **pad)
        tk.Label(total_box, text="TOTAL", font=self.f_label,
                 bg=BG, fg=MUTED).pack()
        self.total_label = tk.Label(total_box, text="—", font=self.f_total,
                                    bg=BG, fg=ACCENT)
        self.total_label.pack()

        # Built-in extras that belong to the roller itself - modifier, roll
        # history - sit directly under the total and above anything from mods.
        self.core_area = tk.Frame(parent, bg=BG)
        self.core_area.pack(fill="x", **pad)

        # Mod bar: mod buttons on the left, mod manager on the right.
        self.mod_bar = tk.Frame(parent, bg=BG)
        self.mod_bar.pack(fill="x", pady=(0, 6), **pad)
        self._flat_button(self.mod_bar, "⚙ Mods", self.open_mod_manager,
                          fg=MUTED, hot=ACCENT).pack(side="right")
        self.mod_actions = tk.Frame(self.mod_bar, bg=BG)
        self.mod_actions.pack(side="left")

        self.panel_area = tk.Frame(parent, bg=BG)
        self.panel_area.pack(fill="x", pady=(0, 14), **pad)

        self.bind("<Return>", self._hotkey(self.roll))
        self.bind("<space>", self._hotkey(self.roll))
        self.bind("<Escape>", self._hotkey(self.clear_pool))

    def _hotkey(self, action):
        """Window-wide shortcut that stays out of the way while typing."""
        def handler(_event=None):
            if isinstance(self.focus_get(), (tk.Entry, tk.Text, tk.Spinbox)):
                return  # a mod's text field has the keyboard
            action()
        return handler

    def _flat_button(self, parent, text, command, fg=FG, hot=ACCENT, bg=BG):
        return tk.Button(parent, text=text, font=self.f_label, bg=bg, fg=fg,
                         activebackground=bg, activeforeground=hot,
                         relief="flat", bd=0, cursor="hand2", command=command)

    def _reflow_dice(self, width):
        """Lay the dice out in as many columns as will fit.

        Four across is right for the usual window; narrower than that they
        would be squeezed to nothing, so the grid folds to three, then two.
        """
        # Measured against the page, which is a scrollbar's width narrower
        # than the window itself.
        cols = 4 if width >= 280 else (3 if width >= 230 else 2)
        if cols == getattr(self, "_die_cols", 4):
            return
        self._die_cols = cols
        if getattr(self, "die_buttons", None):
            self._build_die_grid()

    def _build_die_grid(self):
        for child in self.grid_frame.winfo_children():
            child.destroy()
        self.die_buttons.clear()
        cols = getattr(self, "_die_cols", 4)
        for i, die in enumerate(self.ordered_dice()):
            b = tk.Button(
                self.grid_frame, text=die.label, font=self.f_die, width=4,
                bg=PANEL, fg=FG, activebackground=ACCENT, activeforeground=BG,
                relief="flat", bd=0, cursor="hand2",
                command=lambda k=die.key: self.add_die(k))
            b.grid(row=i // cols, column=i % cols, padx=2, pady=2,
                   ipady=2, sticky="ew")
            b.bind("<Button-3>", lambda _e, k=die.key: self.add_die(k, -1))
            self.die_buttons[die.key] = b
        for c in range(cols):
            self.grid_frame.columnconfigure(c, weight=1)

    def ordered_dice(self):
        return sorted(self.dice.values(), key=lambda d: (d.order, d.sides))

    # ------------------------------------------------------------------
    # Mod registration (called through PluginAPI)
    # ------------------------------------------------------------------
    def register_die(self, die):
        self.dice[die.key] = die
        self.pool.setdefault(die.key, 0)
        return die

    def register_action(self, label, callback, color=None):
        b = self._flat_button(self.mod_actions, label, callback,
                              fg=color or FG, bg=PANEL)
        b.configure(bg=PANEL, activebackground=PANEL)
        b.pack(side="left", padx=(0, 6), ipadx=8, ipady=4)
        return b

    def register_panel(self, title, builder, area="mods"):
        """Where the panel goes:

        "dice" - pinned right under the dice buttons, above the pool
        "core" - pinned under the total, above anything from mods
        "mods" - the draggable stack at the bottom (the default)
        """
        parent = {"dice": getattr(self, "dice_extras", None),
                  "core": getattr(self, "core_area", None)}.get(area)
        if parent is None:
            parent = self.panel_area
        box = tk.Frame(parent, bg=PANEL)
        box.pack(fill="x", pady=(0, 8))
        body = tk.Frame(box, bg=PANEL)

        if not title:
            self._fill_panel_body(body, builder)
            body.pack(fill="x")
            return box

        # Title bar: click to minimise, and for mod panels drag to reorder.
        header = tk.Frame(box, bg=PANEL, cursor="hand2")
        header.pack(fill="x", padx=12, pady=(8, 0))
        arrow = tk.Label(header, font=self.f_label, bg=PANEL, fg=ACCENT, width=2)
        arrow.pack(side="left")
        name = tk.Label(header, text=title.upper(), font=self.f_label,
                        bg=PANEL, fg=MUTED, anchor="w")
        name.pack(side="left", fill="x", expand=True)
        grip = None
        if area not in ("core", "dice"):
            grip = tk.Label(header, text="≡", font=self.f_label, bg=PANEL,
                            fg=MUTED)
            grip.pack(side="right", padx=(6, 0))

        self._fill_panel_body(body, builder)
        state = {"collapsed": title in self._collapsed}

        def apply():
            if state["collapsed"]:
                body.pack_forget()
                arrow.config(text="▼")          # click to drop it back down
                header.pack_configure(pady=(8, 8))
            else:
                body.pack(fill="x")             # goes below the header
                arrow.config(text="▲")          # click to minimise
                header.pack_configure(pady=(8, 0))

        def toggle():
            state["collapsed"] = not state["collapsed"]
            apply()
            self._remember_collapsed(title, state["collapsed"])

        if area in ("core", "dice"):
            # Pinned in place: collapsing only, no dragging.
            for widget in (header, arrow, name):
                widget.bind("<Button-1>", lambda _e: toggle())
            apply()
            return box

        entry = {"title": title, "box": box, "header": header,
                 "labels": (arrow, name, grip), "toggle": toggle}
        self.panels.append(entry)
        self.panel_order.append(entry)

        for widget in (header, arrow, name, grip):
            widget.bind("<Button-1>", lambda e, en=entry: self._panel_press(en, e))
            widget.bind("<B1-Motion>", lambda e, en=entry: self._panel_drag(en, e))
            widget.bind("<ButtonRelease-1>",
                        lambda e, en=entry: self._panel_release(en, e))
        apply()
        return box

    # -- drag to reorder --------------------------------------------------
    def _pack_panel(self, entry, index):
        """Pack a panel box at a given position among its siblings."""
        entry["box"].pack_forget()
        below = self.panel_order[index + 1:]
        if below:
            entry["box"].pack(fill="x", pady=(0, 8), before=below[0]["box"])
        else:
            entry["box"].pack(fill="x", pady=(0, 8))
        # Settle the new geometry so the next motion event measures correctly.
        self.panel_area.update_idletasks()

    def _panel_press(self, entry, event):
        self._drag = {
            "entry": entry,
            "start": event.y_root,
            # Where on the panel the user grabbed it, so the panel can be
            # tracked rather than just the pointer.
            "offset": event.y_root - entry["box"].winfo_rooty(),
            "moved": False,
        }

    def _panel_drag(self, entry, event):
        drag = self._drag
        if not drag or drag["entry"] is not entry:
            return
        if not drag["moved"]:
            if abs(event.y_root - drag["start"]) < 5:
                return  # still just a click
            drag["moved"] = True
            for label in entry["labels"]:
                label.config(fg=ACCENT)

        # Where would the middle of the dragged panel sit right now? Comparing
        # that against the other panels' midpoints makes moving up and moving
        # down take the same drag distance.
        top = event.y_root - drag["offset"] - self.panel_area.winfo_rooty()
        centre = top + entry["box"].winfo_height() / 2
        target = 0
        for other in self.panel_order:
            if other is entry:
                continue
            box = other["box"]
            if centre > box.winfo_y() + box.winfo_height() / 2:
                target += 1
            else:
                break

        current = self.panel_order.index(entry)
        if target != current:
            self.panel_order.remove(entry)
            self.panel_order.insert(target, entry)
            self._pack_panel(entry, target)

    def _panel_release(self, entry, _event):
        drag = self._drag
        self._drag = None
        if not drag or drag["entry"] is not entry:
            return
        if drag["moved"]:
            arrow, name, grip = entry["labels"]
            arrow.config(fg=ACCENT)
            name.config(fg=MUTED)
            grip.config(fg=MUTED)
            self._save_panel_order()
        else:
            entry["toggle"]()

    def _apply_saved_panel_order(self):
        """Restore the order the panels were left in, new mods last."""
        saved = self._config.get("panel_order", [])
        rank = {title: i for i, title in enumerate(saved)}
        self.panel_order = sorted(
            self.panels,
            key=lambda e: (rank.get(e["title"], len(saved)), self.panels.index(e)))
        for entry in self.panel_order:
            entry["box"].pack_forget()
        for entry in self.panel_order:
            entry["box"].pack(fill="x", pady=(0, 8))

    def _save_panel_order(self):
        self._config = dice_api.load_config()
        self._config["panel_order"] = [e["title"] for e in self.panel_order]
        dice_api.save_config(self._config)

    def _fill_panel_body(self, body, builder):
        inner = builder(body)
        if isinstance(inner, tk.Widget):
            inner.pack(fill="both", expand=True, padx=12, pady=(4, 10))

    def _remember_collapsed(self, title, collapsed):
        if collapsed:
            self._collapsed.add(title)
        else:
            self._collapsed.discard(title)
        self._config = dice_api.load_config()
        self._config["collapsed"] = sorted(self._collapsed)
        dice_api.save_config(self._config)

    def emit(self, event, payload):
        for name, callback in self.hooks.get(event, []):
            try:
                callback(payload)
            except Exception:
                print(f"[mods] {name} failed on {event}:\n{traceback.format_exc()}")

    # ------------------------------------------------------------------
    # Pool
    # ------------------------------------------------------------------
    def add_die(self, key, delta=1):
        self.pool[key] = max(0, self.pool.get(key, 0) + delta)
        self._refresh_pool()

    def set_pool(self, counts):
        for key in self.pool:
            self.pool[key] = 0
        for key, n in counts.items():
            if key in self.pool:
                self.pool[key] = max(0, int(n))
        self._refresh_pool()

    def clear_pool(self):
        self.set_pool({})
        self._render(RollResult())
        self.total_label.config(text="—")

    def _refresh_pool(self):
        parts = [f"{n}{self.dice[k].label}" for k, n in self.pool.items() if n]
        self.pool_label.config(
            text="Pool:  " + (" + ".join(parts) if parts else "empty"),
            fg=FG if parts else MUTED)
        for key, b in self.die_buttons.items():
            n = self.pool.get(key, 0)
            label = self.dice[key].label
            b.config(text=label if not n else f"{label}  ×{n}",
                     bg=ACCENT if n else PANEL, fg=BG if n else FG)
        self.roll_button.config(state="normal" if parts else "disabled")

    # ------------------------------------------------------------------
    # Rolling
    # ------------------------------------------------------------------
    def roll(self, counts=None):
        counts = {k: v for k, v in (counts or self.pool).items() if v > 0}
        if not counts:
            return None
        request = RollRequest(counts=dict(counts))
        self.emit("before_roll", request)
        if request.cancelled:
            return None

        groups = []
        for key, n in request.counts.items():
            die = self.dice.get(key)
            if die is None or n <= 0:
                continue
            groups.append(Group(die=die, values=[die.roll() for _ in range(n)]))
        if not groups:
            return None
        return self.present(RollResult(groups=groups))

    def present(self, result, hooks=True):
        """Run after_roll hooks, show the result, then fire `rolled`."""
        if hooks:
            self.emit("after_roll", result)
        self._render(result)
        self.total_label.config(text=str(result.total))
        self.last_result = result
        self.emit("rolled", result)
        return result

    def _render(self, result):
        self.results.config(state="normal")
        self.results.delete("1.0", "end")
        first = True
        for group in result.groups:
            if not first:
                self.results.insert("end", "\n")
            first = False
            die = group.die
            self.results.insert("end", f"{die.label}: ", "die")
            for i, v in enumerate(group.values):
                if i:
                    self.results.insert("end", "  ", "die")
                if i in group.dropped:
                    tag = "drop"
                elif v == die.maximum:
                    tag = "crit"
                elif v == die.minimum:
                    tag = "fumble"
                else:
                    tag = "val"
                self.results.insert("end", die.fmt(v), tag)
            extra = []
            if len(group.kept) > 1:
                extra.append(f"= {group.subtotal}")
            if group.note:
                extra.append(group.note)
            if extra:
                self.results.insert("end", "   (" + ", ".join(extra) + ")", "die")
        if result.bonus:
            self.results.insert("end", f"\nmodifier: {result.bonus:+d}", "note")
        for note in result.notes:
            self.results.insert("end", f"\n{note}", "note")
        self.results.config(state="disabled")

    # ------------------------------------------------------------------
    # Mod manager window
    # ------------------------------------------------------------------
    def open_mod_manager(self):
        win = tk.Toplevel(self)
        win.title("Mods")
        win.configure(bg=BG)
        win.geometry("480x420")
        win.transient(self)

        tk.Label(win, text="INSTALLED MODS", font=self.f_die, bg=BG,
                 fg=ACCENT).pack(anchor="w", padx=16, pady=(14, 2))
        tk.Label(win, text="Changes apply on restart.", font=self.f_label,
                 bg=BG, fg=MUTED).pack(anchor="w", padx=16, pady=(0, 10))

        cfg = dice_api.load_config()
        disabled = set(cfg.get("disabled", []))
        vars_by_file = {}

        listing = tk.Frame(win, bg=BG)
        listing.pack(fill="both", expand=True, padx=16)
        if not self.plugins:
            tk.Label(listing, text="No mods found in plugins/.",
                     font=self.f_label, bg=BG, fg=MUTED).pack(anchor="w")

        for info in self.plugins:
            row = tk.Frame(listing, bg=PANEL)
            row.pack(fill="x", pady=3)
            var = tk.BooleanVar(value=info.filename not in disabled)
            vars_by_file[info.filename] = var
            tk.Checkbutton(
                row, variable=var, bg=PANEL, activebackground=PANEL,
                selectcolor=PANEL, fg=ACCENT, bd=0, highlightthickness=0
            ).pack(side="left", padx=(6, 2))
            text = tk.Frame(row, bg=PANEL)
            text.pack(side="left", fill="x", expand=True, pady=6)
            title = info.name + (f"  v{info.version}" if info.version else "")
            tk.Label(text, text=title, font=self.f_label, bg=PANEL,
                     fg=FUMBLE if info.error else FG, anchor="w").pack(fill="x")
            detail = info.error.strip().splitlines()[-1] if info.error else \
                (info.description or info.filename)
            tk.Label(text, text=detail, font=self.f_label, bg=PANEL,
                     fg=MUTED, anchor="w", wraplength=380,
                     justify="left").pack(fill="x")

        def apply_changes():
            # Re-read first: a panel may have been minimised since this window
            # opened, and that also lives in mods.json.
            latest = dice_api.load_config()
            latest["disabled"] = sorted(f for f, v in vars_by_file.items()
                                        if not v.get())
            dice_api.save_config(latest)
            self._config = latest
            win.destroy()

        buttons = tk.Frame(win, bg=BG)
        buttons.pack(fill="x", padx=16, pady=12)
        self._flat_button(buttons, "Open plugins folder",
                          lambda: os.startfile(dice_api.PLUGIN_DIR),
                          fg=MUTED).pack(side="left")
        self._flat_button(buttons, "Save", apply_changes,
                          fg=ACCENT).pack(side="right", ipadx=10)


def _plan_from_menu():
    """Work out what to open. None means they closed the menu - so don't."""
    import main_menu
    if not main_menu.should_show():
        return {"mode": "solo", "campaign": dice_api.current_save()}
    plan = main_menu.ask()
    if plan is None:
        return None
    if plan.get("mode") == "join":
        # Joiners keep their own campaign folder named after the host's, so
        # their dice history and journal belong to this game and not to
        # whatever they had open last.
        wanted = dice_api.clean_save_name(plan.get("campaign") or "Shared Game")
        if wanted not in dice_api.list_saves():
            dice_api.create_save(wanted)
        dice_api.set_current_save(wanted)
    return plan


if __name__ == "__main__":
    opening = _plan_from_menu()
    if opening is not None:
        DiceRoller(opening).mainloop()
