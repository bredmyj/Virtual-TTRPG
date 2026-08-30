"""Playing together over a local network.

The shape of it:

  * One machine hosts. Its app holds the campaign and is the authority on
    what is true; everyone else is a view onto it.
  * A host listens on a TCP port and hands out an invite code. The code is
    just an address in a form somebody can read down a phone - it carries
    the host's LAN address, the port, and a secret so a stray connection
    from elsewhere on the network cannot wander in.
  * Messages are one JSON object per line. Easy to read in a log, easy to
    extend, and no framing bugs to chase.
  * Every socket is read on its own thread and every message it produces is
    dropped into a queue. Nothing here touches Tk - the UI drains the queue
    on its own clock, so a slow network can never freeze the window.

Local network only, deliberately. Reaching a host across the internet needs
either a forwarded port or a machine in the middle, and neither belongs
buried in here.
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
# What marks a code as going through a meeting point rather than straight
# to somebody on the same network.
RELAY_MARK = "R"
# The four bytes every STUN reply is scrambled with.
COOKIE = struct.pack("!I", 0x2112A442)
HANDSHAKE_TIMEOUT = 8.0     # seconds a half-open connection may sit there

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


def make_relay_code(address, port, secret):
    """An invite code for a session held at a meeting point.

    The same shape as the ordinary one with a marker on the front, so a
    joiner can tell at a glance - and so the app knows to dial the relay
    rather than trying to reach the host directly.
    """
    return RELAY_MARK + "-" + make_code(address, port, secret)


def is_relay_code(code):
    """Does this code point at a meeting point rather than a machine here?"""
    if not code:
        return False
    text = "".join(str(code).split()).replace("-", "").replace("_", "").upper()
    return text.startswith(RELAY_MARK)


def read_code(code):
    """(address, port, secret) from a code, or None if it is not one.

    Forgiving about how it was typed: spaces, dashes and case are all
    ignored, because it will have been read off a screen or a phone.
    """
    if not code:
        return None
    text = "".join(code.split()).replace("-", "").replace("_", "").upper()
    if text.startswith(RELAY_MARK):
        text = text[len(RELAY_MARK):]
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


def public_address(port=0, timeout=3.0):
    """The address the internet sees this machine as, or None.

    Asked of a STUN server, which simply reports where the question came
    from. If `port` is given the question is sent from that port, so the
    answer also says whether the network in front of this machine keeps
    port numbers - which is what decides whether anyone can dial in.
    """
    servers = [("stun.l.google.com", 19302), ("stun1.l.google.com", 19302),
               ("stun.cloudflare.com", 3478)]
    request = struct.pack("!HHI", 0x0001, 0, 0x2112A442) + os.urandom(12)
    for host, at in servers:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            if port:
                sock.bind(("", port))
            sock.settimeout(timeout)
            sock.sendto(request, (host, at))
            data, _from = sock.recvfrom(2048)
        except OSError:
            continue
        finally:
            sock.close()
        walk = 20
        while walk + 4 <= len(data):
            kind, size = struct.unpack("!HH", data[walk:walk + 4])
            body = data[walk + 4:walk + 4 + size]
            if kind == 0x0020 and len(body) >= 8:        # XOR-MAPPED-ADDRESS
                seen = struct.unpack("!H", body[2:4])[0] ^ 0x2112
                raw = bytes(b ^ c for b, c in
                            zip(body[4:8], COOKIE))
                return socket.inet_ntoa(raw), seen
            if kind == 0x0001 and len(body) >= 8:        # MAPPED-ADDRESS
                return (socket.inet_ntoa(body[4:8]),
                        struct.unpack("!H", body[2:4])[0])
            walk += 4 + size + ((4 - size % 4) % 4)
    return None


def reachable_from_outside(port=DEFAULT_PORT):
    """Can somebody out there aim at this machine on this port?

    Not a promise - only the network in front of this machine can say for
    certain, and a firewall may still refuse. But if the port number is
    kept on the way out, an incoming connection has somewhere to land, and
    hosting straight from here is worth trying before anything else.
    """
    answer = public_address(port=port)
    if answer is None:
        return None, None
    address, seen = answer
    return address, seen == port


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
        self.link = None                # the relay, when playing over the net
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

    def open_relay(self, address, port=None, room=None):
        """Host through a meeting point instead of listening for callers.

        Returns None, or why it could not. The room name doubles as the
        thing a joiner has to know, so it is made from the session secret
        rather than being anything guessable.
        """
        room = room or base64.b32encode(self.secret).decode().rstrip("=")
        link = RelayLink(self, address, port or RELAY_PORT, room)
        why = link.open()
        if why is not None:
            return why
        self.link = link
        return None

    def _relay_peer(self, number):
        """Whoever is seated under this relay number, if anybody."""
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
        socket of their own, one from the internet arrives down the relay,
        and neither should be let in on different terms.
        """
        sock = peer.sock
        address = peer.address
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
        self.host = None            # the host's profile card
        self.seat = None            # our own card, as the host sees it
        self.peers = []
        self.faces = {}             # token -> where their picture landed
        self.host_version = None
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
        if is_relay_code(code):
            # Through a meeting point: ask for the session first, and after
            # that the conversation is the same as any other.
            room = base64.b32encode(secret).decode().rstrip("=")
            send_line(sock, {"relay": "join", "room": room})
            waiting = LineReader(sock)
            while True:
                batch = waiting.read()
                if batch is None:
                    _shutdown(sock)
                    return "the relay closed the connection"
                answer = None
                for message in batch:
                    if message.get("relay") in ("no", "joined"):
                        answer = message
                        break
                if answer is None:
                    continue
                if answer["relay"] == "no":
                    _shutdown(sock)
                    return answer.get("why", "the relay turned you away")
                break
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
        if self.sock is None:
            return False
        if send_line(self.sock, message):
            return True
        self._dropped("the connection went down")
        return False

    def close(self):
        self._running = False
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
# playing with people who are not on your network
# ==========================================================================
RELAY_PORT = 7788


class RelayPeer:
    """A joiner who is not on the end of a socket of our own.

    Their messages arrive down the host's single line to the relay, tagged
    with which of them sent it, and replies go back the same way. To the
    rest of the code it behaves exactly like a peer on its own socket.
    """

    def __init__(self, link, number):
        self.link = link
        self.number = number
        self.sock = None
        self.address = ("relay", number)
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


class RelayLink:
    """The host's one line out to the relay.

    Everybody dials out to the meeting point - the host included - so no
    connection ever has to come in to a home machine, which is the whole
    reason this works where a forwarded port does not.
    """

    def __init__(self, server, address, port, room):
        self.server = server
        self.address = address
        self.port = port
        self.room = room
        self.sock = None
        self.waiting = {}       # relay's number -> the hello we are expecting
        self._lock = threading.Lock()
        self._running = False

    def open(self, timeout=8.0):
        """Dial the relay and claim the room. Returns None, or why not."""
        try:
            sock = socket.create_connection((self.address, self.port),
                                            timeout=timeout)
        except OSError as exc:
            return "could not reach the relay at %s port %d (%s)" % (
                self.address, self.port, exc)
        sock.settimeout(timeout)
        send_line(sock, {"relay": "host", "room": self.room})
        reader = LineReader(sock)
        while True:
            batch = reader.read()
            if batch is None:
                _shutdown(sock)
                return "the relay closed the connection"
            for message in batch:
                if message.get("relay") == "no":
                    _shutdown(sock)
                    return message.get("why", "the relay turned us away")
                if message.get("relay") == "hosting":
                    self.sock = sock
                    self._running = True
                    sock.settimeout(None)
                    threading.Thread(target=self._listen, args=(reader,),
                                     daemon=True).start()
                    return None

    def close(self):
        self._running = False
        if self.sock is not None:
            _shutdown(self.sock)
            self.sock = None

    def to_peer(self, number, message):
        with self._lock:
            if self.sock is None:
                return False
            return send_line(self.sock, {"peer": number, "body": message})

    def _listen(self, reader):
        while self._running:
            batch = reader.read()
            if batch is None:
                break
            for message in batch:
                self._handle(message)
        self._running = False

    def _handle(self, message):
        kind = message.get("relay")
        number = message.get("peer")
        if kind == "arrived":
            self.waiting[number] = RelayPeer(self, number)
            return
        if kind == "gone":
            peer = self.waiting.pop(number, None)
            seated = self.server._relay_peer(number)
            if seated is not None:
                self.server._lost(seated)
            elif peer is not None:
                peer.close()
            return
        if kind != "from":
            return
        body = message.get("body") or {}
        seated = self.server._relay_peer(number)
        if seated is not None:
            body["from"] = seated.token
            self.server.inbox.put(body)
            return
        # Not seated yet, so this should be their hello.
        peer = self.waiting.get(number)
        if peer is None or body.get("kind") != "hello":
            return
        if self.server._admit(peer, body):
            self.waiting.pop(number, None)
        else:
            self.waiting.pop(number, None)
