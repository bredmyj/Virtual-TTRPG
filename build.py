"""Build a copy that runs without Python installed.

    python build.py

Puts a ready-to-send folder in `dist/`. Whoever you send it to unzips it
and double-clicks the program - no Python, no Pillow, no install, no
administrator rights.

Python itself is packed inside the program, which is why the folder is
larger than the source. Everything that a person is meant to be able to
open and change - the mods, and later their own campaigns - stays as real
files beside it rather than being sealed in.
"""

import os
import shutil
import subprocess
import sys

import paths

HERE = paths.APP_DIR
DIST = os.path.join(HERE, "dist")
WORK = os.path.join(HERE, "build")
NAME = "Bredmyj's VTT"

# Mods are loaded by hand at run time, so nothing that scans the source can
# see what they need. Everything they import is listed here instead.
HIDDEN = [
    "tkinter", "tkinter.font", "tkinter.filedialog", "tkinter.colorchooser",
    "tkinter.messagebox", "tkinter.simpledialog", "tkinter.ttk",
    "PIL", "PIL.Image", "PIL.ImageDraw", "PIL.ImageTk",
    "copy", "json", "math", "random", "shutil", "time",
    "crop", "avatar", "netplay", "paths", "pointer", "roster_bar",
    "session", "main_menu", "core_panels", "dice_api",
]

# Copied beside the program rather than packed inside it, so they can be
# opened, edited and added to.
ALONGSIDE = ["plugins"]

# Loose files that go with it: the icon is read at run time as well as being
# stamped into the program, so the windows can wear it too.
BESIDE = ["app.ico", "server.py", "servers.py", "paths.py", "Run Server.bat"]

ICON = os.path.join(paths.APP_DIR, "app.ico")

SKIP = (".bak", ".pyc", ".pyo")
SKIP_DIRS = {"__pycache__"}


def keep(name):
    return not name.endswith(SKIP) and ".py.bak" not in name


def loose_copy(source, target):
    """Copy a folder, leaving out the clutter."""
    shutil.copytree(source, target, dirs_exist_ok=True,
                    ignore=lambda _d, names: [n for n in names
                                              if n in SKIP_DIRS or not keep(n)])


def folder_size(path):
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            total += os.path.getsize(os.path.join(root, name))
    return total


def main():
    try:
        import PyInstaller                      # noqa: F401
    except ImportError:
        sys.exit("PyInstaller is needed to build:\n"
                 "    python -m pip install pyinstaller")

    for old in (DIST, WORK):
        if not os.path.exists(old):
            continue
        try:
            shutil.rmtree(old)
        except PermissionError:
            # Almost always the last build still being open - Windows will
            # not let a running program be deleted out from under itself.
            sys.exit("Cannot clear %s.%sClose %s if it is still running, "
                     "then try again." % (old, os.linesep + os.linesep, NAME))

    command = [sys.executable, "-m", "PyInstaller",
               "--noconfirm", "--clean",
               "--name", NAME,
               "--windowed",            # no black console behind the window
               "--distpath", DIST,
               "--workpath", WORK,
               "--specpath", WORK,
               os.path.join(HERE, "dice_roller.py")]
    if os.path.exists(ICON):
        command += ["--icon", ICON]
    else:
        print("  no app.ico - run make_icon.py first for a proper icon")
    for module in HIDDEN:
        command += ["--hidden-import", module]

    print("Building %s %s ..." % (NAME, paths.VERSION))
    if subprocess.call(command, cwd=HERE) != 0:
        sys.exit("the build failed - see the messages above")

    out = os.path.join(DIST, NAME)
    for folder in ALONGSIDE:
        source = os.path.join(HERE, folder)
        if os.path.isdir(source):
            loose_copy(source, os.path.join(out, folder))
            print("  copied %s beside the program" % folder)

    for name in BESIDE:
        source = os.path.join(HERE, name)
        if os.path.exists(source):
            shutil.copy2(source, os.path.join(out, name))

    readme = os.path.join(out, "READ ME FIRST.txt")
    with open(readme, "w", encoding="utf-8") as fh:
        fh.write(HANDOUT % {"name": NAME, "version": paths.VERSION})

    shutil.rmtree(WORK, ignore_errors=True)
    size = folder_size(out) / (1024.0 * 1024.0)
    print()
    print("Done. %.0f MB in %s" % (size, out))
    print("Zip that folder and send it. Nothing needs installing at the")
    print("other end - they unzip it and double-click %s.exe." % NAME)


HANDOUT = """%(name)s  -  version %(version)s

To play
-------
Double-click "%(name)s.exe".

That is all. Nothing needs installing - Python and everything else the
app needs is already inside this folder.

Keep the folder together
------------------------
The program, the _internal folder and the plugins folder all belong
together. Move or copy the whole folder, not just the program.

Your campaigns, your profile and your pictures are saved inside this
folder as well, so you can put it on a memory stick or move it to
another PC and everything comes with it.

Playing with other people
-------------------------
On the same network - the same house wifi, or plugged into the same
router - one person hosts with "Host on This Network" and reads out the
invite code; everyone else picks "Join on This Network" and types it in.

To play with people somewhere else, somebody runs server.py on a machine
the internet can reach and forwards its port once. Everyone else picks
"Connect to a Server", adds that address to their list under whatever
name they like, and from then on it is two clicks: connect, then host a
session or join one off the list. Running the server needs Python on
that machine, not on yours.

Everyone must be on the same version of the app - version %(version)s
here. The version is shown on the main menu. If two people have
different versions, the host will say so instead of letting them in
and having the map go wrong later.

The first time you host, Windows will ask whether to allow it through
the firewall. Say yes, and make sure "Private networks" is ticked.
"""


if __name__ == "__main__":
    main()
