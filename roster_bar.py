"""The row of faces: who is at the table right now.

Small enough to leave alone and glance at, big enough to count heads without
squinting. The host right-clicks a face to say what somebody is.

The same strip goes on the main window and on the game map, so wherever you
are looking you can see who else is here.
"""

import tkinter as tk

import avatar
import netplay
from dice_api import THEME

BG = THEME["bg"]
PANEL = THEME["panel"]
FG = THEME["fg"]
MUTED = THEME["muted"]
ACCENT = THEME["accent"]
CRIT = THEME["crit"]
FUMBLE = THEME["fumble"]

FACE = 34               # the circle itself
CHIP = 52               # how much room each person gets
HEIGHT = 58
ANNOUNCE_MS = 6000      # how long "so-and-so joined" stays up


class RosterBar(tk.Frame):
    def __init__(self, parent, session, show_code=True):
        super().__init__(parent, bg=PANEL, highlightthickness=0)
        self.session = session
        self.show_code = show_code
        self.keep = []              # Tk drops images nothing holds on to
        self.spots = []             # (x0, x1, card) for hit testing
        self.note = None            # the announcement showing now
        self._note_after = None

        self.canvas = tk.Canvas(self, height=HEIGHT, bg=PANEL,
                                highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Button-3>", self._menu)
        self.canvas.bind("<Button-1>", self._click)
        self.canvas.bind("<Motion>", self._hover)
        self.canvas.bind("<Leave>", lambda _e: self._hover(None))
        self.canvas.bind("<Configure>", lambda _e: self.redraw())

        session.on("roster", lambda _m: self.redraw())
        session.on("announce", self._announce)
        self.hover_token = None
        self.redraw()

    # ------------------------------------------------------------------
    # drawing
    # ------------------------------------------------------------------
    def redraw(self):
        if not self.winfo_exists():
            return
        self.canvas.delete("all")
        self.keep.clear()
        self.spots = []

        people = self.session.people()
        x = 8
        for card in people:
            self._draw_person(x, card)
            self.spots.append((x, x + CHIP, card))
            x += CHIP

        width = max(self.canvas.winfo_width(), 1)
        right = width - 8

        if self.note:
            text, colour = self.note
            self.canvas.create_text(
                right, HEIGHT / 2 - 8, text=text, anchor="e",
                fill={"crit": CRIT, "fumble": FUMBLE}.get(colour, FG),
                font=("Segoe UI", 9, "bold"))
            right -= 6

        if self.show_code and self.session.code:
            self.canvas.create_text(
                width - 8, HEIGHT / 2 + 10 if self.note else HEIGHT / 2,
                text="invite code  %s" % self.session.code, anchor="e",
                fill=MUTED, font=("Consolas", 9), tags="code")
            self.canvas.tag_bind("code", "<Button-1>",
                                 lambda _e: self._copy_code())
        elif not self.session.is_solo and not self.session.is_host:
            host = people[0].get("name", "the host") if people else "the host"
            self.canvas.create_text(width - 8, HEIGHT / 2,
                                    text="in %s's game" % host, anchor="e",
                                    fill=MUTED, font=("Segoe UI", 9))

    def _draw_person(self, x, card):
        token = card.get("token")
        colour = card.get("colour") or ACCENT
        top = 4

        if token == self.hover_token:
            self.canvas.create_rectangle(x, 1, x + CHIP, HEIGHT - 1,
                                         fill="#2c303a", outline="")

        photo = avatar.draw_face(self.canvas, x + (CHIP - FACE) / 2, top,
                                 FACE, card.get("name", "?"), colour,
                                 card.get("picture"))
        if photo is not None:
            self.keep.append(photo)

        role = card.get("role")
        if role:
            # "GM" or "P3" in the corner of the circle - short, because there
            # is no room for anything longer.
            tag = "GM" if role == "GM" else "P" + role.split()[-1]
            bx = x + CHIP / 2 + FACE / 2 - 9
            by = top + FACE - 11
            self.canvas.create_oval(bx, by, bx + 17, by + 12, fill=BG,
                                    outline=colour)
            self.canvas.create_text(bx + 8.5, by + 6, text=tag, fill=colour,
                                    font=("Segoe UI", 6, "bold"))

        name = card.get("name", "?")
        if len(name) > 9:
            name = name[:8] + "…"
        self.canvas.create_text(
            x + CHIP / 2, HEIGHT - 10, text=name,
            fill=FG if card.get("token") == self.session.my_token else MUTED,
            font=("Segoe UI", 8, "bold" if card.get("host") else "normal"))

    # ------------------------------------------------------------------
    # what it reacts to
    # ------------------------------------------------------------------
    def _card_at(self, x):
        for x0, x1, card in self.spots:
            if x0 <= x <= x1:
                return card
        return None

    def _hover(self, event):
        token = None if event is None else (self._card_at(event.x) or {}).get(
            "token")
        if token != self.hover_token:
            self.hover_token = token
            self.redraw()

    def _click(self, event):
        card = self._card_at(event.x)
        if card is None:
            return
        who = card.get("name", "Someone")
        role = card.get("role")
        self._show("%s%s" % (who, " - " + role if role else ""), None)

    def _menu(self, event):
        """The host says who is what; everyone else just sees the faces."""
        card = self._card_at(event.x)
        if card is None or not self.session.is_host:
            return
        menu = tk.Menu(self.canvas, tearoff=0, bg=PANEL, fg=FG,
                       activebackground=ACCENT, activeforeground=BG, bd=0,
                       font=("Segoe UI", 9))
        token = card.get("token")
        menu.add_command(label=card.get("name", "Someone"), state="disabled")
        menu.add_separator()

        taken = {c.get("role") for c in self.session.people()
                 if c.get("token") != token and c.get("role")}
        for role in netplay.ROLES:
            label = role
            if role == card.get("role"):
                label = "• " + role
            elif role in taken:
                label = role + "   (taken)"
            menu.add_command(label=label,
                             command=lambda r=role: self.session.set_role(
                                 token, r))
        if card.get("role"):
            menu.add_command(label="No role",
                             command=lambda: self.session.set_role(token, None))
        if not card.get("host"):
            menu.add_separator()
            menu.add_command(label="Remove from session",
                             command=lambda: self.session.remove(token))
        menu.tk_popup(event.x_root, event.y_root)

    def _copy_code(self):
        try:
            self.clipboard_clear()
            self.clipboard_append(self.session.code)
            self._show("Invite code copied.", "crit")
        except tk.TclError:
            pass

    def _announce(self, message):
        self._show(message.get("text", ""), message.get("colour"))

    def _show(self, text, colour):
        self.note = (text, colour)
        if self._note_after is not None:
            try:
                self.after_cancel(self._note_after)
            except Exception:
                pass
        self._note_after = self.after(ANNOUNCE_MS, self._clear_note)
        self.redraw()

    def _clear_note(self):
        self._note_after = None
        self.note = None
        if self.winfo_exists():
            self.redraw()
