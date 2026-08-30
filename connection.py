"""The window that answers "will my friend be able to join?"

Hosting fails in three or four different ways that all look identical from
the outside - the other person waits, and then it times out. This runs the
checks that tell them apart, says which one it is in plain words, and where
there is something that can be done about it, offers to do it.

The checks take about ten seconds, nearly all of it waiting on the network,
so they run on a thread and the list fills in as they land.
"""

import queue
import threading
import tkinter as tk
import webbrowser

import netcheck
import netplay
import paths
from dice_api import THEME

BG = THEME["bg"]
PANEL = THEME["panel"]
FG = THEME["fg"]
MUTED = THEME["muted"]
ACCENT = THEME["accent"]
ACCENT_HOT = THEME.get("accent_hot", ACCENT)
GOOD = THEME["crit"]
BAD = THEME["fumble"]

# What each sort of finding looks like down the left-hand side.
MARKS = {
    "good": ("+", GOOD),
    "warn": ("!", "#d8a657"),
    "bad": ("x", BAD),
    "note": ("-", MUTED),
}

# What to tell somebody to send their friend, once Tailscale is running.
FRIEND_STEPS = """Send your friend this:

1. Install Tailscale from tailscale.com/download
2. Sign in - the free personal plan is enough
3. Ask me to invite you to my Tailscale network, and accept it
4. Open %s and use the invite code I send you

You will not need to change any router or firewall settings."""


class ConnectionWindow(tk.Toplevel):
    """Runs the checks and offers whatever fix fits the answer."""

    def __init__(self, parent, port=None, checker=netcheck):
        super().__init__(parent)
        self.checker = checker
        self.port = port or netplay.DEFAULT_PORT
        self.title("Can people reach me?")
        self.configure(bg=BG)
        self.resizable(False, False)
        self.buttons = {}           # label -> what pressing it does
        self.result = None          # the last full diagnosis
        self.rows = []
        self.busy = False
        self._post = queue.Queue()  # thread -> window
        paths.apply_icon(self)

        self.body = tk.Frame(self, bg=BG)
        self.body.pack(padx=22, pady=18, fill="both", expand=True)
        self._build()
        self.transient(parent)
        self.after(60, self._drain)
        self.after(120, self.run_checks)

    # -- putting the window together ---------------------------------------
    def _build(self):
        tk.Label(self.body, text="Can people reach me?", bg=BG, fg=FG,
                 font=("Segoe UI", 14, "bold")).pack(anchor="w")
        tk.Label(self.body,
                 text="Joining somebody is easy. Being joined is the hard "
                      "direction, and this is why.",
                 bg=BG, fg=MUTED, justify="left", wraplength=420,
                 font=("Segoe UI", 9)).pack(anchor="w", pady=(2, 12))

        self.list = tk.Frame(self.body, bg=PANEL)
        self.list.pack(fill="x")
        self.spinner = tk.Label(self.list, text="checking...", bg=PANEL,
                                fg=MUTED, font=("Segoe UI", 9),
                                anchor="w", padx=12, pady=10)
        self.spinner.pack(fill="x")

        self.verdict = tk.Label(self.body, text="", bg=BG, fg=FG,
                                justify="left", wraplength=420, anchor="w",
                                font=("Segoe UI", 11, "bold"))
        self.verdict.pack(fill="x", pady=(14, 2))
        self.explain = tk.Label(self.body, text="", bg=BG, fg=MUTED,
                                justify="left", wraplength=420, anchor="w",
                                font=("Segoe UI", 9))
        self.explain.pack(fill="x")

        self.progress = tk.Label(self.body, text="", bg=BG, fg=ACCENT,
                                 justify="left", wraplength=420, anchor="w",
                                 font=("Segoe UI", 9))
        self.progress.pack(fill="x", pady=(6, 0))

        self.actions = tk.Frame(self.body, bg=BG)
        self.actions.pack(fill="x", pady=(14, 0))

        footer = tk.Frame(self.body, bg=BG)
        footer.pack(fill="x", pady=(14, 0))
        self._button(footer, "Check again", self.run_checks).pack(side="left")
        self._button(footer, "Close", self.destroy).pack(side="right")

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

    # -- the checks --------------------------------------------------------
    def run_checks(self):
        """Start again from the top. Safe to press twice - the second press
        is ignored while the first is still going."""
        if self.busy:
            return
        self.busy = True
        for row in self.rows:
            row.destroy()
        self.rows = []
        self.spinner.pack(fill="x")
        self.spinner.config(text="checking...")
        self.verdict.config(text="")
        self.explain.config(text="")
        self.progress.config(text="")
        for child in self.actions.winfo_children():
            child.destroy()

        def work():
            try:
                found = self.checker.diagnose(
                    self.port, report=lambda f: self._post.put(("row", f)))
                self._post.put(("done", found))
            except Exception as trouble:            # pragma: no cover
                self._post.put(("failed", trouble))

        threading.Thread(target=work, daemon=True).start()

    def _drain(self):
        """Anything the worker thread has said, drawn on Tk's own clock."""
        try:
            while True:
                what, payload = self._post.get_nowait()
                if what == "row":
                    self.add_row(payload)
                elif what == "done":
                    self.finish(payload)
                elif what == "progress":
                    self.progress.config(text=payload)
                elif what == "steps":
                    self.show_firewall_steps()
                elif what == "failed":
                    self.busy = False
                    self.spinner.config(text="the checks could not run: %s"
                                             % payload)
        except queue.Empty:
            pass
        if self.winfo_exists():
            self.after(60, self._drain)

    def add_row(self, finding):
        self.spinner.pack_forget()
        mark, colour = MARKS.get(finding["state"], MARKS["note"])
        row = tk.Frame(self.list, bg=PANEL)
        row.pack(fill="x", padx=12, pady=(8, 0))
        tk.Label(row, text=mark, bg=PANEL, fg=colour, width=2,
                 font=("Consolas", 11, "bold")).pack(side="left", anchor="n")
        text = tk.Frame(row, bg=PANEL)
        text.pack(side="left", fill="x", expand=True)
        tk.Label(text, text=finding["title"], bg=PANEL, fg=FG, anchor="w",
                 justify="left", font=("Segoe UI", 10, "bold")).pack(fill="x")
        tk.Label(text, text=finding["detail"], bg=PANEL, fg=MUTED, anchor="w",
                 justify="left", wraplength=380,
                 font=("Segoe UI", 9)).pack(fill="x")
        self.rows.append(row)

    def finish(self, found):
        self.busy = False
        self.result = found
        tk.Frame(self.list, bg=PANEL, height=10).pack(fill="x")
        verdict = found.get("verdict")
        if verdict is None:
            self.verdict.config(text="Nothing can get out of this network")
            return
        head, body = self.checker.ADVICE[verdict]
        self.verdict.config(text=head)
        self.explain.config(text=body)
        self._offer(verdict, found)

    # -- what to do about it -----------------------------------------------
    def _offer(self, verdict, found):
        make = self.checker
        if verdict == make.FORWARD:
            self._button(self.actions, "Open the port on my router",
                         self.open_port, primary=True).pack(side="left")
        elif verdict == make.FIREWALL:
            self._button(self.actions, "Allow it through Windows",
                         self.allow_firewall, primary=True).pack(side="left")
            self._button(self.actions, "Show me how to do it myself",
                         self.show_firewall_steps).pack(side="left",
                                                        padx=(8, 0))
        elif verdict in (make.TAILSCALE, make.JOIN_ONLY):
            state = found.get("tailscale")
            if state == "missing":
                self._button(self.actions, "Set up Tailscale (free)",
                             self.setup_tailscale,
                             primary=True).pack(side="left")
            elif state == "signed":
                self._button(self.actions, "Sign in to Tailscale",
                             self.sign_in, primary=True).pack(side="left")
            self._button(self.actions, "What is Tailscale?",
                         lambda: webbrowser.open(
                             make.TAILSCALE_HOME)).pack(side="left", padx=(8, 0))
        elif verdict == make.HOST_HERE:
            address = found.get("tailscale_address")
            if address:
                self._button(self.actions, "Copy what to send my friend",
                             self.copy_steps, primary=True).pack(side="left")

    def open_port(self):
        """Ask the router to forward the port, and say what it said."""
        self.progress.config(text="asking the router...")

        def work():
            ok, said = self.checker.forward_port(self.port)
            self._post.put(("progress", said))
            if ok:
                self._post.put(("progress",
                                said + " - check again to confirm."))

        threading.Thread(target=work, daemon=True).start()

    def allow_firewall(self):
        """Add the firewall rule. Windows will ask for permission."""
        self.progress.config(text="Windows will ask for permission...")

        def work():
            ok, said = self.checker.firewall_allow()
            if ok:
                self._post.put(("progress", said + " - checking again."))
            else:
                # Somebody without the administrator password cannot use the
                # button at all, so the way to do it by hand comes up here
                # rather than being something to go looking for.
                self._post.put(("progress", said))
                self._post.put(("steps", None))

        threading.Thread(target=work, daemon=True).start()

    def show_firewall_steps(self):
        """The same job, done through Windows' own settings."""
        steps = self.checker.firewall_steps()
        window = tk.Toplevel(self)
        window.title("Allowing it through the firewall by hand")
        window.configure(bg=BG)
        paths.apply_icon(window)
        pad = tk.Frame(window, bg=BG)
        pad.pack(padx=20, pady=16, fill="both", expand=True)
        tk.Label(pad, text="Allowing it through by hand", bg=BG, fg=FG,
                 font=("Segoe UI", 12, "bold")).pack(anchor="w",
                                                     pady=(0, 10))
        body = "\n".join(steps)
        text = tk.Text(pad, bg=PANEL, fg=FG, relief="flat", wrap="word",
                       width=58, height=min(20, len(steps) + 4),
                       font=("Segoe UI", 9), padx=12, pady=10)
        text.insert("1.0", body)
        text.config(state="disabled")
        text.pack(fill="both", expand=True)
        row = tk.Frame(pad, bg=BG)
        row.pack(fill="x", pady=(10, 0))

        def copy():
            self.clipboard_clear()
            self.clipboard_append(body)

        self._button(row, "Copy these steps", copy).pack(side="left")
        self._button(row, "Close", window.destroy).pack(side="right")
        return window

    def setup_tailscale(self):
        """Download and install Tailscale, then hand over to signing in.

        The address it is fetched from is shown before anything is fetched,
        and installing puts Windows' own permission prompt up - nothing here
        happens quietly.
        """
        self.progress.config(text="downloading from %s"
                                  % self.checker.TAILSCALE_URL)

        def work():
            def along(got, total):
                if total:
                    self._post.put(("progress", "downloading... %d%%"
                                    % (got * 100 // total)))
            installer, said = self.checker.download_tailscale(progress=along)
            if not installer:
                self._post.put(("progress", said))
                return
            self._post.put(("progress",
                            "installing - say yes to the Windows prompt"))
            ok, said = self.checker.install_tailscale(installer)
            self._post.put(("progress", said))
            if ok:
                self._post.put(("progress",
                                said + ". Now sign in - press Check again "
                                       "when you have."))
                self.checker.tailscale_sign_in()

        threading.Thread(target=work, daemon=True).start()

    def sign_in(self):
        ok, said = self.checker.tailscale_sign_in()
        self.progress.config(text=said)

    def copy_steps(self):
        """Put the instructions for the other person on the clipboard."""
        self.clipboard_clear()
        self.clipboard_append(FRIEND_STEPS % paths.APP_NAME)
        self.progress.config(text="copied - paste it to your friend")


def ask(parent, port=None, checker=netcheck):
    """Put the window up and wait for it to be closed."""
    window = ConnectionWindow(parent, port=port, checker=checker)
    window.grab_set()
    parent.wait_window(window)
    return window.result
