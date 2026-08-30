"""Make the double-click icon.

    python make_shortcut.py              in the app folder
    python make_shortcut.py --desktop    and on the desktop too

A batch file cannot carry an icon, so the thing you actually click is a
Windows shortcut pointing at it. That gives the app one launcher symbol like
any other program, instead of a page-with-a-gear.

A shortcut records where its target is, so it has to be remade if the folder
moves. Running this again is all that takes - and "Create Shortcut.bat" is
there so it can be done by double-clicking, without a command prompt.
"""

import os
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
    run, _style = target()
    print("Made %s" % made)
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
    print("again - a shortcut remembers where its target was.")


if __name__ == "__main__":
    main()
