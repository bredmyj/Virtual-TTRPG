"""What the app knows about who else is playing.

One object, whether you are hosting, joining, or on your own - so nothing
else in the app has to keep asking which it is. Playing alone is a real
session with one person in it, and the same calls all work.

The network runs on its own threads and can deliver a message at any moment,
including halfway through a redraw. Everything arrives in a queue and is
drained here on Tk's own clock, so by the time a handler runs it is on the
UI thread like any other event.
"""

import netplay

PUMP_MS = 40                # how often the queue is drained
CURSOR_MS = 60              # the fastest we will tell anyone where our mouse is


class Session:
    """Everyone at the table, and the wire between them."""

    def __init__(self, app, plan=None):
        self.app = app
        self.plan = plan or {"mode": "solo"}
        self.mode = self.plan.get("mode", "solo")
        self.profile = netplay.Profile.load()
        self.server = None
        self.client = None
        self.host_card = None
        self.error = None           # why hosting failed, if it did
        self.code = None
        self.address = None
        self.listeners = {}         # kind -> [callback]
        self.announcements = []     # ("text", colour) waiting to be shown
        self._pumping = False
        self._roles = {}            # token -> role, the host's own record

    # ------------------------------------------------------------------
    # starting up
    # ------------------------------------------------------------------
    def start(self):
        if self.mode == "host":
            self._start_hosting()
        elif self.mode == "join":
            self.client = self.plan.get("client")
            if self.client is None:
                self.mode = "solo"
            else:
                self.host_card = self.client.host or {}
        if self.mode != "solo":
            self._pump()

    def _start_hosting(self):
        self.server = netplay.Server(self.profile,
                                     port=self.plan.get("port",
                                                        netplay.DEFAULT_PORT),
                                     campaign=self.plan.get("campaign", ""))
        relay = self.plan.get("relay")
        if relay:
            # Over the internet: everybody dials out to a meeting point, so
            # this machine never has to be reachable from outside.
            why = self.server.open_relay(relay,
                                         self.plan.get("relay_port")
                                         or netplay.RELAY_PORT)
            if why is not None:
                self.error = why
                self.server = None
                self.mode = "solo"
                return
            self.address = relay
            self.code = netplay.make_relay_code(
                relay, self.plan.get("relay_port") or netplay.RELAY_PORT,
                self.server.secret)
            self._roles[self.profile.token] = "GM"
            return

        self.address = self.plan.get("address") or netplay.local_addresses()[0]
        try:
            self.server.start("")       # every adapter: wifi and cable both
        except OSError as exc:
            # Almost always the port already being in use - another copy of
            # the app still hosting, most likely.
            self.error = str(exc)
            self.server = None
            self.mode = "solo"
            return
        self.code = self.server.code_for(self.address)
        self._roles[self.profile.token] = "GM"

    def close(self):
        self._pumping = False
        if self.server is not None:
            self.server.stop()
            self.server = None
        if self.client is not None:
            self.client.close()
            self.client = None

    # ------------------------------------------------------------------
    # who is here
    # ------------------------------------------------------------------
    @property
    def is_host(self):
        return self.server is not None

    @property
    def is_solo(self):
        return self.server is None and self.client is None

    @property
    def my_token(self):
        return self.profile.token

    def my_role(self):
        if self.is_solo:
            return "GM"
        if self.is_host:
            # Whatever the host has given themselves. They start as the GM
            # but may hand the chair over and sit down as a player.
            return self.server.host_role
        for card in self.people():
            if card.get("token") == self.my_token:
                return card.get("role")
        return None

    def am_gm(self):
        """Playing alone you are your own GM, so this is true by default."""
        return self.my_role() == "GM"

    def people(self):
        """Everyone at the table, host first, each with a local picture path.

        The same list on every machine and in the same order, so the row of
        faces does not jump about depending on who is looking at it.
        """
        if self.is_solo:
            return [self._me_card(host=True, role="GM")]

        if self.is_host:
            cards = [self._me_card(host=True, role=self.server.host_role)]
            for card in self.server.roster():
                card = dict(card)
                card["host"] = False
                card["picture"] = self.server.face_of(card["token"])
                cards.append(card)
            return cards

        # Read afresh: the host's own role can change mid-session, and the
        # card kept from the welcome would still say GM.
        host = dict(self.client.host or self.host_card or {})
        host["host"] = True
        host.setdefault("role", "GM")
        host["picture"] = self.client.faces.get(host.get("token"))
        cards = [host]
        for card in self.client.peers:
            card = dict(card)
            card["host"] = False
            if card.get("token") == self.my_token:
                card["picture"] = self.profile.picture
            else:
                card["picture"] = self.client.faces.get(card.get("token"))
            cards.append(card)
        return cards

    def _me_card(self, host=False, role=None):
        card = self.profile.card()
        card["picture"] = self.profile.picture
        card["host"] = host
        card["role"] = role or self._roles.get(self.my_token)
        return card

    def person(self, token):
        for card in self.people():
            if card.get("token") == token:
                return card
        return None

    def set_role(self, token, role):
        """Only the host decides who is what.

        A role belongs to one person: giving somebody a seat takes it from
        whoever was in it, the GM chair included. Otherwise the table would
        end up with two GMs, both of them able to build.
        """
        if not self.is_host:
            return False
        if role is not None:
            self._clear_role(role, keep=token)
        if token == self.my_token:
            self.server.host_role = role
            self.announce("You are now the %s." % (role or "nothing"))
        elif not self.server.set_role(token, role):
            return False
        else:
            who = self.person(token)
            self.announce("%s is now the %s."
                          % ((who or {}).get("name", "Someone"),
                             role or "nothing"))
        self._keep_a_gm()
        self.server.tell_roster()
        self.emit_local("roster", {})
        return True

    def _keep_a_gm(self):
        """Somebody has to be the GM.

        Handing the chair to a player and later making that player something
        else would otherwise leave the table with nobody able to build. The
        host takes it back rather than letting that happen.
        """
        if self.server.host_role == "GM":
            return
        if any(card.get("role") == "GM" for card in self.server.roster()):
            return
        self.server.host_role = "GM"

    def _clear_role(self, role, keep=None):
        """Take this role off whoever currently holds it."""
        if self.server.host_role == role and keep != self.my_token:
            self.server.host_role = None
        for card in self.server.roster():
            if card.get("role") == role and card.get("token") != keep:
                self.server.set_role(card["token"], None)

    def remove(self, token):
        if not self.is_host or token == self.my_token:
            return False
        return self.server.drop(token)

    # ------------------------------------------------------------------
    # talking
    # ------------------------------------------------------------------
    def on(self, kind, callback):
        """Run `callback(message)` whenever a message of this kind arrives."""
        self.listeners.setdefault(kind, []).append(callback)

    def off(self, kind, callback):
        if callback in self.listeners.get(kind, []):
            self.listeners[kind].remove(callback)

    def send(self, message):
        """To everyone else, whichever end we are."""
        if self.is_host:
            self.server.broadcast(message)
            return True
        if self.client is not None:
            return self.client.send(message)
        return False

    def send_to(self, token, message):
        if self.is_host:
            return self.server.send_to(token, message)
        return False

    def relay(self, message, skip=None):
        """Host only: pass something on to everyone but whoever sent it."""
        if self.is_host:
            self.server.broadcast(message, skip=skip)

    def announce(self, text, colour=None):
        self.announcements.append((text, colour))
        self.emit_local("announce", {"text": text, "colour": colour})

    def emit_local(self, kind, message):
        """Fire handlers for something that happened on this machine."""
        for callback in list(self.listeners.get(kind, [])):
            try:
                callback(message)
            except Exception as exc:            # a bad handler is not fatal
                print("[session] %s handler failed: %s" % (kind, exc))

    # ------------------------------------------------------------------
    # draining the queue
    # ------------------------------------------------------------------
    def _pump(self):
        if self._pumping:
            return
        self._pumping = True
        self._tick()

    def _tick(self):
        if not self._pumping:
            return
        box = self.server.inbox if self.is_host else (
            self.client.inbox if self.client is not None else None)
        if box is not None:
            # A cap, so a flood of cursor updates can never lock up the
            # window - whatever is left waits for the next tick.
            for _ in range(200):
                try:
                    message = box.get_nowait()
                except Exception:
                    break
                self._handle(message)
        try:
            self.app.after(PUMP_MS, self._tick)
        except Exception:
            self._pumping = False       # the window has gone

    def _handle(self, message):
        kind = message.get("kind")

        if kind == "joined":
            who = message.get("peer") or {}
            self.announce("%s joined your campaign."
                          % who.get("name", "Someone"), colour="crit")
            self.emit_local("roster", message)
        elif kind == "left":
            who = message.get("peer") or {}
            self.announce("%s left." % who.get("name", "Someone"))
            self.emit_local("roster", message)
        elif kind == "roster":
            self.emit_local("roster", message)
        elif kind == "face":
            self.emit_local("roster", message)
        elif kind == "bye":
            self.announce("Disconnected: %s"
                          % message.get("why", "the host closed"),
                          colour="fumble")
            self.client = None
            self.emit_local("roster", message)
        elif kind == "dropped":
            self.announce("Lost the connection to the host.", colour="fumble")
            self.emit_local("roster", message)

        self.emit_local(kind, message)
