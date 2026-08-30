"""Mythic GM Emulator 2nd Edition - Fate Chart.

Pick a Chaos Factor (1-9) and the odds of the question, then roll d100 and
read the answer off the chart.

The full chart is filled in: all nine odds across Chaos Factors 1-9.
"""

import tkinter as tk

PLUGIN = {
    "name": "Fate Chart",
    "version": "1.0",
    "description": "Mythic GM Emulator 2e yes/no oracle. All odds, Chaos Factor 1-9.",
    "author": "bundled",
}

# Listed most likely -> least likely, the way the printed chart reads.
ODDS = [
    "Certain",
    "Nearly Certain",
    "Very Likely",
    "Likely",
    "50/50",
    "Unlikely",
    "Very Unlikely",
    "Nearly Impossible",
    "Impossible",
]

# The whole chart is one ladder of "yes" thresholds. Roll d100: at or under
# the threshold is a YES, over it is a NO.
#
# Both axes move along this same ladder. Stepping one step up the odds
# (50/50 -> Likely) and adding one to the Chaos Factor do the exact same
# thing: move one rung up. So 50/50 at Chaos 4 (35) is the same number as
# Unlikely at Chaos 5, and so on.
LADDER = [1, 5, 10, 15, 25, 35, 50, 65, 75, 85, 90, 95, 99]
CENTER = LADDER.index(50)  # 50/50 at Chaos Factor 5, the middle of the chart
CHAOS_MAX = 9

# Rows that don't follow the rules above can be spelled out here instead, as
# (exceptional yes at or under, yes at or under, exceptional no at or over).
EXCEPTIONS = {}


def thresholds(odds, chaos):
    """(exceptional yes max, yes max, exceptional no min), or None if unset.

    Exceptional results are the outer fifth of each side of the threshold:
    with a yes on 65, the best fifth of the yes range (1-13) is an exceptional
    yes, and the worst fifth of the no range (94-100) is an exceptional no.

    Either exceptional band can come back None. In the bottom corner of the
    chart a yes only happens on a 1, which leaves no room under it for an
    exceptional yes; in the top corner a no only happens on a 100, which
    leaves no room above it for an exceptional no.
    """
    if (odds, chaos) in EXCEPTIONS:
        return EXCEPTIONS[(odds, chaos)]
    if odds not in ODDS or not 1 <= chaos <= CHAOS_MAX:
        return None
    # ODDS runs most likely -> least likely, so 50/50 sits at index 4.
    rung = CENTER + (4 - ODDS.index(odds)) + (chaos - 5)
    # The far corners of the chart run off the end of the ladder; they stop at
    # the extremes rather than wrapping.
    yes = LADDER[max(0, min(len(LADDER) - 1, rung))]
    exceptional_yes = yes // 5
    exceptional_no = 101 - (100 - yes) // 5
    return (exceptional_yes if exceptional_yes >= 1 else None,
            yes,
            exceptional_no if exceptional_no <= 100 else None)


def setup(api):
    state = {
        # A saved Chaos Factor of 10 predates the chart being 1-9.
        "chaos": min(max(1, int(api.storage.get("chaos", 5))), CHAOS_MAX),
        "odds": api.storage.get("odds", "50/50"),
        "chaos_buttons": {},
        "odds_buttons": {},
        "target": None,
        "verdict": None,
        "roll_button": None,
    }

    theme, fonts = api.theme, api.fonts

    def chip(parent, text, command, width):
        return tk.Button(
            parent, text=text, font=fonts["label"], width=width,
            bg=theme["bg"], fg=theme["fg"],
            activebackground=theme["accent"], activeforeground=theme["bg"],
            relief="flat", bd=0, cursor="hand2", command=command)

    # -- selection -------------------------------------------------------
    def choose_chaos(value):
        state["chaos"] = value
        remember()

    def choose_odds(value):
        state["odds"] = value
        remember()

    def remember():
        api.storage["chaos"] = state["chaos"]
        api.storage["odds"] = state["odds"]
        api.save()
        refresh()

    def refresh():
        for value, button in state["chaos_buttons"].items():
            on = value == state["chaos"]
            button.config(bg=theme["accent"] if on else theme["bg"],
                          fg=theme["bg"] if on else theme["fg"])
        for value, button in state["odds_buttons"].items():
            on = value == state["odds"]
            button.config(bg=theme["accent"] if on else theme["bg"],
                          fg=theme["bg"] if on else theme["fg"])

        row = thresholds(state["odds"], state["chaos"])
        if row:
            exc_yes, yes, exc_no = row
            parts = [f"Yes on {yes} or under"]
            parts.append(f"Exceptional yes 1-{exc_yes}" if exc_yes
                         else "✕ no exceptional yes")
            parts.append(f"Exceptional no {exc_no}-100" if exc_no
                         else "✕ no exceptional no")
            state["target"].config(text="   ·   ".join(parts),
                                   fg=theme["muted"])
            state["roll_button"].config(state="normal", bg=theme["accent"])
        else:
            state["target"].config(
                text=f"{state['odds']} at Chaos {state['chaos']} "
                     f"isn't in the chart yet.",
                fg=theme["fumble"])
            state["roll_button"].config(state="disabled", bg=theme["panel"])
        state["verdict"].config(text="")

    # -- rolling ---------------------------------------------------------
    def roll():
        row = thresholds(state["odds"], state["chaos"])
        if not row:
            return
        exc_yes, yes, exc_no = row
        value = api.roll_die("d100")

        if exc_yes is not None and value <= exc_yes:
            verdict, color = "EXCEPTIONAL YES", theme["crit"]
        elif value <= yes:
            verdict, color = "YES", theme["crit"]
        elif exc_no is not None and value >= exc_no:
            verdict, color = "EXCEPTIONAL NO", theme["fumble"]
        else:
            verdict, color = "NO", theme["fumble"]

        state["verdict"].config(text=verdict, fg=color)
        # hooks=False so another mod's modifier can't shift a chart reading.
        api.present(
            [api.make_group("d100", [value])],
            notes=[f"{verdict}  ·  {state['odds']} at Chaos {state['chaos']}"],
            label=verdict,
            hooks=False,
        )

    # -- panel -----------------------------------------------------------
    def build(parent):
        frame = tk.Frame(parent, bg=theme["panel"])

        chaos_row = tk.Frame(frame, bg=theme["panel"])
        chaos_row.pack(fill="x")
        tk.Label(chaos_row, text="Chaos", font=fonts["label"],
                 bg=theme["panel"], fg=theme["muted"], width=6,
                 anchor="w").pack(side="left")
        for value in range(1, CHAOS_MAX + 1):
            b = chip(chaos_row, str(value),
                     lambda v=value: choose_chaos(v), width=2)
            b.pack(side="left", padx=2, ipady=2)
            state["chaos_buttons"][value] = b

        odds_grid = tk.Frame(frame, bg=theme["panel"])
        odds_grid.pack(fill="x", pady=(8, 0))
        tk.Label(odds_grid, text="Odds", font=fonts["label"],
                 bg=theme["panel"], fg=theme["muted"], width=6,
                 anchor="nw").grid(row=0, column=0, sticky="nw", pady=1)
        for i, name in enumerate(ODDS):
            # No fixed width: the columns share what room there is, so the
            # panel no longer decides how wide the whole window must be.
            b = chip(odds_grid, name, lambda n=name: choose_odds(n), width=0)
            b.grid(row=i // 3, column=1 + i % 3, padx=1, pady=1,
                   ipady=1, sticky="ew")
            state["odds_buttons"][name] = b
        for c in (1, 2, 3):
            odds_grid.columnconfigure(c, weight=1)

        # Wrapped, so a long reading does not decide how wide the whole
        # window has to be.
        state["target"] = tk.Label(frame, text="", font=fonts["label"],
                                   bg=theme["panel"], fg=theme["muted"],
                                   anchor="w", justify="left", wraplength=300)
        state["target"].pack(fill="x", pady=(6, 4))

        answer_row = tk.Frame(frame, bg=theme["panel"])
        answer_row.pack(fill="x")
        state["roll_button"] = tk.Button(
            answer_row, text="[ ASK THE FATE CHART ]", font=fonts["die"],
            bg=theme["accent"], fg=theme["bg"],
            activebackground=theme["accent_hot"], activeforeground=theme["bg"],
            relief="flat", bd=0, cursor="hand2", command=roll)
        state["roll_button"].pack(side="left", ipadx=5, ipady=4)
        state["verdict"] = tk.Label(answer_row, text="", font=fonts["title"],
                                    bg=theme["panel"], fg=theme["fg"])
        state["verdict"].pack(side="left", padx=8)

        refresh()
        return frame

    api.add_panel("Fate Chart", build)
