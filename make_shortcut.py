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
APP_LAUNCHER = r"""#!/bin/bash
# Written by make_shortcut.py. Remake it if the app folder moves.
#
# A bundle has no console, so anything printed goes nowhere and a failure
# looks like a window flashing once and vanishing. Everything is therefore
# written to a log, and anything that goes wrong is said out loud in a
# dialog. Silence is the one thing this must never do.

HERE=__FOLDER__
CHOSEN=__PYTHON__
NAME=__NAME__
LOG="$HOME/Library/Logs/Bredmyj VTT.log"

mkdir -p "$HOME/Library/Logs" 2>/dev/null
# Passing the text as arguments rather than building a script out of it:
# quotes and apostrophes in a path would otherwise end the AppleScript early.
say() {
    /usr/bin/osascript \
        -e 'on run argv' \
        -e 'display alert (item 1 of argv) message (item 2 of argv) as critical' \
        -e 'end run' \
        -- "$NAME" "$1" >/dev/null 2>&1
}

if [ ! -d "$HERE" ]; then
    say "The app folder is not where this shortcut expects it:

$HERE

It has been moved, renamed or deleted. Put it back, or make the shortcut
again from where it lives now."
    exit 1
fi
cd "$HERE" || { say "Could not open the app folder: $HERE"; exit 1; }

# The interpreter this was built with, then the usual places, then whatever
# is on PATH. The first one that can draw a window with a Tk new enough to
# be trusted wins.
#
# Tk 8.5 is the one Apple ships with the system python3. It is a decade out
# of date, unsupported on current macOS, and crashes at random - which is
# what "sometimes Python just quits and Reopen does nothing" is. So a Python
# carrying 8.6 is taken over one carrying 8.5 even if the older one was the
# one this shortcut was built with.
PY=""
OLD_TK=""
NO_TK=""
for candidate in "$CHOSEN" /usr/local/bin/python3 /opt/homebrew/bin/python3 \
                 /Library/Frameworks/Python.framework/Versions/Current/bin/python3 \
                 "$(command -v python3 2>/dev/null)"; do
    [ -n "$candidate" ] && [ -x "$candidate" ] || continue
    if "$candidate" -c 'import sys, tkinter; sys.exit(0 if float(tkinter.TkVersion) >= 8.6 else 1)' >/dev/null 2>&1; then
        PY="$candidate"
        break
    fi
    if "$candidate" -c "import tkinter" >/dev/null 2>&1; then
        [ -z "$OLD_TK" ] && OLD_TK="$candidate"
    else
        [ -z "$NO_TK" ] && NO_TK="$candidate"
    fi
done

if [ -z "$PY" ] && [ -n "$OLD_TK" ]; then
    # Better to run than to refuse, but not without saying why it may fall
    # over. Installing Python from python.org makes this go away for good.
    say "The only Python on this Mac uses Tk 8.5, the version Apple ships
with the system. It is long out of date and crashes at random on current
macOS - if the app quits by itself, that is why.

Installing Python from python.org fixes it for good. It brings its own,
newer Tk. Make this shortcut again afterwards.

Carrying on with the old one for now."
    PY="$OLD_TK"
fi
if [ -z "$PY" ] && [ -n "$NO_TK" ]; then
    say "Python is installed, but the copy found here has no Tkinter in it,
which is the part that draws the windows:

$NO_TK

Install Python from python.org - that one includes it - then make this
shortcut again."
    exit 1
fi
if [ -z "$PY" ]; then
    say "Python 3 could not be found on this Mac.

Install it from python.org, then make this shortcut again."
    exit 1
fi

# A log that grows forever is its own problem.
if [ -f "$LOG" ] && [ "$(wc -c <"$LOG" 2>/dev/null || echo 0)" -gt 1000000 ]; then
    rm -f "$LOG"
fi
# Enough to tell, from the log alone, which of the usual macOS problems this
# is - without having to ask for any of it.
{
    echo
    echo "=== $(date) ==="
    echo "folder: $HERE"
    echo "python: $PY"
    "$PY" -c 'import platform, sys, tkinter; print("version:", sys.version.replace(chr(10), " ")); print("tk:", tkinter.TkVersion); print("macos:", platform.mac_ver()[0]); print("arch:", platform.machine())' 2>&1
} >>"$LOG" 2>/dev/null

"$PY" dice_roller.py >>"$LOG" 2>&1
status=$?

if [ "$status" -ne 0 ]; then
    echo "--- stopped with code $status" >>"$LOG" 2>/dev/null
    say "It stopped with an error.

The log is being opened now. Send it along and the fault can be found - it
is the only record there is, because an app started from the Finder has
nowhere to print to.

$LOG"
    /usr/bin/open -e "$LOG" >/dev/null 2>&1
fi
exit "$status"
"""


def shell_quoted(text):
    """Text inside shell single quotes, apostrophes and all.

    The app's own name has an apostrophe in it, and so will a home folder
    belonging to anyone called O'Brien. Closing the quote, escaping the
    apostrophe outside it and opening a new one is how a shell takes it.
    """
    return "'" + str(text).replace("'", "'\\''") + "'"


# The sizes an .iconset is made of: the name macOS wants, and how many
# pixels across it is. Anything bigger than the picture we have is left out
# rather than blown up - a stretched icon is what "faded" looks like.
ICON_SIZES = (
    ("icon_16x16.png", 16), ("icon_16x16@2x.png", 32),
    ("icon_32x32.png", 32), ("icon_32x32@2x.png", 64),
    ("icon_128x128.png", 128), ("icon_128x128@2x.png", 256),
    ("icon_256x256.png", 256), ("icon_256x256@2x.png", 512),
    ("icon_512x512.png", 512), ("icon_512x512@2x.png", 1024),
)


def biggest_icon():
    """The largest picture inside the .ico, as a square RGBA image."""
    from PIL import Image
    image = Image.open(paths.ICON)
    try:
        # An .ico holds several sizes. Pillow opens one of them; ask for the
        # largest by name rather than trusting which one that was.
        sizes = sorted(image.ico.sizes())
        if sizes:
            image = image.ico.getimage(sizes[-1])
    except AttributeError:
        pass
    image = image.convert("RGBA")
    if image.width != image.height:
        side = max(image.size)
        square = Image.new("RGBA", (side, side), (0, 0, 0, 0))
        square.paste(image, ((side - image.width) // 2,
                             (side - image.height) // 2))
        image = square
    return image


def make_icns(resources):
    """Turn the .ico into the .icns a bundle wants, if that can be done.

    Built as an .iconset and handed to iconutil, which is macOS's own tool
    for this and is on every Mac. Each size is made from the full-size
    picture, and any size larger than that picture is skipped - the previous
    attempt scaled a 256-pixel icon up to 1024 and it came out washed out at
    every size, because that blurred copy was then all macOS had to shrink.

    Only cosmetic: without it the app wears the generic blank icon and works
    the same, so every failure here is shrugged off.
    """
    if not os.path.exists(paths.ICON):
        return None
    try:
        from PIL import Image
    except ImportError:
        return None

    out = os.path.join(resources, "app.icns")
    try:
        source = biggest_icon()
    except Exception:
        return None

    iconset = os.path.join(resources, "app.iconset")
    try:
        os.makedirs(iconset, exist_ok=True)
        made = 0
        for name, pixels in ICON_SIZES:
            if pixels > source.width:
                continue            # never upscale; that is the fade
            sized = (source if pixels == source.width
                     else source.resize((pixels, pixels), Image.LANCZOS))
            sized.save(os.path.join(iconset, name), format="PNG")
            made += 1
        if not made:
            raise ValueError("nothing to put in the iconset")
        done = subprocess.run(["iconutil", "-c", "icns", iconset, "-o", out],
                              capture_output=True, timeout=60)
        if done.returncode == 0 and os.path.exists(out):
            return "app.icns"
    except (OSError, ValueError, subprocess.SubprocessError):
        pass                        # not a Mac, or no iconutil - try Pillow
    finally:
        shutil.rmtree(iconset, ignore_errors=True)

    # Pillow can write one directly. Worse than iconutil, but better than a
    # blank icon, and it keeps this testable off a Mac.
    try:
        source.save(out, format="ICNS")
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
            # Token replacement rather than %-formatting: a shell script is
            # full of percent signs that a format string would try to read,
            # and one of them already turned into a crash once. Every value
            # is shell-quoted, because this app's own name has an apostrophe
            # in it and unquoted that ends the string and takes the rest of
            # the script down with it.
            script = APP_LAUNCHER
            for token, value in (("__FOLDER__", paths.APP_DIR),
                                 ("__PYTHON__", sys.executable or "python3"),
                                 ("__NAME__", paths.APP_NAME)):
                script = script.replace(token, shell_quoted(value))
            fh.write(script)
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
