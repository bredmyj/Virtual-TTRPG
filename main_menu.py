"""The front door: carry on alone, host a game, or join somebody else's.

`ask()` puts the menu up and hands back what to do next - or None if the
window was closed, which means don't start at all. Joining is finished here
rather than in the app, so a mistyped code leaves you in the menu with a
message instead of dropping you into a game that isn't there.
"""

import os
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog

import avatar
import connection
import crop
import dice_api
import netcheck
import relay_window
import paths
import netplay
from dice_api import THEME

BG = THEME["bg"]
PANEL = THEME["panel"]
FG = THEME["fg"]
MUTED = THEME["muted"]
ACCENT = THEME["accent"]
ACCENT_HOT = THEME["accent_hot"]
CRIT = THEME["crit"]
FUMBLE = THEME["fumble"]


def should_show():
    """The menu is the front door unless they asked to skip it."""
    config = dice_api.load_config()
    if config.get("force_menu"):
        return True
    return not config.get("skip_menu")


def clear_force():
    config = dice_api.load_config()
    if config.pop("force_menu", None):
        dice_api.save_config(config)


def ask():
    """Show the menu. Returns a plan dict, or None to quit."""
    clear_force()
    menu = MainMenu()
    menu.mainloop()
    return menu.plan


class MainMenu(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("%s  %s" % (paths.APP_NAME, paths.VERSION))
        paths.apply_icon(self)
        self.configure(bg=BG)
        self.resizable(False, False)

        self.plan = None
        self.buttons = {}           # label -> what choosing it does
        self.profile = netplay.Profile.load()
        self.config_data = dice_api.load_config()
        self.keep = []              # images Tk must not throw away

        self._build()
        self._centre()
        self.protocol("WM_DELETE_WINDOW", self.destroy)

    # ------------------------------------------------------------------
    # laying it out
    # ------------------------------------------------------------------
    def _build(self):
        pad = tk.Frame(self, bg=BG)
        pad.pack(padx=34, pady=26)

        tk.Label(pad, text=paths.APP_NAME, bg=BG, fg=FG,
                 font=("Segoe UI", 26, "bold")).pack(anchor="w")
        line = tk.Frame(pad, bg=BG)
        line.pack(fill="x", pady=(0, 20))
        tk.Label(line, text="solo and tabletop RPG tracker", bg=BG, fg=MUTED,
                 font=("Segoe UI", 10)).pack(side="left")
        # Everyone playing together has to be on the same build, so it is
        # worth being able to read yours out without going looking for it.
        tk.Label(line, text="version %s" % paths.VERSION, bg=BG, fg=MUTED,
                 font=("Segoe UI", 9)).pack(side="right")

        saves = dice_api.list_saves()
        current = dice_api.current_save()

        self._big(pad, "Continue", current if current in saves else "New game",
                  self._continue, accent=True)
        self._big(pad, "New Campaign", "start a fresh adventure",
                  self._new_campaign)

        self._rule(pad)

        self._big(pad, "Host a Session",
                  "play with others on this network", self._host)
        self._big(pad, "Join a Session",
                  "someone has sent you an invite code", self._join)
        # The way two people in different houses play when neither of their
        # connections will accept a call. One of them runs this; it is the
        # only part that has to be reachable.
        self._big(pad, "Run a Relay",
                  "let friends reach each other over the internet",
                  self._relay)

        self._rule(pad)

        # Who they are, sitting right there rather than hidden in a menu.
        self.who = tk.Frame(pad, bg=PANEL, highlightthickness=0)
        self.who.pack(fill="x", pady=(0, 14))
        self._draw_profile()

        self.skip = tk.BooleanVar(value=bool(self.config_data.get("skip_menu")))
        row = tk.Frame(pad, bg=BG)
        row.pack(fill="x")
        tk.Checkbutton(row, text="Go straight to my campaign next time",
                       variable=self.skip, command=self._remember_skip,
                       bg=BG, fg=MUTED, selectcolor=PANEL,
                       activebackground=BG, activeforeground=FG,
                       highlightthickness=0, bd=0,
                       font=("Segoe UI", 9)).pack(anchor="w")
        tk.Label(row, text="File → Main Menu brings this back.",
                 bg=BG, fg=MUTED, font=("Segoe UI", 8)).pack(anchor="w",
                                                             padx=(22, 0))

    def _big(self, parent, title, detail, command, accent=False):
        """A whole row that lights up and can be clicked anywhere."""
        row = tk.Frame(parent, bg=PANEL, cursor="hand2")
        row.pack(fill="x", pady=3, ipady=2)
        inner = tk.Frame(row, bg=PANEL)
        inner.pack(fill="x", padx=14, pady=8)
        name = tk.Label(inner, text=title, bg=PANEL,
                        fg=ACCENT if accent else FG,
                        font=("Segoe UI", 12, "bold"), anchor="w")
        name.pack(fill="x")
        note = tk.Label(inner, text=detail, bg=PANEL, fg=MUTED,
                        font=("Segoe UI", 9), anchor="w")
        note.pack(fill="x")

        widgets = (row, inner, name, note)
        for widget in widgets:
            widget.bind("<Button-1>", lambda _e: command())
            widget.bind("<Enter>", lambda _e: [w.configure(bg="#2c303a")
                                               for w in widgets])
            widget.bind("<Leave>", lambda _e: [w.configure(bg=PANEL)
                                               for w in widgets])
        self.buttons[title] = command
        return row

    def _rule(self, parent):
        tk.Frame(parent, bg="#31353f", height=1).pack(fill="x", pady=12)

    def _draw_profile(self):
        for child in self.who.winfo_children():
            child.destroy()
        self.keep.clear()

        face = tk.Canvas(self.who, width=44, height=44, bg=PANEL,
                         highlightthickness=0)
        face.pack(side="left", padx=12, pady=10)
        photo = avatar.draw_face(face, 1, 1, 42,
                                 self.profile.name or "?",
                                 self.profile.colour, self.profile.picture)
        if photo is not None:
            self.keep.append(photo)

        text = tk.Frame(self.who, bg=PANEL)
        text.pack(side="left", fill="both", expand=True, pady=10)
        tk.Label(text, text=self.profile.name or "No name yet", bg=PANEL,
                 fg=FG if self.profile.name else FUMBLE,
                 font=("Segoe UI", 11, "bold"), anchor="w").pack(fill="x")
        tk.Label(text, text="this is how others see you", bg=PANEL, fg=MUTED,
                 font=("Segoe UI", 9), anchor="w").pack(fill="x")

        button = tk.Label(self.who, text="Profile", bg=PANEL, fg=ACCENT,
                          font=("Segoe UI", 10, "bold"), cursor="hand2")
        button.pack(side="right", padx=14)
        button.bind("<Button-1>", lambda _e: self._edit_profile())

    def _centre(self):
        self.update_idletasks()
        width, height = self.winfo_width(), self.winfo_height()
        x = (self.winfo_screenwidth() - width) // 2
        y = (self.winfo_screenheight() - height) // 3
        self.geometry("+%d+%d" % (max(0, x), max(0, y)))

    # ------------------------------------------------------------------
    # the choices
    # ------------------------------------------------------------------
    def _remember_skip(self):
        self.config_data = dice_api.load_config()
        self.config_data["skip_menu"] = bool(self.skip.get())
        dice_api.save_config(self.config_data)

    def _leave(self, plan):
        self.plan = plan
        self.destroy()

    def _continue(self):
        self._leave({"mode": "solo", "campaign": dice_api.current_save()})

    def _new_campaign(self):
        name = simpledialog.askstring("New campaign", "Name this campaign:",
                                      parent=self)
        if not name:
            return
        created = dice_api.create_save(name)
        if created is None:
            messagebox.showerror("Campaign exists",
                                 "There is already a campaign called %r."
                                 % dice_api.clean_save_name(name), parent=self)
            return
        dice_api.set_current_save(created)
        self._leave({"mode": "solo", "campaign": created})

    def _need_name(self):
        if self.profile.is_ready():
            return True
        messagebox.showinfo("Who are you?",
                            "Set a display name in your profile first, so the "
                            "others know who has turned up.", parent=self)
        self._edit_profile()
        return self.profile.is_ready()

    def _host(self):
        if not self._need_name():
            return
        chosen = HostDialog(self, self.profile).result
        if chosen is None:
            return
        dice_api.set_current_save(chosen["campaign"])
        self._leave({"mode": "host", "campaign": chosen["campaign"],
                     "address": chosen["address"],
                     "port": chosen["port"]})

    def _relay(self):
        """The meeting point, run from here rather than from a file."""
        relay_window.ask(self)

    def _join(self):
        if not self._need_name():
            return
        joined = JoinDialog(self, self.profile).result
        if joined is None:
            return
        self._leave({"mode": "join", "client": joined["client"],
                     "campaign": joined["campaign"]})

    def _edit_profile(self):
        ProfileDialog(self, self.profile)
        self.profile = netplay.Profile.load()
        self._draw_profile()


# ======================================================================
# a small dark dialog to build the rest on
# ======================================================================
class Dialog(tk.Toplevel):
    def __init__(self, parent, title, width=None):
        super().__init__(parent)
        self.title(title)
        self.configure(bg=BG)
        self.resizable(False, False)
        self.result = None
        self.buttons = {}           # label -> what pressing it does
        self.body = tk.Frame(self, bg=BG)
        self.body.pack(padx=22, pady=18, fill="both", expand=True)
        self.transient(parent)
        self.build()
        self.update_idletasks()
        x = parent.winfo_rootx() + (parent.winfo_width()
                                    - self.winfo_width()) // 2
        y = parent.winfo_rooty() + 70
        self.geometry("+%d+%d" % (max(0, x), max(0, y)))
        self.grab_set()
        self.wait_window(self)

    def build(self):                    # pragma: no cover - overridden
        raise NotImplementedError

    def heading(self, text, detail=None):
        tk.Label(self.body, text=text, bg=BG, fg=FG,
                 font=("Segoe UI", 14, "bold")).pack(anchor="w")
        if detail:
            tk.Label(self.body, text=detail, bg=BG, fg=MUTED, justify="left",
                     font=("Segoe UI", 9), wraplength=380).pack(anchor="w",
                                                                pady=(2, 14))

    def button(self, parent, text, command, colour=ACCENT, primary=False):
        """`primary` is the one to press - filled in rather than outlined."""
        rest = ACCENT if primary else PANEL
        hot = ACCENT_HOT if primary else "#2c303a"
        widget = tk.Label(parent, text=text, bg=rest,
                          fg=BG if primary else colour, padx=16, pady=7,
                          cursor="hand2", font=("Segoe UI", 10, "bold"))
        widget.bind("<Button-1>", lambda _e: command())
        widget.bind("<Enter>", lambda _e: widget.configure(bg=hot))
        widget.bind("<Leave>", lambda _e: widget.configure(bg=rest))
        self.buttons[text] = command
        return widget

    def entry(self, parent, font=("Segoe UI", 11), **kwargs):
        return tk.Entry(parent, bg=PANEL, fg=FG, insertbackground=FG,
                        relief="flat", font=font, **kwargs)


# ======================================================================
# profile
# ======================================================================
class ProfileDialog(Dialog):
    def __init__(self, parent, profile):
        self.profile = profile
        self.keep = []
        # Set before build() runs: picking a colour redraws the preview, and
        # that happens while the rest of the window is still being put up.
        self.preview = None
        self.picture = profile.picture
        self.colour = profile.colour
        super().__init__(parent, "Your profile")

    def build(self):
        self.heading("Your profile",
                     "A name, a colour and a face. There is no password and "
                     "nothing to sign into - this is only so the other "
                     "players know who you are.")

        tk.Label(self.body, text="Display name", bg=BG, fg=MUTED,
                 font=("Segoe UI", 9)).pack(anchor="w")
        self.name = self.entry(self.body, width=28)
        self.name.insert(0, self.profile.name)
        self.name.pack(fill="x", ipady=5, pady=(2, 14))
        self.name.focus_set()

        tk.Label(self.body, text="Your colour", bg=BG, fg=MUTED,
                 font=("Segoe UI", 9)).pack(anchor="w")
        tk.Label(self.body, text="your cursor and your name badge use this",
                 bg=BG, fg="#5f6472",
                 font=("Segoe UI", 8)).pack(anchor="w")
        grid = tk.Frame(self.body, bg=BG)
        grid.pack(anchor="w", pady=(6, 14))
        self.swatches = {}
        for index, (name, value) in enumerate(netplay.PROFILE_COLOURS):
            cell = tk.Frame(grid, bg=BG, highlightthickness=2,
                            highlightbackground=BG, cursor="hand2")
            cell.grid(row=index // 8, column=index % 8, padx=2, pady=2)
            block = tk.Frame(cell, bg=value, width=26, height=26)
            block.pack()
            for widget in (cell, block):
                widget.bind("<Button-1>",
                            lambda _e, v=value: self._pick_colour(v))
            self.swatches[value] = cell
        self._pick_colour(self.colour)

        tk.Label(self.body, text="Picture", bg=BG, fg=MUTED,
                 font=("Segoe UI", 9)).pack(anchor="w")
        picture_row = tk.Frame(self.body, bg=BG)
        picture_row.pack(fill="x", pady=(4, 16))
        self.preview = tk.Canvas(picture_row, width=64, height=64, bg=BG,
                                 highlightthickness=0)
        self.preview.pack(side="left")
        self._draw_preview()

        picks = tk.Frame(picture_row, bg=BG)
        picks.pack(side="left", padx=14)
        self.button(picks, "Choose...", self._choose).pack(anchor="w")
        self.button(picks, "Remove", self._remove,
                    colour=MUTED).pack(anchor="w", pady=(6, 0))
        if not avatar.HAVE_PIL:
            tk.Label(picture_row, text="(pictures need Pillow installed)",
                     bg=BG, fg=FUMBLE,
                     font=("Segoe UI", 8)).pack(side="left")

        buttons = tk.Frame(self.body, bg=BG)
        buttons.pack(fill="x", pady=(4, 0))
        self.button(buttons, "Cancel", self.destroy,
                    colour=MUTED).pack(side="right")
        self.button(buttons, "Save Profile", self._save,
                    primary=True).pack(side="right", padx=(0, 8))
        self.bind("<Return>", lambda _e: self._save())

    def _pick_colour(self, value):
        self.colour = value
        for swatch, cell in self.swatches.items():
            cell.configure(highlightbackground=FG if swatch == value else BG)
        self._draw_preview()

    def _draw_preview(self):
        if self.preview is None:
            return              # the window is still being built
        self.preview.delete("all")
        self.keep.clear()
        photo = avatar.draw_face(self.preview, 1, 1, 62,
                                 self.name.get() if hasattr(self, "name")
                                 else self.profile.name,
                                 self.colour, self.picture)
        if photo is not None:
            self.keep.append(photo)

    def _choose(self):
        if not avatar.HAVE_PIL:
            messagebox.showinfo("Pillow needed",
                                "Profile pictures need the Pillow library.",
                                parent=self)
            return
        path = filedialog.askopenfilename(
            parent=self, title="Choose a picture", filetypes=crop.KINDS)
        if not path:
            return                      # they thought better of it
        try:
            # The same window the figures on the map use: line the face up
            # in the circle, zoom until it sits right, then confirm.
            self.cropper = crop.CropDialog(
                self, path, title="Your picture", theme=THEME,
                on_accept=self._use_picture, store=avatar.STORED_SIZE)
        except Exception as exc:        # a broken file, an odd format
            messagebox.showerror("Could not read that",
                                 "That file could not be opened as a "
                                 "picture.%s%s" % (chr(10) + chr(10), exc),
                                 parent=self)

    def _use_picture(self, picture):
        """Called by the crop window once the framing is settled."""
        if not self.winfo_exists():
            return          # they closed the profile while framing it
        stored = avatar.store_image(picture, netplay.PROFILE_PICTURE)
        if stored is None:
            messagebox.showerror("Could not save that",
                                 "That picture could not be saved.",
                                 parent=self)
            return
        # Kept as our own copy, so moving the original later changes nothing.
        self.picture = stored
        self._draw_preview()

    def _remove(self):
        self.picture = None
        self._draw_preview()

    def _save(self):
        name = self.name.get().strip()
        if not name:
            messagebox.showinfo("Name needed",
                                "Put in a display name so the others can tell "
                                "who you are.", parent=self)
            return
        self.profile.name = name
        self.profile.colour = self.colour
        self.profile.picture = self.picture
        self.profile.save()
        self.result = self.profile
        self.destroy()


# ======================================================================
# hosting
# ======================================================================
class HostDialog(Dialog):
    def __init__(self, parent, profile):
        self.profile = profile
        super().__init__(parent, "Host a session")

    def build(self):
        self.heading("Host a session",
                     "Your machine runs the game and everyone else looks in. "
                     "They need to be on the same network as you - wifi or "
                     "cable, either is fine, and on version %s like you."
                     % paths.VERSION)

        tk.Label(self.body, text="Campaign", bg=BG, fg=MUTED,
                 font=("Segoe UI", 9)).pack(anchor="w")
        saves = dice_api.list_saves() or [dice_api.current_save()]
        self.campaign = tk.StringVar(value=dice_api.current_save())
        if self.campaign.get() not in saves:
            self.campaign.set(saves[0])
        picker = tk.OptionMenu(self.body, self.campaign, *saves)
        picker.configure(bg=PANEL, fg=FG, activebackground=ACCENT,
                         activeforeground=BG, relief="flat",
                         highlightthickness=0, font=("Segoe UI", 10),
                         anchor="w")
        picker["menu"].configure(bg=PANEL, fg=FG, activebackground=ACCENT,
                                 activeforeground=BG, bd=0)
        picker.pack(fill="x", pady=(3, 14))

        # Where the session is held: on this network, or at a meeting point
        # anybody can dial out to.
        tk.Label(self.body, text="Who is playing", bg=BG, fg=MUTED,
                 font=("Segoe UI", 9)).pack(anchor="w")
        self.where = tk.StringVar(value=self.config_where())
        for value, label in (
                ("lan", "People on this network"),
                ("direct", "People anywhere, straight from this computer"),
                ("net", "People anywhere, through a relay")):
            tk.Radiobutton(self.body, text=label, value=value,
                           variable=self.where, command=self._sync_where,
                           bg=BG, fg=FG, selectcolor=PANEL,
                           activebackground=BG, activeforeground=FG,
                           highlightthickness=0, bd=0,
                           font=("Segoe UI", 10)).pack(anchor="w")

        self.relay_row = tk.Frame(self.body, bg=BG)
        tk.Label(self.relay_row, text="Relay address", bg=BG, fg=MUTED,
                 font=("Segoe UI", 9)).pack(anchor="w")
        tk.Label(self.relay_row,
                 text="the machine running relay.py, and its port",
                 bg=BG, fg="#5f6472",
                 font=("Segoe UI", 8)).pack(anchor="w")
        entry_row = tk.Frame(self.relay_row, bg=BG)
        entry_row.pack(fill="x", pady=(2, 0))
        self.relay = self.entry(entry_row, width=22)
        self.relay.insert(0, dice_api.load_config().get("relay", ""))
        self.relay.pack(side="left", ipady=4)
        self.relay_port = self.entry(entry_row, width=6)
        self.relay_port.insert(0, str(dice_api.load_config().get(
            "relay_port", netplay.RELAY_PORT)))
        self.relay_port.pack(side="left", padx=(6, 0), ipady=4)
        tk.Frame(self.body, bg=BG, height=8).pack()

        addresses = netplay.local_addresses()
        self._addresses = list(addresses)
        self.address = tk.StringVar(value=addresses[0])
        self.public = None
        self.check_row = tk.Frame(self.body, bg=BG)
        self.button(self.check_row, "Can people reach me?",
                    self._check_connection).pack(anchor="w")
        self.check_note = tk.Label(self.check_row, text="", bg=BG, fg=MUTED,
                                   wraplength=360, justify="left",
                                   font=("Segoe UI", 8))
        self.check_note.pack(anchor="w", pady=(4, 0))

        self.address_row = tk.Frame(self.body, bg=BG)
        self.address_row.pack(fill="x")
        if len(addresses) > 1:
            # More than one adapter - wired and wireless both, most likely.
            # Only they can say which network the others are on.
            tk.Label(self.body, text="This machine's address", bg=BG, fg=MUTED,
                     font=("Segoe UI", 9)).pack(anchor="w")
            tk.Label(self.body,
                     text="pick the network the other players are on",
                     bg=BG, fg="#5f6472",
                     font=("Segoe UI", 8)).pack(anchor="w")
            for found in addresses:
                tk.Radiobutton(self.body, text=found, value=found,
                               variable=self.address, bg=BG, fg=FG,
                               selectcolor=PANEL, activebackground=BG,
                               activeforeground=FG, highlightthickness=0,
                               bd=0, font=("Segoe UI", 10)).pack(anchor="w")
            tk.Frame(self.body, bg=BG, height=10).pack()
        else:
            tk.Label(self.body, text="Hosting from %s" % addresses[0], bg=BG,
                     fg=MUTED,
                     font=("Segoe UI", 9)).pack(anchor="w", pady=(0, 14))

        buttons = tk.Frame(self.body, bg=BG)
        buttons.pack(fill="x", pady=(4, 0))
        self.button(buttons, "Cancel", self.destroy,
                    colour=MUTED).pack(side="right")
        self.button(buttons, "Start Hosting", self._start,
                    primary=True).pack(side="right", padx=(0, 8))
        # The window opens on whatever was chosen last time, and until this
        # was here nothing had shown the rows that choice needs - they only
        # appeared on pressing a radio button, and pressing the one already
        # selected does nothing. Somebody who always hosts through a relay
        # never saw the box to put the relay address in.
        self._sync_where()

    def config_where(self):
        return dice_api.load_config().get("host_where", "lan")

    def _sync_where(self):
        """Only show what the chosen way of playing actually needs."""
        if self.where.get() == "net":
            self.relay_row.pack(fill="x", pady=(6, 0),
                                before=self.address_row)
        else:
            self.relay_row.pack_forget()
        if self.where.get() == "direct":
            self.check_row.pack(fill="x", pady=(6, 0),
                                before=self.address_row)
        else:
            self.check_row.pack_forget()

    def _check_connection(self):
        """Run the real checks and say which of them is the problem.

        This used to guess: it sent a packet out, saw the port number
        survive, and called that reachable. Port preservation on the way out
        says nothing about whether anything is allowed in, so on a shared
        provider network - where nobody can be reached at all - it gave a
        green light and the other person timed out with no explanation.
        """
        found = connection.ask(self, port=netplay.DEFAULT_PORT)
        if not found:
            return
        if found.get("public"):
            self.public = found["public"]
        # Tailscale gives an address that works from anywhere, so if one is
        # running it is almost certainly the one to host on.
        address = found.get("tailscale_address")
        if address and address not in self._addresses:
            self._addresses.append(address)
            self.address.set(address)
        verdict = found.get("verdict")
        if verdict is None:
            self.check_note.config(text="Nothing can get out of this "
                                        "network at all.", fg=FUMBLE)
            return
        head, _body = netcheck.ADVICE[verdict]
        self.check_note.config(
            text=head, fg=CRIT if verdict == netcheck.HOST_HERE else FUMBLE)

    def _start(self):
        chosen = {"campaign": self.campaign.get(),
                  "address": self.address.get(),
                  "port": netplay.DEFAULT_PORT}
        settings = dice_api.load_config()
        settings["host_where"] = self.where.get()
        if self.where.get() == "direct":
            found = self.public or (netplay.public_address() or (None,))[0]
            if not found:
                messagebox.showinfo(
                    "Could not find your address",
                    "Nothing answered when asked what address the internet "
                    "sees you as, so there is no code to hand out. Try "
                    "Check my connection, or use a relay.", parent=self)
                return
            chosen["address"] = found
        if self.where.get() == "net":
            where = self.relay.get().strip()
            if not where:
                messagebox.showinfo(
                    "Relay needed",
                    "Playing with people beyond this network needs a machine "
                    "in the middle that everyone can reach.\n\n"
                    "Run relay.py on it, then put its address "
                    "here.", parent=self)
                return
            try:
                port = int(self.relay_port.get().strip()
                           or netplay.RELAY_PORT)
            except ValueError:
                port = netplay.RELAY_PORT
            chosen["relay"] = where
            chosen["relay_port"] = port
            settings["relay"] = where
            settings["relay_port"] = port
        dice_api.save_config(settings)
        self.result = chosen
        self.destroy()


# ======================================================================
# joining
# ======================================================================
class JoinDialog(Dialog):
    def __init__(self, parent, profile):
        self.profile = profile
        super().__init__(parent, "Join a session")

    def build(self):
        self.heading("Join a session",
                     "Type the invite code the host read out to you. Dashes "
                     "and capitals do not matter.")

        self.code = self.entry(self.body, width=26,
                               font=("Consolas", 14))
        self.code.pack(fill="x", ipady=6, pady=(0, 6))
        self.code.focus_set()
        self.code.bind("<Return>", lambda _e: self._connect())

        self.note = tk.Label(self.body, text="", bg=BG, fg=FUMBLE,
                             wraplength=380, justify="left",
                             font=("Segoe UI", 9))
        self.note.pack(anchor="w", pady=(0, 12))

        buttons = tk.Frame(self.body, bg=BG)
        buttons.pack(fill="x")
        self.button(buttons, "Cancel", self.destroy,
                    colour=MUTED).pack(side="right")
        self.go = self.button(buttons, "Join", self._connect, primary=True)
        self.go.pack(side="right", padx=(0, 8))
        # The same checks the host can run. A join that times out is usually
        # the host's end, but not always, and this is how to tell.
        self.help = self.button(buttons, "Why can I not join?",
                                self._diagnose, colour=MUTED)

    def _diagnose(self):
        connection.ask(self, port=netplay.DEFAULT_PORT)

    def _connect(self):
        code = self.code.get().strip()
        if not code:
            return
        self.note.configure(text="Looking for the host...", fg=MUTED)
        self.update_idletasks()

        client = netplay.Client(self.profile)
        why = client.connect(code)
        if why is not None:
            self.note.configure(text=why[:1].upper() + why[1:], fg=FUMBLE)
            # A timeout is the one worth explaining: it means nothing
            # answered at all, which is almost always the host being
            # unreachable rather than anything this end has done.
            if "timed out" in why.lower() or "could not reach" in why.lower():
                self.note.configure(
                    text=why[:1].upper() + why[1:] +
                         "\n\nNothing answered. Usually that means the host "
                         "cannot be reached from outside - ask them to run "
                         "\"Can people reach me?\" in their host window.")
                self.help.pack(side="left")
            return

        campaign = (client.host or {}).get("campaign") or "Shared Game"
        self.note.configure(text="Joined %s's game."
                                 % (client.host or {}).get("name", "the host"),
                            fg=CRIT)
        self.result = {"client": client, "campaign": campaign}
        self.after(400, self.destroy)
