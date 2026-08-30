"""Running the meeting point, without going near a command line.

Somebody has to be reachable for people in different houses to play
together, and on a lot of home connections that is nobody. The way round it
is for one person to run a meeting point that everybody else dials out to -
the same idea as running a game server for friends, except this one only
carries messages and knows nothing about the game.

That person does not have to be the one running the game. Whoever has the
most ordinary home connection should run this; the host can be anybody.

This window starts it, sets it up as far as it can, and shows the one line
everybody else needs. The relay lives on a thread, so the window stays
answerable while it runs.
"""

import queue
import threading
import tkinter as tk

import netcheck
import paths
import relay as relay_module
from dice_api import THEME

BG = THEME["bg"]
PANEL = THEME["panel"]
FG = THEME["fg"]
MUTED = THEME["muted"]
ACCENT = THEME["accent"]
ACCENT_HOT = THEME.get("accent_hot", ACCENT)
GOOD = THEME["crit"]
BAD = THEME["fumble"]

WHAT_IT_IS = (
    "One person runs this and leaves the window open. Everybody else - "
    "including whoever is running the game - dials out to it, so nobody "
    "has to be reachable from outside except this one machine.\n\n"
    "Run it on whichever computer has the most ordinary home connection. "
    "It does not have to be the person running the game, and it carries "
    "messages only: it never sees a campaign, and keeps nothing."
)


class RelayWindow(tk.Toplevel):
    def __init__(self, parent, port=None, checker=netcheck,
                 engine=relay_module):
        super().__init__(parent)
        self.checker = checker
        self.engine = engine
        self.wanted_port = port or engine.DEFAULT_PORT
        self.relay = None
        self.address = None
        self.opened = False         # did the router open a port for us
        self.port = None
        self.buttons = {}
        self._post = queue.Queue()
        self.title("Run a relay for your friends")
        self.configure(bg=BG)
        self.resizable(False, False)
        paths.apply_icon(self)

        self.body = tk.Frame(self, bg=BG)
        self.body.pack(padx=22, pady=18, fill="both", expand=True)
        self._build()
        self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.after(60, self._drain)

    # -- the window --------------------------------------------------------
    def _build(self):
        tk.Label(self.body, text="Run a relay for your friends", bg=BG, fg=FG,
                 font=("Segoe UI", 14, "bold")).pack(anchor="w")
        tk.Label(self.body, text=WHAT_IT_IS, bg=BG, fg=MUTED, justify="left",
                 wraplength=430, font=("Segoe UI", 9)).pack(anchor="w",
                                                            pady=(4, 14))

        self.notes = tk.Label(self.body, text="", bg=PANEL, fg=MUTED,
                              justify="left", anchor="w", wraplength=406,
                              padx=12, pady=10, font=("Segoe UI", 9))

        # The one line everybody else needs, big enough to read out.
        self.share_box = tk.Frame(self.body, bg=PANEL)
        tk.Label(self.share_box, text="TELL EVERYONE TO USE", bg=PANEL,
                 fg=MUTED, font=("Segoe UI", 8, "bold")).pack(anchor="w",
                                                              padx=12,
                                                              pady=(10, 2))
        self.share = tk.Label(self.share_box, text="", bg=PANEL, fg=ACCENT,
                              font=("Consolas", 15, "bold"))
        self.share.pack(anchor="w", padx=12)
        tk.Label(self.share_box,
                 text="They put that in Host a Session -> People anywhere, "
                      "through a relay.\nAnyone joining only needs the "
                      "invite code, as usual.",
                 bg=PANEL, fg=MUTED, justify="left", wraplength=400,
                 font=("Segoe UI", 8)).pack(anchor="w", padx=12,
                                            pady=(4, 10))

        self.state = tk.Label(self.body, text="", bg=BG, fg=FG, anchor="w",
                              justify="left", wraplength=430,
                              font=("Segoe UI", 10, "bold"))
        self.state.pack(fill="x", pady=(12, 0))
        self.who = tk.Label(self.body, text="", bg=BG, fg=MUTED, anchor="w",
                            justify="left", font=("Segoe UI", 9))
        self.who.pack(fill="x")

        self.buttons_row = tk.Frame(self.body, bg=BG)
        self.buttons_row.pack(fill="x", pady=(16, 0))
        self.go = self._button(self.buttons_row, "Start the relay",
                               self.start, primary=True)
        self.go.pack(side="left")
        self._button(self.buttons_row, "Close",
                     self.close).pack(side="right")

    def _button(self, parent, text, command, primary=False):
        rest = ACCENT if primary else PANEL
        hot = ACCENT_HOT if primary else "#2c303a"
        widget = tk.Label(parent, text=text, bg=rest,
                          fg=BG if primary else ACCENT, padx=16, pady=7,
                          cursor="hand2", font=("Segoe UI", 10, "bold"))
        widget.bind("<Button-1>", lambda _e: command())
        widget.bind("<Enter>", lambda _e: widget.configure(bg=hot))
        widget.bind("<Leave>", lambda _e: widget.configure(bg=rest))
        self.buttons[text] = command
        return widget

    # -- running it --------------------------------------------------------
    def start(self):
        if self.relay is not None:
            return
        try:
            self.relay = self.engine.Relay(self.wanted_port, quiet=True)
            self.port = self.relay.start()
        except OSError as trouble:
            self.relay = None
            self.state.config(text="Could not listen on port %d: %s"
                                   % (self.wanted_port, trouble), fg=BAD)
            return
        self.state.config(text="Listening on port %d - setting up..."
                               % self.port, fg=FG)
        self.notes.pack(fill="x", pady=(0, 10), before=self.state)
        self.notes.config(text="asking the router, checking the firewall, "
                               "finding your address...")
        self.go.config(text="Stop the relay")
        self.buttons["Stop the relay"] = self.stop
        self._tick()

        def work():
            address, opened, notes = self.engine.set_up(self.port,
                                                        opener=self.checker)
            self._post.put(("ready", (address, opened, notes)))

        threading.Thread(target=work, daemon=True).start()

    def stop(self):
        """Put the machine back as it was, and let go of the port."""
        if self.relay is None:
            return
        if self.opened and self.checker is not None:
            self.checker.unforward_port(self.port)
        self.opened = False
        self.relay.stop()
        self.relay = None
        self.share_box.pack_forget()
        self.notes.pack_forget()
        self.state.config(text="Stopped. Any session that was running on it "
                               "has ended.", fg=MUTED)
        self.who.config(text="")
        self.go.config(text="Start the relay")
        self.buttons["Start the relay"] = self.start

    def close(self):
        self.stop()
        self.destroy()

    def _ready(self, address, opened, notes):
        self.address = address
        self.opened = opened
        self.notes.config(text="\n".join(notes))
        if address and opened:
            self.share_box.pack(fill="x", pady=(4, 0),
                                before=self.state)
            self.share.config(text="%s     port %d" % (address, self.port))
            self.state.config(text="Running. Leave this window open.",
                              fg=GOOD)
            if "Copy this" not in self.buttons:
                self._button(self.buttons_row, "Copy this",
                             self.copy).pack(side="left", padx=(8, 0))
        else:
            self.state.config(
                text="Running, but nobody outside can reach it yet.", fg=BAD)
            self.who.config(
                text="Nothing opened a port to this computer. Forward port "
                     "%d here on the router by hand, or run this on "
                     "somebody else's computer instead." % self.port)

    def copy(self):
        self.clipboard_clear()
        self.clipboard_append("%s port %d" % (self.address, self.port))

    def _tick(self):
        """How many people are on it, refreshed while it runs."""
        if self.relay is None or not self.winfo_exists():
            return
        rooms = list(self.relay.rooms.values())
        people = sum(1 + len(room.guests) for room in rooms)
        if rooms:
            self.who.config(
                text="%d session%s, %d %s connected"
                     % (len(rooms), "" if len(rooms) == 1 else "s", people,
                        "person" if people == 1 else "people"))
        elif self.address and self.opened:
            self.who.config(text="Nobody has connected yet.")
        self.after(1000, self._tick)

    def _drain(self):
        try:
            while True:
                what, payload = self._post.get_nowait()
                if what == "ready":
                    self._ready(*payload)
        except queue.Empty:
            pass
        if self.winfo_exists():
            self.after(60, self._drain)


def ask(parent, port=None, checker=netcheck, engine=relay_module):
    window = RelayWindow(parent, port=port, checker=checker, engine=engine)
    window.grab_set()
    parent.wait_window(window)
    return window
