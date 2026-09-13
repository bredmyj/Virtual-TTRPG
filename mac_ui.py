"""What macOS has to have drawn differently.

Tk does not draw its own buttons on a Mac. It asks the system to, and the
system draws an Aqua button - so `-background` is ignored and there is no
option that turns that off. In a dark app every button therefore comes out
white, with pale text meant for a dark face sitting nearly invisible on it.
That is the whole of the "the dice buttons are white" problem.

A Label takes the colours it is given on every platform. So on macOS, and
only there, tk.Button is swapped for a Label that behaves like a button. The
main menu has drawn its buttons that way from the start and looks right on a
Mac already; this is the same trick applied to all of them at once, rather
than editing fifty-odd call sites and trusting the next one to remember.

Swapping the class rather than each call site is deliberate. It covers the
core, the mods, the dialogs, and anything a mod written later puts on screen,
which is exactly the code that will not know to ask. Nothing here runs on
Windows, where the real Button is fine and is left alone.

Buttons are not the only widget Aqua draws itself - menubuttons, checkbuttons,
radiobuttons and scrollbars are in the same boat. They are far rarer here, and
are left for now.
"""

import tkinter as tk

import paths

# Options a real Button takes that a Label does not. Dropped rather than
# passed on, so a call site written for Button does not raise on a Mac.
BUTTON_ONLY = ("command", "activebackground", "activeforeground", "default",
               "overrelief", "repeatdelay", "repeatinterval", "offrelief")


class LabelButton(tk.Label):
    """A button that is a label underneath, so its colours are its own."""

    def __init__(self, master=None, cnf=None, **kw):
        self._command = kw.get("command")
        self._hot_bg = kw.get("activebackground")
        self._hot_fg = kw.get("activeforeground")
        self._rest_bg = kw.get("bg", kw.get("background"))
        self._rest_fg = kw.get("fg", kw.get("foreground"))
        self._hovering = False
        for name in BUTTON_ONLY:
            kw.pop(name, None)
        # A Button pads its text and a Label does not, so without this every
        # swapped button would come out tighter than the one it replaced.
        kw.setdefault("padx", 6)
        kw.setdefault("pady", 2)
        kw.setdefault("justify", "center")
        tk.Label.__init__(self, master, cnf or {}, **kw)
        self.bind("<Enter>", self._enter)
        self.bind("<Leave>", self._leave)
        self.bind("<ButtonPress-1>", self._press)
        self.bind("<ButtonRelease-1>", self._release)

    # -- behaving like a button --------------------------------------------
    def _live(self):
        return str(self.cget("state")) != "disabled"

    def _paint(self, background, foreground):
        if background:
            tk.Label.configure(self, bg=background)
        if foreground:
            tk.Label.configure(self, fg=foreground)

    def _enter(self, _event=None):
        self._hovering = True
        if self._live():
            self._paint(self._hot_bg, self._hot_fg)

    def _leave(self, _event=None):
        self._hovering = False
        self._paint(self._rest_bg, self._rest_fg)

    def _press(self, _event=None):
        if self._live():
            self._paint(self._hot_bg, self._hot_fg)

    def _release(self, event=None):
        if not self._live():
            return
        self._leave()
        # Only if the pointer is still on it. Pressing a button and sliding
        # off is how a real one is cancelled, and it should be here too.
        if event is not None:
            if not (0 <= event.x < self.winfo_width()
                    and 0 <= event.y < self.winfo_height()):
                return
        self.invoke()

    def invoke(self):
        if self._live() and self._command is not None:
            return self._command()

    # -- keeping up with whatever the caller changes later -----------------
    def configure(self, cnf=None, **kw):
        if "command" in kw:
            self._command = kw.pop("command")
        if "activebackground" in kw:
            self._hot_bg = kw.pop("activebackground")
        if "activeforeground" in kw:
            self._hot_fg = kw.pop("activeforeground")
        for name in BUTTON_ONLY:
            kw.pop(name, None)
        # A colour set while the pointer is elsewhere is the resting colour.
        # Set while hovering it is not, or moving the mouse away would undo
        # what was just asked for.
        if not self._hovering:
            for name in ("bg", "background"):
                if name in kw:
                    self._rest_bg = kw[name]
            for name in ("fg", "foreground"):
                if name in kw:
                    self._rest_fg = kw[name]
        return tk.Label.configure(self, cnf, **kw)

    config = configure


def install():
    """Put the label-drawn button in tk.Button's place, on a Mac only.

    Called once, before anything builds a window. Returns whether it did
    anything, which is what the tests check.
    """
    if not paths.MAC:
        return False
    if getattr(tk.Button, "_is_label_button", False):
        return True            # already done; installing twice is harmless
    LabelButton._is_label_button = True
    tk.Button = LabelButton
    return True
