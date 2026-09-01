"""A server everybody dials into, so a table can be spread across houses.

One person runs this - whoever is willing to forward a port once - and
everyone else adds its address to their server list. From then on the people
on it behave as though they share a network: anybody can open a session,
everybody can see the sessions that are open, and joining one is picking it
off a list.

    python server.py                    (listens on port 7777)
    python server.py --port 9000
    python server.py --name "Tuesday Game"

What it is, and is not:

  * It is a switchboard with a memory. It carries messages between a host
    and the people who joined that host, and it keeps the last map each
    session sent so somebody arriving late is caught up without having to
    wait on the GM's machine to answer.
  * It is not the authority on the game. It holds no campaign, no rules and
    no save files. The GM's app is still the one that decides what is true.
    Close a session and it is gone; close the server and every session on
    it ends.

Its name, port and password live in server.json beside this file, written on
first run. So does its identity, which matters more than it sounds: a saved
entry in somebody's server list has to still work next week, so the server
keeps who it is across restarts rather than becoming a stranger every time
it starts up.
"""

import argparse
import base64
import json
import os
import socket
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import paths

VERSION = paths.VERSION
DEFAULT_PORT = 7777
CONFIG_PATH = os.path.join(HERE, "server.json")
HELLO_TIMEOUT = 10.0        # how long somebody has to say who they are
MAX_LINE = 4 * 1024 * 1024  # a whole map, with pictures, and room to spare
MAX_PEOPLE = 32             # on the server at once, across every session
MAX_SESSIONS = 8
RULE = "-" * 68


# ==========================================================================
# the wire
# ==========================================================================
def send_line(sock, message):
    """One JSON object and a newline. False if the line has gone."""
    try:
        sock.sendall((json.dumps(message) + "\n").encode("utf-8"))
        return True
    except OSError:
        return False


class Line:
    """Reads whole lines off a socket, however the bytes arrive.

    A map with pictures in it is far bigger than one packet, so a read can
    stop anywhere - halfway through a word, halfway through a number. The
    leftovers stay here until the rest of the line turns up.
    """

    def __init__(self, sock):
        self.sock = sock
        self.rest = b""

    def read(self):
        """The next batch of messages, or None once the line is closed."""
        try:
            chunk = self.sock.recv(65536)
        except OSError:
            return None
        if not chunk:
            return None
        self.rest += chunk
        if len(self.rest) > MAX_LINE:
            return None             # nothing honest is this big
        out = []
        while b"\n" in self.rest:
            raw, self.rest = self.rest.split(b"\n", 1)
            raw = raw.strip()
            if not raw:
                continue
            try:
                out.append(json.loads(raw.decode("utf-8")))
            except Exception:
                continue            # one bad line is not worth a disconnect
        return out


def _shut(sock):
    """Close a socket without caring how far gone it already is."""
    try:
        sock.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass
    try:
        sock.close()
    except OSError:
        pass


# ==========================================================================
# settings that outlive a restart
# ==========================================================================
def load_settings():
    """What this server calls itself, written down so it stays that way.

    Somebody's saved list entry points at an address and expects the same
    server to be there tomorrow. Rolling a new identity on every start would
    quietly break every entry, so it is made once and kept.
    """
    settings = {}
    try:
        with open(CONFIG_PATH, encoding="utf-8") as fh:
            settings = json.load(fh)
    except Exception:
        settings = {}
    changed = False
    if not settings.get("id"):
        settings["id"] = base64.b32encode(os.urandom(5)).decode().rstrip("=")
        changed = True
    settings.setdefault("name", "%s server" % paths.APP_NAME)
    settings.setdefault("motd", "")
    settings.setdefault("port", DEFAULT_PORT)
    settings.setdefault("password", "")
    settings.setdefault("max_people", MAX_PEOPLE)
    if changed or not os.path.exists(CONFIG_PATH):
        save_settings(settings)
    return settings


def save_settings(settings):
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
            json.dump(settings, fh, indent=2)
        return True
    except OSError as exc:
        print("[server] could not write %s: %s" % (CONFIG_PATH, exc))
        return False


# ==========================================================================
# the people on it
# ==========================================================================
class Guest:
    """One connection, and whatever it is doing at the moment.

    Everybody starts in the lobby. From there they either open a session of
    their own or join somebody else's, and `session` says which - along with
    `number`, the handle their host knows them by.
    """

    def __init__(self, sock, where):
        self.sock = sock
        self.where = where
        self.token = None
        self.name = "..."
        self.colour = "#c8a24a"
        self.face = None
        self.version = "unknown"
        self.session = None         # the Session they are in, if any
        self.number = None          # their handle within that session
        self.hosting = False
        self.at = time.time()
        self.gone = False
        self._lock = threading.Lock()

    def send(self, message):
        if self.gone:
            return False
        with self._lock:            # two threads can both have news for them
            return send_line(self.sock, message)

    def close(self):
        self.gone = True
        _shut(self.sock)

    def card(self):
        return {"token": self.token, "name": self.name,
                "colour": self.colour, "version": self.version}


class Session:
    """One game in progress: a host, the people who joined, and the last map.

    The map is the only thing kept. It is a whole snapshot - the app sends
    it as one object with a revision number on it - so holding the newest
    one is enough to catch anybody up, and handing over a stale one is
    harmless because the app ignores a revision older than the one it has.
    """

    def __init__(self, ident, host, campaign, seats):
        self.id = ident
        self.host = host            # a Guest
        self.campaign = campaign or "Shared Game"
        self.seats = seats
        self.people = {}            # number -> Guest
        self.map = None             # the newest {"kind": "map", ...} seen
        self.map_rev = -1
        self.started = time.time()
        self.next_number = 1
        self._lock = threading.RLock()

    def card(self):
        """What the lobby shows: [Person's Name: Campaign Name]."""
        return {"id": self.id, "host": self.host.name,
                "host_token": self.host.token, "campaign": self.campaign,
                "players": len(self.people), "seats": self.seats,
                "version": self.host.version,
                "started": int(self.started)}

    def seat(self, guest):
        """Give somebody a handle in this session, or None if it is full."""
        with self._lock:
            if len(self.people) >= self.seats:
                return None
            number = self.next_number
            self.next_number += 1
            self.people[number] = guest
        return number

    def leave(self, number):
        with self._lock:
            return self.people.pop(number, None)

    def remember(self, body):
        """Keep the newest map, so a latecomer does not have to wait on one."""
        if body.get("kind") != "map" or not body.get("world"):
            return
        rev = body.get("rev", 0)
        if rev >= self.map_rev:
            self.map_rev = rev
            self.map = body

    def close(self, why="the host closed the session"):
        with self._lock:
            people = list(self.people.values())
            self.people.clear()
        for guest in people:
            guest.send({"hub": "ended", "why": why})
            guest.session = None
            guest.number = None


# ==========================================================================
# the server
# ==========================================================================
class Hub:
    """Everything the server knows: who is on it and what they are playing."""

    def __init__(self, settings=None, quiet=False):
        self.settings = settings or load_settings()
        self.port = int(self.settings.get("port") or DEFAULT_PORT)
        self.name = self.settings.get("name") or "%s server" % paths.APP_NAME
        self.motd = self.settings.get("motd") or ""
        self.password = self.settings.get("password") or ""
        self.max_people = int(self.settings.get("max_people") or MAX_PEOPLE)
        self.quiet = quiet
        self.guests = {}            # token -> Guest
        self.sessions = {}          # id -> Session
        self._lock = threading.RLock()
        self._listener = None
        self._running = False

    def say(self, message):
        if not self.quiet:
            print("[%s] %s" % (time.strftime("%H:%M:%S"), message))

    # -- lifecycle ---------------------------------------------------------
    def start(self, address=""):
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            # Windows will otherwise let a second copy share the port and
            # split the arrivals between them, which looks like people
            # randomly not seeing each other. Claim it outright instead.
            listener.setsockopt(socket.SOL_SOCKET,
                                socket.SO_EXCLUSIVEADDRUSE, 1)
        else:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((address, self.port))
        listener.listen(16)
        self.port = listener.getsockname()[1]
        self._listener = listener
        self._running = True
        threading.Thread(target=self._accept_loop, daemon=True).start()
        return self.port

    def stop(self):
        self._running = False
        with self._lock:
            guests = list(self.guests.values())
            self.guests.clear()
            self.sessions.clear()
        for guest in guests:
            guest.send({"hub": "ended", "why": "the server is shutting down"})
            guest.close()
        if self._listener is not None:
            _shut(self._listener)
            self._listener = None

    # -- the lobby ---------------------------------------------------------
    def lobby_card(self):
        with self._lock:
            people = [g.card() for g in self.guests.values() if g.token]
            sessions = [s.card() for s in self.sessions.values()]
        people.sort(key=lambda c: (c.get("name") or "").lower())
        sessions.sort(key=lambda c: c.get("started", 0))
        return {"people": people, "sessions": sessions}

    def tell_lobby(self):
        """Everybody hears who is on and what is open.

        Sent to people inside a session too. Their line is carrying game
        traffic, but a hub message is marked as one and the app knows to
        keep it out of the game - which is what lets the list of who is
        here stay right while you are playing.
        """
        news = dict(self.lobby_card(), hub="lobby")
        with self._lock:
            guests = list(self.guests.values())
        for guest in guests:
            guest.send(news)

    # -- the threads -------------------------------------------------------
    def _accept_loop(self):
        while self._running:
            try:
                sock, where = self._listener.accept()
            except OSError:
                break
            threading.Thread(target=self._greet, args=(sock, where),
                             daemon=True).start()

    def _greet(self, sock, where):
        """Wait for a hello, check it, then put them in the lobby."""
        sock.settimeout(HELLO_TIMEOUT)
        reader = Line(sock)
        hello = None
        while hello is None:
            batch = reader.read()
            if batch is None:
                _shut(sock)
                return
            for message in batch:
                if message.get("hub") == "hello":
                    hello = message
                    break

        guest = Guest(sock, where)
        if not self._admit(guest, hello):
            return
        sock.settimeout(None)
        try:
            self._listen(guest, reader)
        finally:
            self._drop(guest)

    def _admit(self, guest, hello):
        """Check a hello and seat whoever sent it in the lobby."""
        if self.password and hello.get("password", "") != self.password:
            guest.send({"hub": "no", "why": "that is not the right password "
                                            "for this server"})
            guest.close()
            return False

        with self._lock:
            full = len(self.guests) >= self.max_people
        if full:
            guest.send({"hub": "no",
                        "why": "the server is full (%d people)"
                               % self.max_people})
            guest.close()
            return False

        card = hello.get("profile") or {}
        guest.token = card.get("token") or ("guest-%d"
                                            % int(time.time() * 1000))
        guest.name = (card.get("name") or "Someone").strip()[:24]
        guest.colour = card.get("colour") or guest.colour
        guest.version = hello.get("version") or "unknown"
        guest.face = hello.get("face")

        with self._lock:
            older = self.guests.get(guest.token)
            if older is not None and older is not guest:
                # The same person reconnecting - usually after a drop their
                # end noticed and this end did not. Let the newer line win
                # rather than leaving a ghost in the list.
                self._tear_down(older)
                older.close()
            self.guests[guest.token] = guest

        guest.send(dict(self.lobby_card(), hub="welcome", server=self.name,
                        motd=self.motd, you=guest.card(), version=VERSION))
        self.say("%s joined the server (%s)" % (guest.name, guest.version))
        self.tell_lobby()
        return True

    def _listen(self, guest, reader):
        while self._running and not guest.gone:
            batch = reader.read()
            if batch is None:
                break
            for message in batch:
                self._handle(guest, message)

    def _handle(self, guest, message):
        """One message from somebody.

        Three shapes arrive here. A hub verb is business with the server
        itself. A host in a session sends {"peer": n, "body": ...} for one
        of their players. Anything else from somebody in a session is game
        traffic for their host.
        """
        verb = message.get("hub")
        if verb == "open":
            self._open(guest, message)
        elif verb == "join":
            self._join(guest, message)
        elif verb == "leave":
            self._tear_down(guest)
            self.tell_lobby()
        elif verb == "lobby":
            guest.send(dict(self.lobby_card(), hub="lobby"))
        elif verb is not None:
            return                  # a verb from a newer build; ignore it
        elif guest.hosting:
            self._from_host(guest, message)
        elif guest.session is not None:
            self._to_host(guest, message)

    # -- sessions ----------------------------------------------------------
    def _open(self, guest, message):
        """Somebody wants to run a game here."""
        if guest.session is not None:
            guest.send({"hub": "no", "why": "you are already in a session"})
            return
        with self._lock:
            if len(self.sessions) >= MAX_SESSIONS:
                guest.send({"hub": "no",
                            "why": "this server already has %d sessions "
                                   "running" % MAX_SESSIONS})
                return
            ident = base64.b32encode(os.urandom(5)).decode().rstrip("=")
            seats = int(message.get("seats") or 8)
            session = Session(ident, guest, message.get("campaign"),
                              max(1, min(seats, 16)))
            self.sessions[ident] = session
        guest.session = session
        guest.hosting = True
        guest.send({"hub": "opened", "session": ident,
                    "campaign": session.campaign, "seats": session.seats})
        self.say("%s opened \"%s\"" % (guest.name, session.campaign))
        self.tell_lobby()

    def _join(self, guest, message):
        """Somebody picked a session off the list."""
        if guest.session is not None:
            guest.send({"hub": "no", "why": "you are already in a session"})
            return
        with self._lock:
            session = self.sessions.get(message.get("session"))
        if session is None:
            guest.send({"hub": "no", "why": "that session has ended"})
            return
        if session.host is guest:
            guest.send({"hub": "no", "why": "that is your own session"})
            return
        number = session.seat(guest)
        if number is None:
            guest.send({"hub": "no",
                        "why": "that session is full (%d seats)"
                               % session.seats})
            return
        guest.session = session
        guest.number = number
        guest.hosting = False
        guest.send({"hub": "joined", "session": session.id,
                    "campaign": session.campaign,
                    "host": session.host.name})
        # The host's app treats this exactly like somebody arriving on a
        # socket of its own, and answers with the usual welcome.
        session.host.send({"hub": "arrived", "peer": number})
        self.say("%s joined \"%s\"" % (guest.name, session.campaign))
        self.tell_lobby()

    def _from_host(self, guest, message):
        """A host's message for one of their players."""
        session = guest.session
        if session is None:
            return
        number = message.get("peer")
        body = message.get("body") or {}
        session.remember(body)
        with session._lock:
            target = session.people.get(number)
        if target is None:
            return
        target.send(body)
        # The host has just let them in, so this is the moment the newcomer
        # can make sense of a map. Sending the kept one here means an empty
        # board never sits there waiting on the GM's machine to be asked.
        if body.get("kind") == "welcome" and session.map is not None:
            target.send(session.map)

    def _to_host(self, guest, message):
        """A player's message, on its way to whoever is running their game."""
        session = guest.session
        if session is None or guest.number is None:
            return
        session.host.send({"hub": "from", "peer": guest.number,
                           "body": message})

    def _tear_down(self, guest):
        """Take somebody out of whatever session they were in."""
        session = guest.session
        if session is None:
            return
        guest.session = None
        if guest.hosting:
            guest.hosting = False
            with self._lock:
                self.sessions.pop(session.id, None)
            session.close("%s ended the session" % guest.name)
            self.say("%s ended \"%s\"" % (guest.name, session.campaign))
            return
        number = guest.number
        guest.number = None
        if number is not None:
            session.leave(number)
            session.host.send({"hub": "gone", "peer": number})

    def _drop(self, guest):
        """The line went down, or they closed it."""
        if guest.gone and guest.token not in self.guests:
            return
        self._tear_down(guest)
        with self._lock:
            if self.guests.get(guest.token) is guest:
                del self.guests[guest.token]
            else:
                guest.close()
                return
        guest.close()
        self.say("%s left the server" % guest.name)
        self.tell_lobby()


# ==========================================================================
# running it from a console
# ==========================================================================
def addresses():
    """Every address this machine answers on, best guess first."""
    found = []
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))       # no packet is actually sent
        found.append(sock.getsockname()[0])
        sock.close()
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None,
                                       socket.AF_INET):
            where = info[4][0]
            if where not in found and not where.startswith("127."):
                found.append(where)
    except OSError:
        pass
    return found or ["127.0.0.1"]


def public_address(timeout=3.0):
    """What the internet sees this machine as, asked of a STUN server.

    Only ever used to print it. Knowing the number saves the person running
    this from going to look it up, and nothing here depends on the answer.
    """
    import struct
    request = struct.pack("!HHI", 0x0001, 0, 0x2112A442) + os.urandom(12)
    for host, at in (("stun.l.google.com", 19302),
                     ("stun.cloudflare.com", 3478)):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(timeout)
        try:
            sock.sendto(request, (host, at))
            reply, _ = sock.recvfrom(2048)
        except OSError:
            continue
        finally:
            sock.close()
        at_byte = 20
        while at_byte + 4 <= len(reply):
            kind, size = struct.unpack("!HH", reply[at_byte:at_byte + 4])
            body = reply[at_byte + 4:at_byte + 4 + size]
            if kind == 0x0020 and len(body) >= 8:       # XOR-MAPPED-ADDRESS
                raw = bytes(a ^ b for a, b in
                            zip(body[4:8], struct.pack("!I", 0x2112A442)))
                return socket.inet_ntoa(raw)
            at_byte += 4 + size + (-size % 4)
    return None


def report(hub, public):
    """Everything the person running this needs, in the order they need it."""
    print(RULE)
    print("  %s" % hub.name)
    if hub.motd:
        print("  %s" % hub.motd)
    print(RULE)
    print("  Version:  %s   (everyone connecting needs this same one)"
          % VERSION)
    print("  Port:     %d   (TCP)" % hub.port)
    print("  Password: %s" % ("set" if hub.password else "none"))
    print("  Settings: %s" % CONFIG_PATH)
    print()
    print("  On this network, people use:")
    for where in addresses():
        print("      %s:%d" % (where, hub.port))
    print()
    if public:
        print("  From anywhere else, people use:")
        print("      %s:%d" % (public, hub.port))
        print()
        print("  That only works while TCP port %d is forwarded to this"
              % hub.port)
        print("  machine on the router, and allowed through its firewall.")
    else:
        print("  Could not work out this machine's public address. If people")
        print("  outside the house need in, find it and forward TCP port %d"
              % hub.port)
        print("  to this machine.")
    print(RULE)
    print("  Running. Ctrl-C to stop - every session on it ends.")
    print(RULE)


def main(argv=None):
    settings = load_settings()
    parser = argparse.ArgumentParser(
        description="Run a %s server." % paths.APP_NAME)
    parser.add_argument("--port", type=int, default=None,
                        help="TCP port to listen on (default %d)"
                             % settings.get("port", DEFAULT_PORT))
    parser.add_argument("--name", default=None,
                        help="what this server calls itself")
    parser.add_argument("--motd", default=None,
                        help="a line shown to everyone who connects")
    parser.add_argument("--password", default=None,
                        help="require this to connect (empty for none)")
    parser.add_argument("--quiet", action="store_true",
                        help="do not print who comes and goes")
    args = parser.parse_args(argv)

    # Anything given on the command line is meant to stick, otherwise the
    # person running this would have to remember the same flags every time.
    for key, value in (("port", args.port), ("name", args.name),
                       ("motd", args.motd), ("password", args.password)):
        if value is not None:
            settings[key] = value
    save_settings(settings)

    hub = Hub(settings, quiet=args.quiet)
    try:
        hub.start()
    except OSError as exc:
        print("Could not listen on port %d: %s" % (hub.port, exc))
        print("Something else is probably using it. Try --port with another "
              "number.")
        return 1

    report(hub, public_address())
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        print()
        print("Stopping...")
    finally:
        hub.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
