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
import crop
import dice_api
import paths
import netplay
import servers
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

        self._big(pad, "Host on This Network",
                  "play with others in the same house", self._host)
        self._big(pad, "Join on This Network",
                  "someone has read you an invite code", self._join)
        # Everybody somewhere else meets on a server: one machine somebody
        # leaves running, which is the only part that has to be reachable.
        self._big(pad, "Connect to a Server",
                  "play with people anywhere", self._server)

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

    def _join(self):
        if not self._need_name():
            return
        joined = JoinDialog(self, self.profile).result
        if joined is None:
            return
        self._leave({"mode": "join", "client": joined["client"],
                     "campaign": joined["campaign"]})

    def _server(self):
        """Onto a server, and out of here with whatever was picked there.

        The lobby hands back a plan already made - hosting or joining - so
        there is nothing to work out at this end.
        """
        if not self._need_name():
            return
        plan = ServerListDialog(self, self.profile).result
        if plan is None:
            return
        self._leave(plan)

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
    """Hosting for people on the same network as you.

    Deliberately short. Everything about reaching a host somewhere else has
    moved to servers, so what is left here is the two things that actually
    have to be decided: which campaign, and which network card.
    """

    def __init__(self, parent, profile):
        self.profile = profile
        super().__init__(parent, "Host on this network")

    def build(self):
        self.heading("Host on this network",
                     "Your machine runs the game and everyone else looks in. "
                     "They need to be on the same network as you - wifi or "
                     "cable, either is fine - and on version %s like you.\n\n"
                     "For people somewhere else, use Connect to a Server "
                     "instead."
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

        # Hardly anybody needs to touch the port, but if something else on
        # this machine has already taken it, hosting simply will not start.
        # The number rides inside the invite code, so nobody joining ever
        # has to be told it changed.
        tk.Label(self.body, text="Port", bg=BG, fg=MUTED,
                 font=("Segoe UI", 9)).pack(anchor="w")
        tk.Label(self.body, text="leave this alone unless something else "
                                 "on this machine is using it",
                 bg=BG, fg="#5f6472", font=("Segoe UI", 8)).pack(anchor="w")
        self.port = self.entry(self.body, width=6)
        self.port.insert(0, str(dice_api.load_config().get(
            "host_port", netplay.DEFAULT_PORT)))
        self.port.pack(anchor="w", ipady=4, pady=(2, 12))

        addresses = netplay.local_addresses()
        self.address = tk.StringVar(value=addresses[0])
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

    def chosen_port(self):
        """What is in the port box, or the usual one if it is not a port."""
        try:
            port = int(self.port.get().strip())
        except ValueError:
            return netplay.DEFAULT_PORT
        return port if 1 <= port <= 65535 else netplay.DEFAULT_PORT

    def _start(self):
        port = self.chosen_port()
        settings = dice_api.load_config()
        settings["host_port"] = port
        dice_api.save_config(settings)
        self.result = {"campaign": self.campaign.get(),
                       "address": self.address.get(),
                       "port": port}
        self.destroy()


# ======================================================================
# joining somebody on this network
# ======================================================================
class JoinDialog(Dialog):
    def __init__(self, parent, profile):
        self.profile = profile
        super().__init__(parent, "Join on this network")

    def build(self):
        self.heading("Join on this network",
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
        self.button(buttons, "Join", self._connect,
                    primary=True).pack(side="right", padx=(0, 8))

    def _connect(self):
        code = self.code.get().strip()
        if not code:
            return
        self.note.configure(text="Looking for the host...", fg=MUTED)
        self.update_idletasks()

        client = netplay.Client(self.profile)
        why = client.connect(code)
        if why is not None:
            said = why[:1].upper() + why[1:]
            # A timeout is the one worth explaining: it means nothing
            # answered at all, which on one network is nearly always the
            # host not being on it.
            if "timed out" in why.lower() or "could not reach" in why.lower():
                said += ("\n\nNothing answered. Check you are both on the "
                         "same network, and that they have started hosting.")
            self.note.configure(text=said, fg=FUMBLE)
            return

        campaign = (client.host or {}).get("campaign") or "Shared Game"
        self.note.configure(text="Joined %s's game."
                                 % (client.host or {}).get("name", "the host"),
                            fg=CRIT)
        self.result = {"client": client, "campaign": campaign}
        self.after(400, self.destroy)


# ======================================================================
# the server list
# ======================================================================
class ServerListDialog(Dialog):
    """Servers somebody has added, and the way onto one.

    The name in the list is theirs, not the server's. A server says what it
    calls itself on connecting, but "Dave's box" is more use to the person
    looking at the list than whatever Dave typed into his settings.
    """

    def __init__(self, parent, profile):
        self.profile = profile
        self.entries = []
        super().__init__(parent, "Connect to a server", width=460)

    def build(self):
        self.heading("Connect to a server",
                     "A server is a machine somebody leaves running - once "
                     "you are on one, everybody else on it is as good as on "
                     "your network. Anyone there can host, and you pick a "
                     "session off a list.")

        holder = tk.Frame(self.body, bg=PANEL)
        holder.pack(fill="both", expand=True, pady=(0, 10))
        self.list = tk.Listbox(holder, bg=PANEL, fg=FG, height=7,
                               selectbackground=ACCENT, selectforeground=BG,
                               highlightthickness=0, bd=0, activestyle="none",
                               font=("Segoe UI", 10))
        self.list.pack(side="left", fill="both", expand=True, padx=6, pady=6)
        bar = tk.Scrollbar(holder, command=self.list.yview)
        bar.pack(side="right", fill="y")
        self.list.configure(yscrollcommand=bar.set)
        self.list.bind("<Double-Button-1>", lambda _e: self._connect())
        self.list.bind("<Return>", lambda _e: self._connect())

        self.note = tk.Label(self.body, text="", bg=BG, fg=MUTED,
                             wraplength=420, justify="left",
                             font=("Segoe UI", 9))
        self.note.pack(anchor="w", pady=(0, 10))

        buttons = tk.Frame(self.body, bg=BG)
        buttons.pack(fill="x")
        self.button(buttons, "Add", self._add, colour=MUTED).pack(side="left")
        self.button(buttons, "Edit", self._edit,
                    colour=MUTED).pack(side="left", padx=(6, 0))
        self.button(buttons, "Remove", self._remove,
                    colour=MUTED).pack(side="left", padx=(6, 0))
        self.button(buttons, "Close", self.destroy,
                    colour=MUTED).pack(side="right")
        self.button(buttons, "Connect", self._connect,
                    primary=True).pack(side="right", padx=(0, 8))

        self._refill()

    # -- the list ----------------------------------------------------------
    def _refill(self, keep=0):
        self.entries = servers.load()
        self.list.delete(0, "end")
        for entry in self.entries:
            self.list.insert("end", "  %s      %s:%d"
                             % (entry["name"], entry["address"],
                                entry["port"]))
        if not self.entries:
            self.note.configure(
                text="No servers yet. Add one with its address - the person "
                     "running it will have read out something like "
                     "12.34.56.78:7777.", fg=MUTED)
            return
        self.note.configure(text="", fg=MUTED)
        self.list.selection_clear(0, "end")
        self.list.selection_set(min(keep, len(self.entries) - 1))
        self.list.activate(min(keep, len(self.entries) - 1))

    def _chosen(self):
        picked = self.list.curselection()
        if not picked:
            return None
        return self.entries[picked[0]]

    # -- keeping it ---------------------------------------------------------
    def _add(self):
        got = ServerDialog(self, None).result
        if got is None:
            return
        servers.add(got["name"], got["address"], got["port"],
                    got["password"])
        self._refill()

    def _edit(self):
        entry = self._chosen()
        if entry is None:
            return
        got = ServerDialog(self, entry).result
        if got is None:
            return
        servers.update(entry["address"], entry["port"], name=got["name"],
                       new_address=got["address"], new_port=got["port"],
                       password=got["password"])
        self._refill(keep=self.list.curselection()[0]
                     if self.list.curselection() else 0)

    def _remove(self):
        entry = self._chosen()
        if entry is None:
            return
        if not messagebox.askyesno("Remove server",
                                   "Take %s off the list?" % entry["name"],
                                   parent=self):
            return
        servers.remove(entry["address"], entry["port"])
        self._refill()

    # -- getting on one -----------------------------------------------------
    def _connect(self):
        entry = self._chosen()
        if entry is None:
            self.note.configure(text="Pick a server first.", fg=FUMBLE)
            return
        self.note.configure(text="Connecting to %s..." % entry["name"],
                            fg=MUTED)
        self.update_idletasks()

        hub = netplay.HubClient(self.profile)
        why = hub.connect(entry["address"], entry["port"],
                          entry.get("password", ""))
        if why is not None:
            self.note.configure(text=why[:1].upper() + why[1:], fg=FUMBLE)
            return
        servers.touch(entry["address"], entry["port"])

        # The lobby is where everything else happens, so this window has
        # done its job. It stays open behind it: closing the lobby without
        # joining anything should land back on the list, not on the menu.
        lobby = LobbyDialog(self, self.profile, hub)
        if lobby.result is None:
            hub.close()
            self._refill()
            return
        self.result = lobby.result
        self.destroy()


class ServerDialog(Dialog):
    """Adding or renaming one server."""

    def __init__(self, parent, saved=None):
        self.saved = saved
        super().__init__(parent, "Edit server" if saved else "Add server",
                         width=400)

    def build(self):
        existing = self.saved or {}
        self.heading("Edit server" if self.saved else "Add server",
                     "The name is yours - call it whatever helps you know "
                     "which one it is.")

        tk.Label(self.body, text="Name", bg=BG, fg=MUTED,
                 font=("Segoe UI", 9)).pack(anchor="w")
        self.name = self.entry_box(existing.get("name", ""))

        tk.Label(self.body, text="Address", bg=BG, fg=MUTED,
                 font=("Segoe UI", 9)).pack(anchor="w", pady=(10, 0))
        tk.Label(self.body, text="a name or a number, and the port after a "
                                 "colon if it is not %d"
                                 % servers.DEFAULT_PORT,
                 bg=BG, fg="#5f6472", font=("Segoe UI", 8)).pack(anchor="w")
        where = existing.get("address", "")
        if where and existing.get("port", servers.DEFAULT_PORT) \
                != servers.DEFAULT_PORT:
            where = "%s:%d" % (where, existing["port"])
        self.address = self.entry_box(where)
        self.address.bind("<Return>", lambda _e: self._save())

        tk.Label(self.body, text="Password", bg=BG, fg=MUTED,
                 font=("Segoe UI", 9)).pack(anchor="w", pady=(10, 0))
        tk.Label(self.body, text="only if the server has one",
                 bg=BG, fg="#5f6472", font=("Segoe UI", 8)).pack(anchor="w")
        self.password = self.entry_box(existing.get("password", ""))

        self.note = tk.Label(self.body, text="", bg=BG, fg=FUMBLE,
                             wraplength=340, justify="left",
                             font=("Segoe UI", 9))
        self.note.pack(anchor="w", pady=(8, 8))

        buttons = tk.Frame(self.body, bg=BG)
        buttons.pack(fill="x")
        self.button(buttons, "Cancel", self.destroy,
                    colour=MUTED).pack(side="right")
        self.button(buttons, "Save", self._save,
                    primary=True).pack(side="right", padx=(0, 8))
        (self.name if not self.saved else self.address).focus_set()

    def entry_box(self, value=""):
        box = self.entry(self.body)
        if value:
            box.insert(0, value)
        box.pack(fill="x", ipady=4, pady=(2, 0))
        return box

    def _save(self):
        address, port = servers.split(self.address.get())
        if not address:
            self.note.configure(text="An address is needed - that is the "
                                     "whole point of the entry.")
            return
        name = self.name.get().strip() or address
        self.result = {"name": name, "address": address, "port": port,
                       "password": self.password.get().strip()}
        self.destroy()


# ======================================================================
# the lobby on a server
# ======================================================================
class LobbyDialog(Dialog):
    """Who is on the server, and what is being played on it.

    Two lists that keep themselves up to date. Nothing here blocks: the
    server's news arrives on its own thread and lands in a queue, and this
    drains it on Tk's clock like everything else in the app.
    """

    REFRESH_MS = 60

    def __init__(self, parent, profile, hub):
        self.profile = profile
        self.hub = hub
        self.sessions = []
        self._alive = True
        super().__init__(parent, hub.name or "Server", width=470)

    def build(self):
        detail = self.hub.motd or ("Connected to %s:%d."
                                   % (self.hub.address, self.hub.port))
        self.heading(self.hub.name or "Server", detail)

        # Who else is here. Small on purpose - it is worth knowing at a
        # glance who turned up, and not worth a panel of its own.
        tk.Label(self.body, text="On this server", bg=BG, fg=MUTED,
                 font=("Segoe UI", 9)).pack(anchor="w")
        self.people = tk.Frame(self.body, bg=BG)
        self.people.pack(fill="x", pady=(2, 12))

        tk.Label(self.body, text="Sessions", bg=BG, fg=MUTED,
                 font=("Segoe UI", 9)).pack(anchor="w")
        holder = tk.Frame(self.body, bg=PANEL)
        holder.pack(fill="both", expand=True, pady=(2, 10))
        self.list = tk.Listbox(holder, bg=PANEL, fg=FG, height=6,
                               selectbackground=ACCENT, selectforeground=BG,
                               highlightthickness=0, bd=0, activestyle="none",
                               font=("Segoe UI", 10))
        self.list.pack(side="left", fill="both", expand=True, padx=6, pady=6)
        bar = tk.Scrollbar(holder, command=self.list.yview)
        bar.pack(side="right", fill="y")
        self.list.configure(yscrollcommand=bar.set)
        self.list.bind("<Double-Button-1>", lambda _e: self._join())

        self.note = tk.Label(self.body, text="", bg=BG, fg=MUTED,
                             wraplength=430, justify="left",
                             font=("Segoe UI", 9))
        self.note.pack(anchor="w", pady=(0, 10))

        buttons = tk.Frame(self.body, bg=BG)
        buttons.pack(fill="x")
        self.button(buttons, "Host a Session", self._host,
                    colour=MUTED).pack(side="left")
        self.button(buttons, "Disconnect", self.destroy,
                    colour=MUTED).pack(side="right")
        self.button(buttons, "Join", self._join,
                    primary=True).pack(side="right", padx=(0, 8))

        self._draw_people(self.hub.people)
        self._draw_sessions(self.hub.sessions)
        self._tick()

    def destroy(self):
        self._alive = False
        super().destroy()

    # -- what the server tells us ------------------------------------------
    def _tick(self):
        if not self._alive:
            return
        while True:
            try:
                message = self.hub.inbox.get_nowait()
            except Exception:
                break
            kind = message.get("kind")
            if kind == "lobby":
                self._draw_people(message.get("people") or [])
                self._draw_sessions(message.get("sessions") or [])
            elif kind == "hub_lost":
                self.note.configure(text=message.get("why", "the server has "
                                                            "gone"),
                                    fg=FUMBLE)
                self._alive = False
                return
        try:
            self.after(self.REFRESH_MS, self._tick)
        except Exception:
            self._alive = False

    def _draw_people(self, people):
        for child in self.people.winfo_children():
            child.destroy()
        if not people:
            tk.Label(self.people, text="nobody yet", bg=BG, fg="#5f6472",
                     font=("Segoe UI", 9)).pack(anchor="w")
            return
        row = tk.Frame(self.people, bg=BG)
        row.pack(anchor="w", fill="x")
        for card in people:
            name = card.get("name") or "Someone"
            mine = card.get("token") == self.profile.token
            chip = tk.Frame(row, bg=PANEL)
            chip.pack(side="left", padx=(0, 5), pady=1)
            tk.Frame(chip, bg=card.get("colour") or ACCENT,
                     width=3).pack(side="left", fill="y")
            tk.Label(chip, text=name + (" (you)" if mine else ""),
                     bg=PANEL, fg=FG if not mine else ACCENT,
                     font=("Segoe UI", 9), padx=6).pack(side="left")

    def _draw_sessions(self, sessions):
        picked = self.list.curselection()
        was = self.sessions[picked[0]]["id"] if picked and picked[0] < len(
            self.sessions) else None
        self.sessions = list(sessions)
        self.list.delete(0, "end")
        for card in self.sessions:
            # What they asked for: whose game it is, and what it is called.
            self.list.insert("end", "  [%s: %s]      %d/%d"
                             % (card.get("host", "Someone"),
                                card.get("campaign", "Shared Game"),
                                card.get("players", 0),
                                card.get("seats", 0)))
        if not self.sessions:
            self.note.configure(text="Nothing is being played yet. Host a "
                                     "session and it appears here for "
                                     "everyone else.", fg=MUTED)
            return
        self.note.configure(text="", fg=MUTED)
        for at, card in enumerate(self.sessions):
            if card["id"] == was:
                self.list.selection_set(at)
                return
        self.list.selection_set(0)

    # -- doing something about it ------------------------------------------
    def _host(self):
        chosen = HostOnServerDialog(self, self.profile).result
        if chosen is None:
            return
        self.note.configure(text="Opening the session...", fg=MUTED)
        self.update_idletasks()
        server, why = self.hub.open_session(chosen["campaign"],
                                            chosen["seats"])
        if why is not None:
            self.note.configure(text=why[:1].upper() + why[1:], fg=FUMBLE)
            return
        dice_api.set_current_save(chosen["campaign"])
        self.result = {"mode": "host", "campaign": chosen["campaign"],
                       "server": server, "hub": self.hub}
        self.destroy()

    def _join(self):
        picked = self.list.curselection()
        if not picked or picked[0] >= len(self.sessions):
            self.note.configure(text="Pick a session first.", fg=FUMBLE)
            return
        card = self.sessions[picked[0]]
        self.note.configure(text="Joining %s's game..."
                                 % card.get("host", "the host"), fg=MUTED)
        self.update_idletasks()
        client, why = self.hub.join_session(card["id"])
        if why is not None:
            self.note.configure(text=why[:1].upper() + why[1:], fg=FUMBLE)
            return
        campaign = (client.host or {}).get("campaign") \
            or card.get("campaign") or "Shared Game"
        self.result = {"mode": "join", "campaign": campaign,
                       "client": client, "hub": self.hub}
        self.destroy()


class HostOnServerDialog(Dialog):
    """Which campaign to open on the server, and how many can sit down."""

    def __init__(self, parent, profile):
        self.profile = profile
        super().__init__(parent, "Host a session", width=380)

    def build(self):
        self.heading("Host a session",
                     "Everyone on the server sees it appear, with your name "
                     "and what the campaign is called. Your machine is still "
                     "the one running the game.")

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

        tk.Label(self.body, text="Seats", bg=BG, fg=MUTED,
                 font=("Segoe UI", 9)).pack(anchor="w")
        tk.Label(self.body, text="how many people can join, not counting you",
                 bg=BG, fg="#5f6472", font=("Segoe UI", 8)).pack(anchor="w")
        self.seats = self.entry(self.body, width=4)
        self.seats.insert(0, str(netplay.MAX_SEATS))
        self.seats.pack(anchor="w", ipady=4, pady=(2, 14))

        buttons = tk.Frame(self.body, bg=BG)
        buttons.pack(fill="x")
        self.button(buttons, "Cancel", self.destroy,
                    colour=MUTED).pack(side="right")
        self.button(buttons, "Open It", self._start,
                    primary=True).pack(side="right", padx=(0, 8))

    def _start(self):
        try:
            seats = int(self.seats.get().strip())
        except ValueError:
            seats = netplay.MAX_SEATS
        self.result = {"campaign": self.campaign.get(),
                       "seats": max(1, min(seats, 16))}
        self.destroy()
