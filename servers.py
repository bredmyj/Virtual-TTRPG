"""The list of servers somebody has added, kept between runs.

Deliberately dumb: a name, an address, a port, and whether a password was
saved with it. The name is whatever the person felt like calling it - the
server has a name of its own and says so on connecting, but the one in the
list is theirs. "Dave's box" is more use to them than whatever Dave typed
into his server.json.

Stored beside the app rather than in mods.json, because a server list is
worth being able to hand to somebody else as a file.
"""

import json
import os

import paths

LIST_PATH = os.path.join(paths.APP_DIR, "servers.json")
DEFAULT_PORT = 7777


def load():
    """Every saved server, newest use first."""
    try:
        with open(LIST_PATH, encoding="utf-8") as fh:
            saved = json.load(fh)
    except Exception:
        return []
    if not isinstance(saved, list):
        return []
    out = []
    for entry in saved:
        if not isinstance(entry, dict):
            continue
        address = (entry.get("address") or "").strip()
        if not address:
            continue
        out.append({"name": (entry.get("name") or address).strip()[:40],
                    "address": address,
                    "port": _port(entry.get("port")),
                    "password": entry.get("password") or "",
                    "last": float(entry.get("last") or 0)})
    out.sort(key=lambda e: e["last"], reverse=True)
    return out


def save(entries):
    try:
        with open(LIST_PATH, "w", encoding="utf-8") as fh:
            json.dump(entries, fh, indent=2)
        return True
    except OSError as exc:
        print("[servers] could not write %s: %s" % (LIST_PATH, exc))
        return False


def add(name, address, port=DEFAULT_PORT, password=""):
    """Put one in the list, replacing any entry at the same place.

    Same place means same address and port. Adding a server you already
    have should rename it rather than leaving two rows that do the same
    thing and disagree about what it is called.
    """
    entries = load()
    address = (address or "").strip()
    port = _port(port)
    for entry in entries:
        if entry["address"].lower() == address.lower() \
                and entry["port"] == port:
            entry["name"] = (name or address).strip()[:40]
            entry["password"] = password
            save(entries)
            return entry
    entry = {"name": (name or address).strip()[:40], "address": address,
             "port": port, "password": password, "last": 0.0}
    entries.append(entry)
    save(entries)
    return entry


def update(address, port, name=None, new_address=None, new_port=None,
           password=None):
    """Change a saved entry. Returns it, or None if there is no such one."""
    entries = load()
    for entry in entries:
        if entry["address"].lower() == (address or "").lower() \
                and entry["port"] == _port(port):
            if name is not None:
                entry["name"] = name.strip()[:40] or entry["address"]
            if new_address is not None and new_address.strip():
                entry["address"] = new_address.strip()
            if new_port is not None:
                entry["port"] = _port(new_port)
            if password is not None:
                entry["password"] = password
            save(entries)
            return entry
    return None


def remove(address, port):
    entries = load()
    kept = [e for e in entries
            if not (e["address"].lower() == (address or "").lower()
                    and e["port"] == _port(port))]
    if len(kept) == len(entries):
        return False
    save(kept)
    return True


def touch(address, port):
    """Note that this one was just used, so it sorts to the top next time."""
    import time
    entries = load()
    for entry in entries:
        if entry["address"].lower() == (address or "").lower() \
                and entry["port"] == _port(port):
            entry["last"] = time.time()
            save(entries)
            return True
    return False


def split(text, fallback=DEFAULT_PORT):
    """"host:port" as (host, port). A bare host keeps the usual port.

    Forgiving, because this is typed by hand off something read out loud:
    stray spaces, a trailing colon, or a port that is not a number all come
    back as the address with the usual port rather than as an error.
    """
    text = (text or "").strip()
    if not text:
        return "", fallback
    if text.count(":") == 1:
        host, _, port = text.partition(":")
        host = host.strip()
        try:
            number = int(port.strip())
        except ValueError:
            return host or text, fallback
        if 1 <= number <= 65535:
            return host, number
        return host, fallback
    return text, fallback


def _port(value):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return DEFAULT_PORT
    return number if 1 <= number <= 65535 else DEFAULT_PORT
