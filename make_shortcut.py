"""Make the double-click icon.

    python make_shortcut.py              in the app folder
    python3 make_shortcut.py --desktop   and on the desktop too

On Windows a batch file cannot carry an icon, so the thing you actually click
is a shortcut pointing at it. That gives the app one launcher symbol like any
other program, instead of a page-with-a-gear.

On a Mac it builds a real .app bundle. That matters for more than looks:
Finder always opens a .app through the system, so unlike a .command file it
cannot be claimed by whatever editor happens to be installed, it needs no
permission bit setting by hand, and it leaves no Terminal window behind. Once
it exists the app is a normal double-click and Terminal is never needed
again.

Either one records where the app folder is, so both have to be remade if that
folder moves. Running this again is all that takes.
"""

import os
import plistlib
import shutil
import stat
import subprocess
import sys

import paths

LAUNCHER = os.path.join(paths.APP_DIR, "launcher.bat")
PROGRAM = os.path.join(paths.APP_DIR, "%s.exe" % paths.APP_NAME)
SHORTCUT = "%s.lnk" % paths.APP_NAME

# Windows has no way to write a shortcut from a plain file - it is a small
# structured thing only the shell knows how to build. PowerShell can ask the
# shell to do it, and PowerShell is on every Windows machine.
MAKE = """
$link = (New-Object -ComObject WScript.Shell).CreateShortcut('%(where)s')
$link.TargetPath       = '%(target)s'
$link.WorkingDirectory = '%(folder)s'
$link.IconLocation     = '%(icon)s'
$link.Description      = '%(name)s %(version)s'
$link.WindowStyle      = %(style)d
$link.Save()
"""


def quoted(text):
    """Text inside PowerShell single quotes.

    The app's own name has an apostrophe in it, which would otherwise end
    the string halfway through and leave PowerShell reading the rest as
    code. Doubling it is how PowerShell escapes one.
    """
    return str(text).replace("'", "''")


def target():
    """What the shortcut should run.

    The built program if this is a built copy, otherwise the launcher that
    checks Python is there first.
    """
    if os.path.exists(PROGRAM):
        return PROGRAM, 1           # a normal window
    # 7 is minimised: the launcher only opens a console to say something is
    # missing, and there is no reason to flash an empty black box otherwise.
    return LAUNCHER, 7


def make(folder):
    """The double-click thing for this machine, in `folder`."""
    if paths.MAC:
        return make_app(folder)
    return make_lnk(folder)


# --------------------------------------------------------------------------
# macOS: a .app bundle, which is a folder the system knows how to launch
# --------------------------------------------------------------------------
# What is inside one, and why each part is there:
#
#   Contents/Info.plist     what the app is called and which file to run
#   Contents/MacOS/launcher the shell script that starts the Python
#   Contents/Resources      the icon, if one could be made
#
# The launcher has the app folder and the interpreter written into it, rather
# than working them out, because a .app is opened by the system with no shell
# set up and none of the PATH a Terminal would have had.
APP_LAUNCHER = """#!/bin/bash
# Written by make_shortcut.py. Remake it if the app folder moves.
HERE=%(folder)s
PY=%(python)s

if [ ! -x "$PY" ]; then
    PY="$(command -v python3 || true)"
fi
if [ -z "$PY" ] || [ ! -x "$PY" ]; then
    osascript -e 'display alert "%(name)s" message "Python 3 is not installed, or has been moved. Install it from python.org and make this shortcut again."'
    exit 1
fi
if ! "$PY" -c "import tkinter" >/dev/null 2>&1; then
    osascript -e 'display alert "%(name)s" message "This copy of Python is missing Tkinter, which draws the windows. Install Python from python.org and make this shortcut again."'
    exit 1
fi
cd "$HERE" || exit 1
exec "$PY" dice_roller.py
"""


def shell_quoted(text):
    """Text inside shell single quotes, apostrophes and all.

    The app's own name has an apostrophe in it, and so will a home folder
    belonging to anyone called O'Brien. Closing the quote, escaping the
    apostrophe outside it and opening a new one is how a shell takes it.
    """
    return "'" + str(text).replace("'", "'\\''") + "'"


def make_icns(resources):
    """Turn the .ico into the .icns a bundle wants, if that can be done.

    Only cosmetic - without it the app wears the generic blank icon and
    everything else still works - so every failure here is shrugged off.
    """
    if not os.path.exists(paths.ICON):
        return None
    try:
        from PIL import Image
    except ImportError:
        return None
    try:
        image = Image.open(paths.ICON)
        image = image.convert("RGBA")
        side = max(image.size)
        square = Image.new("RGBA", (side, side), (0, 0, 0, 0))
        square.paste(image, ((side - image.width) // 2,
                             (side - image.height) // 2))
        # ICNS wants a big one to scale down from.
        square = square.resize((1024, 1024), Image.LANCZOS)
        out = os.path.join(resources, "app.icns")
        square.save(out, format="ICNS")
        return "app.icns"
    except Exception:
        return None


def make_app(folder):
    bundle = os.path.join(folder, "%s.app" % paths.APP_NAME)
    contents = os.path.join(bundle, "Contents")
    macos = os.path.join(contents, "MacOS")
    resources = os.path.join(contents, "Resources")
    try:
        if os.path.exists(bundle):
            shutil.rmtree(bundle)
        os.makedirs(macos)
        os.makedirs(resources)

        icon = make_icns(resources)
        info = {
            "CFBundleName": paths.APP_NAME,
            "CFBundleDisplayName": paths.APP_NAME,
            "CFBundleExecutable": "launcher",
            "CFBundleIdentifier": "com.bredmyj.vtt",
            "CFBundlePackageType": "APPL",
            "CFBundleShortVersionString": paths.VERSION,
            "CFBundleVersion": paths.VERSION,
            "NSHighResolutionCapable": True,
        }
        if icon:
            info["CFBundleIconFile"] = icon
        with open(os.path.join(contents, "Info.plist"), "wb") as fh:
            plistlib.dump(info, fh)

        run = os.path.join(macos, "launcher")
        # Unix line endings whatever machine wrote it: a shell script with
        # carriage returns in it does not run.
        with open(run, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(APP_LAUNCHER % {
                "folder": shell_quoted(paths.APP_DIR),
                "python": shell_quoted(sys.executable or "python3"),
                "name": paths.APP_NAME.replace('"', ""),
            })
        # The bit that makes it runnable. Set here rather than hoped for,
        # which is the whole reason this beats unzipping a .command file.
        os.chmod(run, os.stat(run).st_mode | stat.S_IXUSR | stat.S_IXGRP
                 | stat.S_IXOTH)
    except OSError as exc:
        return None, str(exc)
    return bundle, None


# --------------------------------------------------------------------------
# Windows: a .lnk, which only the shell knows how to write
# --------------------------------------------------------------------------
def make_lnk(folder):
    run, style = target()
    if not os.path.exists(run):
        return None, "there is nothing to launch - %s is missing" % run
    icon = paths.ICON if os.path.exists(paths.ICON) else run
    where = os.path.join(folder, SHORTCUT)
    script = MAKE % {"where": quoted(where), "target": quoted(run),
                     "folder": quoted(paths.APP_DIR), "icon": quoted(icon),
                     "name": quoted(paths.APP_NAME),
                     "version": quoted(paths.VERSION), "style": style}
    try:
        done = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:
        return None, str(exc)
    if done.returncode != 0 or not os.path.exists(where):
        return None, (done.stderr or "the shortcut was not created").strip()
    return where, None


def main():
    made, why = make(paths.APP_DIR)
    if made is None:
        sys.exit("Could not make the shortcut: %s" % why)
    print("Made %s" % made)
    if not paths.MAC:
        run, _style = target()
        print("  it runs %s" % os.path.basename(run))

    if "--desktop" in sys.argv:
        desktop = os.path.join(os.path.expanduser("~"), "Desktop")
        if os.path.isdir(desktop):
            also, why = make(desktop)
            print("Made %s" % (also or "nothing on the desktop: %s" % why))
        else:
            print("No Desktop folder found, so nothing was put there.")

    print()
    print("Double-click it to play. If you ever move this folder, run this")
    print("again - it remembers where the app folder was.")
    if paths.MAC:
        print()
        print("The first open may ask whether you are sure, because it was")
        print("not downloaded from the App Store. Control-click it and pick")
        print("Open, and it will not ask again.")


if __name__ == "__main__":
    main()
