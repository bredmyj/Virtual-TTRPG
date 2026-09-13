#!/bin/bash
# Bredmyj's VTT - put the app on the desktop, on a Mac.
#
# Builds a real .app bundle you can double-click like any other program, so
# Terminal is never needed again. Run this again if you ever move the app
# folder. The Windows equivalent is "Create Shortcut.bat".
#
# If double-clicking this file opens it in a text editor instead of running
# it, that is the editor claiming shell scripts - run this instead, in
# Terminal, in this folder:
#
#     python3 make_shortcut.py --desktop

cd "$(dirname "$0")" || exit 1

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
    echo
    echo "  This needs Python 3, and this Mac does not have it."
    echo "  Get it from  https://www.python.org/downloads/"
    echo
    read -r -p "  Press return to close. "
    exit 1
fi

echo
read -r -p "  Put it on the desktop too? [Y/n] " answer
case "$answer" in
    [Nn]*) "$PY" make_shortcut.py ;;
    *)     "$PY" make_shortcut.py --desktop ;;
esac

echo
read -r -p "  Press return to close. "
