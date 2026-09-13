#!/bin/bash
# Bredmyj's VTT - run the multiplayer server on a Mac.
#
# Double-click this in Finder. It prints the addresses to hand round and
# keeps running until you close the window. The Windows equivalent is
# "Run Server.bat".

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
    echo "  The server needs Python 3, and this Mac does not have it."
    echo "  Get it from  https://www.python.org/downloads/"
    echo
    read -r -p "  Press return to close. "
    exit 1
fi

"$PY" server.py
echo
read -r -p "  The server has stopped. Press return to close. "
