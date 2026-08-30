"""Working out whether people can actually reach you, and fixing it if not.

Hosting a game means somebody far away has to be able to open a connection
*to* this machine. Dialling out is easy and nearly always allowed; being
dialled into is neither. Three separate things have to line up:

  * a router that will pass the connection on to this machine
  * Windows agreeing to accept it, on the network you are currently on
  * nothing in between quietly dropping it

Each one fails in its own way and none of them say so out loud, which is why
this exists. Everything here answers a question a person would actually ask
- "will my friend be able to join?" - rather than reporting a number.

Nothing in here changes anything on its own. The checks only look; the
fixes are separate calls, so the window can ask first.
"""

import io
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import urllib.request

import netplay
import paths

# Where Tailscale comes from. Their own site, over https - this is the same
# file a person would download by hand, and the address is shown before
# anything is fetched so it can be checked.
TAILSCALE_URL = ("https://pkgs.tailscale.com/stable/"
                 "tailscale-setup-latest-amd64.msi")
TAILSCALE_HOME = "https://tailscale.com/download/windows"

# Addresses handed out by an internet provider's own shared network rather
# than by a router in your house. Nobody can forward a port on one of these.
CARRIER_RANGE = (100, 64, 127)          # 100.64.0.0/10

# How many machines a household network holds. A house is a /24 - 256
# addresses. Anything bigger is a building, a campus or a provider, and the
# router will not be yours.
HOME_NETWORK = 256

# Somewhere out there that answers on every port, so dialling out can be
# tested on the ports this app really uses.
OUTBOUND_HOST = "portquiz.net"

SSDP_ADDRESS = ("239.255.255.250", 1900)
SSDP_TARGETS = (
    "urn:schemas-upnp-org:device:InternetGatewayDevice:1",
    "urn:schemas-upnp-org:device:InternetGatewayDevice:2",
    "upnp:rootdevice",
)


def _quiet():
    """Keep subprocesses from flashing a console window up on Windows."""
    if os.name != "nt":
        return {}
    info = subprocess.STARTUPINFO()
    info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    return {"startupinfo": info,
            "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}


def _run(command, timeout=20):
    """A command's output, or "" if it could not be run at all."""
    try:
        done = subprocess.run(command, capture_output=True, text=True,
                              timeout=timeout, **_quiet())
    except (OSError, subprocess.SubprocessError):
        return ""
    return done.stdout or ""


def _powershell(script, timeout=25):
    return _run(["powershell", "-NoProfile", "-NonInteractive",
                 "-Command", script], timeout=timeout)


# --------------------------------------------------------------------------
# where this machine sits
# --------------------------------------------------------------------------
def is_private(address):
    """An address that only means something on the local network."""
    try:
        parts = [int(p) for p in address.split(".")]
    except ValueError:
        return False
    if len(parts) != 4:
        return False
    a, b = parts[0], parts[1]
    if a == 10 or a == 127:
        return True
    if a == 192 and b == 168:
        return True
    if a == 172 and 16 <= b <= 31:
        return True
    if a == 169 and b == 254:
        return True
    return False


def is_carrier(address):
    """An address from the provider's own shared pool.

    A machine on one of these is behind a NAT belonging to the provider, not
    to anybody in the building. There is no router to forward a port on and
    no amount of settings will produce one.
    """
    try:
        parts = [int(p) for p in address.split(".")]
    except ValueError:
        return False
    first, second = parts[0], parts[1] if len(parts) > 1 else 0
    base, low, high = CARRIER_RANGE
    return first == base and low <= second <= high


def is_tailscale(address):
    """Tailscale hands out addresses from 100.64/10 as well, so the range
    alone cannot tell the two apart - only asking Tailscale can."""
    return is_carrier(address)


def gateway():
    """The address this machine sends everything else through."""
    out = _powershell(
        "(Get-NetIPConfiguration | Where-Object {$_.IPv4DefaultGateway} | "
        "Select-Object -First 1).IPv4DefaultGateway.NextHop")
    found = re.search(r"\d+\.\d+\.\d+\.\d+", out)
    return found.group(0) if found else None


def subnet_size():
    """How many machines share this network.

    A house is a /24 - 254 addresses. Anything markedly bigger is a building,
    a campus or a provider's own network, which is worth knowing because it
    is never yours to configure.
    """
    out = _powershell(
        "(Get-NetIPConfiguration | Where-Object {$_.IPv4DefaultGateway} | "
        "Select-Object -First 1).IPv4Address.PrefixLength")
    found = re.search(r"\d+", out)
    if not found:
        return None
    prefix = int(found.group(0))
    return 2 ** (32 - prefix)


# --------------------------------------------------------------------------
# can anything get out, and what does the world see
# --------------------------------------------------------------------------
def outbound(port, host=OUTBOUND_HOST, timeout=6):
    """Can this machine dial out on this port?

    Almost always yes. When it is no, nothing else matters - a network that
    will not let you out will certainly not let anybody in.
    """
    probe = socket.socket()
    probe.settimeout(timeout)
    try:
        probe.connect((host, port))
        return True
    except OSError:
        return False
    finally:
        probe.close()


def public_address(port):
    """What the outside world sees this machine as, and whether the port
    number survived the trip."""
    answer = netplay.public_address(port=port)
    if answer is None:
        return None, None
    return answer


# --------------------------------------------------------------------------
# a router that will open a port for you
# --------------------------------------------------------------------------
def find_router(timeout=4):
    """A router on this network offering to forward ports, if there is one.

    This is the most telling question of the lot. A router in your own home
    answers; the box in a building's cupboard does not, because it is not
    yours and was never meant to take instructions from the flats.

    Returns the address of its description document, or None.
    """
    message = ("M-SEARCH * HTTP/1.1\r\n"
               "HOST: %s:%d\r\n"
               'MAN: "ssdp:discover"\r\n'
               "MX: 2\r\n"
               "ST: %s\r\n\r\n")
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.settimeout(timeout)
    try:
        for target in SSDP_TARGETS:
            try:
                sock.sendto((message % (SSDP_ADDRESS[0], SSDP_ADDRESS[1],
                                        target)).encode(), SSDP_ADDRESS)
            except OSError:
                return None
        while True:
            try:
                data, _who = sock.recvfrom(65535)
            except (socket.timeout, OSError):
                return None
            text = data.decode("utf-8", "replace")
            if "InternetGatewayDevice" not in text and "WANIP" not in text:
                continue
            found = re.search(r"(?im)^location:\s*(\S+)", text)
            if found:
                return found.group(1)
    finally:
        sock.close()


def _router_service(description_url, timeout=6):
    """The part of the router that actually opens ports."""
    try:
        with urllib.request.urlopen(description_url, timeout=timeout) as page:
            body = page.read().decode("utf-8", "replace")
    except Exception:
        return None, None
    for kind in ("WANIPConnection:1", "WANIPConnection:2",
                 "WANPPPConnection:1"):
        spot = body.find(kind)
        if spot < 0:
            continue
        control = re.search(r"<controlURL>\s*([^<]+)\s*</controlURL>",
                            body[spot:])
        if not control:
            continue
        path = control.group(1).strip()
        root = re.match(r"(https?://[^/]+)", description_url)
        if not root:
            return None, None
        if not path.startswith("/"):
            path = "/" + path
        return root.group(1) + path, "urn:schemas-upnp-org:service:" + kind
    return None, None


def forward_port(port, address=None, description_url=None, timeout=8):
    """Ask the router to send this port through to this machine.

    Returns (True, message) if it agreed. This is what a game does when it
    opens its own port, and it is undone by `unforward_port`.
    """
    description_url = description_url or find_router()
    if not description_url:
        return False, "no router here offers to forward ports"
    control, service = _router_service(description_url)
    if not control:
        return False, "the router answered but will not open ports"
    address = address or (netplay.local_addresses() or [None])[0]
    if not address:
        return False, "could not work out this machine's address"
    body = (
        '<?xml version="1.0"?>'
        '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
        's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">'
        '<s:Body><u:AddPortMapping xmlns:u="%s">'
        "<NewRemoteHost></NewRemoteHost>"
        "<NewExternalPort>%d</NewExternalPort>"
        "<NewProtocol>TCP</NewProtocol>"
        "<NewInternalPort>%d</NewInternalPort>"
        "<NewInternalClient>%s</NewInternalClient>"
        "<NewEnabled>1</NewEnabled>"
        "<NewPortMappingDescription>%s</NewPortMappingDescription>"
        "<NewLeaseDuration>0</NewLeaseDuration>"
        "</u:AddPortMapping></s:Body></s:Envelope>"
        % (service, port, port, address, paths.APP_NAME))
    request = urllib.request.Request(
        control, data=body.encode(),
        headers={"Content-Type": 'text/xml; charset="utf-8"',
                 "SOAPAction": '"%s#AddPortMapping"' % service})
    try:
        with urllib.request.urlopen(request, timeout=timeout):
            return True, "the router is now sending port %d here" % port
    except Exception as trouble:
        return False, "the router refused: %s" % trouble


def unforward_port(port, description_url=None, timeout=8):
    """Take the forwarding back off again."""
    description_url = description_url or find_router()
    if not description_url:
        return False
    control, service = _router_service(description_url)
    if not control:
        return False
    body = (
        '<?xml version="1.0"?>'
        '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
        's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">'
        '<s:Body><u:DeletePortMapping xmlns:u="%s">'
        "<NewRemoteHost></NewRemoteHost>"
        "<NewExternalPort>%d</NewExternalPort>"
        "<NewProtocol>TCP</NewProtocol>"
        "</u:DeletePortMapping></s:Body></s:Envelope>" % (service, port))
    request = urllib.request.Request(
        control, data=body.encode(),
        headers={"Content-Type": 'text/xml; charset="utf-8"',
                 "SOAPAction": '"%s#DeletePortMapping"' % service})
    try:
        with urllib.request.urlopen(request, timeout=timeout):
            return True
    except Exception:
        return False


# --------------------------------------------------------------------------
# Windows' own opinion
# --------------------------------------------------------------------------
def network_profile():
    """Whether Windows counts this network as Private or Public.

    It matters more than it looks. A rule allowing the app through on a
    Private network does nothing at all on a Public one, and Windows will
    not ask again once any rule exists - so it fails silently, with no
    notification, which is exactly what it looks like when nothing is wrong.
    """
    out = _powershell("(Get-NetConnectionProfile | "
                      "Select-Object -First 1).NetworkCategory")
    name = out.strip().splitlines()
    return name[0].strip() if name and name[0].strip() else None


def firewall_state():
    """Is this app allowed to accept connections on the network it is on?

    Returns (allowed, profile, rules) - `allowed` is None when it could not
    be worked out at all rather than False, because "we could not tell" and
    "you are blocked" call for different advice.
    """
    profile = network_profile()
    programs = _firewall_names()
    if not programs:
        return None, profile, []
    # PowerShell ends a quoted string at an apostrophe, and the app's own
    # name has one in it - doubling them is how PowerShell escapes its own
    # quote. Without this the query matches nothing and every machine looks
    # blocked.
    pattern = "|".join(re.escape(name) for name in programs)
    out = _powershell(
        "Get-NetFirewallRule -Direction Inbound -Enabled True -Action Allow "
        "-ErrorAction SilentlyContinue | Where-Object { $_.DisplayName "
        "-match '%s' } | Select-Object DisplayName,Profile | ConvertTo-Json"
        % pattern.replace("'", "''"))
    rules = _parse_rules(out)
    if not rules:
        return False, profile, []
    if profile is None:
        return None, profile, rules
    for rule in rules:
        if covers_profile(rule.get("Profile"), profile):
            return True, profile, rules
    return False, profile, rules


# Which networks a firewall rule applies to. PowerShell hands this back as a
# name when asked for text and as a bitmask when asked for JSON, so both have
# to be understood - and a rule for Private does nothing at all on a Public
# network, which is the whole reason this is checked.
PROFILE_BITS = {"domain": 1, "private": 2, "public": 4}
PROFILE_ANY = (0, 2147483647)


def covers_profile(rule_profile, network):
    """Does a rule set to `rule_profile` apply on a `network` network?"""
    if rule_profile is None or network is None:
        return False
    wanted = PROFILE_BITS.get(network.strip().lower())
    if isinstance(rule_profile, bool):
        return False
    if isinstance(rule_profile, int):
        if rule_profile in PROFILE_ANY:
            return True
        return bool(wanted and rule_profile & wanted)
    text = str(rule_profile).strip().lower()
    if not text:
        return False
    if text in ("any", "all"):
        return True
    return network.strip().lower() in [
        piece.strip() for piece in text.split(",")]


def _firewall_names():
    """What a firewall rule for this app would be called.

    Built into a program it is the program; run from source it is Python
    itself, because that is the thing holding the socket open.
    """
    if getattr(sys, "frozen", False):
        return [os.path.basename(sys.executable), paths.APP_NAME]
    return ["python.exe", "pythonw.exe", paths.APP_NAME]


def _parse_rules(text):
    text = (text or "").strip()
    if not text:
        return []
    try:
        found = json.loads(text)
    except ValueError:
        return []
    if isinstance(found, dict):
        return [found]
    return [r for r in found if isinstance(r, dict)]


def firewall_allow():
    """Ask Windows to let this app be dialled into, on every profile.

    Needs an administrator, so this puts up the usual prompt. Returns
    (True, message) once the rule is really there rather than once the
    prompt has been answered - agreeing to it and it silently failing are
    otherwise indistinguishable.
    """
    if os.name != "nt":
        return False, "this only applies to Windows"
    targets = []
    if getattr(sys, "frozen", False):
        targets.append((paths.APP_NAME, sys.executable))
    else:
        base = os.path.dirname(sys.executable)
        for name in ("python.exe", "pythonw.exe"):
            full = os.path.join(base, name)
            if os.path.exists(full):
                targets.append(("%s (%s)" % (paths.APP_NAME, name), full))
    if not targets:
        return False, "could not work out what to allow"
    # Written to a file and run, rather than threaded through PowerShell into
    # cmd into netsh. The app's name has an apostrophe and a space in it and
    # the rule names have brackets; getting all of that through four levels
    # of quoting intact is not worth attempting, and it silently produced a
    # mangled rule name when it was tried.
    lines = ["@echo off"]
    for label, program in targets:
        lines.append('netsh advfirewall firewall delete rule name="%s" '
                     ">nul 2>&1" % label)
        lines.append('netsh advfirewall firewall add rule name="%s" dir=in '
                     'action=allow profile=any program="%s" enable=yes'
                     % (label, program))
    script = os.path.join(tempfile.gettempdir(),
                          "vtt-allow-%d.bat" % os.getpid())
    try:
        with io.open(script, "w", encoding="ascii", newline="\r\n") as out:
            out.write("\r\n".join(lines) + "\r\n")
    except OSError as trouble:
        return False, "could not write the fix: %s" % trouble
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Start-Process -FilePath '%s' -Verb RunAs -Wait "
             "-WindowStyle Hidden" % script.replace("'", "''")],
            capture_output=True, text=True, timeout=120, **_quiet())
    except (OSError, subprocess.SubprocessError) as trouble:
        return False, "could not ask for permission: %s" % trouble
    finally:
        try:
            os.remove(script)
        except OSError:
            pass
    allowed, profile, _rules = firewall_state()
    if allowed:
        return True, "Windows will now let people reach this app"
    return False, ("the rule was not added - the permission prompt was "
                   "probably turned down")


def firewall_steps():
    """How to allow the app by hand, for when the button will not do.

    Somebody without an administrator account cannot use the button at all,
    and this is the same job done through the settings - worth having in
    words so it can be read out to whoever does have the password.
    """
    if getattr(sys, "frozen", False):
        program = sys.executable
    else:
        program = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    return [
        "Open Start and type: Windows Defender Firewall",
        "Choose 'Allow an app or feature through Windows Defender Firewall'",
        "Press 'Change settings', then 'Allow another app...'",
        "Press 'Browse...' and pick this file:",
        "    %s" % program,
        "Press 'Add'",
        "Tick BOTH boxes beside it - Private and Public",
        "Press OK",
        "",
        "Ticking both is the part people miss. A tick against Private only "
        "does nothing on a Public network, and Windows never asks again "
        "once any entry exists - so it goes on refusing people in silence.",
    ]


# --------------------------------------------------------------------------
# Tailscale: a way round all of it
# --------------------------------------------------------------------------
def tailscale_program():
    """Where Tailscale is, if it is here at all."""
    for place in (r"C:\Program Files\Tailscale\tailscale.exe",
                  r"C:\Program Files (x86)\Tailscale\tailscale.exe"):
        if os.path.exists(place):
            return place
    found = _run(["where", "tailscale.exe"], timeout=8).strip().splitlines()
    return found[0].strip() if found else None


def tailscale_state():
    """What Tailscale is doing, in the three states that matter.

    Returns (state, address) where state is one of:
      "missing"   - not installed
      "signed"    - installed but not signed in yet
      "ready"     - signed in, with an address people can reach you on
    """
    program = tailscale_program()
    if not program:
        return "missing", None
    out = _run([program, "status", "--json"], timeout=15)
    if not out.strip():
        return "signed", None
    try:
        status = json.loads(out)
    except ValueError:
        return "signed", None
    if status.get("BackendState") != "Running":
        return "signed", None
    me = status.get("Self") or {}
    for address in me.get("TailscaleIPs") or []:
        if ":" not in address:
            return "ready", address
    return "signed", None


def download_tailscale(into=None, url=TAILSCALE_URL, progress=None):
    """Fetch Tailscale's own installer.

    Downloaded, not run - installing is a separate step so the window can
    say what is about to happen and let it be turned down.
    """
    into = into or os.path.join(paths.APP_DIR, "tailscale-setup.msi")
    try:
        with urllib.request.urlopen(url, timeout=60) as source:
            total = int(source.headers.get("Content-Length") or 0)
            got = 0
            with open(into, "wb") as target:
                while True:
                    lump = source.read(64 * 1024)
                    if not lump:
                        break
                    target.write(lump)
                    got += len(lump)
                    if progress:
                        progress(got, total)
    except Exception as trouble:
        return None, "could not download it: %s" % trouble
    return into, "downloaded"


def install_tailscale(installer):
    """Run the installer that was just downloaded.

    Windows asks for permission; this waits for the answer either way.
    """
    if not installer or not os.path.exists(installer):
        return False, "the installer is not there"
    try:
        subprocess.run(["msiexec", "/i", installer, "/passive", "/norestart"],
                       capture_output=True, text=True, timeout=600, **_quiet())
    except (OSError, subprocess.SubprocessError) as trouble:
        return False, "could not run the installer: %s" % trouble
    if tailscale_program():
        return True, "Tailscale is installed"
    return False, "the installer finished but Tailscale is not there"


def tailscale_sign_in():
    """Open the sign-in page. It happens in a browser, not in here."""
    program = tailscale_program()
    if not program:
        return False, "Tailscale is not installed"
    try:
        subprocess.Popen([program, "up"], **_quiet())
    except (OSError, subprocess.SubprocessError) as trouble:
        return False, "could not start it: %s" % trouble
    return True, "sign in with the browser window that just opened"


# --------------------------------------------------------------------------
# putting it together
# --------------------------------------------------------------------------
# What a single check came back as. `state` is one of "good", "warn", "bad"
# or "note", and `detail` is the one line a person reads.
def _finding(state, title, detail):
    return {"state": state, "title": title, "detail": detail}


# What to do about it, in the order worth trying.
HOST_HERE = "host"          # people can be told to join you as things are
FORWARD = "forward"         # a router is here and willing - open the port
FIREWALL = "firewall"       # Windows is the thing in the way
TAILSCALE = "tailscale"     # nothing here can be opened; go round it instead
JOIN_ONLY = "join"          # you can join others but cannot be joined


def diagnose(port=None, report=None):
    """Every check, in order, and a verdict at the end.

    `report` is called with each finding as it lands so a window can fill in
    while the slow ones are still running. The whole thing takes a few
    seconds, most of it waiting on the network.
    """
    port = port or netplay.DEFAULT_PORT
    findings = []

    def add(state, title, detail):
        found = _finding(state, title, detail)
        findings.append(found)
        if report:
            report(found)
        return found

    # 1. Where this machine sits.
    addresses = netplay.local_addresses()
    here = addresses[0] if addresses else None
    ts_state, ts_address = tailscale_state()
    if ts_state == "ready" and ts_address:
        add("good", "Tailscale is running",
            "You can be reached on %s from anywhere, whatever this network "
            "does. This is the address to host on." % ts_address)
    if here:
        add("note", "This machine",
            "%s on the local network" % here)

    # 2. Can anything get out at all.
    if not outbound(port):
        add("bad", "Nothing can get out",
            "This network will not even let you dial out on port %d. You "
            "will not be able to host or join until that changes." % port)
        return {"findings": findings, "verdict": None, "port": port,
                "tailscale": ts_state, "tailscale_address": ts_address}
    add("good", "You can reach other people",
        "Joining somebody else's game works from here.")

    # 3. What the world sees.
    public, kept = public_address(port)
    if public is None:
        add("warn", "Could not find your public address",
            "Nothing answered when asked. You may be offline, or something "
            "is blocking the question.")
    else:
        add("note", "The internet sees you as", public)

    # 4. Is there a router here that will open a port.
    router = find_router()
    shared = subnet_size()
    carrier = bool(here and is_carrier(here) and ts_state != "ready")
    if router:
        add("good", "There is a router here you control",
            "It offers to forward ports, so the port can be opened without "
            "you going near its settings page.")
    elif carrier:
        add("bad", "Your provider shares one connection between many homes",
            "Your address comes from their pool, so there is no router "
            "anywhere that could send a port to you. Forwarding is not "
            "possible on this connection - not by you, and not by them.")
    elif shared and shared > HOME_NETWORK:
        add("bad", "This is somebody else's network",
            "You are on a network shared by about %d machines, and nothing "
            "on it offers to forward a port. That is a building, campus or "
            "provider network - the router is not yours to configure."
            % shared)
    else:
        add("warn", "No router here offers to open a port",
            "There may still be one you can set up by hand, but nothing "
            "answered when asked politely.")

    # 5. Windows' own opinion.
    allowed, profile, _rules = firewall_state()
    if allowed is True:
        add("good", "Windows will let people in",
            "This app is allowed to accept connections on your %s network."
            % (profile or "current"))
    elif allowed is False and profile:
        add("bad", "Windows is blocking connections in",
            "This app is not allowed to accept connections on your %s "
            "network. Windows will not ask you about it either - it only "
            "asks once, so a session simply times out with nothing said."
            % profile)
    else:
        add("warn", "Could not tell what Windows will do",
            "The firewall could not be read. Worth allowing the app by hand "
            "if people cannot reach you.")

    # 6. And so.
    if ts_state == "ready":
        verdict = HOST_HERE
    elif carrier or (shared and shared > HOME_NETWORK and not router):
        verdict = TAILSCALE
    elif allowed is False:
        verdict = FIREWALL
    elif router:
        verdict = FORWARD
    elif kept:
        verdict = HOST_HERE
    else:
        verdict = JOIN_ONLY

    return {"findings": findings, "verdict": verdict, "port": port,
            "public": public, "router": router, "firewall": allowed,
            "profile": profile, "tailscale": ts_state,
            "tailscale_address": ts_address, "shared": shared,
            "carrier": carrier}


# The plain-words version of each verdict, and what the window offers to do.
ADVICE = {
    HOST_HERE: ("You can host",
                "Give people your invite code and they should get straight "
                "in."),
    FORWARD: ("Your router needs to let people through",
              "There is a router here that will do it on request - one "
              "button and it is done."),
    FIREWALL: ("Windows is turning people away",
               "Everything else is fine. Allowing this app through the "
               "firewall should be the whole fix."),
    TAILSCALE: ("You cannot be reached on this network",
                "Nothing you can change here will fix that - there is no "
                "router of yours in the way to open. Tailscale gives you an "
                "address that works anyway, it is free, and both of you "
                "install it once."),
    JOIN_ONLY: ("You can join, but probably cannot be joined",
                "Let whoever has an ordinary home connection host, and join "
                "them instead - or use Tailscale so it stops mattering."),
}
