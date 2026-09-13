#!/bin/bash
# Bredmyj's VTT - macOS launcher.
#
# Double-click this in Finder. It checks Python is there, checks the bit of
# it that draws windows is there, offers the one optional extra, and starts
# the app. The Windows equivalent is launcher.bat.

cd "$(dirname "$0")" || exit 1

echo
echo "  Bredmyj's VTT"
echo

# ------------------------------------------------------------------
#  Python. macOS has not shipped one since Monterey, so this is the
#  step most people will need.
# ------------------------------------------------------------------
PY=""
for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then
        if "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' 2>/dev/null; then
            PY="$candidate"
            break
        fi
    fi
done

if [ -z "$PY" ]; then
    echo "  Bredmyj's VTT needs Python 3, and this Mac does not have it."
    echo
    echo "    1. Go to  https://www.python.org/downloads/"
    echo "    2. Download Python for macOS and run the installer."
    echo "    3. Finish the install, then double-click this file again."
    echo
    echo "  It is a normal, safe install and takes about two minutes."
    echo
    read -r -p "  Open the download page now? [y/N] " answer
    case "$answer" in
        [Yy]*) open "https://www.python.org/downloads/" ;;
    esac
    echo
    read -r -p "  Press return to close. "
    exit 1
fi

# ------------------------------------------------------------------
#  Tkinter draws the windows. It comes with the python.org installer,
#  but a Python from Homebrew often leaves it out.
# ------------------------------------------------------------------
if ! "$PY" -c "import tkinter" >/dev/null 2>&1; then
    echo "  This copy of Python is missing Tkinter, which draws the windows."
    echo
    echo "  The installer from python.org includes it. If you installed"
    echo "  Python with Homebrew, either run:"
    echo
    echo "      brew install python-tk"
    echo
    echo "  or install Python from python.org instead, then try again."
    echo
    read -r -p "  Press return to close. "
    exit 1
fi

# ------------------------------------------------------------------
#  Pillow is only needed for pictures, so this is an offer, not a
#  demand. Everything else works without it.
# ------------------------------------------------------------------
if ! "$PY" -c "import PIL" >/dev/null 2>&1; then
    echo "  One optional extra is missing: Pillow."
    echo
    echo "  Without it the app still runs - dice, journal, map and playing"
    echo "  with other people all work. What you lose is pictures: profile"
    echo "  photos, character portraits, and the coloured mouse pointer."
    echo
    read -r -p "  Install it now? It takes a few seconds. [y/N] " answer
    case "$answer" in
        [Yy]*)
            echo
            echo "  Installing Pillow..."
            if ! "$PY" -m pip install --upgrade pillow; then
                echo
                echo "  That did not work. The app will still open, just"
                echo "  without pictures. To try again later:"
                echo "      $PY -m pip install pillow"
                echo
                read -r -p "  Press return to carry on. "
            fi
            ;;
    esac
fi

echo "  Starting..."
exec "$PY" dice_roller.py
