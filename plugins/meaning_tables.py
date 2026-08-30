"""Meaning Tables - roll a d100 for a word to interpret.

Tables live in the meaning_tables/ folder next to this file, one folder per
category:

    meaning_tables/
        actions/
            action_1.txt
            action_2.txt
        characters/
            appearance.txt
            ...

Each .txt is one entry per line, in order, so line 1 is what you get on a roll
of 1. An optional first line starting with "#" is the name shown in the
dropdown; otherwise the file name is used. Add a folder or a file and it turns
up in the dropdowns on the next launch - no code to touch.
"""

import os
import tkinter as tk

PLUGIN = {
    "name": "Meaning Tables",
    "version": "1.1",
    "description": "Roll d100 on a word table for inspiration, grouped by category.",
    "author": "bundled",
}

TABLE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "meaning_tables")


def _pretty(filename):
    return os.path.splitext(filename)[0].replace("_", " ").title()


def _read_table(path):
    """(display name, entries) or (None, []) if the file is unusable."""
    try:
        with open(path, encoding="utf-8-sig") as fh:
            lines = [line.strip() for line in fh]
    except OSError:
        return None, []
    name = None
    if lines and lines[0].startswith("#"):
        name = lines[0].lstrip("#").strip() or None
        lines = lines[1:]
    return name, [line for line in lines if line]


def load_catalogue():
    """{category: {table name: [entry for 1, entry for 2, ...]}}"""
    catalogue = {}
    if not os.path.isdir(TABLE_DIR):
        return catalogue

    def collect(folder):
        tables = {}
        for filename in sorted(os.listdir(folder)):
            if not filename.endswith(".txt") or filename.startswith(("_", ".")):
                continue
            name, entries = _read_table(os.path.join(folder, filename))
            if entries:
                tables[name or _pretty(filename)] = entries
        return tables

    for item in sorted(os.listdir(TABLE_DIR)):
        path = os.path.join(TABLE_DIR, item)
        if os.path.isdir(path) and not item.startswith(("_", ".")):
            tables = collect(path)
            if tables:
                catalogue[_pretty(item)] = tables

    # Any .txt sitting loose at the top level still works.
    loose = collect(TABLE_DIR)
    if loose:
        catalogue.setdefault("General", {}).update(loose)
    return catalogue


def setup(api):
    theme, fonts = api.theme, api.fonts
    catalogue = load_catalogue()
    categories = list(catalogue)

    state = {
        "category": None,   # StringVar
        "table": None,      # StringVar
        "picker": None,     # the table dropdown, rebuilt per category
        "result": None,
        "detail": None,
    }

    def current():
        tables = catalogue.get(state["category"].get(), {})
        name = state["table"].get()
        return name, tables.get(name, [])

    def fill_table_menu(*_args):
        """Point the table dropdown at the newly chosen category."""
        tables = catalogue.get(state["category"].get(), {})
        menu = state["picker"]["menu"]
        menu.delete(0, "end")
        for name in tables:
            menu.add_command(label=name,
                             command=lambda v=name: state["table"].set(v))
        if state["table"].get() not in tables:
            state["table"].set(next(iter(tables), ""))
        else:
            remember()

    def remember(*_args):
        api.storage["category"] = state["category"].get()
        api.storage["table"] = state["table"].get()
        api.save()
        state["result"].config(text="")
        _, entries = current()
        state["detail"].config(
            text=f"{len(entries)} entries" if entries else "table is empty",
            fg=theme["muted"])

    def roll():
        name, entries = current()
        if not entries:
            return
        # A full table is a straight d100 so it shows up with the other dice;
        # a short one just rolls its own length.
        if len(entries) == 100:
            value = api.roll_die("d100")
        else:
            value = api.roll_die("d100") % len(entries) + 1
        word = entries[value - 1]

        state["result"].config(text=word, fg=theme["accent"])
        state["detail"].config(text=f"rolled {value} on {name}",
                               fg=theme["muted"])
        # hooks=False: a table lookup shouldn't pick up another mod's modifier.
        api.present(
            [api.make_group("d100", [value])],
            notes=[f"{name}: {word}"],
            label=word,
            hooks=False,
        )

    def dropdown(parent, variable, options, width):
        widget = tk.OptionMenu(parent, variable, *options)
        widget.config(font=fonts["label"], bg=theme["bg"], fg=theme["fg"],
                      activebackground=theme["accent"],
                      activeforeground=theme["bg"], relief="flat", bd=0,
                      highlightthickness=0, cursor="hand2", width=width,
                      anchor="w")
        widget["menu"].config(font=fonts["label"], bg=theme["panel"],
                              fg=theme["fg"],
                              activebackground=theme["accent"],
                              activeforeground=theme["bg"], relief="flat", bd=0)
        return widget

    def build(parent):
        frame = tk.Frame(parent, bg=theme["panel"])

        if not categories:
            tk.Label(frame, text=f"No tables found in {TABLE_DIR}",
                     font=fonts["label"], bg=theme["panel"],
                     fg=theme["fumble"], anchor="w").pack(fill="x")
            return frame

        saved_category = api.storage.get("category")
        if saved_category not in catalogue:
            saved_category = categories[0]
        saved_table = api.storage.get("table")
        if saved_table not in catalogue[saved_category]:
            saved_table = next(iter(catalogue[saved_category]))

        state["category"] = tk.StringVar(value=saved_category)
        state["table"] = tk.StringVar(value=saved_table)

        top = tk.Frame(frame, bg=theme["panel"])
        top.pack(fill="x")
        tk.Label(top, text="Category", font=fonts["label"], bg=theme["panel"],
                 fg=theme["muted"]).pack(side="left", padx=(0, 6))
        dropdown(top, state["category"], categories, 12).pack(side="left")
        tk.Label(top, text="Table", font=fonts["label"], bg=theme["panel"],
                 fg=theme["muted"]).pack(side="left", padx=(12, 6))
        state["picker"] = dropdown(top, state["table"],
                                   list(catalogue[saved_category]), 18)
        state["picker"].pack(side="left")

        tk.Button(frame, text="[ ROLL MEANING ]", font=fonts["die"],
                  bg=theme["accent"], fg=theme["bg"],
                  activebackground=theme["accent_hot"],
                  activeforeground=theme["bg"], relief="flat", bd=0,
                  cursor="hand2", command=roll).pack(
            anchor="w", pady=(10, 0), ipadx=8, ipady=6)

        state["result"] = tk.Label(frame, text="", font=fonts["title"],
                                   bg=theme["panel"], fg=theme["accent"],
                                   anchor="w")
        state["result"].pack(fill="x", pady=(10, 0))
        state["detail"] = tk.Label(frame, text="", font=fonts["label"],
                                   bg=theme["panel"], fg=theme["muted"],
                                   anchor="w")
        state["detail"].pack(fill="x")

        state["category"].trace_add("write", fill_table_menu)
        state["table"].trace_add("write", remember)
        fill_table_menu()
        return frame

    api.add_panel("Meaning Tables", build)
