"""Encounters - build a fight, roll for initiative, then run it round by round.

Opens from Tools > Encounters, next to the Adventuring Journal and the Game
Map. One window, four parts and no tabs:

  * the roster (left half)  - the creatures in this encounter. Add them from
                              the library, or make one up on the spot.
  * the stat block (right)  - whatever numbers the selected creature carries.
                              Right-click it to add, rename or remove a stat;
                              type straight into the values.
  * the summary (bottom)    - a few lines on what is going on, who started it
                              and what the room looks like.
  * the turn bar (below it) - only there once the encounter is running: the
                              round, whose turn it is, and Next.

Creatures in an encounter are copies. Wounding the goblin here never touches
the goblin in the library, so the same entry can be pulled in again next week
at full health.

Players come in the same way creatures do. Add player offers the characters
already standing on the game map, along with whoever is at the table without
one yet, so a fight can be set up without typing anybody's name twice.

Everything belongs to the campaign that is currently open, so each save file
has its own library and its own encounter in progress.
"""

import copy
import json
import os
import tkinter as tk
import uuid
from tkinter import messagebox, simpledialog

import dice_api

PLUGIN = {
    "name": "Encounters",
    "version": "1.0",
    "description": "Build an encounter, roll initiative and run it turn by turn.",
    "author": "bundled",
}

# What a creature made from scratch starts with. Three numbers is enough to
# fight with; anything else the game needs gets right-clicked in.
DEFAULT_STATS = [["HP", "10"], ["AC", "12"], ["Init Mod", "0"]]

# The stat that gets added to the d20. Whichever of these a creature happens
# to carry is used - one game calls it a modifier, another calls it dexterity.
INIT_STATS = ("Init Mod", "Initiative", "Init", "Dex Mod", "DEX")

# Where the Game Map keeps its figures. Read-only, and only if it is there -
# the two windows are separate mods and either can be turned off.
MAP_FILE = "game_map.json"

# Copied into the campaign's library the first time the window opens, so the
# Add menu is never an empty box. Edit or delete them like any other entry.
BESTIARY = [
    ("Giant Rat", [["HP", "7"], ["AC", "12"], ["Init Mod", "+2"],
                   ["Attack", "+3"], ["Damage", "1d4"], ["Speed", "30"]]),
    ("Goblin", [["HP", "12"], ["AC", "15"], ["Init Mod", "+2"],
                ["Attack", "+4"], ["Damage", "1d6+2"], ["Speed", "30"]]),
    ("Kobold", [["HP", "5"], ["AC", "12"], ["Init Mod", "+2"],
                ["Attack", "+4"], ["Damage", "1d4+2"], ["Speed", "30"]]),
    ("Wolf", [["HP", "11"], ["AC", "13"], ["Init Mod", "+2"],
              ["Attack", "+4"], ["Damage", "2d4+2"], ["Speed", "40"]]),
    ("Bandit", [["HP", "11"], ["AC", "12"], ["Init Mod", "+1"],
                ["Attack", "+3"], ["Damage", "1d6+1"], ["Speed", "30"]]),
    ("Ogre", [["HP", "59"], ["AC", "11"], ["Init Mod", "-1"],
              ["Attack", "+6"], ["Damage", "2d8+4"], ["Speed", "40"]]),
]

CTRL = 0x0004       # the bit Tk sets on an event while Ctrl is held


def setup(api):
    holder = {"window": None}

    def open_encounters():
        window = holder["window"]
        if window is not None and window.alive():
            window.win.deiconify()
            window.win.lift()
            window.win.focus_force()
            return
        holder["window"] = Encounters(api)

    def flush(_name=None):
        window = holder["window"]
        if window is not None and window.alive():
            window.save()

    api.add_menu_command("Tools", "Encounters...", open_encounters)
    api.on("save", flush)


def _number(text):
    """The number in a stat value, or 0. '+2', '2', ' -1 ' and '' all work."""
    try:
        return int(str(text).strip().lstrip("+") or 0)
    except ValueError:
        return 0


def _init_score(text):
    """What a typed initiative box means. Blank is no count at all - the same
    as never having rolled - and anything unreadable settles at zero rather
    than refusing the keystroke."""
    text = str(text).strip()
    return _number(text) if text else None


class Encounters:
    def __init__(self, api):
        self.api = api
        self.t = api.theme
        self.f = api.fonts

        self.creatures = []     # the roster: [{"id", "name", "stats", "init"}]
        self.library = []       # reusable entries: [{"name", "stats"}]
        self.selected = []      # ids, in the order they were picked
        self.summary = ""       # a few lines on what is going on
        self.running = False
        self.round = 1
        self.turn = 0
        self.order = []         # ids, fixed while the encounter runs
        self._save_job = None
        self._settling = False  # a re-sort is already under way

        self._load()
        self._build()
        self._render_roster()
        self._render_stats()
        self._render_runner()

    # -- data --------------------------------------------------------------
    def alive(self):
        try:
            return bool(self.win.winfo_exists())
        except tk.TclError:
            return False

    def _load(self):
        store = self.api.storage
        for raw in store.get("creatures", []):
            self.creatures.append(self._clean(raw))
        self.library = [{"name": entry.get("name", "Unnamed"),
                         "stats": [[str(n), str(v)]
                                   for n, v in entry.get("stats", [])]}
                        for entry in store.get("library", [])]
        if "library" not in store:
            self.library = [{"name": name, "stats": copy.deepcopy(stats)}
                            for name, stats in BESTIARY]
        self.summary = str(store.get("summary", ""))
        self.running = bool(store.get("running", False))
        self.round = max(1, int(store.get("round", 1)))
        self.turn = max(0, int(store.get("turn", 0)))
        self.order = [str(i) for i in store.get("order", [])]

    def _clean(self, raw):
        """One creature, with everything it needs and nothing it doesn't."""
        init = raw.get("init")
        return {
            "id": str(raw.get("id") or uuid.uuid4().hex[:8]),
            "name": str(raw.get("name", "Unnamed")),
            "stats": [[str(n), str(v)] for n, v in raw.get("stats", [])],
            "init": None if init is None else int(init),
            "player": bool(raw.get("player", False)),
        }

    def save(self):
        store = self.api.storage
        self._read_summary()
        store["creatures"] = self.creatures
        store["library"] = self.library
        store["summary"] = self.summary
        store["running"] = self.running
        store["round"] = self.round
        store["turn"] = self.turn
        store["order"] = self.order
        self.api.save()

    def schedule_save(self):
        """Coalesce the flurry of edits from typing into one write."""
        if self._save_job is not None:
            self.win.after_cancel(self._save_job)
        self._save_job = self.win.after(600, self._do_save)

    def _do_save(self):
        self._save_job = None
        if self.alive():        # the window may have gone since this was set
            self.save()

    def _cancel_save(self):
        """Don't leave a timer pointing at a window that has gone."""
        if self._save_job is not None:
            try:
                self.win.after_cancel(self._save_job)
            except tk.TclError:
                pass
            self._save_job = None

    def _on_destroy(self, event):
        if event.widget is self.win:
            self._cancel_save()

    def _close(self):
        self._cancel_save()
        self.save()
        self.win.destroy()

    # -- looking things up -------------------------------------------------
    def _find(self, cid):
        for creature in self.creatures:
            if creature["id"] == cid:
                return creature
        return None

    def _current(self):
        """The creature whose stats the right-hand side is showing."""
        return self._find(self.selected[-1]) if self.selected else None

    def _sorted(self):
        """The roster in initiative order. Unrolled creatures sink to the
        bottom; ties keep the order they were added in, so the list never
        shuffles itself about between renders."""
        indexed = list(enumerate(self.creatures))
        indexed.sort(key=lambda pair: (pair[1]["init"] is None,
                                       -(pair[1]["init"] or 0), pair[0]))
        return [creature for _index, creature in indexed]

    def _turn_order(self):
        """While running, the order fixed at Run Encounter - minus anyone who
        has left the fight, plus anyone who joined it late."""
        known = {creature["id"] for creature in self.creatures}
        self.order = [cid for cid in self.order if cid in known]
        for creature in self._sorted():
            if creature["id"] not in self.order:
                self.order.append(creature["id"])
        return self.order

    def _display_order(self):
        """What the roster shows. Standing still it is initiative order; once
        the encounter is running it is rotated so whoever is up is on top."""
        if not self.running:
            return self._sorted()
        order = self._turn_order()
        if not order:
            return []
        self.turn %= len(order)
        rotated = order[self.turn:] + order[:self.turn]
        return [self._find(cid) for cid in rotated if self._find(cid)]

    # -- window ------------------------------------------------------------
    def _build(self):
        self.win = tk.Toplevel(self.api.app)
        self.win.title(f"Encounters - {self.api.save_name}")
        self.win.configure(bg=self.t["bg"])
        self.win.geometry("900x700")
        self.win.minsize(720, 560)
        self.win.protocol("WM_DELETE_WINDOW", self._close)
        self.win.bind("<Destroy>", self._on_destroy)

        # Down the middle: the roster and the stat block get a half each,
        # whatever the window is doing. `uniform` is what holds them level -
        # weights alone would let the wider content push its side out.
        self.win.columnconfigure(0, weight=1, uniform="halves")
        self.win.columnconfigure(1, weight=1, uniform="halves")
        self.win.rowconfigure(0, weight=1)

        self._build_roster()
        self._build_stats()
        self._build_summary()
        self._build_runner()

    def _heading(self, parent, text):
        return tk.Label(parent, text=text, font=self.f["label"],
                        bg=self.t["panel"], fg=self.t["muted"], anchor="w")

    def _button(self, parent, text, command, fg=None, width=None):
        return tk.Button(parent, text=text, font=self.f["label"],
                         bg=self.t["bg"], fg=fg or self.t["fg"],
                         activebackground=self.t["accent"],
                         activeforeground=self.t["bg"], relief="flat", bd=0,
                         cursor="hand2", command=command,
                         **({"width": width} if width else {}))

    def _entry(self, parent, width, value=""):
        widget = tk.Entry(parent, width=width, font=self.f["label"],
                          bg=self.t["bg"], fg=self.t["fg"],
                          insertbackground=self.t["fg"], relief="flat", bd=0,
                          highlightthickness=1,
                          highlightbackground=self.t["panel"],
                          highlightcolor=self.t["accent"])
        if value:
            widget.insert(0, value)
        return widget

    def _menu(self, parent=None):
        return tk.Menu(parent or self.win, tearoff=0, font=self.f["label"],
                       bg=self.t["panel"], fg=self.t["fg"],
                       activebackground=self.t["accent"],
                       activeforeground=self.t["bg"], relief="flat", bd=0)

    def _scroller(self, parent):
        outer = tk.Frame(parent, bg=self.t["panel"])
        canvas = tk.Canvas(outer, bg=self.t["panel"], highlightthickness=0, bd=0)
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
        canvas.bind("<MouseWheel>",
                    lambda e: canvas.yview_scroll(-int(e.delta / 120), "units"))
        return outer, inner, canvas

    def _bind_wheel(self, widget, canvas):
        def scroll(event):
            canvas.yview_scroll(-int(event.delta / 120), "units")
            return "break"
        widget.bind("<MouseWheel>", scroll)
        for child in widget.winfo_children():
            self._bind_wheel(child, canvas)

    # -- the roster, down the left -----------------------------------------
    def _build_roster(self):
        box = tk.Frame(self.win, bg=self.t["panel"])
        box.grid(row=0, column=0, sticky="nsew", padx=(8, 4), pady=8)

        self._heading(box, "ENCOUNTER").pack(fill="x", padx=10, pady=(8, 6))
        outer, self.roster_rows, self.roster_canvas = self._scroller(box)
        outer.pack(fill="both", expand=True, padx=6)

        tk.Label(box, text="Ctrl-click to pick several, then right-click.",
                 font=self.f["label"], bg=self.t["panel"], fg=self.t["muted"],
                 anchor="w", wraplength=400,
                 justify="left").pack(fill="x", padx=10, pady=(6, 2))

        buttons = tk.Frame(box, bg=self.t["panel"])
        buttons.pack(fill="x", padx=10, pady=(2, 10))
        # Rolling sits above the adding on purpose: it is the button reached
        # for once the room is assembled, so it wants to be the one nearest
        # the list rather than buried under the two that built it.
        self._button(buttons, "Roll Initiative", self._roll_all).pack(
            fill="x", ipady=4)
        adders = tk.Frame(buttons, bg=self.t["panel"])
        adders.pack(fill="x", pady=(4, 0))
        adders.columnconfigure(0, weight=1, uniform="adders")
        adders.columnconfigure(1, weight=1, uniform="adders")
        self.add_button = self._button(adders, "+  Add creature",
                                       self._show_add_menu, fg=self.t["accent"])
        self.add_button.grid(row=0, column=0, sticky="ew", ipady=4,
                             padx=(0, 2))
        self.player_button = self._button(adders, "+  Add player",
                                          self._show_player_menu,
                                          fg=self.t["accent"])
        self.player_button.grid(row=0, column=1, sticky="ew", ipady=4,
                                padx=(2, 0))
        self.run_button = self._button(buttons, "Run Encounter",
                                       self._toggle_run, fg=self.t["crit"])
        self.run_button.pack(fill="x", ipady=4, pady=(4, 0))

    def _render_roster(self):
        for child in self.roster_rows.winfo_children():
            child.destroy()

        if not self.creatures:
            tk.Label(self.roster_rows, text="Nothing here yet. Add a creature "
                     "to start building the fight.", font=self.f["label"],
                     bg=self.t["panel"], fg=self.t["muted"], anchor="w",
                     wraplength=200,
                     justify="left").pack(fill="x", padx=6, pady=6)
            return

        for index, creature in enumerate(self._display_order()):
            active = self.running and index == 0
            picked = creature["id"] in self.selected
            row_bg = self.t["bg"] if (picked or active) else self.t["panel"]
            if active:
                fg = self.t["crit"]
            elif picked:
                fg = self.t["accent"]
            else:
                fg = self.t["fg"]

            row = tk.Frame(self.roster_rows, bg=row_bg)
            row.pack(fill="x", pady=1)
            name = tk.Label(row, text=("> " if active else "   ") + creature["name"],
                            font=self.f["label"], bg=row_bg, fg=fg, anchor="w")
            name.pack(side="left", fill="x", expand=True, padx=(6, 2), pady=3)
            # A box rather than a label. A rolled number is a suggestion:
            # the GM overruling it, or setting one by hand without rolling at
            # all, should not mean clearing it and rolling again.
            init = creature["init"]
            edge = self.t["panel"] if row_bg == self.t["bg"] else self.t["bg"]
            score = tk.Entry(row, width=3, font=self.f["die"],
                             bg=self.t["bg"], fg=fg, insertbackground=fg,
                             justify="center", relief="flat", bd=0,
                             highlightthickness=1, highlightbackground=edge,
                             highlightcolor=self.t["accent"])
            if init is not None:
                score.insert(0, str(init))
            score._init_box = True
            score.pack(side="right", padx=(2, 8), ipady=2)
            score.bind("<KeyRelease>",
                       lambda _e, c=creature, w=score: self._type_init(c, w))
            score.bind("<Return>",
                       lambda _e, c=creature, w=score: self._enter_init(c, w))
            score.bind("<FocusOut>",
                       lambda _e, c=creature, w=score: self._leave_init(c, w))
            tag = tk.Label(row, text="PC" if creature.get("player") else "",
                           font=self.f["label"], bg=row_bg,
                           fg=self.t["accent"], width=2, anchor="e")
            tag.pack(side="right", padx=(2, 4))

            # Clicking the box means editing the number, so it is left out of
            # the picking. The name and the rest of the row still select.
            for widget in (row, name, tag):
                widget.bind("<Button-1>",
                            lambda e, c=creature["id"]: self._click(c, e))
            for widget in (row, name, score, tag):
                widget.bind("<Button-3>",
                            lambda e, c=creature["id"]: self._roster_menu(c, e))
        self._bind_wheel(self.roster_rows, self.roster_canvas)

    def _click(self, cid, event):
        if event.state & CTRL:
            if cid in self.selected:
                self.selected.remove(cid)
            else:
                self.selected.append(cid)
        else:
            self.selected = [cid]
        self._render_roster()
        self._render_stats()

    def _picked(self):
        """The selected creatures, in roster order and with the dead links
        from a removal dropped."""
        return [c for c in self._sorted() if c["id"] in self.selected]

    def _roster_menu(self, cid, event):
        if cid not in self.selected:
            self.selected = [cid]
            self._render_roster()
            self._render_stats()

        picked = self._picked()
        if not picked:
            return
        menu = self._menu()
        if len(picked) > 1:
            menu.add_command(label=f"Roll initiative separately ({len(picked)})",
                             command=lambda: self._roll_for(picked))
            menu.add_command(label=f"Roll group initiative ({len(picked)})",
                             command=lambda: self._roll_group(picked))
        else:
            menu.add_command(label="Roll initiative",
                             command=lambda: self._roll_for(picked))
        menu.add_separator()
        menu.add_command(label="Clear initiative",
                         command=lambda: self._clear_init(picked))
        menu.add_command(label="Duplicate",
                         command=lambda: self._duplicate(picked))
        menu.add_command(label="Save to library",
                         command=lambda: self._to_library(picked))
        menu.add_separator()
        menu.add_command(label="Remove", command=lambda: self._remove(picked))
        menu.tk_popup(event.x_root, event.y_root)

    # -- adding creatures ---------------------------------------------------
    def _show_add_menu(self):
        menu = self._menu()
        for index, entry in enumerate(self.library):
            menu.add_command(label=entry["name"],
                             command=lambda i=index: self._add_from_library(i))
        if self.library:
            menu.add_separator()
        menu.add_command(label="New creature...", command=self._add_blank)
        if self.library:
            drop = self._menu(menu)
            for index, entry in enumerate(self.library):
                drop.add_command(label=entry["name"],
                                 command=lambda i=index: self._drop_library(i))
            menu.add_cascade(label="Delete from library", menu=drop)
        button = self.add_button
        menu.tk_popup(button.winfo_rootx(),
                      button.winfo_rooty() + button.winfo_height())

    def _unique(self, name):
        """Two goblins both called Goblin make for a confusing initiative
        list, so the second one becomes Goblin 2."""
        taken = {creature["name"] for creature in self.creatures}
        if name not in taken:
            return name
        number = 2
        while f"{name} {number}" in taken:
            number += 1
        return f"{name} {number}"

    def _base_name(self, name):
        """'Goblin 3' back to 'Goblin', so copies and library entries don't
        pick up a run of numbers."""
        return name.rstrip("0123456789 ").strip() or name

    def _add(self, name, stats, player=False):
        creature = {"id": uuid.uuid4().hex[:8], "name": self._unique(name),
                    "stats": copy.deepcopy(stats), "init": None,
                    "player": player}
        self.creatures.append(creature)
        self.selected = [creature["id"]]
        self._render_roster()
        self._render_stats()
        self.save()

    def _add_from_library(self, index):
        entry = self.library[index]
        self._add(entry["name"], entry["stats"])

    def _add_blank(self):
        name = simpledialog.askstring("New creature", "Name:", parent=self.win)
        if not name or not name.strip():
            return
        self._add(name.strip(), DEFAULT_STATS)

    def _duplicate(self, creatures):
        for creature in list(creatures):
            self._add(self._base_name(creature["name"]), creature["stats"],
                      player=creature.get("player", False))

    # -- adding players -----------------------------------------------------
    def _map_characters(self):
        """The player figures standing on the game map, each with whoever
        they belong to. Read straight off the map's own save file: the two
        windows are separate mods, so there is nothing else to ask, and a
        missing or half-written file just means no suggestions.
        """
        path = os.path.join(dice_api.save_path(create=False), MAP_FILE)
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh).get("map", {})
        except (OSError, ValueError, AttributeError):
            return []
        owners = {}
        for player in data.get("players", []):
            if isinstance(player, dict) and "id" in player:
                owners[player["id"]] = player
        found = []
        for level in data.get("levels", []):
            for token in level.get("tokens", []):
                if not isinstance(token, dict) or token.get("kind") != "player":
                    continue
                owner = owners.get(token.get("owner"))
                found.append({
                    "name": str(token.get("name") or "Character"),
                    "owner": (owner or {}).get("name"),
                    "seat": (owner or {}).get("seat"),
                    "stats": self._map_stats(token.get("stats")),
                })
        return found

    def _map_stats(self, saved):
        """A map figure's numbers as stat rows. Whatever it carries comes
        across as it is; an initiative modifier is added if it has none, so
        there is somewhere to type the bonus."""
        stats = [[str(name), str(value)]
                 for name, value in (saved or {}).items()]
        if not stats:
            stats = copy.deepcopy(DEFAULT_STATS)
        if not any(name.strip() in INIT_STATS for name, _v in stats):
            stats.append(["Init Mod", "0"])
        return stats

    def _table_people(self):
        """Everyone at the table, with the seat they are sitting in."""
        session = self.api.session
        if session is None or session.is_solo:
            return []
        people = []
        for card in session.people():
            people.append({"name": str(card.get("name") or "Someone"),
                           "role": card.get("role"),
                           "seat": card.get("token")})
        return people

    def _show_player_menu(self):
        menu = self._menu()
        characters = self._map_characters()
        spoken_for = {c["seat"] for c in characters if c.get("seat")}

        for entry in characters:
            label = entry["name"]
            if entry["owner"]:
                label = f"{entry['name']}  -  {entry['owner']}"
            menu.add_command(
                label=label,
                command=lambda e=entry: self._add(e["name"], e["stats"],
                                                  player=True))
        waiting = [p for p in self._table_people()
                   if p["seat"] not in spoken_for]
        if characters and waiting:
            menu.add_separator()
        for person in waiting:
            label = person["name"]
            if person["role"]:
                label = f"{person['name']}  ({person['role']})"
            menu.add_command(
                label=label,
                command=lambda p=person: self._add(p["name"], DEFAULT_STATS,
                                                   player=True))
        if characters or waiting:
            menu.add_separator()
        menu.add_command(label="Player by hand...", command=self._add_by_hand)
        button = self.player_button
        menu.tk_popup(button.winfo_rootx(),
                      button.winfo_rooty() + button.winfo_height())

    def _add_by_hand(self):
        name = simpledialog.askstring("Add player", "Name:", parent=self.win)
        if not name or not name.strip():
            return
        bonus = simpledialog.askstring("Add player",
                                       f"{name.strip()}'s initiative bonus:",
                                       initialvalue="0", parent=self.win)
        if bonus is None:
            return
        stats = copy.deepcopy(DEFAULT_STATS)
        for row in stats:
            if row[0] == "Init Mod":
                row[1] = bonus.strip() or "0"
        self._add(name.strip(), stats, player=True)

    def _remove(self, creatures):
        names = ", ".join(c["name"] for c in creatures)
        if not messagebox.askyesno("Remove", f"Remove {names}?", parent=self.win):
            return
        gone = {c["id"] for c in creatures}
        self.creatures = [c for c in self.creatures if c["id"] not in gone]
        self.selected = [c for c in self.selected if c not in gone]
        self.order = [c for c in self.order if c not in gone]
        if self.running and not self.creatures:
            self._end_run()
            return
        self._render_roster()
        self._render_stats()
        self._render_runner()
        self.save()

    def _to_library(self, creatures):
        for creature in creatures:
            name = self._base_name(creature["name"])
            stats = copy.deepcopy(creature["stats"])
            for entry in self.library:
                if entry["name"] == name:
                    entry["stats"] = stats
                    break
            else:
                self.library.append({"name": name, "stats": stats})
        self.library.sort(key=lambda entry: entry["name"].lower())
        self.save()

    def _drop_library(self, index):
        entry = self.library[index]
        if messagebox.askyesno("Delete from library",
                               f"Delete {entry['name']} from the library?\n\n"
                               "Creatures already in the encounter are not "
                               "affected.", parent=self.win):
            del self.library[index]
            self.save()

    # -- initiative ---------------------------------------------------------
    def _init_mod(self, creature):
        for name, value in creature["stats"]:
            if name.strip() in INIT_STATS:
                return _number(value)
        return 0

    def _roll_for(self, creatures):
        """A d20 each - everyone acts on their own count."""
        for creature in creatures:
            creature["init"] = self.api.roll_die("d20") + self._init_mod(creature)
        self._after_rolling()

    def _roll_all(self):
        if self.creatures:
            self._roll_for(self.creatures)

    def _roll_group(self, creatures):
        """One d20 for the lot of them - the whole gang acts together. Each
        still adds its own modifier, so a quick goblin edges out a slow one."""
        names = ", ".join(c["name"] for c in creatures)
        if not messagebox.askyesno(
                "Group initiative",
                f"Roll one initiative for these {len(creatures)} creatures?"
                f"\n\n{names}", parent=self.win):
            return
        roll = self.api.roll_die("d20")
        for creature in creatures:
            creature["init"] = roll + self._init_mod(creature)
        self._after_rolling()

    def _clear_init(self, creatures):
        for creature in creatures:
            creature["init"] = None
        self._after_rolling()

    def _type_init(self, creature, widget):
        """Typed into a box. The number is taken as it is typed, but the
        roster is left standing - re-sorting under a half-typed number would
        pull the box out from under the next keystroke."""
        creature["init"] = _init_score(widget.get())
        self.schedule_save()

    def _enter_init(self, creature, widget):
        """Return - done with this one, so the list can settle now."""
        self._type_init(creature, widget)
        self._resettle()

    def _leave_init(self, creature, widget):
        """Focus has left a box. Reading it fails if the box went with a
        re-render rather than a click, and in that case its number was taken
        on the way in to that render anyway."""
        if self._settling:
            return
        try:
            creature["init"] = _init_score(widget.get())
        except tk.TclError:
            return
        self.schedule_save()
        self.win.after_idle(self._settle_if_done)

    def _settle_if_done(self):
        """Somebody filling the column in by hand goes box to box, and a
        re-sort between two of them would throw away the click that got
        there. So the order waits until the boxes are done with."""
        try:
            focus = self.win.focus_get()
        except (tk.TclError, KeyError):
            focus = None
        if getattr(focus, "_init_box", False):
            return
        self._resettle()

    def _resettle(self):
        """Back into initiative order after a number was typed by hand.
        Mid-fight the order is rebuilt around whoever is up, so correcting a
        number does not send the round back to the top."""
        if self._settling or not self.alive():
            return
        self._settling = True
        try:
            if self.running:
                order = self._turn_order()
                up = order[self.turn % len(order)] if order else None
                self.order = [c["id"] for c in self._sorted()]
                self.turn = self.order.index(up) if up in self.order else 0
            self._render_roster()
            self._render_stats()
            self._render_runner()
            self.save()
        finally:
            self._settling = False

    def _after_rolling(self):
        if self.running:
            # A fresh roll means a fresh order; start the round over rather
            # than leave the turn marker pointing at whoever used to be here.
            self.order = [c["id"] for c in self._sorted()]
            self.turn = 0
        self._render_roster()
        self._render_stats()
        self._render_runner()
        self.save()

    # -- the stat block, on the right ---------------------------------------
    def _build_stats(self):
        box = tk.Frame(self.win, bg=self.t["panel"])
        box.grid(row=0, column=1, sticky="nsew", padx=(4, 8), pady=8)
        box.rowconfigure(2, weight=1)
        box.columnconfigure(0, weight=1)

        self._heading(box, "STATS").grid(row=0, column=0, sticky="ew",
                                         padx=10, pady=(8, 6))
        self.stat_header = tk.Frame(box, bg=self.t["panel"])
        self.stat_header.grid(row=1, column=0, sticky="ew", padx=10)
        outer, self.stat_rows, self.stat_canvas = self._scroller(box)
        outer.grid(row=2, column=0, sticky="nsew", padx=6, pady=(6, 10))
        self.stat_rows.bind("<Button-3>", lambda e: self._stat_menu(None, e))
        self.stat_canvas.bind("<Button-3>", lambda e: self._stat_menu(None, e))

    def _render_stats(self):
        for child in self.stat_header.winfo_children():
            child.destroy()
        for child in self.stat_rows.winfo_children():
            child.destroy()

        creature = self._current()
        if creature is None:
            tk.Label(self.stat_rows, text="Pick a creature on the left to see "
                     "its stats, or add one.", font=self.f["label"],
                     bg=self.t["panel"], fg=self.t["muted"], anchor="w",
                     wraplength=380,
                     justify="left").pack(fill="x", padx=6, pady=6)
            return

        name = self._entry(self.stat_header, 24, creature["name"])
        name.pack(side="left", fill="x", expand=True, ipady=4)
        name.bind("<KeyRelease>",
                  lambda _e, c=creature, w=name: self._rename(c, w))
        init = creature["init"]
        tk.Label(self.stat_header,
                 text="init " + ("-" if init is None else str(init)),
                 font=self.f["die"], bg=self.t["panel"],
                 fg=self.t["muted"] if init is None else self.t["accent"]).pack(
                     side="left", padx=(8, 4))
        self._button(self.stat_header, "Roll",
                     lambda c=creature: self._roll_for([c])).pack(side="left")

        for index, (stat, value) in enumerate(creature["stats"]):
            row = tk.Frame(self.stat_rows, bg=self.t["panel"])
            row.pack(fill="x", padx=4, pady=2)
            label = tk.Label(row, text=stat, font=self.f["label"],
                             bg=self.t["panel"], fg=self.t["muted"], width=14,
                             anchor="w")
            label.pack(side="left")
            field = self._entry(row, 12, value)
            field.pack(side="left", ipady=3)
            field.bind("<KeyRelease>",
                       lambda _e, c=creature, i=index, w=field:
                       self._edit_stat(c, i, w))
            for widget in (row, label, field):
                widget.bind("<Button-3>",
                            lambda e, i=index: self._stat_menu(i, e))

        tk.Label(self.stat_rows, text="Right-click for add, rename and remove.",
                 font=self.f["label"], bg=self.t["panel"], fg=self.t["muted"],
                 anchor="w").pack(fill="x", padx=8, pady=(10, 4))
        self._bind_wheel(self.stat_rows, self.stat_canvas)

    def _rename(self, creature, widget):
        creature["name"] = widget.get()
        self._render_roster()
        self.schedule_save()

    def _edit_stat(self, creature, index, widget):
        creature["stats"][index][1] = widget.get()
        self.schedule_save()

    def _stat_menu(self, index, event):
        creature = self._current()
        if creature is None:
            return
        menu = self._menu()
        menu.add_command(label="Add stat...", command=self._add_stat)
        if index is not None and index < len(creature["stats"]):
            stat = creature["stats"][index][0]
            menu.add_command(label=f"Rename '{stat}'...",
                             command=lambda: self._rename_stat(index))
            menu.add_command(label=f"Remove '{stat}'",
                             command=lambda: self._remove_stat(index))
        menu.add_separator()
        menu.add_command(label="Save to library",
                         command=lambda: self._to_library([creature]))
        menu.tk_popup(event.x_root, event.y_root)

    def _add_stat(self):
        creature = self._current()
        if creature is None:
            return
        name = simpledialog.askstring("Add stat", "Stat name:", parent=self.win)
        if not name or not name.strip():
            return
        value = simpledialog.askstring("Add stat", f"{name.strip()} value:",
                                       parent=self.win) or ""
        creature["stats"].append([name.strip(), value.strip()])
        self._render_stats()
        self.save()

    def _rename_stat(self, index):
        creature = self._current()
        if creature is None or index >= len(creature["stats"]):
            return
        name = simpledialog.askstring("Rename stat", "Stat name:",
                                      initialvalue=creature["stats"][index][0],
                                      parent=self.win)
        if not name or not name.strip():
            return
        creature["stats"][index][0] = name.strip()
        self._render_stats()
        self.save()

    def _remove_stat(self, index):
        creature = self._current()
        if creature is None or index >= len(creature["stats"]):
            return
        del creature["stats"][index]
        self._render_stats()
        self.save()

    # -- the summary, along the bottom --------------------------------------
    def _build_summary(self):
        box = tk.Frame(self.win, bg=self.t["panel"])
        box.grid(row=1, column=0, columnspan=2, sticky="ew", padx=8,
                 pady=(0, 4))
        self._heading(box, "WHAT'S GOING ON").pack(fill="x", padx=10,
                                                   pady=(8, 4))
        self.summary_box = tk.Text(
            box, height=4, wrap="word", font=self.f["label"],
            bg=self.t["bg"], fg=self.t["fg"], insertbackground=self.t["fg"],
            relief="flat", bd=0, padx=8, pady=6, highlightthickness=1,
            highlightbackground=self.t["panel"],
            highlightcolor=self.t["accent"])
        self.summary_box.pack(fill="x", padx=10, pady=(0, 10))
        if self.summary:
            self.summary_box.insert("1.0", self.summary)
        self.summary_box.bind("<KeyRelease>", lambda _e: self.schedule_save())

    def _read_summary(self):
        """Whatever is in the box right now. Called on the way to storage
        rather than on every keystroke, so typing stays cheap."""
        box = getattr(self, "summary_box", None)
        if box is None:
            return
        try:
            self.summary = box.get("1.0", "end-1c")
        except tk.TclError:
            pass        # the window has gone; the last read still stands

    # -- running the encounter ----------------------------------------------
    def _build_runner(self):
        self.runner = tk.Frame(self.win, bg=self.t["panel"])
        self.runner.grid(row=2, column=0, columnspan=2, sticky="ew",
                         padx=8, pady=(0, 8))
        self.runner.grid_remove()

        self.round_label = tk.Label(self.runner, text="", font=self.f["title"],
                                    bg=self.t["panel"], fg=self.t["accent"])
        self.round_label.pack(side="left", padx=(12, 16), pady=10)
        self.turn_label = tk.Label(self.runner, text="", font=self.f["title"],
                                   bg=self.t["panel"], fg=self.t["fg"])
        self.turn_label.pack(side="left")
        self.next_label = tk.Label(self.runner, text="", font=self.f["label"],
                                   bg=self.t["panel"], fg=self.t["muted"])
        self.next_label.pack(side="left", padx=12)
        self._button(self.runner, "End", self._end_run,
                     fg=self.t["muted"]).pack(side="right", padx=(6, 12),
                                              ipady=4)
        self._button(self.runner, "  Next  ", self._next_turn,
                     fg=self.t["crit"]).pack(side="right", ipady=4)

    def _toggle_run(self):
        if self.running:
            self._end_run()
        else:
            self._start_run()

    def _start_run(self):
        if not self.creatures:
            messagebox.showinfo("Run encounter", "Add a creature or two first.",
                                parent=self.win)
            return
        # Anyone still without a count gets one now, rather than the fight
        # starting with half the room in an undefined place in the order.
        for creature in self.creatures:
            if creature["init"] is None:
                creature["init"] = (self.api.roll_die("d20")
                                    + self._init_mod(creature))
        self.running = True
        self.round = 1
        self.turn = 0
        self.order = [c["id"] for c in self._sorted()]
        self._render_roster()
        self._render_stats()
        self._render_runner()
        self.save()

    def _end_run(self):
        self.running = False
        self.round = 1
        self.turn = 0
        self.order = []
        self._render_roster()
        self._render_stats()
        self._render_runner()
        self.save()

    def _next_turn(self):
        order = self._turn_order()
        if not order:
            return
        self.turn += 1
        if self.turn >= len(order):
            self.turn = 0
            self.round += 1
        self._render_roster()
        self._render_runner()
        self.save()

    def _render_runner(self):
        if not self.running:
            self.runner.grid_remove()
            self.run_button.configure(text="Run Encounter", fg=self.t["crit"])
            return
        self.runner.grid()
        self.run_button.configure(text="End Encounter", fg=self.t["fumble"])
        order = self._turn_order()
        if not order:
            return
        self.turn %= len(order)
        now = self._find(order[self.turn])
        later = self._find(order[(self.turn + 1) % len(order)])
        self.round_label.configure(text=f"Round {self.round}")
        self.turn_label.configure(text=now["name"] if now else "-")
        if later is not None and len(order) > 1:
            self.next_label.configure(text=f"up next: {later['name']}")
        else:
            self.next_label.configure(text="")
