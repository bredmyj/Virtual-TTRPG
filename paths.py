"""Where the app lives, and what it calls itself.

Every other module asks here rather than working it out from its own
`__file__`. There are two reasons for that. One, it is the same answer
everywhere, so a saved file cannot end up somewhere different from where it
is looked for. Two, when the app is built into a single program with Python
inside it, `__file__` points into the bundle - a temporary folder that is
thrown away when the app closes - and anything written there would vanish.

So: campaigns, profiles and pictures sit next to the program, wherever the
folder has been put. Move the folder, copy it to another machine, run it off
a memory stick - it all still works, because nothing records an address that
only means something on one computer.
"""

import os
import sys

VERSION = "1.2.1"
APP_NAME = "Bredmyj's VTT"


def _app_dir():
    if getattr(sys, "frozen", False):
        # Built into a program: the folder holding the .exe, not the
        # unpacked-and-deleted bundle that `__file__` would point at.
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


APP_DIR = _app_dir()
FROZEN = bool(getattr(sys, "frozen", False))
ICON = os.path.join(APP_DIR, "app.ico")


def apply_icon(window):
    """Put the app's icon on a window, its taskbar button included.

    Silently does nothing if the icon file is not there - a missing picture
    is not a reason for a window to refuse to open.
    """
    if not os.path.exists(ICON):
        return False
    try:
        # `default` puts it on every window this app opens - the map, the
        # journal and each dialog - rather than only the one asked about.
        window.iconbitmap(default=ICON)
        return True
    except Exception:
        pass
    try:
        window.iconbitmap(ICON)
        return True
    except Exception:
        return False


def inside(path):
    """The path, written down so it survives the folder being moved.

    Anything within the app's own folder is recorded as where it sits
    relative to that folder; anything outside keeps its full address,
    because there is nothing else to hang it on.
    """
    if not path:
        return path
    try:
        full = os.path.abspath(path)
        if os.path.commonpath([full, APP_DIR]) == APP_DIR:
            return os.path.relpath(full, APP_DIR).replace("\\", "/")
    except ValueError:
        pass            # a different drive - there is no relative form
    return path


def resolve(path):
    """Back to a real path. The other half of `inside`."""
    if not path:
        return path
    if os.path.isabs(path):
        return path
    return os.path.normpath(os.path.join(APP_DIR, path))
