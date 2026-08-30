"""Panels that ship with the dice roller itself.

These used to be mods. They are built in now because they are part of what the
app is rather than something you would turn off, so they don't appear in the
Mods window and can't be disabled.

They are still written against the same api a mod gets, so nothing here is
doing anything a mod couldn't - see plugins/README.md for that api.
"""

import tkinter as tk

import dice_api

HISTORY_LIMIT = 20


def install(app):
    """Build the built-in panels. Called before mods load, so they sit first.

    The Modifier sits right under the dice buttons since it is reached for
    constantly, Roll History goes under the total, and Initiative is its own
    thing so it joins the movable stack with the mods.
    """
    modifier(dice_api.core_api(app, "modifier", "Modifier"))
    roll_history(dice_api.core_api(app, "roll_history", "Roll History"))
    initiative(dice_api.core_api(app, "initiative", "Initiative"))


# --------------------------------------------------------------------------
# Modifier - a flat bonus added to every roll
# --------------------------------------------------------------------------
def modifier(api):
    state = {"value": int(api.storage.get("value", 0))}

    def build(parent):
        row = tk.Frame(parent, bg=api.theme["panel"])
        value_label = tk.Label(row, text="", font=api.fonts["die"],
                               bg=api.theme["panel"], fg=api.theme["accent"],
                               width=5)

        def show():
            value_label.config(text=f"{state['value']:+d}")

        def bump(delta):
            state["value"] += delta
            api.storage["value"] = state["value"]
            api.save()
            show()

        def button(text, command):
            return tk.Button(row, text=text, font=api.fonts["die"], width=3,
                             bg=api.theme["bg"], fg=api.theme["fg"],
                             activebackground=api.theme["accent"],
                             activeforeground=api.theme["bg"],
                             relief="flat", bd=0, cursor="hand2",
                             command=command)

        button("−", lambda: bump(-1)).pack(side="left")
        value_label.pack(side="left", padx=6)
        button("+", lambda: bump(1)).pack(side="left")
        button("0", lambda: bump(-state["value"])).pack(side="left", padx=(10, 0))
        show()
        return row

    def apply_bonus(result):
        result.bonus += state["value"]

    api.add_panel("Modifier", build, area="dice")
    api.on("after_roll", apply_bonus)


# --------------------------------------------------------------------------
# Roll history
# --------------------------------------------------------------------------
def roll_history(api):
    box = {"text": None, "count": 0}

    def build(parent):
        frame = tk.Frame(parent, bg=api.theme["panel"])
        text = tk.Text(frame, font=api.fonts["result"], bg=api.theme["bg"],
                       fg=api.theme["fg"], relief="flat", bd=0, height=5,
                       width=1, wrap="none", padx=6, pady=4,
                       state="disabled", cursor="arrow")
        scroll = tk.Scrollbar(frame, command=text.yview,
                              bg=api.theme["panel"], relief="flat", bd=0)
        text.configure(yscrollcommand=scroll.set)
        text.tag_configure("dim", foreground=api.theme["muted"])
        text.tag_configure("val", foreground=api.theme["fg"])
        text.tag_configure("total", foreground=api.theme["accent"])
        scroll.pack(side="right", fill="y")
        text.pack(side="left", fill="both", expand=True)
        box["text"] = text
        return frame

    def record(result):
        text = box["text"]
        if text is None:
            return
        rolls = "  ".join(str(v) for g in result.groups for v in g.kept)
        box["count"] += 1
        text.config(state="normal")
        # Newest entry on top: one insert at 1.0, alternating text/tag.
        text.insert(
            "1.0",
            f"#{box['count']:<4}", "dim",
            f"{result.describe():<16} ", "dim",
            f"{rolls}  ", "val",
            f"→ {result.total}\n", "total",
        )
        # Trim to the most recent HISTORY_LIMIT lines.
        if int(text.index("end-1c").split(".")[0]) > HISTORY_LIMIT:
            text.delete(f"{HISTORY_LIMIT + 1}.0", "end")
        text.config(state="disabled")

    api.add_panel("Roll History", build, area="core")
    api.on("rolled", record)


# --------------------------------------------------------------------------
# Initiative tracker
# --------------------------------------------------------------------------
def initiative(api):
    theme, fonts = api.theme, api.fonts
    state = {
        "combatants": [],   # [{"id", "name", "init"}] - init may be None
        "current": None,    # id of whoever's turn it is
        "round": 1,
        "next_id": 1,
        "rows": None,
        "round_label": None,
        "add_name": None,
        "add_init": None,
        "add_count": None,
    }

    # -- model ------------------------------------------------------------
    def new_id():
        state["next_id"] += 1
        return state["next_id"] - 1

    def order():
        """Everyone, highest initiative first. Blank initiatives sink."""
        return sorted(
            state["combatants"],
            key=lambda c: (c["init"] is None, -(c["init"] or 0), c["name"].lower()),
        )

    def load():
        for saved in api.storage.get("roster", []):
            state["combatants"].append({
                "id": new_id(),
                "name": saved.get("name", ""),
                "init": saved.get("init"),
            })
        state["round"] = api.storage.get("round", 1)
        index = api.storage.get("current")
        if isinstance(index, int) and 0 <= index < len(state["combatants"]):
            state["current"] = state["combatants"][index]["id"]

    def save():
        roster = order()
        api.storage["roster"] = [{"name": c["name"], "init": c["init"]}
                                 for c in roster]
        api.storage["round"] = state["round"]
        api.storage["current"] = next(
            (i for i, c in enumerate(roster) if c["id"] == state["current"]), None)
        api.save()

    # -- actions -----------------------------------------------------------
    def parse_init(text):
        try:
            return int(text.strip())
        except (TypeError, ValueError):
            return None

    def add():
        name = state["add_name"].get().strip() or "Combatant"
        init = parse_init(state["add_init"].get())
        try:
            count = max(1, min(20, int(state["add_count"].get())))
        except (TypeError, ValueError):
            count = 1

        for i in range(count):
            state["combatants"].append({
                "id": new_id(),
                "name": f"{name} {i + 1}" if count > 1 else name,
                "init": init,
            })
        state["add_name"].delete(0, "end")
        state["add_init"].delete(0, "end")
        state["add_count"].delete(0, "end")
        state["add_count"].insert(0, "1")
        state["add_name"].focus_set()
        rebuild()

    def remove(combatant_id):
        if state["current"] == combatant_id:
            advance(save_after=False)  # don't strand the turn marker
            if state["current"] == combatant_id:
                state["current"] = None
        state["combatants"] = [c for c in state["combatants"]
                               if c["id"] != combatant_id]
        rebuild()

    def advance(save_after=True):
        """Move the turn marker one place down the order."""
        line_up = order()
        if not line_up:
            state["current"] = None
        else:
            position = next((i for i, c in enumerate(line_up)
                             if c["id"] == state["current"]), None)
            if position is None:
                state["current"] = line_up[0]["id"]
            else:
                position += 1
                if position >= len(line_up):
                    position = 0
                    state["round"] += 1
                state["current"] = line_up[position]["id"]
        if save_after:
            rebuild()

    def new_combat():
        for c in state["combatants"]:
            c["init"] = None
        state["current"] = None
        state["round"] = 1
        rebuild()

    def clear_all():
        state["combatants"] = []
        state["current"] = None
        state["round"] = 1
        rebuild()

    # -- widgets -----------------------------------------------------------
    def entry(parent, width, value=""):
        e = tk.Entry(parent, width=width, font=fonts["label"],
                     bg=theme["bg"], fg=theme["fg"],
                     insertbackground=theme["fg"], relief="flat", bd=0,
                     highlightthickness=1, highlightbackground=theme["panel"],
                     highlightcolor=theme["accent"])
        if value:
            e.insert(0, value)
        return e

    def button(parent, text, command, fg=None, bg=None, font=None, width=None):
        return tk.Button(parent, text=text, font=font or fonts["label"],
                         bg=bg or theme["bg"], fg=fg or theme["fg"],
                         activebackground=theme["accent"],
                         activeforeground=theme["bg"], relief="flat", bd=0,
                         cursor="hand2", command=command,
                         **({"width": width} if width else {}))

    def rebuild():
        """Redraw the list in initiative order."""
        rows = state["rows"]
        if rows is None:
            return
        for child in rows.winfo_children():
            child.destroy()

        line_up = order()
        if not line_up:
            tk.Label(rows, text="Nobody in the order yet - add someone above.",
                     font=fonts["label"], bg=theme["panel"], fg=theme["muted"],
                     anchor="w").grid(row=0, column=0, sticky="w", pady=4)
        for i, c in enumerate(line_up):
            active = c["id"] == state["current"]
            tk.Label(rows, text="▶" if active else "", font=fonts["label"],
                     bg=theme["panel"], fg=theme["accent"], width=2).grid(
                row=i, column=0)

            init_box = entry(rows, 4, "" if c["init"] is None else str(c["init"]))
            init_box.configure(justify="center",
                               fg=theme["accent"] if active else theme["fg"])
            init_box.grid(row=i, column=1, padx=(0, 6), pady=1, ipady=2)

            name_box = entry(rows, 1, c["name"])
            name_box.configure(fg=theme["accent"] if active else theme["fg"])
            name_box.grid(row=i, column=2, sticky="ew", pady=1, ipady=2)

            # Typing commits straight to the model; Enter re-sorts the list.
            init_box.bind("<KeyRelease>",
                          lambda _e, c=c, w=init_box: commit_init(c, w))
            name_box.bind("<KeyRelease>",
                          lambda _e, c=c, w=name_box: commit_name(c, w))
            for w in (init_box, name_box):
                w.bind("<Return>", lambda _e: rebuild())
                w.bind("<FocusOut>", lambda _e: save())

            button(rows, "×", lambda c=c: remove(c["id"]),
                   fg=theme["muted"], bg=theme["panel"], width=2).grid(
                row=i, column=3, padx=(6, 0))

        rows.columnconfigure(2, weight=1)
        state["round_label"].config(text=f"Round {state['round']}")
        save()

    def commit_init(combatant, widget):
        combatant["init"] = parse_init(widget.get())

    def commit_name(combatant, widget):
        combatant["name"] = widget.get()

    def build(parent):
        frame = tk.Frame(parent, bg=theme["panel"])

        # Row of controls for adding combatants.
        adder = tk.Frame(frame, bg=theme["panel"])
        adder.pack(fill="x")
        state["add_name"] = entry(adder, 11)
        state["add_name"].pack(side="left", ipady=3)
        state["add_name"].bind("<Return>", lambda _e: add())
        state["add_init"] = entry(adder, 4)
        state["add_init"].configure(justify="center")
        state["add_init"].pack(side="left", padx=6, ipady=3)
        state["add_init"].bind("<Return>", lambda _e: add())
        tk.Label(adder, text="×", font=fonts["label"], bg=theme["panel"],
                 fg=theme["muted"]).pack(side="left")
        state["add_count"] = entry(adder, 3, "1")
        state["add_count"].configure(justify="center")
        state["add_count"].pack(side="left", padx=(4, 6), ipady=3)
        state["add_count"].bind("<Return>", lambda _e: add())
        button(adder, "+ Add", add, fg=theme["accent"],
               bg=theme["panel"]).pack(side="left", ipadx=4, ipady=1)

        state["rows"] = tk.Frame(frame, bg=theme["panel"])
        state["rows"].pack(fill="x", pady=(8, 6))

        footer = tk.Frame(frame, bg=theme["panel"])
        footer.pack(fill="x")
        tk.Button(footer, text="[ NEXT ]", font=fonts["die"],
                  bg=theme["accent"], fg=theme["bg"],
                  activebackground=theme["accent_hot"],
                  activeforeground=theme["bg"], relief="flat", bd=0,
                  cursor="hand2", command=advance).pack(
            side="left", ipadx=4, ipady=3)
        state["round_label"] = tk.Label(footer, text="", font=fonts["die"],
                                        bg=theme["panel"], fg=theme["fg"])
        state["round_label"].pack(side="left", padx=12)
        button(footer, "Clear", clear_all, fg=theme["muted"],
               bg=theme["panel"]).pack(side="right", padx=(6, 0))
        button(footer, "New", new_combat, fg=theme["muted"],
               bg=theme["panel"]).pack(side="right", padx=(6, 0))
        button(footer, "Sort", rebuild, fg=theme["muted"],
               bg=theme["panel"]).pack(side="right")

        rebuild()
        return frame

    load()
    api.add_panel("Initiative", build)
