"""Playing together, on this network or through a server.

The shape of it:

  * One machine hosts. Its app holds the campaign and is the authority on
    what is true; everyone else is a view onto it.
  * There are two ways to reach a host. On the same network they listen on
    a TCP port and hand out an invite code - an address in a form somebody
    can read down a phone, carrying the host's address, the port, and a
    secret so a stray connection cannot wander in. Anywhere else, everybody
    dials out to a server (see server.py) and picks the session off a list.
  * Either way the conversation past that point is identical, which is the
    point: nothing above this file has to know which way in was used.
  * Messages are one JSON object per line. Easy to read in a log, easy to
    extend, and no framing bugs to chase.
  * Every socket is read on its own thread and every message it produces is
    dropped into a queue. Nothing here touches Tk - the UI drains the queue
    on its own clock, so a slow network can never freeze the window.
"""

import base64
import json
import os
import queue
import socket
import struct
import threading
import time

DEFAULT_PORT = 7777
MAX_SEATS = 8               # joiners; the host does not take a seat
SECRET_BYTES = 5
HANDSHAKE_TIMEOUT = 8.0     # seconds a half-open connection may sit there
ANSWER_TIMEOUT = 10.0       # how long to wait on a server answering us

import paths

VERSION = paths.VERSION
APP_DIR = paths.APP_DIR
PROFILE_PATH = os.path.join(APP_DIR, "profile.json")
PROFILE_PICTURE = os.path.join(APP_DIR, "profile.png")
FACE_CACHE = os.path.join(APP_DIR, "faces")
MAX_FACE = 400 * 1024       # a picture bigger than this is not worth sending

# Colours somebody can be, for their cursor and their name badge.
PROFILE_COLOURS = [
    ("Gold", "#c8a24a"), ("Crimson", "#e2585f"),
    ("Azure", "#5aa9e6"), ("Emerald", "#5fd38d"),
    ("Violet", "#b98cff"), ("Amber", "#e8a33d"),
    ("Rose", "#ef7ea8"), ("Teal", "#3fbfae"),
    ("Lime", "#a8d84a"), ("Cyan", "#6fd8ff"),
    ("Indigo", "#7d7bf0"), ("Coral", "#f08a5d"),
    ("Mint", "#8ee6c0"), ("Slate", "#8b90a0"),
    ("Sand", "#ddd6b4"), ("Plum", "#a55b9c"),
]

ROLES = ["GM"] + ["Player %d" % n for n in range(1, MAX_SEATS + 1)]


# ==========================================================================
# who you are
# ==========================================================================
class Profile:
    """A name, a colour and a picture, kept next to the app.

    Not an account in any real sense - there is no password and nothing to
    log into. It exists so that when you turn up in somebody's campaign they
    see a person rather than an address.
    """

    def __init__(self, name="", colour=PROFILE_COLOURS[0][1], token=None,
                 picture=None):
        self.name = name
        self.colour = colour
        self.token = token or base64.b32encode(os.urandom(8)).decode().rstrip("=")
        self.picture = picture          # path to a local image, or None

    @classmethod
    def load(cls, path=None):
        path = path or PROFILE_PATH
        try:
            with open(path, encoding="utf-8") as fh:
                saved = json.load(fh)
        except (OSError, ValueError):
            return cls()
        picture = paths.resolve(saved.get("picture"))
        if picture and not os.path.exists(picture):
            picture = None              # they moved or deleted it
        return cls(name=saved.get("name", ""),
                   colour=saved.get("colour", PROFILE_COLOURS[0][1]),
                   token=saved.get("token"), picture=picture)

    def save(self, path=None):
        path = path or PROFILE_PATH
        try:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump({"name": self.name, "colour": self.colour,
                           "token": self.token,
                           "picture": paths.inside(self.picture)},
                          fh, indent=2)
            return True
        except OSError:
            return False

    def is_ready(self):
        return bool(self.name.strip())

    def card(self):
        """What the other machines are told about you."""
        return {"token": self.token, "name": self.name.strip() or "Someone",
                "colour": self.colour}

    def face(self):
        """The picture itself, ready to put on the wire, or None.

        Sent once when somebody joins rather than with every roster update -
        it is by far the biggest thing any of this moves around.
        """
        if not self.picture or not os.path.exists(self.picture):
            return None
        try:
            if os.path.getsize(self.picture) > MAX_FACE:
                return None
            with open(self.picture, "rb") as fh:
                return base64.b64encode(fh.read()).decode()
        except OSError:
            return None


def cache_face(token, encoded):
    """Write somebody else's picture down and return where it went.

    Their machine has the original; this is just so Tk has a file to open.
    """
    if not encoded:
        return None
    try:
        raw = base64.b64decode(encoded)
    except Exception:
        return None
    if len(raw) > MAX_FACE:
        return None
    safe = "".join(c for c in str(token) if c.isalnum() or c in "-_")[:48]
    if not safe:
        return None
    try:
        os.makedirs(FACE_CACHE, exist_ok=True)
        path = os.path.join(FACE_CACHE, safe + ".png")
        with open(path, "wb") as fh:
            fh.write(raw)
        return path
    except OSError:
        return None


# ==========================================================================
# invite codes
# ==========================================================================
def make_code(address, port, secret):
    """An address somebody can read out loud.

    Eleven bytes - four of address, two of port, five of secret - in base32
    and grouped in fours. Short enough to type, and the secret means a code
    is needed to get in rather than just knowing the host is there.
    """
    raw = socket.inet_aton(address) + struct.pack("!H", port) + secret
    text = base64.b32encode(raw).decode().rstrip("=")
    return "-".join(text[i:i + 4] for i in range(0, len(text), 4))


def read_code(code):
    """(address, port, secret) from a code, or None if it is not one.

    Forgiving about how it was typed: spaces, dashes and case are all
    ignored, because it will have been read off a screen or a phone.
    """
    if not code:
        return None
    text = "".join(code.split()).replace("-", "").replace("_", "").upper()
    text = text.replace("0", "O").replace("1", "I")   # common misreadings
    padding = "=" * (-len(text) % 8)
    try:
        raw = base64.b32decode(text + padding)
    except Exception:
        return None
    if len(raw) != 4 + 2 + SECRET_BYTES:
        return None
    address = socket.inet_ntoa(raw[:4])
    port = struct.unpack("!H", raw[4:6])[0]
    return address, port, raw[6:]


def local_addresses():
    """Every address this machine can be reached on, best guess first.

    A laptop on wifi and a desktop on ethernet are both perfectly normal, and
    a machine with both has two answers - so offer them all rather than
    picking one and being wrong.
    """
    found = []

    # The address that would be used to reach the outside world is almost
    # always the one on the network everybody else is on.
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("10.255.255.255", 1))
        found.append(probe.getsockname()[0])
    except OSError:
        pass
    finally:
        probe.close()

    try:
        for info in socket.getaddrinfo(socket.gethostname(), None,
                                       socket.AF_INET):
            address = info[4][0]
            if address not in found:
                found.append(address)
    except OSError:
        pass

    usable = [a for a in found if not a.startswith("127.")]
    return usable or ["127.0.0.1"]


# ==========================================================================
# the wire
# ==========================================================================
def send_line(sock, message):
    """One JSON object, one line. Returns False if the socket has gone."""
    try:
        sock.sendall((json.dumps(message) + "\n").encode("utf-8"))
        return True
    except OSError:
        return False


class LineReader:
    """Turns a socket's bytes back into whole JSON messages.

    TCP does not preserve message boundaries, so a read can hand back half a
    message or three of them; this keeps whatever is left over.
    """

    def __init__(self, sock):
        self.sock = sock
        self.buffer = b""

    def read(self):
        """Block for more data, then return every complete message in it.

        Three different answers, and they must not be confused:
          None  - the other end has gone.
          []    - something arrived, but not a whole message yet. Read again.
          [...] - one or more complete messages.

        A profile picture makes the opening message far larger than a single
        packet, so [] is the normal state of affairs partway through one.
        """
        try:
            chunk = self.sock.recv(65536)
        except OSError:
            return None
        if not chunk:
            return None
        self.buffer += chunk
        messages = []
        while b"\n" in self.buffer:
            line, self.buffer = self.buffer.split(b"\n", 1)
            line = line.strip()
            if not line:
                continue
            try:
                messages.append(json.loads(line.decode("utf-8")))
            except (ValueError, UnicodeDecodeError):
                continue        # garbage on the wire is not worth dying over
        return messages


class Peer:
    """One joiner, from the host's side of the wire.

    How to reach them is asked of the peer rather than assumed to be a
    socket, because over the internet it will not be one: everybody dials
    out to a relay and their messages arrive down that single line.
    """

    def __init__(self, sock, address):
        self.sock = sock
        self.address = address
        self.token = None
        self.name = "..."
        self.colour = PROFILE_COLOURS[0][1]
        self.role = None
        self.joined_at = time.time()

    def send(self, message):
        """One message to this joiner. False if they have gone."""
        return send_line(self.sock, message)

    def close(self):
        _shutdown(self.sock)

    def card(self):
        return {"token": self.token, "name": self.name, "colour": self.colour,
                "role": self.role}


class Server:
    """The host's end. Accepts joiners, keeps the roster, fans out messages.

    Everything public here is safe to call from the Tk thread; the sockets
    live on threads of their own and talk back through `inbox`.
    """

    def __init__(self, profile, port=DEFAULT_PORT, seats=MAX_SEATS,
                 campaign=""):
        self.profile = profile
        self.version = VERSION          # what this build calls itself
        self.host_role = "GM"           # the host is the GM until they say
                                        # otherwise, and they may
        self.campaign = campaign        # so joiners can name their own copy
        self.port = port
        self.seats = seats
        self.secret = os.urandom(SECRET_BYTES)
        mine = profile.face()
        self.faces = {profile.token: mine} if mine else {}   # token -> base64
        # Where each picture landed on this machine, so the host can show
        # the same faces the joiners are looking at.
        self.face_paths = {}
        if profile.picture:
            self.face_paths[profile.token] = profile.picture
        self.link = None                # the line to a server, if on one
        self.inbox = queue.Queue()
        self.peers = {}                 # token -> Peer
        self._lock = threading.RLock()
        self._listener = None
        self._running = False

    # -- lifecycle ---------------------------------------------------------
    def start(self, address=""):
        """Listen. An empty address means every adapter - wifi and ethernet
        both, which is the point of not naming one."""
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            # Windows lets two sockets share a port under SO_REUSEADDR, which
            # would mean two copies of the app quietly splitting the joiners
            # between them. Claim it outright instead, so a second host fails
            # here and can say so.
            listener.setsockopt(socket.SOL_SOCKET,
                                socket.SO_EXCLUSIVEADDRUSE, 1)
        else:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((address, self.port))
        listener.listen(self.seats + 2)
        self.port = listener.getsockname()[1]
        self._listener = listener
        self._running = True
        threading.Thread(target=self._accept_loop, daemon=True).start()
        return self.port

    def host_on(self, hub):
        """Run this session on a server rather than listening for callers.

        Nothing has to be reachable at this end: the line to the server is
        one we opened, and everybody who joins arrives down it. The server
        has already agreed to the session by the time this is called, so
        there is nothing here that can fail.
        """
        self.link = HubLink(self, hub)
        return None

    def _hub_peer(self, number):
        """Whoever is seated under this server's number, if anybody."""
        with self._lock:
            for peer in self.peers.values():
                if getattr(peer, "number", None) == number:
                    return peer
        return None

    def stop(self):
        self._running = False
        with self._lock:
            peers = list(self.peers.values())
            self.peers.clear()
        for peer in peers:
            peer.send({"kind": "bye", "why": "the host closed"})
            peer.close()
        if self._listener is not None:
            _shutdown(self._listener)
            self._listener = None
        if self.link is not None:
            self.link.close()
            self.link = None

    def code_for(self, address):
        return make_code(address, self.port, self.secret)

    # -- the roster --------------------------------------------------------
    def roster(self):
        with self._lock:
            return [peer.card() for peer in self.peers.values()]

    def host_card(self):
        """What everyone else is told about the host.

        Sent with every roster, not just the welcome - the host's own role
        can change, and handing the GM chair over has to reach the table.
        """
        return dict(self.profile.card(), role=self.host_role,
                    campaign=self.campaign, host=True)

    def tell_roster(self):
        self.broadcast({"kind": "roster", "peers": self.roster(),
                        "host": self.host_card()})

    def set_role(self, token, role):
        with self._lock:
            peer = self.peers.get(token)
            if peer is None:
                return False
            peer.role = role
        self.tell_roster()
        return True

    def drop(self, token, why="the host removed you"):
        with self._lock:
            peer = self.peers.pop(token, None)
        if peer is None:
            return False
        peer.send({"kind": "bye", "why": why})
        peer.close()
        self.inbox.put({"kind": "left", "peer": peer.card()})
        self.tell_roster()
        return True

    # -- talking -----------------------------------------------------------
    def broadcast(self, message, skip=None):
        with self._lock:
            peers = [p for p in self.peers.values() if p.token != skip]
        for peer in peers:
            if not peer.send(message):
                self._lost(peer)

    def send_to(self, token, message):
        with self._lock:
            peer = self.peers.get(token)
        if peer is None:
            return False
        if not peer.send(message):
            self._lost(peer)
            return False
        return True

    # -- the threads -------------------------------------------------------
    def _accept_loop(self):
        while self._running:
            try:
                sock, address = self._listener.accept()
            except OSError:
                break
            threading.Thread(target=self._greet, args=(sock, address),
                             daemon=True).start()

    def _greet(self, sock, address):
        """Wait for a hello, check the secret, then let them in."""
        sock.settimeout(HANDSHAKE_TIMEOUT)
        reader = LineReader(sock)
        hello = None
        while hello is None:
            batch = reader.read()
            if batch is None:
                _shutdown(sock)        # they really have gone
                return
            for message in batch:
                if message.get("kind") == "hello":
                    hello = message
                    break
        peer = Peer(sock, address)
        if self._admit(peer, hello):
            sock.settimeout(None)
            threading.Thread(target=self._listen_to, args=(peer, reader),
                             daemon=True).start()

    def _admit(self, peer, hello):
        """Check a hello and seat whoever sent it.

        Shared by both ways in - a joiner on the same network arrives on a
        socket of their own, one from a server arrives down our single line
        to it, and neither should be let in on different terms.
        """
        sock = peer.sock
        address = peer.address
        # An invite code is how somebody on this network proves they were
        # invited. Through a server there is no code to know: they picked
        # the session off a list, and the server would not have sent them
        # here unless it had already let them onto it - so the secret it
        # stands in for has already been checked, by the server.
        if not isinstance(peer, HubPeer):
            secret = base64.b64decode(hello.get("secret", "") or "")
            if secret != self.secret:
                peer.send({"kind": "denied", "why": "that code is not for "
                                                    "this session"})
                peer.close()
                return False

        # Everyone has to be running the same build. The map is sent as one
        # whole thing, so a version that knows about something this one does
        # not would quietly lose it the first time anybody saved.
        theirs = hello.get("version") or "unknown"
        if theirs != self.version:
            peer.send({"kind": "denied", "version": self.version,
                       "your_version": theirs,
                       "why": "the host is running version %s and you have "
                              "%s - you both need the same one"
                              % (self.version, theirs)})
            peer.close()
            return False

        with self._lock:
            if len(self.peers) >= self.seats:
                full = True
            else:
                full = False
        if full:
            peer.send({"kind": "denied",
                       "why": "the session is full (%d seats)" % self.seats})
            peer.close()
            return False

        card = hello.get("profile") or {}
        peer.token = card.get("token") or ("guest-%d" % int(time.time() * 1000))
        peer.name = (card.get("name") or "Someone").strip()[:24]
        peer.colour = card.get("colour") or PROFILE_COLOURS[0][1]

        with self._lock:
            existing = self.peers.get(peer.token)
            if existing is not None:
                # Same person reconnecting - let the newer line win rather
                # than leaving a ghost in the roster.
                existing.close()
            self.peers[peer.token] = peer

        face = hello.get("face")
        if face:
            self.faces[peer.token] = face
            landed = cache_face(peer.token, face)
            if landed:
                self.face_paths[peer.token] = landed

        peer.send({"kind": "welcome", "you": peer.card(),
                   "host": self.host_card(), "seats": self.seats,
                   "version": self.version})
        # Everyone already here, then tell everyone else about the newcomer.
        for token, picture in list(self.faces.items()):
            if token != peer.token:
                peer.send({"kind": "face", "token": token, "data": picture})
        if face:
            self.broadcast({"kind": "face", "token": peer.token,
                            "data": face}, skip=peer.token)
        self.inbox.put({"kind": "joined", "peer": peer.card()})
        self.tell_roster()
        return True

    def _listen_to(self, peer, reader):
        while self._running:
            batch = reader.read()
            if batch is None:
                break
            for message in batch:
                message["from"] = peer.token
                self.inbox.put(message)
        self._lost(peer)

    def face_of(self, token):
        return self.face_paths.get(token)

    def _lost(self, peer):
        with self._lock:
            if self.peers.get(peer.token) is not peer:
                return              # already replaced or removed
            del self.peers[peer.token]
        peer.close()
        self.inbox.put({"kind": "left", "peer": peer.card()})
        self.tell_roster()


class Client:
    """The joiner's end."""

    def __init__(self, profile):
        self.profile = profile
        self.inbox = queue.Queue()
        self.sock = None
        self.hub = None             # set when we got here through a server
        self.host = None            # the host's profile card
        self.seat = None            # our own card, as the host sees it
        self.peers = []
        self.faces = {}             # token -> where their picture landed
        self.host_version = None
        # Only used on the way in through a server: the reply to our hello
        # arrives on the server's reading thread rather than in a loop of
        # our own, so joining waits here for it.
        self.ready = threading.Event()
        self.refused = None
        self._running = False

    def connect(self, code, timeout=6.0):
        """Join a session. Returns None on success, or why it failed."""
        parsed = read_code(code)
        if parsed is None:
            return "that does not look like an invite code"
        address, port, secret = parsed
        try:
            sock = socket.create_connection((address, port), timeout=timeout)
        except OSError as exc:
            return "could not reach %s on port %d (%s)" % (address, port, exc)
        sock.settimeout(timeout)
        send_line(sock, {"kind": "hello",
                         "secret": base64.b64encode(secret).decode(),
                         "version": VERSION,
                         "profile": self.profile.card(),
                         "face": self.profile.face()})
        reader = LineReader(sock)
        while True:
            batch = reader.read()
            if batch is None:
                _shutdown(sock)
                return "the host closed the connection"
            for message in batch:
                if message.get("kind") == "denied":
                    _shutdown(sock)
                    return message.get("why", "the host turned you away")
                if message.get("kind") == "welcome":
                    self.sock = sock
                    self.host = message.get("host")
                    self.seat = message.get("you")
                    self.host_version = message.get("version")
                    self._running = True
                    sock.settimeout(None)
                    # The host sends the faces straight after the welcome, so
                    # they can easily be in this same batch of bytes. Take the
                    # rest of it before handing over to the reader thread.
                    tail = batch[batch.index(message) + 1:]
                    for extra in tail:
                        self._take(extra)
                    threading.Thread(target=self._listen, args=(reader,),
                                     daemon=True).start()
                    return None

    def send(self, message):
        if self.hub is not None:
            # Through a server: the one line out carries everything, and the
            # server knows which host these belong to.
            return self.hub.send(message)
        if self.sock is None:
            return False
        if send_line(self.sock, message):
            return True
        self._dropped("the connection went down")
        return False

    def close(self):
        self._running = False
        if self.hub is not None:
            # The line out stays up - leaving a session puts us back in the
            # server's lobby rather than throwing us off it.
            hub, self.hub = self.hub, None
            hub.leave_session()
            return
        if self.sock is not None:
            _shutdown(self.sock)
            self.sock = None

    def _listen(self, reader):
        while self._running:
            batch = reader.read()
            if batch is None:
                break
            for message in batch:
                self._take(message)
        if self._running:
            self._dropped("lost the host")

    def _take(self, message):
        """Note anything we keep our own copy of, then pass it along."""
        kind = message.get("kind")
        if self.hub is not None and not self.ready.is_set():
            # Still joining. The host either lets us in or does not, and
            # nothing else means anything until one of those has happened.
            if kind == "denied":
                self.refused = message.get("why",
                                           "the host turned you away")
                self.ready.set()
                return
            if kind == "welcome":
                self.host = message.get("host")
                self.seat = message.get("you")
                self.host_version = message.get("version")
                self._running = True
                self.ready.set()
                return
        if kind == "roster":
            self.peers = message.get("peers") or []
            if message.get("host"):
                self.host = message["host"]
        elif kind == "face":
            landed = cache_face(message.get("token"), message.get("data"))
            if landed:
                self.faces[message["token"]] = landed
                message["path"] = landed
        self.inbox.put(message)

    def _dropped(self, why):
        self._running = False
        self.sock = None
        self.inbox.put({"kind": "dropped", "why": why})


def _shutdown(sock):
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
# playing through a server
# ==========================================================================
class HubPeer:
    """A joiner who is not on the end of a socket of our own.

    Their messages arrive down the host's single line to the server, tagged
    with which of them sent it, and replies go back the same way. To the
    rest of the code it behaves exactly like a peer on its own socket, which
    is what lets Server not care how anybody got here.
    """

    def __init__(self, link, number):
        self.link = link
        self.number = number
        self.sock = None
        self.address = ("server", number)
        self.token = None
        self.name = "..."
        self.colour = PROFILE_COLOURS[0][1]
        self.role = None
        self.joined_at = time.time()
        self.gone = False

    def send(self, message):
        if self.gone:
            return False
        return self.link.to_peer(self.number, message)

    def close(self):
        self.gone = True

    def card(self):
        return {"token": self.token, "name": self.name, "colour": self.colour,
                "role": self.role}


class HubLink:
    """A hosting session's end of the line to the server.

    It owns no socket. The HubClient holds the only one and hands this the
    traffic that belongs to the session, which is what lets one line carry
    the game and the lobby at the same time.
    """

    def __init__(self, server, hub):
        self.server = server
        self.hub = hub
        self.waiting = {}       # number -> somebody who has not said hello
        self._running = True

    def close(self):
        self._running = False

    def to_peer(self, number, message):
        if not self._running:
            return False
        return self.hub.send({"peer": number, "body": message})

    def handle(self, message):
        """One of the server's messages about somebody in our session."""
        verb = message.get("hub")
        number = message.get("peer")
        if verb == "arrived":
            self.waiting[number] = HubPeer(self, number)
            return
        if verb == "gone":
            peer = self.waiting.pop(number, None)
            seated = self.server._hub_peer(number)
            if seated is not None:
                self.server._lost(seated)
            elif peer is not None:
                peer.close()
            return
        if verb != "from":
            return
        body = message.get("body") or {}
        seated = self.server._hub_peer(number)
        if seated is not None:
            body["from"] = seated.token
            self.server.inbox.put(body)
            return
        # Not seated yet, so this should be their hello. Either way they stop
        # being expected: admitted, or turned away with a reason.
        peer = self.waiting.pop(number, None)
        if peer is None or body.get("kind") != "hello":
            return
        self.server._admit(peer, body)


class HubClient:
    """The app's one line to a server, carrying the lobby and a session.

    Everything on the line is either business with the server itself -
    marked with a "hub" key - or traffic for whatever session this app is
    in. Keeping both on one connection is what makes the list of who else is
    on the server stay right while a game is running.

    Nothing here touches Tk. Lobby news lands in `inbox` and the window
    drains it on its own clock, the same as everything else.
    """

    def __init__(self, profile):
        self.profile = profile
        self.inbox = queue.Queue()      # lobby news for whoever is looking
        self.sock = None
        self.address = ""
        self.port = DEFAULT_PORT
        self.name = ""                  # what the server calls itself
        self.motd = ""
        self.people = []                # everybody on the server
        self.sessions = []              # every session open on it
        self.session = None             # the id of ours, when we are in one
        self.server = None              # our Server, when we are hosting
        self.client = None              # our Client, when we joined one
        self.link = None                # HubLink, when we are hosting
        self._answers = queue.Queue()   # replies to something we asked
        self._send_lock = threading.Lock()
        self._running = False

    # -- getting on it -----------------------------------------------------
    def connect(self, address, port=DEFAULT_PORT, password="", timeout=8.0):
        """Dial a server. Returns None, or why it did not work."""
        try:
            sock = socket.create_connection((address, port), timeout=timeout)
        except OSError as exc:
            return "could not reach %s on port %d (%s)" % (address, port, exc)
        sock.settimeout(timeout)
        send_line(sock, {"hub": "hello", "version": VERSION,
                         "profile": self.profile.card(),
                         "face": self.profile.face(),
                         "password": password or ""})
        reader = LineReader(sock)
        while True:
            batch = reader.read()
            if batch is None:
                _shutdown(sock)
                return "the server closed the connection"
            for message in batch:
                if message.get("hub") == "no":
                    _shutdown(sock)
                    return message.get("why", "the server turned you away")
                if message.get("hub") != "welcome":
                    continue
                self.sock = sock
                self.address = address
                self.port = port
                self.name = message.get("server") or address
                self.motd = message.get("motd") or ""
                self.people = message.get("people") or []
                self.sessions = message.get("sessions") or []
                self._running = True
                sock.settimeout(None)
                threading.Thread(target=self._listen, args=(reader,),
                                 daemon=True).start()
                return None

    def close(self):
        self._running = False
        if self.link is not None:
            self.link.close()
            self.link = None
        if self.sock is not None:
            _shutdown(self.sock)
            self.sock = None

    def send(self, message):
        """One message up the line. False once it has gone."""
        with self._send_lock:       # the game and the lobby share this line
            if self.sock is None:
                return False
            return send_line(self.sock, message)

    def refresh(self):
        """Ask for the lobby again rather than waiting to be told."""
        self.send({"hub": "lobby"})

    # -- sessions ----------------------------------------------------------
    def open_session(self, campaign="", seats=MAX_SEATS,
                     timeout=ANSWER_TIMEOUT):
        """Run a game here. Returns (Server, None) or (None, why)."""
        if self.session is not None:
            return None, "you are already in a session"
        self._drain_answers()
        if not self.send({"hub": "open", "campaign": campaign,
                          "seats": seats}):
            return None, "the line to the server went down"
        answer = self._answer(("opened", "no"), timeout)
        if answer is None:
            return None, "the server did not answer"
        if answer.get("hub") == "no":
            return None, answer.get("why", "the server said no")

        server = Server(self.profile, campaign=campaign,
                        seats=answer.get("seats") or seats)
        server.host_on(self)
        self.server = server
        self.link = server.link
        self.session = answer.get("session")
        return server, None

    def join_session(self, ident, timeout=ANSWER_TIMEOUT):
        """Sit down at somebody's game. Returns (Client, None) or (None, why).

        Two handshakes, one after the other: the server has to agree to seat
        us, and then the host has to let us in. They are separate because the
        server does not know or care what the host's rules are - it only
        knows whether there is a chair.
        """
        if self.session is not None:
            return None, "you are already in a session"
        self._drain_answers()
        if not self.send({"hub": "join", "session": ident}):
            return None, "the line to the server went down"
        answer = self._answer(("joined", "no"), timeout)
        if answer is None:
            return None, "the server did not answer"
        if answer.get("hub") == "no":
            return None, answer.get("why", "the server said no")

        client = Client(self.profile)
        client.hub = self
        self.client = client            # so the host's replies find their way
        self.session = ident
        self.send({"kind": "hello",
                   "secret": "",        # the server vouched for us instead
                   "version": VERSION,
                   "profile": self.profile.card(),
                   "face": self.profile.face()})
        if not client.ready.wait(timeout):
            self._back_to_lobby()
            return None, "the host did not answer"
        if client.refused:
            why = client.refused
            self._back_to_lobby()
            return None, why
        return client, None

    def leave_session(self):
        """Step out of whatever we are in, staying on the server."""
        if self.session is None:
            return
        if self.server is not None:
            self.server.stop()
        self._back_to_lobby()

    def _back_to_lobby(self):
        self.session = None
        self.server = None
        self.client = None
        if self.link is not None:
            self.link.close()
            self.link = None
        self.send({"hub": "leave"})

    # -- the reading thread ------------------------------------------------
    def _listen(self, reader):
        while self._running:
            batch = reader.read()
            if batch is None:
                break
            for message in batch:
                self._route(message)
        if self._running:
            self._running = False
            self.sock = None
            self.inbox.put({"kind": "hub_lost",
                            "why": "lost the connection to %s"
                                   % (self.name or self.address)})
            # Whoever is in a session hears about it the way they would hear
            # about any other disconnection, rather than sitting there
            # wondering why nothing is moving any more.
            if self.client is not None:
                self.client._dropped("lost the server")
            elif self.server is not None:
                self.server.inbox.put({"kind": "dropped",
                                       "why": "lost the server"})

    def _route(self, message):
        """Server business, or traffic for the session we are in."""
        verb = message.get("hub")
        if verb is None:
            # Game traffic. Only a joiner ever sees it raw - a host's peers
            # arrive wrapped, and go through the link above.
            if self.client is not None:
                self.client._take(message)
            return
        if verb in ("lobby", "welcome"):
            self.people = message.get("people") or []
            self.sessions = message.get("sessions") or []
            self.inbox.put({"kind": "lobby", "people": self.people,
                            "sessions": self.sessions})
            return
        if verb in ("arrived", "gone", "from"):
            if self.link is not None:
                self.link.handle(message)
            return
        if verb == "ended":
            why = message.get("why", "the session ended")
            self.session = None
            if self.client is not None:
                self.client._dropped(why)
                self.client = None
            if self.server is not None:
                self.server.stop()
                self.server = None
            self.link = None
            self.inbox.put({"kind": "session_ended", "why": why})
            return
        # Anything else is the answer to something we asked for.
        self._answers.put(message)

    def _answer(self, verbs, timeout):
        """Wait for one of these replies, ignoring anything else."""
        deadline = time.time() + timeout
        while True:
            left = deadline - time.time()
            if left <= 0:
                return None
            try:
                message = self._answers.get(timeout=left)
            except Exception:
                return None
            if message.get("hub") in verbs:
                return message

    def _drain_answers(self):
        """Throw away replies to something we have stopped waiting for."""
        while True:
            try:
                self._answers.get_nowait()
            except Exception:
                return
