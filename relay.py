"""A meeting point, for playing with people who are not on your network.

This is the middleman. One person runs it - whoever has the most ordinary
home connection - and everybody else, the host included, dials out to it.
Nothing has to dial in to anybody except this one machine, which is the
whole trick: home connections nearly always allow calls out and nearly
never allow calls in.

    python relay.py                 (listens on port 7788)
    python relay.py --port 9000

It sets itself up as far as it can. On starting it will ask the router to
open its port, check the firewall, work out the address to hand round, and
then say in plain words either what to tell everybody or what is still in
the way. Whatever it opens, it closes again on the way out.

Then in the app, host with "People anywhere, through a relay" and put in
the address it prints.

It carries messages and nothing else. It does not read them, keep them, or
know what a campaign is - it only knows which line a message came in on and
which lines it should go out to. Close it and every session on it ends.
"""

import argparse
import json
import socket
import threading
import time

try:
    import netcheck
except Exception:                   # pragma: no cover - a bare machine
    # The relay runs on its own if it has to. Without netcheck it simply
    # cannot set itself up or say what is wrong, so it says that instead.
    netcheck = None

DEFAULT_PORT = 7788
ROOM_TIMEOUT = 8.0          # a host has this long to say who it is
MAX_LINE = 4 * 1024 * 1024  # a whole map, with pictures, and room to spare


def send_line(sock, message):
    try:
        sock.sendall((json.dumps(message) + "\n").encode("utf-8"))
        return True
    except OSError:
        return False


class Line:
    """One connection, read a message at a time."""

    def __init__(self, sock):
        self.sock = sock
        self.buffer = b""

    def read(self):
        """None if it has gone, [] if there is more still coming."""
        try:
            chunk = self.sock.recv(65536)
        except OSError:
            return None
        if not chunk:
            return None
        self.buffer += chunk
        if len(self.buffer) > MAX_LINE:
            return None             # nothing sane is this big
        out = []
        while b"\n" in self.buffer:
            raw, self.buffer = self.buffer.split(b"\n", 1)
            raw = raw.strip()
            if not raw:
                continue
            try:
                out.append(json.loads(raw.decode("utf-8")))
            except (ValueError, UnicodeDecodeError):
                continue
        return out


class Room:
    """One session: a host, and everybody who has dialled in to it."""

    def __init__(self, name, host):
        self.name = name
        self.host = host
        self.guests = {}            # id -> socket
        self.next_id = 1
        self.lock = threading.Lock()
        self.opened = time.time()

    def add(self, sock):
        with self.lock:
            number = self.next_id
            self.next_id += 1
            self.guests[number] = sock
        return number

    def drop(self, number):
        with self.lock:
            return self.guests.pop(number, None)

    def close(self):
        with self.lock:
            guests = list(self.guests.values())
            self.guests.clear()
        for sock in guests:
            _shut(sock)
        _shut(self.host)


class Relay:
    def __init__(self, port=DEFAULT_PORT, quiet=False):
        self.port = port
        self.quiet = quiet
        self.rooms = {}
        self.lock = threading.Lock()
        self.listener = None
        self.running = False

    def say(self, message):
        if not self.quiet:
            print("%s  %s" % (time.strftime("%H:%M:%S"), message))

    # -- lifecycle ---------------------------------------------------------
    def start(self, address=""):
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            # Windows lets two sockets share a port under SO_REUSEADDR, so a
            # second relay would start without complaint and the two would
            # split the arrivals between them - half the table meeting in one
            # and half in the other. Claim the port outright instead, so
            # starting a second one fails here and can say why.
            listener.setsockopt(socket.SOL_SOCKET,
                                socket.SO_EXCLUSIVEADDRUSE, 1)
        else:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((address, self.port))
        listener.listen(64)
        self.port = listener.getsockname()[1]
        self.listener = listener
        self.running = True
        threading.Thread(target=self._accept_loop, daemon=True).start()
        return self.port

    def stop(self):
        self.running = False
        with self.lock:
            rooms = list(self.rooms.values())
            self.rooms.clear()
        for room in rooms:
            room.close()
        if self.listener is not None:
            _shut(self.listener)
            self.listener = None

    def _accept_loop(self):
        while self.running:
            try:
                sock, where = self.listener.accept()
            except OSError:
                break
            threading.Thread(target=self._hello, args=(sock, where),
                             daemon=True).start()

    # -- who is this -------------------------------------------------------
    def _hello(self, sock, where):
        """The first message says whether they are hosting or joining."""
        sock.settimeout(ROOM_TIMEOUT)
        line = Line(sock)
        opening = None
        while opening is None:
            batch = line.read()
            if batch is None:
                _shut(sock)
                return
            for message in batch:
                if message.get("relay") in ("host", "join"):
                    opening = message
                    break

        name = str(opening.get("room") or "").strip()[:64]
        if not name:
            send_line(sock, {"relay": "no", "why": "no room name given"})
            _shut(sock)
            return
        sock.settimeout(None)
        if opening["relay"] == "host":
            self._host(sock, where, name, line)
        else:
            self._join(sock, where, name, line)

    def _host(self, sock, where, name, line):
        with self.lock:
            if name in self.rooms:
                send_line(sock, {"relay": "no",
                                 "why": "a session called %r is already "
                                        "open here" % name})
                _shut(sock)
                return
            room = Room(name, sock)
            self.rooms[name] = room
        send_line(sock, {"relay": "hosting", "room": name})
        self.say("%s is hosting %r" % (where[0], name))
        try:
            self._from_host(room, line)
        finally:
            with self.lock:
                if self.rooms.get(name) is room:
                    del self.rooms[name]
            room.close()
            self.say("%r closed" % name)

    def _join(self, sock, where, name, line):
        with self.lock:
            room = self.rooms.get(name)
        if room is None:
            send_line(sock, {"relay": "no",
                             "why": "no session called %r is open" % name})
            _shut(sock)
            return
        number = room.add(sock)
        send_line(sock, {"relay": "joined", "room": name})
        send_line(room.host, {"relay": "arrived", "peer": number})
        self.say("%s joined %r as %d" % (where[0], name, number))
        try:
            while True:
                batch = line.read()
                if batch is None:
                    break
                for message in batch:
                    # Everything from a guest goes to the host, wrapped so
                    # the host knows which of them it came from.
                    if not send_line(room.host, {"relay": "from",
                                                 "peer": number,
                                                 "body": message}):
                        return
        finally:
            room.drop(number)
            _shut(sock)
            send_line(room.host, {"relay": "gone", "peer": number})
            self.say("%d left %r" % (number, name))

    def _from_host(self, room, line):
        """The host's own line: replies to one guest, or to all of them."""
        while True:
            batch = line.read()
            if batch is None:
                return
            for message in batch:
                body = message.get("body")
                if body is None:
                    continue
                who = message.get("peer")
                if who is None:
                    with room.lock:
                        targets = list(room.guests.values())
                else:
                    with room.lock:
                        one = room.guests.get(who)
                    targets = [one] if one is not None else []
                for sock in targets:
                    send_line(sock, body)


def _shut(sock):
    try:
        sock.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass
    try:
        sock.close()
    except OSError:
        pass


RULE = "-" * 68


def set_up(port, opener=None):
    """Get this machine ready to be dialled into, and say how it went.

    Returns (address, opened, notes): the address to hand round or None if
    there is not one, whether a port was opened on the router - so it can be
    closed again afterwards - and the lines to print.
    """
    opener = opener or netcheck
    if opener is None:
        return None, False, [
            "Could not check anything - netcheck.py is not beside this file.",
            "The relay is still running. If people cannot reach it, the port",
            "will need forwarding on the router by hand."]

    notes = []
    opened = False

    router = opener.find_router()
    if router:
        did, said = opener.forward_port(port, description_url=router)
        opened = did
        notes.append(("Router: " + said) if did
                     else "Router: found one, but " + said)
    else:
        notes.append("Router: none here will open a port by itself.")

    allowed, profile, _rules = opener.firewall_state()
    if allowed is True:
        notes.append("Firewall: this app is allowed in on your %s network."
                     % (profile or "current"))
    elif allowed is False:
        notes.append("Firewall: BLOCKED on your %s network - people will "
                     "time out." % (profile or "current"))
        notes.append("")
        notes.extend("   " + step for step in opener.firewall_steps())
        notes.append("")
    else:
        notes.append("Firewall: could not tell. Allow Python through if "
                     "people cannot get in.")

    address, kept = opener.public_address(port)
    if address:
        notes.append("Address: the internet sees this machine as %s"
                     % address)
    else:
        notes.append("Address: could not find out what the internet sees "
                     "this machine as.")
    return address, opened, notes


def report(address, port, notes, reachable):
    """Everything a person needs, in the order they need it."""
    print(RULE)
    for line in notes:
        print(line)
    print(RULE)
    if address and reachable:
        print()
        print("  TELL EVERYONE TO USE:")
        print()
        print("      %s        port %d" % (address, port))
        print()
        print("  In the app: Host a game -> People anywhere, through a")
        print("  relay -> put that address and port in.")
        print("  Whoever is running the game does that too. This machine")
        print("  only carries the messages.")
    else:
        print()
        print("  NOT READY YET.")
        print()
        print("  Nothing above got a port open to this machine, so people")
        print("  will not be able to reach it. Either forward port %d to"
              % port)
        print("  this computer on the router by hand, or run the relay on")
        print("  somebody else's computer instead - it does not have to be")
        print("  the person running the game.")
    print()
    print("  Leave this window open while you play.")
    print("  Ctrl+C stops it, and every session on it ends.")
    print(RULE)


def main():
    parser = argparse.ArgumentParser(
        description="A meeting point for playing over the internet.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT,
                        help="port to listen on (default %d)" % DEFAULT_PORT)
    parser.add_argument("--quiet", action="store_true",
                        help="do not print what is happening")
    parser.add_argument("--plain", action="store_true",
                        help="skip the setup and just listen")
    chosen = parser.parse_args()

    relay = Relay(chosen.port, quiet=chosen.quiet)
    try:
        port = relay.start()
    except OSError as exc:
        raise SystemExit("Could not listen on port %d: %s"
                         % (chosen.port, exc))
    print()
    print("Relay listening on port %d." % port)

    address, opened, notes = (None, False, [])
    if not chosen.plain:
        print("Setting up - this takes a few seconds...")
        print()
        address, opened, notes = set_up(port)
        # A router that agreed to open the port is the strongest sign
        # anybody can get in; without one there is nothing pointing here.
        report(address, port, notes, reachable=opened)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print()
        print("Stopping.")
    finally:
        if opened and netcheck is not None:
            # Leave the router as it was found.
            netcheck.unforward_port(port)
            print("Closed port %d on the router again." % port)
        relay.stop()


if __name__ == "__main__":
    main()
