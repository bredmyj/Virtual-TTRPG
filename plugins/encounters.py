"""Encounters - build a fight, roll for initiative, then run it round by round.

Opens from Tools > Encounters, next to the Adventuring Journal and the Game
Map. One window, four parts and no tabs:

  * the roster (left half)  - the creatures in this encounter. Adding one
                              turns this side into the library picker, and
                              turns back once the creatures are in.
  * the creature (right)    - everything the selected creature carries: its
                              ability scores, its stats, the things it can do
                              and a description. Most numbers have a Roll
                              beside them.
  * the summary (bottom)    - a few lines on what is going on, who started it
                              and what the room looks like.
  * the turn bar (below it) - only there once the encounter is running: the
                              round, whose turn it is, and Next.

Creatures in an encounter are copies. Wounding the goblin here never touches
the goblin in the library, so the same entry can be pulled in again next week
at full health.

Players come in the same way creatures do. Add player offers the characters
already standing on the game map, along with whoever is at the table without
one yet, so a fight can be set up without typing anybody's name twice.

Which numbers a creature carries is the game's business, not this window's, so
it lives in a system preset: the ability scores, how a score becomes a
modifier, and what a new creature starts with. Dungeons & Dragons is the one
set up to begin with; make your own for anything else.

Everything belongs to the campaign that is currently open, so each save file
has its own library, its own systems and its own encounter in progress.
"""

import copy
import json
import os
import re
import tkinter as tk
import uuid
from tkinter import messagebox, simpledialog

import dice_api

PLUGIN = {
    "name": "Encounters",
    "version": "1.2",
    "description": "Build an encounter, roll initiative and run it turn by turn.",
    "author": "bundled",
}

# The stat that gets added to the d20. Whichever of these a creature happens
# to carry is used - one game calls it a modifier, another calls it dexterity.
INIT_STATS = ("Init Mod", "Initiative", "Init", "Dex Mod", "DEX")

# Where the Game Map keeps its figures. Read-only, and only if it is there -
# the two windows are separate mods and either can be turned off.
MAP_FILE = "game_map.json"

# A stat whose value reads as a modifier for a d20 rather than a number to
# look up gets a Roll beside it without being asked. Anything else has to be
# told, by right-clicking it and picking a die.
CHECK_STATS = ("attack", "to hit", "hit", "init mod", "initiative", "init",
               "save", "spell attack", "spell save", "melee", "ranged",
               "perception", "stealth")
CHECK_ENDINGS = (" mod", " bonus", " attack", " save", " check", " throw")

# The bits Tk sets on a click while a modifier is held. Ctrl everywhere,
# and Command on a Mac, where Ctrl-click is the right button and picking
# several of anything is done with Command.
CTRL = 0x0004
COMMAND = 0x0008
PICK_MANY = (CTRL | COMMAND) if dice_api.MAC else CTRL

# One term of a dice expression: '2d6', 'd20', '-1d4', or a plain '+2'. The
# look-behind is what keeps a word out of it: the d in 'road 20' is not a die,
# so that value reads as the plain 20 it is.
TERM = re.compile(r"([+-]?)\s*(?:(\d*)\s*(?<![A-Za-z])[dD]\s*(\d+)|(\d+))")

# How many copies of one library entry can go in at once.
MAX_COPIES = 20

# How many rolls the log beside the stats keeps. It is a running note of a
# fight, not a record - Roll History in the main window has every one.
MAX_LOG = 40

# Encounters kept for every campaign rather than one, so a fight worth
# reusing is not trapped in the game it was built for. Beside the app with
# the profile and the server list, for the same reason those are: it belongs
# to the person, not to any one campaign.
SHARED_PATH = os.path.join(dice_api.APP_DIR, "shared_encounters.json")

# Bumped whenever stock creatures are added below. A campaign whose library
# was built under an older number gets the new entries merged in by name, so
# an existing library gains them without losing anything that was edited -
# and anything deleted after that stays deleted.
STOCK_VERSION = 2


# --------------------------------------------------------------------------
# Systems - which numbers a creature carries, and what they mean
# --------------------------------------------------------------------------
# `rule` is how a score becomes the modifier that gets added to a roll:
#   "dnd"  - the 10-is-average table. 10 and 11 are +0, and every two points
#            either side is one more point of modifier, so 19 is +4 and 7 is
#            -2. A score raised by a belt or a spell is just a higher number
#            in the box; the modifier follows it on its own.
#   "flat" - the number in the box is the modifier. For games without scores.
SYSTEMS = [
    {"name": "Dungeons & Dragons",
     "rule": "dnd",
     "abilities": ["STR", "DEX", "CON", "INT", "WIS", "CHA"],
     "stats": [["HP", "10"], ["AC", "12"], ["Init Mod", "0"],
               ["Speed", "30 ft."]]},
    {"name": "Plain Numbers",
     "rule": "flat",
     "abilities": [],
     "stats": [["HP", "10"], ["AC", "12"], ["Init Mod", "0"],
               ["Attack", "+0"], ["Damage", "1d6"]]},
]

ABILITY_ORDER = ("STR", "DEX", "CON", "INT", "WIS", "CHA")


def _atk(name, hit, dice, dmg_type="", note="", hit_ability="",
         dmg_ability=""):
    """An attack: roll to hit, then roll the damage."""
    return {"kind": "attack", "name": name, "hit": hit,
            "hit_ability": hit_ability, "dice": dice,
            "dmg_ability": dmg_ability, "dmg_type": dmg_type, "dc": "",
            "dc_ability": "", "on_fail": "", "on_save": "", "note": note}


def _save(name, dc, ability, dice="", dmg_type="", on_fail="", on_save="",
          note=""):
    """Something the target saves against. Nothing is rolled for the save
    itself - the number is the players' to beat, so it is shown, not rolled."""
    return {"kind": "save", "name": name, "hit": "", "hit_ability": "",
            "dice": dice, "dmg_ability": "", "dmg_type": dmg_type,
            "dc": str(dc), "dc_ability": ability, "on_fail": on_fail,
            "on_save": on_save, "note": note}


def _stock(name, hp, ac, init, speed, scores, actions, desc, extra=()):
    """One entry for the starting library, spelled out the long way."""
    stats = [["HP", str(hp)], ["AC", str(ac)], ["Init Mod", str(init)],
             ["Speed", str(speed)]]
    stats.extend([[str(n), str(v)] for n, v in extra])
    return {"name": name, "stats": stats,
            "abilities": {key: str(score)
                          for key, score in zip(ABILITY_ORDER, scores)},
            "actions": list(actions), "rolls": {}, "desc": desc,
            "system": "Dungeons & Dragons"}


# Copied into the campaign's library so the picker is never an empty box.
# Printed numbers, the way a stat block gives them: the bonuses are already
# worked out, so nothing shifts about under you. The fighter at the end is
# the one built the other way - its to hit and its damage are a proficiency
# bonus plus an ability score, so raising its STR raises both.
BESTIARY = [
    _stock("Bat", 1, 12, "+2", "5 ft., fly 30 ft.", (2, 15, 8, 2, 12, 4),
           [_atk("Bite", "+0", "1", "piercing")],
           "A scrap of leather and teeth. Blind, but it hears everything "
           "within 60 feet of it."),
    _stock("Stirge", 2, 14, "+3", "10 ft., fly 40 ft.", (4, 16, 11, 2, 8, 6),
           [_atk("Blood Drain", "+5", "1d4+2", "piercing",
                 "On a hit it attaches, and drains 1d4+2 again at the start "
                 "of each of its turns until it is pulled off.")],
           "A flying tick the size of a cat. It latches on and does not let "
           "go."),
    _stock("Giant Rat", 7, 12, "+2", "30 ft.", (7, 15, 11, 2, 10, 4),
           [_atk("Bite", "+4", "1d4+2", "piercing")],
           "Never alone. Where there is one there are six more in the dark "
           "behind it."),
    _stock("Kobold", 5, 12, "+2", "30 ft.", (7, 15, 9, 8, 7, 8),
           [_atk("Dagger", "+4", "1d4+2", "piercing"),
            _atk("Sling", "+4", "1d4+2", "bludgeoning", "range 30/120")],
           "Small, cowardly, and dangerous in numbers. Fights from behind "
           "traps and gangs up for advantage."),
    _stock("Goblin", 7, 15, "+2", "30 ft.", (8, 14, 10, 10, 8, 8),
           [_atk("Scimitar", "+4", "1d6+2", "slashing"),
            _atk("Shortbow", "+4", "1d6+2", "piercing", "range 80/320")],
           "Can disengage or hide as a bonus action, so it knifes you and is "
           "gone behind the rocks before you swing back."),
    _stock("Skeleton", 13, 13, "+2", "30 ft.", (10, 14, 15, 6, 8, 5),
           [_atk("Shortsword", "+4", "1d6+2", "piercing"),
            _atk("Shortbow", "+4", "1d6+2", "piercing", "range 80/320")],
           "Obeys the last order it was given and nothing else. Vulnerable "
           "to bludgeoning; immune to poison and exhaustion."),
    _stock("Zombie", 22, 8, "-2", "20 ft.", (13, 6, 16, 3, 6, 5),
           [_atk("Slam", "+3", "1d6+1", "bludgeoning"),
            _save("Undead Fortitude", "5 + damage taken", "CON",
                  on_fail="it drops",
                  on_save="it is left standing with 1 hit point",
                  note="Made whenever damage would put it to 0 hit points, "
                       "unless that damage was radiant or a critical hit.")],
           "Slow, stupid, and very hard to put down for good. It gets back "
           "up more often than it has any right to."),
    _stock("Wolf", 11, 13, "+2", "40 ft.", (12, 15, 12, 3, 12, 6),
           [_atk("Bite", "+4", "2d4+2", "piercing"),
            _save("Knock Prone", 11, "STR",
                  on_fail="knocked prone", on_save="stays on its feet",
                  note="Only on a hit with the bite.")],
           "Hunts as a pack, and has advantage on a bite whenever one of its "
           "packmates is beside the same target."),
    _stock("Wild Boar", 11, 11, "+0", "40 ft.", (13, 11, 12, 2, 9, 5),
           [_atk("Tusk", "+3", "1d6+1", "slashing")],
           "Charges in a straight line, and keeps fighting for one more round "
           "at 0 hit points out of sheer spite."),
    _stock("Giant Spider", 26, 14, "+3", "30 ft., climb 30 ft.",
           (14, 16, 12, 2, 11, 4),
           [_atk("Bite", "+5", "1d8+3", "piercing"),
            _save("Bite Poison", 11, "CON", "2d8", "poison",
                  on_fail="full poison damage, and poisoned until the end of "
                          "its next turn",
                  on_save="half damage, and no poisoning",
                  note="Only on a hit with the bite."),
            _save("Web", 12, "DEX",
                  on_fail="restrained; a DC 12 STR check breaks free",
                  on_save="ducks the strand",
                  note="Ranged, 30/60 ft. The web has AC 10 and 5 hit "
                       "points, and is vulnerable to fire.")],
           "Waits on the ceiling. Sees in the dark, walks on walls, and knows "
           "the moment anything touches its web."),
    _stock("Bandit", 11, 12, "+1", "30 ft.", (11, 12, 12, 10, 10, 10),
           [_atk("Scimitar", "+3", "1d6+1", "slashing"),
            _atk("Light Crossbow", "+3", "1d8+1", "piercing",
                 "range 80/320")],
           "In it for the money. Will take a bribe, and will run once the "
           "fight stops being worth it."),
    _stock("Guard", 11, 16, "+1", "30 ft.", (13, 12, 12, 10, 11, 10),
           [_atk("Spear", "+3", "1d6+1", "piercing", "thrown 20/60")],
           "City watch, or somebody's hired muscle. Chainmail, a shield, and "
           "a whistle that brings four more."),
    _stock("Hobgoblin", 11, 18, "+1", "30 ft.", (13, 12, 12, 10, 10, 9),
           [_atk("Longsword", "+3", "1d8+1", "slashing"),
            _atk("Longbow", "+3", "1d8+1", "piercing", "range 150/600")],
           "Disciplined where a goblin is not. Deals an extra 2d6 whenever "
           "one of its allies is within 5 feet of the target."),
    _stock("Orc", 15, 13, "+1", "30 ft.", (16, 12, 16, 7, 11, 10),
           [_atk("Greataxe", "+5", "1d12+3", "slashing"),
            _atk("Javelin", "+5", "1d6+3", "piercing", "range 30/120")],
           "Moves toward the nearest enemy as a bonus action. It does not "
           "hold a line and it does not wait."),
    _stock("Ogre", 59, 11, "-1", "40 ft.", (19, 8, 16, 5, 7, 7),
           [_atk("Greatclub", "+6", "2d8+4", "bludgeoning"),
            _atk("Javelin", "+6", "2d6+4", "piercing", "range 30/120")],
           "Eight feet of appetite and bad temper. Slow to work anything out, "
           "and one swing can end a first-level character."),
    _stock("Human Fighter", 25, 16, "+1", "30 ft.",
           (16, 13, 14, 10, 11, 10),
           [_atk("Longsword", "+2", "1d8", "slashing",
                 "Proficiency plus STR, both to hit and to damage.",
                 hit_ability="STR", dmg_ability="STR"),
            _atk("Longbow", "+2", "1d8", "piercing", "range 150/600",
                 hit_ability="DEX", dmg_ability="DEX")],
           "A hired sword, a rival, or the captain of the guard. Its attacks "
           "are built out of its ability scores rather than written in, so "
           "hand it a belt of giant strength - put 19 in STR - and the "
           "longsword goes to +6 for 1d8+4 on its own.",
           extra=[["Proficiency", "+2"]]),
]


# What the first version of this mod shipped. Only used to recognise one of
# its six creatures that nobody has touched since, so it can be replaced by
# the fuller entry above - anything edited is left exactly as it is.
LEGACY_STOCK = {
    "Giant Rat": [["HP", "7"], ["AC", "12"], ["Init Mod", "+2"],
                  ["Attack", "+3"], ["Damage", "1d4"], ["Speed", "30"]],
    "Goblin": [["HP", "12"], ["AC", "15"], ["Init Mod", "+2"],
               ["Attack", "+4"], ["Damage", "1d6+2"], ["Speed", "30"]],
    "Kobold": [["HP", "5"], ["AC", "12"], ["Init Mod", "+2"],
               ["Attack", "+4"], ["Damage", "1d4+2"], ["Speed", "30"]],
    "Wolf": [["HP", "11"], ["AC", "13"], ["Init Mod", "+2"],
             ["Attack", "+4"], ["Damage", "2d4+2"], ["Speed", "40"]],
    "Bandit": [["HP", "11"], ["AC", "12"], ["Init Mod", "+1"],
               ["Attack", "+3"], ["Damage", "1d6+1"], ["Speed", "30"]],
    "Ogre": [["HP", "59"], ["AC", "11"], ["Init Mod", "-1"],
             ["Attack", "+6"], ["Damage", "2d8+4"], ["Speed", "40"]],
}


def _clean_saved(raw):
    """One encounter off the shelf: a name, who is in it, and the two notes.

    No initiative and no turn - a saved encounter is one that is prepared,
    not one halfway through. Loading it always starts from nobody having
    rolled, which is what Roll Initiative is for.
    """
    return {
        "name": str(raw.get("name", "") or "Encounter"),
        "creatures": [c for c in (raw.get("creatures") or [])
                      if isinstance(c, dict)],
        "summary": str(raw.get("summary", "")),
        "treasure": str(raw.get("treasure", "")),
    }


def load_shared():
    """The encounters that belong to no single campaign."""
    try:
        with open(SHARED_PATH, encoding="utf-8") as fh:
            saved = json.load(fh)
    except (OSError, ValueError):
        return []
    if not isinstance(saved, list):
        return []
    return [_clean_saved(raw) for raw in saved if isinstance(raw, dict)]


def save_shared(entries):
    """Written straight to disk rather than through api.storage, which only
    ever knows about the campaign that is open."""
    try:
        with open(SHARED_PATH, "w", encoding="utf-8") as fh:
            json.dump(entries, fh, indent=2)
        return True
    except OSError as exc:
        print(f"[encounters] could not write {SHARED_PATH}: {exc}")
        return False


def setup(api):
    holder = {"window": None}

    def open_encounters():
        window = holder["window"]
        if window is not None and window.alive():
            window.win.deiconify()
            window.win.lift()
            window.win.focus_force()
            return
        holder["window"] = Encounters(api)

    def flush(_name=None):
        window = holder["window"]
        if window is not None and window.alive():
            window.save()

    api.add_menu_command("Tools", "Encounters...", open_encounters)
    api.on("save", flush)


def _number(text):
    """The number in a stat value, or 0. '+2', '2', ' -1 ' and '' all work."""
    try:
        return int(str(text).strip().lstrip("+") or 0)
    except ValueError:
        return 0


def _init_score(text):
    """What a typed initiative box means. Blank is no count at all - the same
    as never having rolled - and anything unreadable settles at zero rather
    than refusing the keystroke."""
    text = str(text).strip()
    return _number(text) if text else None


def parse_dice(text):
    """A dice expression split into its dice and its flat part.

    '2d6+1d4-1' gives ([(1, 2, 6), (1, 1, 4)], -1): a list of (sign, how
    many, how many sides), and everything that was not a die. A value with no
    dice in it comes back with an empty list, which is how a plain modifier
    like '+3' is told apart from something rollable like '1d6+1'.
    """
    terms = []
    flat = 0
    for sign, count, sides, const in TERM.findall(str(text)):
        mult = -1 if sign == "-" else 1
        if sides:
            faces = int(sides)
            if faces > 0:
                terms.append((mult, max(1, int(count or 1)), faces))
        elif const:
            flat += mult * int(const)
    return terms, flat


def ability_mod(score, rule="dnd"):
    """What an ability score is worth as a modifier, under a system's rule."""
    if rule == "flat":
        return score
    # Floor division, so a score under 10 gives a penalty on the same curve:
    # 9 and 8 are -1, 7 and 6 are -2, and so on down.
    return (score - 10) // 2


def _is_check_stat(name):
    """Whether a stat's value reads as a modifier for a d20 roll."""
    lowered = str(name).strip().lower()
    return lowered in CHECK_STATS or lowered.endswith(CHECK_ENDINGS)


def _signed(number):
    return "%+d" % number


def _line(what, detail, total, tag="total", tail=""):
    """One rolled line in the log: 'to hit  1d20 14  +4 = 18 slashing'."""
    return (what, detail, total, tag, tail)


def _clean_action(raw):
    """One thing a creature can do, with every field present."""
    kind = "save" if str(raw.get("kind", "")) == "save" else "attack"
    return {
        "kind": kind,
        "name": str(raw.get("name", "") or "Attack"),
        "hit": str(raw.get("hit", "")),
        "hit_ability": str(raw.get("hit_ability", "")),
        "dice": str(raw.get("dice", "")),
        "dmg_ability": str(raw.get("dmg_ability", "")),
        "dmg_type": str(raw.get("dmg_type", "")),
        "dc": str(raw.get("dc", "")),
        "dc_ability": str(raw.get("dc_ability", "")),
        "on_fail": str(raw.get("on_fail", "")),
        "on_save": str(raw.get("on_save", "")),
        "note": str(raw.get("note", "")),
    }


def _clean_rolls(raw):
    """Which die and which ability score were pinned to a stat by hand."""
    rolls = {}
    for name, spec in (raw or {}).items():
        if not isinstance(spec, dict):
            continue
        die = str(spec.get("die", "")).strip()
        ability = str(spec.get("ability", "")).strip()
        if die or ability:
            rolls[str(name)] = {"die": die, "ability": ability}
    return rolls


def _body(raw, system=""):
    """Everything a creature and a library entry have in common."""
    rows = []
    for row in (raw.get("stats") or []):
        if isinstance(row, (list, tuple)) and len(row) >= 2:
            rows.append([str(row[0]), str(row[1])])
    return {
        "name": str(raw.get("name", "Unnamed")),
        "stats": rows,
        "abilities": {str(key): str(value) for key, value
                      in (raw.get("abilities") or {}).items()},
        "actions": [_clean_action(a) for a in (raw.get("actions") or [])
                    if isinstance(a, dict)],
        "rolls": _clean_rolls(raw.get("rolls")),
        "desc": str(raw.get("desc", "")),
        "system": str(raw.get("system", "") or system),
    }


def _clean_system(raw):
    """One system preset: its abilities, its rule, and what a new creature
    starts with."""
    abilities = []
    for key in (raw.get("abilities") or []):
        key = str(key).strip()
        if key and key not in abilities:
            abilities.append(key)
    rows = []
    for row in (raw.get("stats") or []):
        if isinstance(row, (list, tuple)) and len(row) >= 2:
            rows.append([str(row[0]), str(row[1])])
    return {"name": str(raw.get("name", "") or "System"),
            "rule": "flat" if str(raw.get("rule", "")) == "flat" else "dnd",
            "abilities": abilities,
            "stats": rows}


class Encounters:
    def __init__(self, api):
        self.api = api
        self.t = api.theme
        self.f = api.fonts

        self.creatures = []     # the roster: [{"id", "name", "stats", ...}]
        self.library = []       # reusable entries, same shape minus the id
        self.systems = []       # presets: [{"name", "rule", "abilities", ...}]
        self.system = ""        # the one in use
        self.selected = []      # ids, in the order they were picked
        self.summary = ""       # a few lines on what is going on
        self.treasure = ""      # and what the party walks away with
        self.running = False
        self.round = 1
        self.turn = 0
        self.order = []         # ids, fixed while the encounter runs
        self.mode = "roster"    # or "picker", while choosing what to add
        self.pick = None        # index into the library, while picking
        self.rolls = []         # the log beside the stats, newest first
        self.saved = []         # encounters kept for this campaign
        self.current = {"name": "", "shared": False}    # the one that is open
        self._save_job = None
        self._settling = False  # a re-sort is already under way
        self._desc_owner = None  # whose description is in the box
        self._ability_mods = {}  # ability key -> the label showing its modifier

        self._load()
        self._build()
        self._show_name()
        self._render_left()
        self._render_stats()
        self._render_runner()

    # -- data --------------------------------------------------------------
    def alive(self):
        try:
            return bool(self.win.winfo_exists())
        except tk.TclError:
            return False

    def _load(self):
        store = self.api.storage

        self.systems = [_clean_system(raw) for raw in store.get("systems", [])
                        if isinstance(raw, dict)]
        if not self.systems:
            self.systems = [_clean_system(raw) for raw in SYSTEMS]
        self.system = str(store.get("system", ""))
        if not any(entry["name"] == self.system for entry in self.systems):
            self.system = self.systems[0]["name"]

        for raw in store.get("creatures", []):
            self.creatures.append(self._clean(raw))
        self.library = [_body(raw) for raw in store.get("library", [])
                        if isinstance(raw, dict)]
        if "library" not in store:
            self.library = [_body(raw) for raw in BESTIARY]
            self.library.sort(key=lambda entry: entry["name"].lower())
            stocked = STOCK_VERSION
        else:
            stocked = _number(store.get("stocked", 0))
        if stocked < STOCK_VERSION:
            self._merge_stock()

        self.saved = [_clean_saved(raw) for raw in store.get("encounters", [])
                      if isinstance(raw, dict)]
        opened = store.get("current")
        if isinstance(opened, dict):
            self.current = {"name": str(opened.get("name", "")),
                            "shared": bool(opened.get("shared", False))}

        self.summary = str(store.get("summary", ""))
        self.treasure = str(store.get("treasure", ""))
        self.running = bool(store.get("running", False))
        self.round = max(1, int(store.get("round", 1)))
        self.turn = max(0, int(store.get("turn", 0)))
        self.order = [str(i) for i in store.get("order", [])]

    def _merge_stock(self):
        """Bring a library built under an older version up to date.

        Anything new is appended. An entry that is still exactly what an older
        version shipped - same stats, and nothing added to it since - is
        replaced by the fuller one, which is how the six originals pick up
        their ability scores and their attacks. Everything else is left alone:
        an entry that was edited is the user's, not ours.
        """
        have = {entry["name"]: index
                for index, entry in enumerate(self.library)}
        for raw in BESTIARY:
            entry = _body(raw)
            index = have.get(entry["name"])
            if index is None:
                self.library.append(entry)
            elif (not self.library[index]["actions"]
                    and not self.library[index]["abilities"]
                    and self.library[index]["stats"]
                    == LEGACY_STOCK.get(entry["name"])):
                self.library[index] = entry
        self.library.sort(key=lambda entry: entry["name"].lower())

    def _clean(self, raw):
        """One creature, with everything it needs and nothing it doesn't."""
        init = raw.get("init")
        creature = _body(raw, self.system)
        creature.update({
            "id": str(raw.get("id") or uuid.uuid4().hex[:8]),
            "init": None if init is None else int(init),
            "player": bool(raw.get("player", False)),
        })
        return creature

    def save(self):
        store = self.api.storage
        self._read_notes()
        self._read_desc()
        store["creatures"] = self.creatures
        store["library"] = self.library
        store["systems"] = self.systems
        store["system"] = self.system
        store["stocked"] = STOCK_VERSION
        store["encounters"] = self.saved
        store["current"] = self.current
        store["summary"] = self.summary
        store["treasure"] = self.treasure
        store["running"] = self.running
        store["round"] = self.round
        store["turn"] = self.turn
        store["order"] = self.order
        self.api.save()

    def schedule_save(self):
        """Coalesce the flurry of edits from typing into one write."""
        if self._save_job is not None:
            self.win.after_cancel(self._save_job)
        self._save_job = self.win.after(600, self._do_save)

    def _do_save(self):
        self._save_job = None
        if self.alive():        # the window may have gone since this was set
            self.save()

    def _cancel_save(self):
        """Don't leave a timer pointing at a window that has gone."""
        if self._save_job is not None:
            try:
                self.win.after_cancel(self._save_job)
            except tk.TclError:
                pass
            self._save_job = None

    def _on_destroy(self, event):
        if event.widget is self.win:
            self._cancel_save()

    def _close(self):
        self._cancel_save()
        self.save()
        self.win.destroy()

    # -- looking things up -------------------------------------------------
    def _find(self, cid):
        for creature in self.creatures:
            if creature["id"] == cid:
                return creature
        return None

    def _current(self):
        """The creature whose stats the right-hand side is showing."""
        return self._find(self.selected[-1]) if self.selected else None

    def _sorted(self):
        """The roster in initiative order. Unrolled creatures sink to the
        bottom; ties keep the order they were added in, so the list never
        shuffles itself about between renders."""
        indexed = list(enumerate(self.creatures))
        indexed.sort(key=lambda pair: (pair[1]["init"] is None,
                                       -(pair[1]["init"] or 0), pair[0]))
        return [creature for _index, creature in indexed]

    def _turn_order(self):
        """While running, the order fixed at Run Encounter - minus anyone who
        has left the fight, plus anyone who joined it late."""
        known = {creature["id"] for creature in self.creatures}
        self.order = [cid for cid in self.order if cid in known]
        for creature in self._sorted():
            if creature["id"] not in self.order:
                self.order.append(creature["id"])
        return self.order

    def _display_order(self):
        """What the roster shows. Standing still it is initiative order; once
        the encounter is running it is rotated so whoever is up is on top."""
        if not self.running:
            return self._sorted()
        order = self._turn_order()
        if not order:
            return []
        self.turn %= len(order)
        rotated = order[self.turn:] + order[:self.turn]
        return [self._find(cid) for cid in rotated if self._find(cid)]

    # -- the system in use -------------------------------------------------
    def _system(self):
        for entry in self.systems:
            if entry["name"] == self.system:
                return entry
        return self.systems[0]

    def _abilities(self, creature=None):
        """Which ability scores to show. The system's, in its order, and then
        anything the creature carries that the system does not know about -
        switching system hides nothing a creature already had."""
        keys = list(self._system()["abilities"])
        for key in (creature or {}).get("abilities", {}):
            if key not in keys:
                keys.append(key)
        return keys

    def _ability_mod(self, creature, key):
        """The modifier a creature's score in one ability is worth. An empty
        box is no modifier rather than a score of zero."""
        if not key:
            return 0
        raw = str((creature.get("abilities") or {}).get(key, "")).strip()
        if not raw:
            return 0
        return ability_mod(_number(raw), self._system()["rule"])

    def _new_stats(self):
        """What a creature made from scratch starts with."""
        rows = copy.deepcopy(self._system()["stats"])
        if not rows:
            rows = [["HP", "10"], ["AC", "12"], ["Init Mod", "0"]]
        return rows

    def _new_abilities(self):
        """Blank boxes for the system's abilities, so the creature has a row
        for each without a score being invented for it."""
        return {key: "" for key in self._system()["abilities"]}

    # -- window ------------------------------------------------------------
    def _build(self):
        self.win = tk.Toplevel(self.api.app)
        self.win.title(f"Encounters - {self.api.save_name}")
        self.win.configure(bg=self.t["bg"])
        self.win.geometry("980x820")
        self.win.minsize(760, 640)
        self.win.protocol("WM_DELETE_WINDOW", self._close)
        self.win.bind("<Destroy>", self._on_destroy)

        # Down the middle: the roster and the stat block get a half each,
        # whatever the window is doing. `uniform` is what holds them level -
        # weights alone would let the wider content push its side out.
        self.win.columnconfigure(0, weight=1, uniform="halves")
        self.win.columnconfigure(1, weight=1, uniform="halves")
        self.win.rowconfigure(0, weight=1)

        self._build_menubar()
        self._build_roster()
        self._build_picker()
        self._build_stats()
        self._build_summary()
        self._build_runner()

    def _heading(self, parent, text):
        return tk.Label(parent, text=text, font=self.f["label"],
                        bg=self.t["panel"], fg=self.t["muted"], anchor="w")

    def _button(self, parent, text, command, fg=None, width=None):
        return tk.Button(parent, text=text, font=self.f["label"],
                         bg=self.t["bg"], fg=fg or self.t["fg"],
                         activebackground=self.t["accent"],
                         activeforeground=self.t["bg"], relief="flat", bd=0,
                         cursor="hand2", command=command,
                         **({"width": width} if width else {}))

    def _tiny(self, parent, text, command, fg=None, bg=None):
        """The little Roll beside a number. Small enough to sit in a row
        without crowding the value it belongs to."""
        return tk.Button(parent, text=text, font=self.f["label"],
                         bg=bg or self.t["panel"], fg=fg or self.t["muted"],
                         activebackground=self.t["accent"],
                         activeforeground=self.t["bg"], relief="flat", bd=0,
                         padx=6, pady=0, cursor="hand2", command=command)

    def _entry(self, parent, width, value=""):
        widget = tk.Entry(parent, width=width, font=self.f["label"],
                          bg=self.t["bg"], fg=self.t["fg"],
                          insertbackground=self.t["fg"], relief="flat", bd=0,
                          highlightthickness=1,
                          highlightbackground=self.t["panel"],
                          highlightcolor=self.t["accent"])
        if value:
            widget.insert(0, value)
        return widget

    def _menu(self, parent=None):
        return tk.Menu(parent or self.win, tearoff=0, font=self.f["label"],
                       bg=self.t["panel"], fg=self.t["fg"],
                       activebackground=self.t["accent"],
                       activeforeground=self.t["bg"], relief="flat", bd=0)

    def _scroller(self, parent):
        outer = tk.Frame(parent, bg=self.t["panel"])
        canvas = tk.Canvas(outer, bg=self.t["panel"], highlightthickness=0, bd=0)
        bar = tk.Scrollbar(outer, orient="vertical", command=canvas.yview,
                           bg=self.t["panel"], troughcolor=self.t["bg"],
                           activebackground=self.t["accent"], relief="flat",
                           bd=0, width=10)
        canvas.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        inner = tk.Frame(canvas, bg=self.t["panel"])
        window = canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>",
                   lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>",
                    lambda e: canvas.itemconfigure(window, width=e.width))
        canvas.bind("<MouseWheel>",
                    lambda e: canvas.yview_scroll(dice_api.wheel_steps(e),
                                                  "units"))
        return outer, inner, canvas

    def _bind_wheel(self, widget, canvas):
        def scroll(event):
            canvas.yview_scroll(dice_api.wheel_steps(event), "units")
            return "break"
        # A Text box keeps its own wheel - the description scrolls itself
        # rather than dragging the whole panel past.
        if not isinstance(widget, tk.Text):
            widget.bind("<MouseWheel>", scroll)
        for child in widget.winfo_children():
            self._bind_wheel(child, canvas)

    # -- the left-hand side: roster, or the picker while adding -------------
    def _render_left(self):
        if self.mode == "picker":
            self.roster_box.grid_remove()
            self.picker_box.grid()
            self._render_picker()
        else:
            self.picker_box.grid_remove()
            self.roster_box.grid()
            self._render_roster()

    def _build_roster(self):
        box = tk.Frame(self.win, bg=self.t["panel"])
        box.grid(row=0, column=0, sticky="nsew", padx=(8, 4), pady=8)
        self.roster_box = box

        top = tk.Frame(box, bg=self.t["panel"])
        top.pack(fill="x", padx=10, pady=(8, 6))
        self._heading(top, "ENCOUNTER").pack(side="left")
        # Which saved encounter this is. Naming one is only worth anything if
        # the name is in front of you afterwards.
        self.name_label = tk.Label(top, text="", font=self.f["label"],
                                   bg=self.t["panel"], fg=self.t["accent"],
                                   anchor="e")
        self.name_label.pack(side="right")
        outer, self.roster_rows, self.roster_canvas = self._scroller(box)
        outer.pack(fill="both", expand=True, padx=6)

        tk.Label(box, text="Ctrl-click to pick several, then right-click.",
                 font=self.f["label"], bg=self.t["panel"], fg=self.t["muted"],
                 anchor="w", wraplength=400,
                 justify="left").pack(fill="x", padx=10, pady=(6, 2))

        buttons = tk.Frame(box, bg=self.t["panel"])
        buttons.pack(fill="x", padx=10, pady=(2, 10))
        # Rolling sits above the adding on purpose: it is the button reached
        # for once the room is assembled, so it wants to be the one nearest
        # the list rather than buried under the two that built it.
        self._button(buttons, "Roll Initiative", self._roll_all).pack(
            fill="x", ipady=4)
        adders = tk.Frame(buttons, bg=self.t["panel"])
        adders.pack(fill="x", pady=(4, 0))
        adders.columnconfigure(0, weight=1, uniform="adders")
        adders.columnconfigure(1, weight=1, uniform="adders")
        self.add_button = self._button(adders, "+  Add creature",
                                      self._open_picker, fg=self.t["accent"])
        self.add_button.grid(row=0, column=0, sticky="ew", ipady=4,
                             padx=(0, 2))
        self.player_button = self._button(adders, "+  Add player",
                                          self._show_player_menu,
                                          fg=self.t["accent"])
        self.player_button.grid(row=0, column=1, sticky="ew", ipady=4,
                                padx=(2, 0))
        self.run_button = self._button(buttons, "Run Encounter",
                                       self._toggle_run, fg=self.t["crit"])
        self.run_button.pack(fill="x", ipady=4, pady=(4, 0))

    def _render_roster(self):
        for child in self.roster_rows.winfo_children():
            child.destroy()

        if not self.creatures:
            tk.Label(self.roster_rows, text="Nothing here yet. Add a creature "
                     "to start building the fight.", font=self.f["label"],
                     bg=self.t["panel"], fg=self.t["muted"], anchor="w",
                     wraplength=200,
                     justify="left").pack(fill="x", padx=6, pady=6)
            return

        for index, creature in enumerate(self._display_order()):
            active = self.running and index == 0
            picked = creature["id"] in self.selected
            row_bg = self.t["bg"] if (picked or active) else self.t["panel"]
            if active:
                fg = self.t["crit"]
            elif picked:
                fg = self.t["accent"]
            else:
                fg = self.t["fg"]

            row = tk.Frame(self.roster_rows, bg=row_bg)
            row.pack(fill="x", pady=1)
            name = tk.Label(row, text=("> " if active else "   ") + creature["name"],
                            font=self.f["label"], bg=row_bg, fg=fg, anchor="w")
            name.pack(side="left", fill="x", expand=True, padx=(6, 2), pady=3)
            # A box rather than a label. A rolled number is a suggestion:
            # the GM overruling it, or setting one by hand without rolling at
            # all, should not mean clearing it and rolling again.
            init = creature["init"]
            edge = self.t["panel"] if row_bg == self.t["bg"] else self.t["bg"]
            score = tk.Entry(row, width=3, font=self.f["die"],
                             bg=self.t["bg"], fg=fg, insertbackground=fg,
                             justify="center", relief="flat", bd=0,
                             highlightthickness=1, highlightbackground=edge,
                             highlightcolor=self.t["accent"])
            if init is not None:
                score.insert(0, str(init))
            score._init_box = True
            score.pack(side="right", padx=(2, 8), ipady=2)
            score.bind("<KeyRelease>",
                       lambda _e, c=creature, w=score: self._type_init(c, w))
            score.bind("<Return>",
                       lambda _e, c=creature, w=score: self._enter_init(c, w))
            score.bind("<FocusOut>",
                       lambda _e, c=creature, w=score: self._leave_init(c, w))
            tag = tk.Label(row, text="PC" if creature.get("player") else "",
                           font=self.f["label"], bg=row_bg,
                           fg=self.t["accent"], width=2, anchor="e")
            tag.pack(side="right", padx=(2, 4))

            # Clicking the box means editing the number, so it is left out of
            # the picking. The name and the rest of the row still select.
            for widget in (row, name, tag):
                widget.bind("<Button-1>",
                            lambda e, c=creature["id"]: self._click(c, e))
            for widget in (row, name, score, tag):
                widget.bind("<Button-3>",
                            lambda e, c=creature["id"]: self._roster_menu(c, e))
        self._bind_wheel(self.roster_rows, self.roster_canvas)

    def _click(self, cid, event):
        if event.state & PICK_MANY:
            if cid in self.selected:
                self.selected.remove(cid)
            else:
                self.selected.append(cid)
        else:
            self.selected = [cid]
        self._render_roster()
        self._render_stats()

    def _picked(self):
        """The selected creatures, in roster order and with the dead links
        from a removal dropped."""
        return [c for c in self._sorted() if c["id"] in self.selected]

    def _roster_menu(self, cid, event):
        if cid not in self.selected:
            self.selected = [cid]
            self._render_roster()
            self._render_stats()

        picked = self._picked()
        if not picked:
            return
        menu = self._menu()
        if len(picked) > 1:
            menu.add_command(label=f"Roll initiative separately ({len(picked)})",
                             command=lambda: self._roll_for(picked))
            menu.add_command(label=f"Roll group initiative ({len(picked)})",
                             command=lambda: self._roll_group(picked))
        else:
            menu.add_command(label="Roll initiative",
                             command=lambda: self._roll_for(picked))
        menu.add_separator()
        menu.add_command(label="Clear initiative",
                         command=lambda: self._clear_init(picked))
        menu.add_command(label="Duplicate",
                         command=lambda: self._duplicate(picked))
        menu.add_command(label="Save to library",
                         command=lambda: self._to_library(picked))
        menu.add_separator()
        menu.add_command(label="Remove", command=lambda: self._remove(picked))
        menu.tk_popup(event.x_root, event.y_root)

    # -- the picker, in the roster's place while adding ----------------------
    def _build_picker(self):
        box = tk.Frame(self.win, bg=self.t["panel"])
        box.grid(row=0, column=0, sticky="nsew", padx=(8, 4), pady=8)
        box.grid_remove()
        self.picker_box = box

        self._heading(box, "ADD A CREATURE").pack(fill="x", padx=10,
                                                  pady=(8, 6))
        outer, self.picker_rows, self.picker_canvas = self._scroller(box)
        outer.pack(fill="both", expand=True, padx=6)

        tk.Label(box, text="Click one to look it over. Right-click to rename "
                 "or delete it.", font=self.f["label"], bg=self.t["panel"],
                 fg=self.t["muted"], anchor="w", wraplength=400,
                 justify="left").pack(fill="x", padx=10, pady=(6, 2))

        buttons = tk.Frame(box, bg=self.t["panel"])
        buttons.pack(fill="x", padx=10, pady=(2, 10))
        self._button(buttons, "New creature...", self._add_blank).pack(
            fill="x", ipady=4)

        bar = tk.Frame(buttons, bg=self.t["panel"])
        bar.pack(fill="x", pady=(4, 0))
        tk.Label(bar, text="How many", font=self.f["label"],
                 bg=self.t["panel"], fg=self.t["muted"]).pack(side="left")
        self.count_var = tk.IntVar(value=1)
        # A spinbox for the up and down arrows: one click per extra goblin,
        # and the number can be typed over for a swarm of them.
        self.count_box = tk.Spinbox(
            bar, from_=1, to=MAX_COPIES, width=3, textvariable=self.count_var,
            font=self.f["die"], bg=self.t["bg"], fg=self.t["fg"],
            buttonbackground=self.t["panel"], insertbackground=self.t["fg"],
            relief="flat", bd=0, highlightthickness=1,
            highlightbackground=self.t["bg"], justify="center",
            command=self._sync_add)
        self.count_box.pack(side="left", padx=(6, 8), ipady=2)
        self.count_box.bind("<KeyRelease>", lambda _e: self._sync_add())
        self.count_box.bind("<Return>", lambda _e: self._add_picked())
        # Add sits right beside the arrows: set the number, then add, without
        # the pointer going anywhere else.
        self.add_now = self._button(bar, "Add", self._add_picked,
                                    fg=self.t["accent"])
        self.add_now.pack(side="left", fill="x", expand=True, ipady=4)
        self._button(bar, "Back", self._close_picker,
                     fg=self.t["muted"]).pack(side="left", padx=(6, 0),
                                              ipady=4)

    def _open_picker(self):
        self.mode = "picker"
        self.pick = None
        self._render_left()
        self._render_stats()

    def _close_picker(self):
        self.mode = "roster"
        self.pick = None
        self._render_left()
        self._render_stats()

    def _count(self):
        try:
            return max(1, min(MAX_COPIES, int(self.count_var.get())))
        except (tk.TclError, ValueError):
            return 1

    def _sync_add(self):
        """Keep the Add button saying what it is about to do."""
        entry = self._picked_entry()
        if entry is None:
            self.add_now.configure(text="Add", state="disabled",
                                   fg=self.t["muted"])
            return
        count = self._count()
        label = entry["name"] if count == 1 else f"{count} x {entry['name']}"
        self.add_now.configure(text=f"Add {label}", state="normal",
                               fg=self.t["accent"])

    def _picked_entry(self):
        if self.pick is None or self.pick >= len(self.library):
            return None
        return self.library[self.pick]

    def _render_picker(self):
        for child in self.picker_rows.winfo_children():
            child.destroy()

        if not self.library:
            tk.Label(self.picker_rows, text="The library is empty. New "
                     "creature... makes one from scratch, and Save to library "
                     "on anything in the encounter puts it in here.",
                     font=self.f["label"], bg=self.t["panel"],
                     fg=self.t["muted"], anchor="w", wraplength=260,
                     justify="left").pack(fill="x", padx=6, pady=6)
            self._sync_add()
            return

        for index, entry in enumerate(self.library):
            picked = index == self.pick
            row_bg = self.t["bg"] if picked else self.t["panel"]
            fg = self.t["accent"] if picked else self.t["fg"]

            row = tk.Frame(self.picker_rows, bg=row_bg)
            row.pack(fill="x", pady=1)
            name = tk.Label(row, text="   " + entry["name"],
                            font=self.f["label"], bg=row_bg, fg=fg, anchor="w")
            name.pack(side="left", fill="x", expand=True, padx=(6, 2), pady=3)
            glance = tk.Label(row, text=self._glance(entry),
                              font=self.f["label"], bg=row_bg,
                              fg=self.t["muted"], anchor="e")
            glance.pack(side="right", padx=(2, 8))

            for widget in (row, name, glance):
                widget.bind("<Button-1>", lambda _e, i=index: self._pick(i))
                widget.bind("<Double-Button-1>",
                            lambda _e, i=index: self._pick_and_add(i))
                widget.bind("<Button-3>",
                            lambda e, i=index: self._library_menu(i, e))
        self._bind_wheel(self.picker_rows, self.picker_canvas)
        self._sync_add()

    def _glance(self, entry):
        """The two numbers worth seeing without opening an entry up."""
        wanted = ("HP", "AC")
        found = [f"{name} {value}" for name, value in entry["stats"]
                 if name.strip().upper() in wanted]
        return "   ".join(found)

    def _pick(self, index):
        self.pick = index
        self._render_picker()
        self._render_stats()

    def _pick_and_add(self, index):
        self.pick = index
        self._add_picked()

    def _add_picked(self):
        entry = self._picked_entry()
        if entry is None:
            return
        count = self._count()
        added = [self._make(entry) for _ in range(count)]
        # Straight back to the encounter, with what just arrived highlighted -
        # adding is a trip away from the list, not a place to stay.
        self.mode = "roster"
        self.pick = None
        self.selected = [creature["id"] for creature in added]
        self.count_var.set(1)
        self._render_left()
        self._render_stats()
        self.save()

    def _library_menu(self, index, event):
        self.pick = index
        self._render_picker()
        self._render_stats()
        entry = self.library[index]
        menu = self._menu()
        menu.add_command(label=f"Add one {entry['name']}",
                         command=lambda: self._pick_and_add(index))
        menu.add_separator()
        menu.add_command(label="Rename...",
                         command=lambda: self._rename_entry(index))
        menu.add_command(label="Delete from library",
                         command=lambda: self._drop_library(index))
        menu.tk_popup(event.x_root, event.y_root)

    def _rename_entry(self, index):
        entry = self.library[index]
        name = simpledialog.askstring("Rename", "Name:",
                                      initialvalue=entry["name"],
                                      parent=self.win)
        if not name or not name.strip():
            return
        entry["name"] = name.strip()
        self.library.sort(key=lambda item: item["name"].lower())
        self.pick = None
        self._render_left()
        self._render_stats()
        self.save()

    # -- adding creatures ---------------------------------------------------
    def _unique(self, name):
        """Two goblins both called Goblin make for a confusing initiative
        list, so the second one becomes Goblin 2."""
        taken = {creature["name"] for creature in self.creatures}
        if name not in taken:
            return name
        number = 2
        while f"{name} {number}" in taken:
            number += 1
        return f"{name} {number}"

    def _base_name(self, name):
        """'Goblin 3' back to 'Goblin', so copies and library entries don't
        pick up a run of numbers."""
        return name.rstrip("0123456789 ").strip() or name

    def _make(self, body, player=False):
        """Put one creature in the encounter. A copy, always: _body builds
        fresh rows and fresh dicts, so nothing is shared with the library
        entry or the creature this was duplicated from."""
        creature = _body(body, self.system)
        creature["id"] = uuid.uuid4().hex[:8]
        creature["name"] = self._unique(creature["name"])
        creature["init"] = None
        creature["player"] = player
        self.creatures.append(creature)
        return creature

    def _add(self, body, player=False):
        creature = self._make(body, player=player)
        self.selected = [creature["id"]]
        self.mode = "roster"
        self._render_left()
        self._render_stats()
        self.save()
        return creature

    def _add_blank(self):
        name = simpledialog.askstring("New creature", "Name:", parent=self.win)
        if not name or not name.strip():
            return
        self._add({"name": name.strip(), "stats": self._new_stats(),
                   "abilities": self._new_abilities(), "system": self.system})

    def _duplicate(self, creatures):
        for creature in list(creatures):
            copied = dict(creature)
            copied["name"] = self._base_name(creature["name"])
            self._add(copied, player=creature.get("player", False))

    # -- adding players -----------------------------------------------------
    def _map_characters(self):
        """The player figures standing on the game map, each with whoever
        they belong to. Read straight off the map's own save file: the two
        windows are separate mods, so there is nothing else to ask, and a
        missing or half-written file just means no suggestions.
        """
        path = os.path.join(dice_api.save_path(create=False), MAP_FILE)
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh).get("map", {})
        except (OSError, ValueError, AttributeError):
            return []
        owners = {}
        for player in data.get("players", []):
            if isinstance(player, dict) and "id" in player:
                owners[player["id"]] = player
        found = []
        for level in data.get("levels", []):
            for token in level.get("tokens", []):
                if not isinstance(token, dict) or token.get("kind") != "player":
                    continue
                owner = owners.get(token.get("owner"))
                found.append({
                    "name": str(token.get("name") or "Character"),
                    "owner": (owner or {}).get("name"),
                    "seat": (owner or {}).get("seat"),
                    "stats": self._map_stats(token.get("stats")),
                })
        return found

    def _map_stats(self, saved):
        """A map figure's numbers as stat rows. Whatever it carries comes
        across as it is; an initiative modifier is added if it has none, so
        there is somewhere to type the bonus."""
        stats = [[str(name), str(value)]
                 for name, value in (saved or {}).items()]
        if not stats:
            stats = self._new_stats()
        if not any(name.strip() in INIT_STATS for name, _v in stats):
            stats.append(["Init Mod", "0"])
        return stats

    def _table_people(self):
        """Everyone at the table, with the seat they are sitting in."""
        session = self.api.session
        if session is None or session.is_solo:
            return []
        people = []
        for card in session.people():
            people.append({"name": str(card.get("name") or "Someone"),
                           "role": card.get("role"),
                           "seat": card.get("token")})
        return people

    def _show_player_menu(self):
        menu = self._menu()
        characters = self._map_characters()
        spoken_for = {c["seat"] for c in characters if c.get("seat")}

        for entry in characters:
            label = entry["name"]
            if entry["owner"]:
                label = f"{entry['name']}  -  {entry['owner']}"
            menu.add_command(
                label=label,
                command=lambda e=entry: self._add(
                    {"name": e["name"], "stats": e["stats"],
                     "abilities": self._new_abilities()}, player=True))
        waiting = [p for p in self._table_people()
                   if p["seat"] not in spoken_for]
        if characters and waiting:
            menu.add_separator()
        for person in waiting:
            label = person["name"]
            if person["role"]:
                label = f"{person['name']}  ({person['role']})"
            menu.add_command(
                label=label,
                command=lambda p=person: self._add(
                    {"name": p["name"], "stats": self._new_stats(),
                     "abilities": self._new_abilities()}, player=True))
        if characters or waiting:
            menu.add_separator()
        menu.add_command(label="Player by hand...", command=self._add_by_hand)
        button = self.player_button
        menu.tk_popup(button.winfo_rootx(),
                      button.winfo_rooty() + button.winfo_height())

    def _add_by_hand(self):
        name = simpledialog.askstring("Add player", "Name:", parent=self.win)
        if not name or not name.strip():
            return
        bonus = simpledialog.askstring("Add player",
                                       f"{name.strip()}'s initiative bonus:",
                                       initialvalue="0", parent=self.win)
        if bonus is None:
            return
        stats = self._new_stats()
        for row in stats:
            if row[0] in INIT_STATS:
                row[1] = bonus.strip() or "0"
                break
        else:
            stats.append(["Init Mod", bonus.strip() or "0"])
        self._add({"name": name.strip(), "stats": stats,
                   "abilities": self._new_abilities()}, player=True)

    def _remove(self, creatures):
        names = ", ".join(c["name"] for c in creatures)
        if not messagebox.askyesno("Remove", f"Remove {names}?", parent=self.win):
            return
        gone = {c["id"] for c in creatures}
        self.creatures = [c for c in self.creatures if c["id"] not in gone]
        self.selected = [c for c in self.selected if c not in gone]
        self.order = [c for c in self.order if c not in gone]
        if self.running and not self.creatures:
            self._end_run()
            return
        self._render_left()
        self._render_stats()
        self._render_runner()
        self.save()

    def _to_library(self, creatures):
        """Keep a creature for next time - everything it carries, not just its
        numbers, so its attacks and its description come back with it."""
        for creature in creatures:
            entry = _body(creature, self.system)
            entry["name"] = self._base_name(creature["name"])
            for index, existing in enumerate(self.library):
                if existing["name"] == entry["name"]:
                    self.library[index] = entry
                    break
            else:
                self.library.append(entry)
        self.library.sort(key=lambda entry: entry["name"].lower())
        self.save()

    def _drop_library(self, index):
        entry = self.library[index]
        if messagebox.askyesno("Delete from library",
                               f"Delete {entry['name']} from the library?\n\n"
                               "Creatures already in the encounter are not "
                               "affected.", parent=self.win):
            del self.library[index]
            if self.pick is not None and self.pick >= len(self.library):
                self.pick = None
            self._render_left()
            self._render_stats()
            self.save()

    # -- initiative ---------------------------------------------------------
    def _init_mod(self, creature):
        for name, value in creature["stats"]:
            if name.strip() in INIT_STATS:
                return _number(value)
        return 0

    def _roll_for(self, creatures):
        """A d20 each - everyone acts on their own count."""
        for creature in creatures:
            creature["init"] = self.api.roll_die("d20") + self._init_mod(creature)
        self._after_rolling()

    def _roll_all(self):
        if self.creatures:
            self._roll_for(self.creatures)

    def _roll_group(self, creatures):
        """One d20 for the lot of them - the whole gang acts together. Each
        still adds its own modifier, so a quick goblin edges out a slow one."""
        names = ", ".join(c["name"] for c in creatures)
        if not messagebox.askyesno(
                "Group initiative",
                f"Roll one initiative for these {len(creatures)} creatures?"
                f"\n\n{names}", parent=self.win):
            return
        roll = self.api.roll_die("d20")
        for creature in creatures:
            creature["init"] = roll + self._init_mod(creature)
        self._after_rolling()

    def _clear_init(self, creatures):
        for creature in creatures:
            creature["init"] = None
        self._after_rolling()

    def _type_init(self, creature, widget):
        """Typed into a box. The number is taken as it is typed, but the
        roster is left standing - re-sorting under a half-typed number would
        pull the box out from under the next keystroke."""
        creature["init"] = _init_score(widget.get())
        self.schedule_save()

    def _enter_init(self, creature, widget):
        """Return - done with this one, so the list can settle now."""
        self._type_init(creature, widget)
        self._resettle()

    def _leave_init(self, creature, widget):
        """Focus has left a box. Reading it fails if the box went with a
        re-render rather than a click, and in that case its number was taken
        on the way in to that render anyway."""
        if self._settling:
            return
        try:
            creature["init"] = _init_score(widget.get())
        except tk.TclError:
            return
        self.schedule_save()
        self.win.after_idle(self._settle_if_done)

    def _settle_if_done(self):
        """Somebody filling the column in by hand goes box to box, and a
        re-sort between two of them would throw away the click that got
        there. So the order waits until the boxes are done with."""
        try:
            focus = self.win.focus_get()
        except (tk.TclError, KeyError):
            focus = None
        if getattr(focus, "_init_box", False):
            return
        self._resettle()

    def _resettle(self):
        """Back into initiative order after a number was typed by hand.
        Mid-fight the order is rebuilt around whoever is up, so correcting a
        number does not send the round back to the top."""
        if self._settling or not self.alive():
            return
        self._settling = True
        try:
            if self.running:
                order = self._turn_order()
                up = order[self.turn % len(order)] if order else None
                self.order = [c["id"] for c in self._sorted()]
                self.turn = self.order.index(up) if up in self.order else 0
            self._render_left()
            self._render_stats()
            self._render_runner()
            self.save()
        finally:
            self._settling = False

    def _after_rolling(self):
        if self.running:
            # A fresh roll means a fresh order; start the round over rather
            # than leave the turn marker pointing at whoever used to be here.
            self.order = [c["id"] for c in self._sorted()]
            self.turn = 0
        self._render_left()
        self._render_stats()
        self._render_runner()
        self.save()

    # -- rolling anything ---------------------------------------------------
    def _roll_one(self, sides):
        """One die. The app's own dice are used where there is one, so a d20
        keeps the house weighting; anything else falls back to a fair roll."""
        try:
            return self.api.roll_die(f"d{sides}")
        except KeyError:
            return dice_api.rng.randint(1, sides)

    def _roll_expr(self, expr):
        terms, flat = parse_dice(expr)
        rolled = [(mult, sides, [self._roll_one(sides) for _ in range(count)])
                  for mult, count, sides in terms]
        return rolled, flat

    def _do_roll(self, label, expr, mod=0, notes=()):
        """Roll an expression plus a modifier. The result goes to Roll History
        with everything else, and comes back as a line for this window."""
        rolled, flat = self._roll_expr(expr)
        if not rolled and not flat and not mod:
            return None
        total = sum(mult * sum(values) for mult, _s, values in rolled)
        total += flat + mod
        shown = []
        for mult, sides, values in rolled:
            sign = "-" if mult < 0 else ""
            shown.append(f"{sign}{len(values)}d{sides} "
                         + " ".join(str(v) for v in values))
        detail = "  ".join(shown)
        extra = flat + mod
        if not shown:
            detail = str(extra)         # a flat value, with no dice in it
        elif extra:
            detail = f"{detail}  {extra:+d}"

        groups = []
        grouped = 0
        for mult, sides, values in rolled:
            # A die the app does not have - a d3, say - cannot be shown as a
            # group, so it goes into the bonus instead. The total still reads
            # right; only the breakdown is shorter than the expression.
            if mult > 0 and f"d{sides}" in self.api.dice:
                groups.append(self.api.make_group(f"d{sides}", values))
                grouped += sum(values)
        if groups:
            # hooks=False: this roll carries its own modifiers, so the
            # Modifier panel must not quietly add another one on top.
            self.api.present(groups, label=label, bonus=total - grouped,
                             notes=list(notes), hooks=False)
        return {"total": total, "detail": detail, "rolled": rolled}

    def _flavour(self, rolled):
        """How to colour a total that turned on one d20."""
        for _mult, sides, values in rolled:
            if sides == 20 and len(values) == 1:
                if values[0] == 20:
                    return "crit"
                if values[0] == 1:
                    return "fumble"
        return "total"

    def _log(self, title, lines, notes=(), head=()):
        """Put a roll in the log beside the stats. Newest on top, so the one
        just made is the one being read without scrolling anywhere.

        `head` is what has to be read before the numbers - a save DC - and
        `notes` is what follows them, like what a failed save costs.
        """
        self.rolls.insert(0, {"title": title, "lines": list(lines),
                              "head": [n for n in head if n],
                              "notes": [n for n in notes if n]})
        del self.rolls[MAX_LOG:]
        self._render_log()

    def _clear_log(self):
        self.rolls = []
        self._render_log()

    def _render_log(self):
        box = getattr(self, "roll_log", None)
        if box is None:
            return
        try:
            box.configure(state="normal")
            box.delete("1.0", "end")
            for entry in self.rolls:
                box.insert("end", entry["title"] + "\n", "title")
                for note in entry["head"]:
                    box.insert("end", f"  {note}\n", "detail")
                for what, detail, total, tag, tail in entry["lines"]:
                    lead = f"  {what}  " if what else "  "
                    box.insert("end", f"{lead}{detail} = ", "detail")
                    box.insert("end", str(total), tag)
                    box.insert("end", f" {tail}\n" if tail else "\n", "detail")
                for note in entry["notes"]:
                    box.insert("end", f"  {note}\n", "detail")
                box.insert("end", "\n")
            box.configure(state="disabled")
            box.yview_moveto(0.0)
        except tk.TclError:
            self.roll_log = None    # the box went with a re-render

    # -- the creature, on the right -----------------------------------------
    def _build_stats(self):
        box = tk.Frame(self.win, bg=self.t["panel"])
        box.grid(row=0, column=1, sticky="nsew", padx=(4, 8), pady=8)
        box.rowconfigure(2, weight=1)
        box.columnconfigure(0, weight=1)

        top = tk.Frame(box, bg=self.t["panel"])
        top.grid(row=0, column=0, sticky="ew", padx=10, pady=(8, 6))
        self.stat_heading = self._heading(top, "CREATURE")
        self.stat_heading.pack(side="left")
        # Which game these numbers belong to. It decides the ability scores,
        # what a score is worth, and what a new creature starts with.
        self.system_var = tk.StringVar(value=self.system)
        self.system_button = self._tiny(top, "", self._show_system_menu)
        self.system_button.pack(side="right")

        self.stat_header = tk.Frame(box, bg=self.t["panel"])
        self.stat_header.grid(row=1, column=0, sticky="ew", padx=10)
        outer, self.stat_rows, self.stat_canvas = self._scroller(box)
        outer.grid(row=2, column=0, sticky="nsew", padx=6, pady=(6, 4))
        self.stat_rows.bind("<Button-3>", lambda e: self._stat_menu(None, e))
        self.stat_canvas.bind("<Button-3>", lambda e: self._stat_menu(None, e))
        outer.grid_configure(pady=(6, 10))

    def _subheading(self, parent, text):
        """A section label, with room on its right for a button."""
        row = tk.Frame(parent, bg=self.t["panel"])
        row.pack(fill="x", padx=6, pady=(10, 2))
        tk.Label(row, text=text, font=self.f["label"], bg=self.t["panel"],
                 fg=self.t["muted"], anchor="w").pack(side="left")
        return row

    def _render_stats(self):
        self._read_desc()
        self.desc_box = None
        self._desc_owner = None
        self._ability_mods = {}
        self.roll_log = None    # rebuilt with the stats, if they are shown
        for child in self.stat_header.winfo_children():
            child.destroy()
        for child in self.stat_rows.winfo_children():
            child.destroy()
        self.system_button.configure(text=self.system + "  v")

        entry = self._picked_entry() if self.mode == "picker" else None
        if entry is not None:
            self.stat_heading.configure(text="FROM THE LIBRARY")
            self._render_preview(entry)
            return

        self.stat_heading.configure(text="CREATURE")
        creature = self._current()
        if creature is None:
            message = ("Pick a creature on the left to see its stats, or add "
                       "one.")
            if self.mode == "picker":
                message = ("Pick a creature on the left to look it over "
                           "before it goes in.")
            tk.Label(self.stat_rows, text=message, font=self.f["label"],
                     bg=self.t["panel"], fg=self.t["muted"], anchor="w",
                     wraplength=380, justify="left").pack(fill="x", padx=6,
                                                          pady=6)
            return

        self._render_header(creature)
        self.ability_frame = tk.Frame(self.stat_rows, bg=self.t["panel"])
        self.ability_frame.pack(fill="x")
        self.stat_frame = tk.Frame(self.stat_rows, bg=self.t["panel"])
        self.stat_frame.pack(fill="x")
        self.action_frame = tk.Frame(self.stat_rows, bg=self.t["panel"])
        self.action_frame.pack(fill="x")
        self.desc_frame = tk.Frame(self.stat_rows, bg=self.t["panel"])
        self.desc_frame.pack(fill="x")
        self._render_abilities(creature)
        self._render_stat_rows(creature)
        self._render_actions(creature)
        self._render_desc(creature)

    def _render_header(self, creature):
        name = self._entry(self.stat_header, 20, creature["name"])
        name.pack(side="left", fill="x", expand=True, ipady=4)
        name.bind("<KeyRelease>",
                  lambda _e, c=creature, w=name: self._rename(c, w))
        init = creature["init"]
        tk.Label(self.stat_header,
                 text="init " + ("-" if init is None else str(init)),
                 font=self.f["die"], bg=self.t["panel"],
                 fg=self.t["muted"] if init is None else self.t["accent"]).pack(
                     side="left", padx=(8, 4))
        self._button(self.stat_header, "Roll",
                     lambda c=creature: self._roll_for([c])).pack(side="left")

    # -- ability scores ------------------------------------------------------
    def _mod_text(self, creature, key):
        """An empty box is no score yet, rather than a score of nothing."""
        if not str((creature.get("abilities") or {}).get(key, "")).strip():
            return "-"
        return _signed(self._ability_mod(creature, key))

    def _render_abilities(self, creature):
        frame = self.ability_frame
        for child in frame.winfo_children():
            child.destroy()
        keys = self._abilities(creature)
        if not keys:
            return          # a system with no ability scores shows none

        self._subheading(frame, "ABILITY SCORES")
        grid = tk.Frame(frame, bg=self.t["panel"])
        grid.pack(fill="x", padx=6)
        grid.columnconfigure(0, weight=1, uniform="ability")
        grid.columnconfigure(1, weight=1, uniform="ability")
        for index, key in enumerate(keys):
            cell = tk.Frame(grid, bg=self.t["panel"])
            cell.grid(row=index // 2, column=index % 2, sticky="ew", pady=1,
                      padx=(0, 6))
            tk.Label(cell, text=key, font=self.f["label"], bg=self.t["panel"],
                     fg=self.t["muted"], width=5, anchor="w").pack(side="left")
            box = self._entry(cell, 4,
                              creature["abilities"].get(key, ""))
            box.pack(side="left", ipady=2)
            mod = tk.Label(cell, text=self._mod_text(creature, key),
                           font=self.f["die"], bg=self.t["panel"],
                           fg=self.t["accent"], width=3)
            mod.pack(side="left", padx=(4, 0))
            self._ability_mods[key] = mod
            self._tiny(cell, "roll",
                       lambda c=creature, k=key: self._roll_ability(c, k)).pack(
                           side="left")
            box.bind("<KeyRelease>",
                     lambda _e, c=creature, k=key, w=box:
                     self._edit_ability(c, k, w))
        self._bind_wheel(frame, self.stat_canvas)

    def _edit_ability(self, creature, key, widget):
        """A score was typed. Its modifier is redrawn where it stands, and the
        actions with it - theirs are built out of these numbers - but the box
        being typed into is left exactly where it is."""
        creature.setdefault("abilities", {})[key] = widget.get()
        label = self._ability_mods.get(key)
        if label is not None:
            try:
                label.configure(text=self._mod_text(creature, key))
            except tk.TclError:
                pass
        self._render_actions(creature)
        self._render_stat_rows(creature)
        self.schedule_save()

    def _roll_ability(self, creature, key):
        mod = self._ability_mod(creature, key)
        result = self._do_roll(f"{creature['name']} - {key} check", "1d20",
                               mod)
        if result is None:
            return
        self._log(f"{creature['name']} - {key} check",
                  [_line("", result["detail"], result["total"],
                         self._flavour(result["rolled"]))])

    # -- stats ---------------------------------------------------------------
    def _stat_spec(self, creature, name, value):
        """What Roll beside a stat should roll: the expression, any modifier
        the stat's own value is worth, and the ability pinned to it. None for
        a stat that is a number to read rather than a roll to make."""
        pinned = (creature.get("rolls") or {}).get(name, {})
        ability = pinned.get("ability", "")
        terms, _flat = parse_dice(value)
        if terms:
            return value, 0, ability        # the value is itself the dice
        die = pinned.get("die", "")
        if not die and (_is_check_stat(name) or ability):
            die = "1d20"
        if not die:
            return None
        return die, _number(value), ability

    def _render_stat_rows(self, creature):
        """The stats down the left, and the roll log in the space beside them.

        The log wants to be where the eye already is - next to the numbers
        being rolled and the buttons rolling them - rather than on a line
        under everything else, which is easy to miss and only ever showed the
        last roll anyway.
        """
        outer = self.stat_frame
        for child in outer.winfo_children():
            child.destroy()
        outer.columnconfigure(0, weight=0)
        outer.columnconfigure(1, weight=1, minsize=150)
        frame = tk.Frame(outer, bg=self.t["panel"])
        frame.grid(row=0, column=0, sticky="nw")
        self._build_log(outer, creature)
        self._subheading(frame, "STATS")

        for index, (stat, value) in enumerate(creature["stats"]):
            row = tk.Frame(frame, bg=self.t["panel"])
            row.pack(fill="x", padx=4, pady=2)
            label = tk.Label(row, text=stat, font=self.f["label"],
                             bg=self.t["panel"], fg=self.t["muted"], width=14,
                             anchor="w")
            label.pack(side="left")
            field = self._entry(row, 12, value)
            field.pack(side="left", ipady=3)
            field.bind("<KeyRelease>",
                       lambda _e, c=creature, i=index, w=field:
                       self._edit_stat(c, i, w))

            spec = self._stat_spec(creature, stat, value)
            if spec is not None:
                self._tiny(row, "roll", lambda c=creature, i=index:
                           self._roll_stat(c, i), fg=self.t["accent"]).pack(
                               side="left", padx=(6, 0))
                ability = spec[2]
                if ability:
                    tk.Label(row, text=f"{ability} "
                             f"{_signed(self._ability_mod(creature, ability))}",
                             font=self.f["label"], bg=self.t["panel"],
                             fg=self.t["muted"]).pack(side="left", padx=(4, 0))
            for widget in (row, label, field):
                widget.bind("<Button-3>",
                            lambda e, i=index: self._stat_menu(i, e))

        tk.Label(frame, text="Right-click a stat to add, rename, remove, or "
                 "set what its Roll rolls.",
                 font=self.f["label"], bg=self.t["panel"], fg=self.t["muted"],
                 anchor="w", wraplength=230,
                 justify="left").pack(fill="x", padx=8, pady=(6, 0))
        self._bind_wheel(frame, self.stat_canvas)

    def _build_log(self, parent, creature):
        """The roll log. Tall enough to stand beside the stats without
        pushing what it can do off the bottom of the panel."""
        side = tk.Frame(parent, bg=self.t["panel"])
        side.grid(row=0, column=1, sticky="nsew", padx=(10, 4))
        head = self._subheading(side, "ROLLS")
        self._tiny(head, "clear", self._clear_log).pack(side="right")

        lines = max(9, min(16, len(creature["stats"]) + 5))
        box = tk.Text(side, height=lines, width=1, wrap="word",
                      font=self.f["label"], bg=self.t["bg"],
                      fg=self.t["muted"], relief="flat", bd=0, padx=6, pady=4,
                      cursor="arrow", highlightthickness=1,
                      highlightbackground=self.t["panel"],
                      highlightcolor=self.t["panel"])
        box.pack(fill="both", expand=True, padx=6, pady=(0, 2))
        box.tag_configure("title", foreground=self.t["fg"])
        box.tag_configure("detail", foreground=self.t["muted"])
        box.tag_configure("total", foreground=self.t["accent"],
                          font=self.f["die"])
        box.tag_configure("crit", foreground=self.t["crit"],
                          font=self.f["die"])
        box.tag_configure("fumble", foreground=self.t["fumble"],
                          font=self.f["die"])
        box.configure(state="disabled")
        self.roll_log = box
        self._render_log()

    def _roll_stat(self, creature, index):
        if index >= len(creature["stats"]):
            return
        name, value = creature["stats"][index]
        spec = self._stat_spec(creature, name, value)
        if spec is None:
            return
        expr, bonus, ability = spec
        mod = bonus + self._ability_mod(creature, ability)
        result = self._do_roll(f"{creature['name']} - {name}", expr, mod)
        if result is None:
            return
        self._log(f"{creature['name']} - {name}",
                  [_line("", result["detail"], result["total"],
                         self._flavour(result["rolled"]))])

    def _rename(self, creature, widget):
        creature["name"] = widget.get()
        self._render_left()
        self.schedule_save()

    def _edit_stat(self, creature, index, widget):
        creature["stats"][index][1] = widget.get()
        self.schedule_save()

    def _stat_menu(self, index, event):
        creature = self._current()
        if creature is None or self._picked_entry() is not None:
            return      # the panel is previewing a library entry, not editing
        menu = self._menu()
        menu.add_command(label="Add stat...", command=self._add_stat)
        if index is not None and index < len(creature["stats"]):
            stat = creature["stats"][index][0]
            menu.add_command(label=f"Rename '{stat}'...",
                             command=lambda: self._rename_stat(index))
            menu.add_command(label=f"Remove '{stat}'",
                             command=lambda: self._remove_stat(index))
            menu.add_separator()
            menu.add_command(label=f"Roll '{stat}' with...",
                             command=lambda: self._set_stat_roll(index))
            if (creature.get("rolls") or {}).get(stat):
                menu.add_command(label=f"Clear the roll on '{stat}'",
                                 command=lambda: self._clear_stat_roll(index))
        menu.add_separator()
        menu.add_command(label="Add something it can do...",
                         command=lambda: self._edit_action(None))
        menu.add_command(label="Save to library",
                         command=lambda: self._to_library([creature]))
        menu.tk_popup(event.x_root, event.y_root)

    def _add_stat(self):
        creature = self._current()
        if creature is None:
            return
        name = simpledialog.askstring("Add stat", "Stat name:", parent=self.win)
        if not name or not name.strip():
            return
        value = simpledialog.askstring("Add stat", f"{name.strip()} value:",
                                       parent=self.win) or ""
        creature["stats"].append([name.strip(), value.strip()])
        self._render_stats()
        self.save()

    def _rename_stat(self, index):
        creature = self._current()
        if creature is None or index >= len(creature["stats"]):
            return
        was = creature["stats"][index][0]
        name = simpledialog.askstring("Rename stat", "Stat name:",
                                      initialvalue=was, parent=self.win)
        if not name or not name.strip():
            return
        creature["stats"][index][0] = name.strip()
        # Whatever was pinned to the old name follows it, or a renamed stat
        # would quietly lose its Roll.
        pinned = (creature.get("rolls") or {}).pop(was, None)
        if pinned:
            creature.setdefault("rolls", {})[name.strip()] = pinned
        self._render_stats()
        self.save()

    def _remove_stat(self, index):
        creature = self._current()
        if creature is None or index >= len(creature["stats"]):
            return
        name = creature["stats"][index][0]
        del creature["stats"][index]
        (creature.get("rolls") or {}).pop(name, None)
        self._render_stats()
        self.save()

    def _set_stat_roll(self, index):
        creature = self._current()
        if creature is None or index >= len(creature["stats"]):
            return
        name, value = creature["stats"][index]
        pinned = (creature.get("rolls") or {}).get(name, {})
        _RollDialog(self, creature, name, value, pinned,
                    lambda spec: self._save_stat_roll(creature, name, spec))

    def _save_stat_roll(self, creature, name, spec):
        rolls = creature.setdefault("rolls", {})
        if spec.get("die") or spec.get("ability"):
            rolls[name] = spec
        else:
            rolls.pop(name, None)
        self._render_stats()
        self.save()

    def _clear_stat_roll(self, index):
        creature = self._current()
        if creature is None or index >= len(creature["stats"]):
            return
        (creature.get("rolls") or {}).pop(creature["stats"][index][0], None)
        self._render_stats()
        self.save()

    # -- things it can do ----------------------------------------------------
    def _describe_action(self, creature, action):
        """One line saying what an action does, with the numbers worked out."""
        bits = []
        if action["kind"] == "attack":
            if action["hit"] or action["hit_ability"]:
                hit = (_number(action["hit"])
                       + self._ability_mod(creature, action["hit_ability"]))
                bits.append(f"{_signed(hit)} to hit")
        else:
            if action["dc"]:
                ability = (f" {action['dc_ability']}"
                           if action["dc_ability"] else "")
                bits.append(f"DC {action['dc']}{ability} save")
        if action["dice"]:
            mod = self._ability_mod(creature, action["dmg_ability"])
            damage = action["dice"] + (_signed(mod) if mod else "")
            if action["dmg_type"]:
                damage += f" {action['dmg_type']}"
            bits.append(damage)
        return ", ".join(bits)

    def _action_detail(self, action):
        """The lines underneath: what happens, and anything else written in."""
        lines = []
        if action["kind"] == "save":
            if action["on_fail"]:
                lines.append(f"fail: {action['on_fail']}")
            if action["on_save"]:
                lines.append(f"save: {action['on_save']}")
        if action["note"]:
            lines.append(action["note"])
        return lines

    def _render_actions(self, creature):
        frame = self.action_frame
        for child in frame.winfo_children():
            child.destroy()
        head = self._subheading(frame, "WHAT IT CAN DO")
        self._tiny(head, "+ add", lambda: self._edit_action(None),
                   fg=self.t["accent"]).pack(side="right")

        if not creature["actions"]:
            tk.Label(frame, text="Nothing yet. Add an attack to roll to hit "
                     "and damage in one click, or a save for a number the "
                     "players have to beat.", font=self.f["label"],
                     bg=self.t["panel"], fg=self.t["muted"], anchor="w",
                     wraplength=360, justify="left").pack(fill="x", padx=8,
                                                          pady=(2, 0))
            self._bind_wheel(frame, self.stat_canvas)
            return

        for index, action in enumerate(creature["actions"]):
            block = tk.Frame(frame, bg=self.t["panel"])
            block.pack(fill="x", padx=4, pady=(2, 0))
            row = tk.Frame(block, bg=self.t["panel"])
            row.pack(fill="x")
            name = tk.Label(row, text=action["name"], font=self.f["label"],
                            bg=self.t["panel"], fg=self.t["fg"], width=14,
                            anchor="w")
            name.pack(side="left")
            summary = tk.Label(row, text=self._describe_action(creature, action),
                               font=self.f["label"], bg=self.t["panel"],
                               fg=self.t["accent"], anchor="w")
            summary.pack(side="left", fill="x", expand=True)
            # An attack rolls; a save is a number to read out, so its button
            # only offers the damage, and only when it has any.
            if action["kind"] == "attack":
                button = ("roll", self.t["accent"])
            elif action["dice"]:
                button = ("roll dmg", self.t["accent"])
            else:
                button = ("show", self.t["muted"])
            self._tiny(row, button[0],
                       lambda c=creature, a=action: self._use_action(c, a),
                       fg=button[1]).pack(side="right")

            for line in self._action_detail(action):
                tk.Label(block, text=line, font=self.f["label"],
                         bg=self.t["panel"], fg=self.t["muted"], anchor="w",
                         wraplength=340, justify="left").pack(
                             fill="x", padx=(16, 0))
            for widget in (block, row, name, summary):
                widget.bind("<Button-1>",
                            lambda _e, c=creature, a=action:
                            self._use_action(c, a))
                widget.bind("<Button-3>",
                            lambda e, i=index: self._action_menu(i, e))
        self._bind_wheel(frame, self.stat_canvas)

    def _use_action(self, creature, action):
        """Clicked. An attack is rolled; a save is read out, with its damage
        rolled if it has any - the save itself is the players' to make."""
        lines = []
        head = []
        notes = []
        if action["kind"] == "attack":
            mod = (_number(action["hit"])
                   + self._ability_mod(creature, action["hit_ability"]))
            hit = self._do_roll(
                f"{creature['name']} - {action['name']} to hit", "1d20", mod)
            if hit is not None:
                lines.append(_line("to hit", hit["detail"], hit["total"],
                                   self._flavour(hit["rolled"])))
        elif action["dc"]:
            ability = f" {action['dc_ability']}" if action["dc_ability"] else ""
            head.append(f"DC {action['dc']}{ability} save")
        if action["dice"]:
            mod = self._ability_mod(creature, action["dmg_ability"])
            damage = self._do_roll(
                f"{creature['name']} - {action['name']} damage",
                action["dice"], mod)
            if damage is not None:
                lines.append(_line("damage", damage["detail"],
                                   damage["total"], "total",
                                   action["dmg_type"]))
        # What a fail costs is written on the action's own row and stays
        # there, so the log keeps to what actually happened: the DC that was
        # in front of them, and whatever was rolled.
        if not lines and not head and not notes:
            notes = ["nothing set up to roll"]
        self._log(f"{creature['name']} - {action['name']}", lines, notes,
                  head=head)

    def _action_menu(self, index, event):
        creature = self._current()
        if creature is None or index >= len(creature["actions"]):
            return
        action = creature["actions"][index]
        menu = self._menu()
        menu.add_command(label=f"Edit '{action['name']}'...",
                         command=lambda: self._edit_action(index))
        menu.add_command(label="Duplicate",
                         command=lambda: self._copy_action(index))
        if index > 0:
            menu.add_command(label="Move up",
                             command=lambda: self._move_action(index, -1))
        if index < len(creature["actions"]) - 1:
            menu.add_command(label="Move down",
                             command=lambda: self._move_action(index, 1))
        menu.add_separator()
        menu.add_command(label="Add another...",
                         command=lambda: self._edit_action(None))
        menu.add_command(label=f"Remove '{action['name']}'",
                         command=lambda: self._drop_action(index))
        menu.tk_popup(event.x_root, event.y_root)

    def _edit_action(self, index):
        creature = self._current()
        if creature is None:
            return
        action = None
        if index is not None and index < len(creature["actions"]):
            action = creature["actions"][index]
        _ActionDialog(self, creature, action,
                      lambda built: self._keep_action(creature, index, built))

    def _keep_action(self, creature, index, action):
        if index is not None and index < len(creature["actions"]):
            creature["actions"][index] = action
        else:
            creature["actions"].append(action)
        # The whole panel rather than just the list: the dialog is not modal,
        # so the left-hand side may have turned into the picker while it was
        # open, and the section frames are gone in that case.
        self._render_stats()
        self.save()

    def _copy_action(self, index):
        creature = self._current()
        if creature is None or index >= len(creature["actions"]):
            return
        creature["actions"].insert(
            index + 1, _clean_action(creature["actions"][index]))
        self._render_stats()
        self.save()

    def _move_action(self, index, step):
        creature = self._current()
        if creature is None:
            return
        actions = creature["actions"]
        target = index + step
        if not 0 <= target < len(actions):
            return
        actions[index], actions[target] = actions[target], actions[index]
        self._render_stats()
        self.save()

    def _drop_action(self, index):
        creature = self._current()
        if creature is None or index >= len(creature["actions"]):
            return
        del creature["actions"][index]
        self._render_stats()
        self.save()

    # -- the description -----------------------------------------------------
    def _render_desc(self, creature):
        frame = self.desc_frame
        for child in frame.winfo_children():
            child.destroy()
        self._subheading(frame, "DESCRIPTION")
        box = tk.Text(frame, height=5, wrap="word", font=self.f["label"],
                      bg=self.t["bg"], fg=self.t["fg"],
                      insertbackground=self.t["fg"], relief="flat", bd=0,
                      padx=8, pady=6, highlightthickness=1,
                      highlightbackground=self.t["panel"],
                      highlightcolor=self.t["accent"])
        box.pack(fill="x", padx=6, pady=(0, 8))
        if creature["desc"]:
            box.insert("1.0", creature["desc"])
        box.bind("<KeyRelease>", lambda _e: self.schedule_save())
        self.desc_box = box
        self._desc_owner = creature["id"]
        self._bind_wheel(frame, self.stat_canvas)

    def _read_desc(self):
        """Whatever is in the description box right now. Read on the way to
        storage and on the way out of the panel, rather than on every
        keystroke, so typing into it stays cheap and the box keeps its
        cursor."""
        box = getattr(self, "desc_box", None)
        if box is None or self._desc_owner is None:
            return
        creature = self._find(self._desc_owner)
        if creature is None:
            return
        try:
            creature["desc"] = box.get("1.0", "end-1c")
        except tk.TclError:
            pass        # the box has gone; the last read still stands

    # -- a library entry, looked over before it goes in ----------------------
    def _render_preview(self, entry):
        wrap = 360
        tk.Label(self.stat_rows, text=entry["name"], font=self.f["title"],
                 bg=self.t["panel"], fg=self.t["fg"], anchor="w").pack(
                     fill="x", padx=8, pady=(4, 2))

        keys = [key for key in self._abilities() if key in entry["abilities"]]
        keys += [key for key in entry["abilities"] if key not in keys]
        if keys:
            rule = self._system()["rule"]
            scores = []
            for key in keys:
                raw = str(entry["abilities"].get(key, "")).strip()
                if not raw:
                    continue
                scores.append(f"{key} {raw} "
                              f"({_signed(ability_mod(_number(raw), rule))})")
            if scores:
                tk.Label(self.stat_rows, text="   ".join(scores),
                         font=self.f["label"], bg=self.t["panel"],
                         fg=self.t["muted"], anchor="w", wraplength=wrap,
                         justify="left").pack(fill="x", padx=8, pady=(0, 6))

        for name, value in entry["stats"]:
            row = tk.Frame(self.stat_rows, bg=self.t["panel"])
            row.pack(fill="x", padx=8)
            tk.Label(row, text=name, font=self.f["label"], bg=self.t["panel"],
                     fg=self.t["muted"], width=14, anchor="w").pack(side="left")
            tk.Label(row, text=value, font=self.f["label"],
                     bg=self.t["panel"], fg=self.t["fg"], anchor="w").pack(
                         side="left")

        if entry["actions"]:
            self._subheading(self.stat_rows, "WHAT IT CAN DO")
            # Modifiers that come off an ability score are worked out against
            # the entry's own scores, so the preview reads like the creature
            # will once it is in.
            stand_in = dict(entry)
            for action in entry["actions"]:
                tk.Label(self.stat_rows,
                         text=f"{action['name']}  -  "
                              f"{self._describe_action(stand_in, action)}",
                         font=self.f["label"], bg=self.t["panel"],
                         fg=self.t["fg"], anchor="w", wraplength=wrap,
                         justify="left").pack(fill="x", padx=8, pady=1)
                for line in self._action_detail(action):
                    tk.Label(self.stat_rows, text=line, font=self.f["label"],
                             bg=self.t["panel"], fg=self.t["muted"],
                             anchor="w", wraplength=wrap - 20,
                             justify="left").pack(fill="x", padx=(24, 8))

        if entry["desc"]:
            self._subheading(self.stat_rows, "DESCRIPTION")
            tk.Label(self.stat_rows, text=entry["desc"], font=self.f["label"],
                     bg=self.t["panel"], fg=self.t["fg"], anchor="w",
                     wraplength=wrap, justify="left").pack(fill="x", padx=8,
                                                           pady=(0, 8))
        self._bind_wheel(self.stat_rows, self.stat_canvas)

    # -- systems -------------------------------------------------------------
    def _show_system_menu(self):
        menu = self._menu()
        self.system_var.set(self.system)
        for entry in self.systems:
            menu.add_radiobutton(label=entry["name"], value=entry["name"],
                                 variable=self.system_var,
                                 command=lambda n=entry["name"]:
                                 self._use_system(n))
        menu.add_separator()
        menu.add_command(label=f"Edit '{self.system}'...",
                         command=lambda: self._open_system(self._system()))
        menu.add_command(label="New system...", command=self._new_system)
        if len(self.systems) > 1:
            menu.add_command(label=f"Delete '{self.system}'",
                             command=self._delete_system)
        button = self.system_button
        menu.tk_popup(button.winfo_rootx(),
                      button.winfo_rooty() + button.winfo_height())

    def _use_system(self, name):
        """Switch games. Creatures keep every number they already have - the
        system only decides which ability scores are offered, what a score is
        worth, and what the next new creature starts with."""
        self.system = name
        self.system_var.set(name)
        self._render_stats()
        self.save()

    def _new_system(self):
        blank = {"name": "", "rule": self._system()["rule"],
                 "abilities": list(self._system()["abilities"]),
                 "stats": copy.deepcopy(self._system()["stats"])}
        self._open_system(blank, new=True)

    def _open_system(self, system, new=False):
        _SystemDialog(self, system, new,
                      lambda built: self._keep_system(
                          built, "" if new else system["name"]))

    def _keep_system(self, built, was):
        """Save a system preset.

        `was` is the name it had before, or blank for a new one. Editing a
        system under a different name renames it rather than leaving a stale
        copy behind, and the creatures that were on the old name follow it.
        A name that is already taken replaces the preset that had it.
        """
        if was and was != built["name"]:
            for creature in self.creatures:
                if creature.get("system") == was:
                    creature["system"] = built["name"]
            self.systems = [entry for entry in self.systems
                            if entry["name"] != was]
        for index, entry in enumerate(self.systems):
            if entry["name"] == built["name"]:
                self.systems[index] = built
                break
        else:
            self.systems.append(built)
        self.system = built["name"]
        self.system_var.set(self.system)
        self._render_stats()
        self.save()

    def _delete_system(self):
        if len(self.systems) <= 1:
            return
        name = self.system
        if not messagebox.askyesno(
                "Delete system",
                f"Delete the system '{name}'?\n\nCreatures keep every number "
                "they already have. Only the preset goes.",
                parent=self.win):
            return
        self.systems = [entry for entry in self.systems
                        if entry["name"] != name]
        self.system = self.systems[0]["name"]
        self.system_var.set(self.system)
        self._render_stats()
        self.save()


    # -- saved encounters ----------------------------------------------------
    # An encounter is kept under a name, either with the campaign or beside
    # the app where every campaign can see it. Which of the two lists it is
    # in is the whole of what "shared" means - there is no flag to disagree
    # with, and sharing one is moving it from the one list to the other.
    #
    # The shared list comes off disk every time it is asked for, so that a
    # campaign switched in another window is not working from a stale copy.
    # That means a caller changing one must read the list once and write that
    # same list back: an entry found in one call is not the entry in the next.
    def _shelf(self, shared):
        return load_shared() if shared else self.saved

    def _put_shelf(self, shared, entries):
        entries.sort(key=lambda entry: entry["name"].lower())
        if shared:
            save_shared(entries)
        else:
            self.saved = entries
        self.save()

    def _find_saved(self, name, shared, entries=None):
        for entry in (self._shelf(shared) if entries is None else entries):
            if entry["name"] == name:
                return entry
        return None

    def _is_open(self, name, shared):
        """Whether the encounter being acted on is the one on the board."""
        return (self.current["name"] == name
                and self.current["shared"] == bool(shared))

    def _build_menubar(self):
        style = {"bg": self.t["panel"], "fg": self.t["fg"],
                 "activebackground": self.t["accent"],
                 "activeforeground": self.t["bg"], "relief": "flat", "bd": 0,
                 "font": self.f["label"], "tearoff": 0}
        self._menu_style = style
        self.menubar = tk.Menu(self.win, **style)
        self.file_menu = tk.Menu(self.menubar, **style)
        self.menubar.add_cascade(label="File", menu=self.file_menu)
        self.win.configure(menu=self.menubar)
        self._rebuild_file_menu()

    def _rebuild_file_menu(self):
        """Redrawn whenever the list of saved encounters changes."""
        menu = self.file_menu
        menu.delete(0, "end")
        menu.add_command(label="New encounter", command=self._new_encounter)
        menu.add_separator()
        menu.add_command(label="Save encounter", command=self._save_encounter)
        menu.add_command(label="Save encounter as...",
                         command=self._save_encounter_as)
        menu.add_separator()

        opens = tk.Menu(menu, **self._menu_style)
        mine = self.saved
        shared = load_shared()
        for entry in mine:
            opens.add_command(
                label=entry["name"],
                command=lambda n=entry["name"]: self._load_encounter(n, False))
        if mine and shared:
            opens.add_separator()
        for entry in shared:
            # Marked, because loading one and saving over it changes the copy
            # that every campaign sees.
            opens.add_command(
                label=f"{entry['name']}   (shared)",
                command=lambda n=entry["name"]: self._load_encounter(n, True))
        if not mine and not shared:
            opens.add_command(label="nothing saved yet", state="disabled")
        menu.add_cascade(label="Load encounter", menu=opens)
        menu.add_command(label="Saved encounters...", command=self._manage)
        menu.add_separator()
        menu.add_command(label="Close window", command=self._close)

    def _show_name(self):
        """The name of the encounter that is open, on the window and over the
        roster - the point of naming one is being able to see which it is."""
        name = self.current["name"]
        title = f"Encounters - {self.api.save_name}"
        if name:
            title += f" - {name}"
        try:
            self.win.title(title)
            self.name_label.configure(
                text=(name + ("  (shared)" if self.current["shared"] else ""))
                if name else "not saved")
        except tk.TclError:
            pass

    # -- what the File menu does ---------------------------------------------
    def _snapshot(self, name):
        """The encounter as it stands, ready to go on the shelf."""
        self._read_notes()
        self._read_desc()
        creatures = []
        for creature in self.creatures:
            kept = copy.deepcopy(creature)
            kept["init"] = None     # prepared, not halfway through
            creatures.append(kept)
        return {"name": name, "creatures": creatures,
                "summary": self.summary, "treasure": self.treasure}

    def _store_encounter(self, name, shared):
        entries = [e for e in self._shelf(shared) if e["name"] != name]
        entries.append(self._snapshot(name))
        self.current = {"name": name, "shared": bool(shared)}
        self._put_shelf(shared, entries)
        self._show_name()
        self._rebuild_file_menu()

    def _save_encounter(self):
        """Save over the one that is open, or ask where to put it."""
        if not self.current["name"]:
            return self._save_encounter_as()
        self._store_encounter(self.current["name"], self.current["shared"])
        return True

    def _save_encounter_as(self):
        """Returns whether anything was saved, so a caller that asks before
        throwing the board away knows whether to carry on."""
        done = {"saved": False}

        def keep(name, shared):
            if self._find_saved(name, shared) is not None:
                where = "every campaign" if shared else "this campaign"
                if not messagebox.askyesno(
                        "Save encounter",
                        f"'{name}' is already saved for {where}.\n\n"
                        "Replace it?", parent=self.win):
                    return False
            self._store_encounter(name, shared)
            done["saved"] = True
            return True

        dialog = _SaveDialog(self, self.current, keep)
        self.win.wait_window(dialog.win)
        return done["saved"]

    def _keep_current(self, what):
        """Called before the board is thrown away. Anything with a name is
        written back without asking - that is what having a name is for.
        Anything else is offered the chance. False means: leave it alone."""
        if not self.creatures:
            return True
        if self.current["name"]:
            self._store_encounter(self.current["name"], self.current["shared"])
            return True
        answer = messagebox.askyesnocancel(
            what, "The encounter open now has never been saved.\n\n"
                  "Save it first?", parent=self.win)
        if answer is None:
            return False
        if answer:
            return self._save_encounter_as()
        return True

    def _clear_board(self):
        self.creatures = []
        self.selected = []
        self.order = []
        self.running = False
        self.round = 1
        self.turn = 0
        self.rolls = []
        self.mode = "roster"
        self.pick = None

    def _redraw(self):
        self._set_notes()
        self._show_name()
        self._render_left()
        self._render_stats()
        self._render_runner()
        self._rebuild_file_menu()
        self.save()

    def _new_encounter(self):
        if not self._keep_current("New encounter"):
            return
        self._clear_board()
        self.current = {"name": "", "shared": False}
        self.summary = ""
        self.treasure = ""
        self._redraw()

    def _load_encounter(self, name, shared):
        if self._find_saved(name, shared) is None:
            messagebox.showinfo("Load encounter",
                                f"'{name}' is not there any more.",
                                parent=self.win)
            self._rebuild_file_menu()
            return
        if not self._keep_current("Load encounter"):
            return
        # Looked up again on the far side of that: putting the board away may
        # have written over this very record, and the copy read a moment ago
        # would be the version from before it did.
        entry = self._find_saved(name, shared)
        if entry is None:
            return
        creatures = [self._clean(raw) for raw in entry["creatures"]]
        for creature in creatures:
            # Fresh ids: loading the same encounter twice in one sitting must
            # not leave two creatures answering to the same one.
            creature["id"] = uuid.uuid4().hex[:8]
            creature["init"] = None
        self._clear_board()
        self.creatures = creatures
        self.summary = entry["summary"]
        self.treasure = entry["treasure"]
        self.current = {"name": name, "shared": bool(shared)}
        self._redraw()

    def _set_notes(self):
        """Put the loaded notes into the two boxes along the bottom."""
        for box, value in ((getattr(self, "summary_box", None), self.summary),
                           (getattr(self, "treasure_box", None),
                            self.treasure)):
            if box is None:
                continue
            try:
                box.delete("1.0", "end")
                if value:
                    box.insert("1.0", value)
            except tk.TclError:
                pass

    def _manage(self):
        _ShelfDialog(self)

    # -- what the manager does -----------------------------------------------
    def _rename_encounter(self, name, shared, into):
        into = into.strip()
        if not into or into == name:
            return False
        entries = self._shelf(shared)
        if self._find_saved(into, shared, entries) is not None:
            messagebox.showinfo("Rename", f"'{into}' is already saved here.",
                                parent=self.win)
            return False
        entry = self._find_saved(name, shared, entries)
        if entry is None:
            return False
        entry["name"] = into
        self._put_shelf(shared, entries)
        if self._is_open(name, shared):
            self.current["name"] = into
            self._show_name()
        self._rebuild_file_menu()
        return True

    def _copy_encounter(self, name, shared):
        """A duplicate to change a little, rather than one built again."""
        entries = self._shelf(shared)
        entry = self._find_saved(name, shared, entries)
        if entry is None:
            return None
        taken = {e["name"] for e in entries}
        fresh = f"{name} copy"
        number = 2
        while fresh in taken:
            fresh = f"{name} copy {number}"
            number += 1
        made = _clean_saved(copy.deepcopy(entry))
        made["name"] = fresh
        entries.append(made)
        self._put_shelf(shared, entries)
        self._rebuild_file_menu()
        return fresh

    def _share_encounter(self, name, shared):
        """Move it between the campaign's shelf and the one every campaign
        can see. There is only ever the one copy, so editing it afterwards
        edits the copy everybody gets."""
        leaving = self._shelf(shared)
        entry = self._find_saved(name, shared, leaving)
        if entry is None:
            return None
        landing = self._shelf(not shared)
        if self._find_saved(name, not shared, landing) is not None:
            where = "this campaign" if shared else "every campaign"
            if not messagebox.askyesno(
                    "Move encounter",
                    f"'{name}' is already saved for {where}.\n\n"
                    "Replace it?", parent=self.win):
                return None
        moved = _clean_saved(copy.deepcopy(entry))
        self._put_shelf(shared, [e for e in leaving if e["name"] != name])
        self._put_shelf(not shared,
                        [e for e in landing if e["name"] != name] + [moved])
        if self._is_open(name, shared):
            self.current["shared"] = not shared
            self._show_name()
        self._rebuild_file_menu()
        return not shared

    def _delete_encounter(self, name, shared):
        where = "every campaign" if shared else "this campaign"
        if not messagebox.askyesno(
                "Delete encounter",
                f"Delete '{name}' from {where}?\n\nThe encounter open now is "
                "not affected.", parent=self.win):
            return False
        self._put_shelf(shared, [e for e in self._shelf(shared)
                                 if e["name"] != name])
        if self._is_open(name, shared):
            self.current = {"name": "", "shared": False}
            self._show_name()
        self._rebuild_file_menu()
        return True

    # -- the notes, along the bottom -----------------------------------------
    def _build_summary(self):
        box = tk.Frame(self.win, bg=self.t["panel"])
        box.grid(row=1, column=0, columnspan=2, sticky="ew", padx=8,
                 pady=(0, 4))
        # What is going on, and what comes of it. Two ends of the same fight:
        # the first is written before it starts, the second once it is won.
        self.summary_box = self._note_box(box, "WHAT'S GOING ON",
                                          self.summary, 4)
        self.treasure_box = self._note_box(box, "TREASURE AND REWARDS",
                                           self.treasure, 3)

    def _note_box(self, parent, heading, value, height):
        self._heading(parent, heading).pack(fill="x", padx=10, pady=(8, 4))
        widget = tk.Text(
            parent, height=height, wrap="word", font=self.f["label"],
            bg=self.t["bg"], fg=self.t["fg"], insertbackground=self.t["fg"],
            relief="flat", bd=0, padx=8, pady=6, highlightthickness=1,
            highlightbackground=self.t["panel"],
            highlightcolor=self.t["accent"])
        widget.pack(fill="x", padx=10, pady=(0, 10))
        if value:
            widget.insert("1.0", value)
        widget.bind("<KeyRelease>", lambda _e: self.schedule_save())
        return widget

    def _read_notes(self):
        """Whatever is in the two boxes right now. Called on the way to
        storage rather than on every keystroke, so typing stays cheap."""
        for name, attribute in (("summary_box", "summary"),
                                ("treasure_box", "treasure")):
            box = getattr(self, name, None)
            if box is None:
                continue
            try:
                setattr(self, attribute, box.get("1.0", "end-1c"))
            except tk.TclError:
                pass    # the window has gone; the last read still stands

    # -- running the encounter ----------------------------------------------
    def _build_runner(self):
        self.runner = tk.Frame(self.win, bg=self.t["panel"])
        self.runner.grid(row=2, column=0, columnspan=2, sticky="ew",
                         padx=8, pady=(0, 8))
        self.runner.grid_remove()

        self.round_label = tk.Label(self.runner, text="", font=self.f["title"],
                                    bg=self.t["panel"], fg=self.t["accent"])
        self.round_label.pack(side="left", padx=(12, 16), pady=10)
        self.turn_label = tk.Label(self.runner, text="", font=self.f["title"],
                                   bg=self.t["panel"], fg=self.t["fg"])
        self.turn_label.pack(side="left")
        self.next_label = tk.Label(self.runner, text="", font=self.f["label"],
                                   bg=self.t["panel"], fg=self.t["muted"])
        self.next_label.pack(side="left", padx=12)
        self._button(self.runner, "End", self._end_run,
                     fg=self.t["muted"]).pack(side="right", padx=(6, 12),
                                              ipady=4)
        self._button(self.runner, "  Next  ", self._next_turn,
                     fg=self.t["crit"]).pack(side="right", ipady=4)

    def _toggle_run(self):
        if self.running:
            self._end_run()
        else:
            self._start_run()

    def _start_run(self):
        if not self.creatures:
            messagebox.showinfo("Run encounter", "Add a creature or two first.",
                                parent=self.win)
            return
        # Anyone still without a count gets one now, rather than the fight
        # starting with half the room in an undefined place in the order.
        for creature in self.creatures:
            if creature["init"] is None:
                creature["init"] = (self.api.roll_die("d20")
                                    + self._init_mod(creature))
        self.running = True
        self.round = 1
        self.turn = 0
        self.order = [c["id"] for c in self._sorted()]
        # A fight being run wants the roster, not the shop.
        self.mode = "roster"
        self.pick = None
        self._render_left()
        self._render_stats()
        self._render_runner()
        self.save()

    def _end_run(self):
        self.running = False
        self.round = 1
        self.turn = 0
        self.order = []
        self._render_left()
        self._render_stats()
        self._render_runner()
        self.save()

    def _next_turn(self):
        order = self._turn_order()
        if not order:
            return
        self.turn += 1
        if self.turn >= len(order):
            self.turn = 0
            self.round += 1
        self._render_left()
        self._render_runner()
        self.save()

    def _render_runner(self):
        if not self.running:
            self.runner.grid_remove()
            self.run_button.configure(text="Run Encounter", fg=self.t["crit"])
            return
        self.runner.grid()
        self.run_button.configure(text="End Encounter", fg=self.t["fumble"])
        order = self._turn_order()
        if not order:
            return
        self.turn %= len(order)
        now = self._find(order[self.turn])
        later = self._find(order[(self.turn + 1) % len(order)])
        self.round_label.configure(text=f"Round {self.round}")
        self.turn_label.configure(text=now["name"] if now else "-")
        if later is not None and len(order) > 1:
            self.next_label.configure(text=f"up next: {later['name']}")
        else:
            self.next_label.configure(text="")


# --------------------------------------------------------------------------
# The little windows: one for an action, one for a stat's roll, one for a
# system. All three are the same shape - fill the boxes in, Save or Cancel -
# so they share the furniture.
# --------------------------------------------------------------------------
class _Dialog:
    def __init__(self, owner, title, width=None):
        self.owner = owner
        self.api = owner.api
        self.t = owner.t
        self.f = owner.f

        self.win = tk.Toplevel(owner.win)
        self.win.title(title)
        self.win.configure(bg=self.t["bg"])
        self.win.transient(owner.win)
        self.win.resizable(False, False)
        self.body = tk.Frame(self.win, bg=self.t["bg"])
        self.body.pack(padx=16, pady=14, fill="both", expand=True)
        self.win.bind("<Escape>", lambda _e: self.win.destroy())
        if width:
            self.body.configure(width=width)

    # -- furniture ---------------------------------------------------------
    def heading(self, parent, text):
        return tk.Label(parent, text=text, font=self.f["label"],
                        bg=self.t["bg"], fg=self.t["muted"], anchor="w")

    def note(self, parent, text, wrap=380):
        return tk.Label(parent, text=text, font=self.f["label"],
                        bg=self.t["bg"], fg=self.t["muted"], anchor="w",
                        wraplength=wrap, justify="left")

    def entry(self, parent, width, value=""):
        widget = tk.Entry(parent, width=width, font=self.f["label"],
                          bg=self.t["panel"], fg=self.t["fg"],
                          insertbackground=self.t["fg"], relief="flat", bd=0,
                          highlightthickness=1,
                          highlightbackground=self.t["panel"],
                          highlightcolor=self.t["accent"])
        if value:
            widget.insert(0, value)
        return widget

    def button(self, parent, text, command, fg=None, bg=None):
        return tk.Button(parent, text=text, font=self.f["label"],
                         bg=bg or self.t["bg"], fg=fg or self.t["fg"],
                         activebackground=self.t["accent"],
                         activeforeground=self.t["bg"], relief="flat", bd=0,
                         cursor="hand2", command=command)

    def picker(self, parent, value, options, width=8):
        """A drop-down. Returns the variable it writes into."""
        var = tk.StringVar(value=value if value in options else options[0])
        menu = tk.OptionMenu(parent, var, *options)
        menu.config(font=self.f["label"], bg=self.t["panel"], fg=self.t["fg"],
                    activebackground=self.t["accent"],
                    activeforeground=self.t["bg"], relief="flat", bd=0,
                    highlightthickness=0, width=width, cursor="hand2",
                    anchor="w")
        menu["menu"].config(bg=self.t["panel"], fg=self.t["fg"],
                            activebackground=self.t["accent"],
                            activeforeground=self.t["bg"],
                            font=self.f["label"], bd=0)
        menu.pack(side="left")
        return var

    def footer(self, on_save, save_text="Save", extra=None):
        bar = tk.Frame(self.body, bg=self.t["bg"])
        bar.pack(fill="x", pady=(14, 0))
        if extra is not None:
            extra(bar)
        self.button(bar, save_text, on_save, fg=self.t["bg"],
                    bg=self.t["accent"]).pack(side="right", padx=(6, 0),
                                              ipadx=10, ipady=4)
        self.button(bar, "Cancel", self.win.destroy,
                    fg=self.t["muted"]).pack(side="right", ipadx=6, ipady=4)
        self.win.bind("<Return>", lambda _e: on_save())

    def field(self, parent, label, width, value="", hint=""):
        """A labelled box on one line, with room for a hint after it."""
        row = tk.Frame(parent, bg=self.t["bg"])
        row.pack(fill="x", pady=2)
        tk.Label(row, text=label, font=self.f["label"], bg=self.t["bg"],
                 fg=self.t["muted"], width=10, anchor="w").pack(side="left")
        box = self.entry(row, width, value)
        box.pack(side="left", ipady=3)
        if hint:
            tk.Label(row, text=hint, font=self.f["label"], bg=self.t["bg"],
                     fg=self.t["muted"]).pack(side="left", padx=(8, 0))
        return box, row

    def ability_options(self, creature=None):
        """Every ability a modifier could come off, with a way to say none."""
        return ["-"] + self.owner._abilities(creature)


class _RollDialog(_Dialog):
    """What the Roll beside one stat should do.

    Two questions: which die, and which ability score goes on top. A stat
    whose value is already dice - 1d6+2 - needs neither, and says so.
    """

    def __init__(self, owner, creature, stat, value, pinned, on_save):
        super().__init__(owner, f"Roll - {stat}")
        self.on_save = on_save
        terms, _flat = parse_dice(value)

        tk.Label(self.body, text=f"{stat}   {value}", font=self.f["title"],
                 bg=self.t["bg"], fg=self.t["fg"], anchor="w").pack(fill="x")
        if terms:
            self.note(self.body, "This value is dice already, so Roll rolls "
                      "it as it stands. An ability score can still be added "
                      "on top.").pack(fill="x", pady=(2, 10))
        else:
            self.note(self.body, "The value is a modifier, so pick the die it "
                      "gets added to. 1d20 for a check or an attack.").pack(
                          fill="x", pady=(2, 10))

        self.die, _row = self.field(
            self.body, "Die", 12, pinned.get("die", ""),
            hint="blank for none" if terms else "e.g. 1d20")

        row = tk.Frame(self.body, bg=self.t["bg"])
        row.pack(fill="x", pady=2)
        tk.Label(row, text="Ability", font=self.f["label"], bg=self.t["bg"],
                 fg=self.t["muted"], width=10, anchor="w").pack(side="left")
        self.ability = self.picker(row, pinned.get("ability", "") or "-",
                                   self.ability_options(creature))
        tk.Label(row, text="its modifier is added to the roll",
                 font=self.f["label"], bg=self.t["bg"],
                 fg=self.t["muted"]).pack(side="left", padx=(8, 0))

        self.footer(self._save)

    def _save(self):
        ability = self.ability.get()
        self.on_save({"die": self.die.get().strip(),
                      "ability": "" if ability == "-" else ability})
        self.win.destroy()


class _ActionDialog(_Dialog):
    """One thing a creature can do.

    An attack rolls to hit and rolls damage. A save does not roll at all for
    itself - it is a number the players have to beat - so it asks for the DC,
    which save it is, and what happens either way.
    """

    def __init__(self, owner, creature, action, on_save):
        super().__init__(owner, "Action")
        self.on_save = on_save
        self.creature = creature
        fresh = action is None
        action = _clean_action(action or {})
        abilities = self.ability_options(creature)

        # A new one starts on an empty name rather than the word _clean_action
        # falls back to, so the first thing typed is not typed into "Attack".
        self.name, _row = self.field(self.body, "Name", 24,
                                     "" if fresh else action["name"],
                                     hint="Bite, Longsword, Poison Spray")

        kind = tk.Frame(self.body, bg=self.t["bg"])
        kind.pack(fill="x", pady=(8, 4))
        tk.Label(kind, text="It is", font=self.f["label"], bg=self.t["bg"],
                 fg=self.t["muted"], width=10, anchor="w").pack(side="left")
        self.kind = tk.StringVar(value=action["kind"])
        for value, text in (("attack", "an attack"), ("save", "a save")):
            tk.Radiobutton(kind, text=text, value=value, variable=self.kind,
                           command=self._swap, font=self.f["label"],
                           bg=self.t["bg"], fg=self.t["fg"],
                           activebackground=self.t["bg"],
                           activeforeground=self.t["accent"],
                           selectcolor=self.t["panel"], relief="flat", bd=0,
                           highlightthickness=0,
                           cursor="hand2").pack(side="left", padx=(0, 10))

        # -- the attack half
        self.attack_box = tk.Frame(self.body, bg=self.t["bg"])
        self.heading(self.attack_box, "TO HIT").pack(fill="x", pady=(8, 2))
        row = tk.Frame(self.attack_box, bg=self.t["bg"])
        row.pack(fill="x", pady=2)
        tk.Label(row, text="Bonus", font=self.f["label"], bg=self.t["bg"],
                 fg=self.t["muted"], width=10, anchor="w").pack(side="left")
        self.hit = self.entry(row, 6, action["hit"])
        self.hit.pack(side="left", ipady=3)
        tk.Label(row, text="+", font=self.f["label"], bg=self.t["bg"],
                 fg=self.t["muted"]).pack(side="left", padx=6)
        self.hit_ability = self.picker(row, action["hit_ability"] or "-",
                                      abilities)
        self.note(self.attack_box, "A d20 is rolled, plus the bonus, plus the "
                  "ability's modifier. Write the whole bonus in and leave the "
                  "ability at - to use the number a stat block prints.").pack(
                      fill="x", pady=(2, 0))

        # -- shared damage
        self.damage_box = tk.Frame(self.body, bg=self.t["bg"])
        self.damage_box.pack(fill="x")
        self.heading(self.damage_box, "DAMAGE").pack(fill="x", pady=(10, 2))
        row = tk.Frame(self.damage_box, bg=self.t["bg"])
        row.pack(fill="x", pady=2)
        tk.Label(row, text="Dice", font=self.f["label"], bg=self.t["bg"],
                 fg=self.t["muted"], width=10, anchor="w").pack(side="left")
        self.dice = self.entry(row, 10, action["dice"])
        self.dice.pack(side="left", ipady=3)
        tk.Label(row, text="+", font=self.f["label"], bg=self.t["bg"],
                 fg=self.t["muted"]).pack(side="left", padx=6)
        self.dmg_ability = self.picker(row, action["dmg_ability"] or "-",
                                       abilities)
        self.dmg_type, _row = self.field(self.damage_box, "Type", 14,
                                         action["dmg_type"],
                                         hint="slashing, fire, poison")
        self.note(self.damage_box, "1d8, 2d6+2, or blank for an attack that "
                  "does none. Pick an ability and its modifier is added, so a "
                  "stronger creature hits harder without the dice "
                  "changing.").pack(fill="x", pady=(2, 0))

        # -- the save half
        self.save_box = tk.Frame(self.body, bg=self.t["bg"])
        self.heading(self.save_box, "THE SAVE").pack(fill="x", pady=(10, 2))
        row = tk.Frame(self.save_box, bg=self.t["bg"])
        row.pack(fill="x", pady=2)
        tk.Label(row, text="DC", font=self.f["label"], bg=self.t["bg"],
                 fg=self.t["muted"], width=10, anchor="w").pack(side="left")
        self.dc = self.entry(row, 8, action["dc"])
        self.dc.pack(side="left", ipady=3)
        tk.Label(row, text="against", font=self.f["label"], bg=self.t["bg"],
                 fg=self.t["muted"]).pack(side="left", padx=6)
        self.dc_ability = self.picker(row, action["dc_ability"] or "-",
                                      abilities)
        self.on_fail, _row = self.field(self.save_box, "On a fail", 30,
                                        action["on_fail"],
                                        hint="poisoned for an hour")
        self.on_pass, _row = self.field(self.save_box, "On a save", 30,
                                        action["on_save"],
                                        hint="half damage")
        self.note(self.save_box, "Nothing is rolled for a save: the DC is the "
                  "players' number to beat, so it is shown instead. Damage, "
                  "if there is any, still rolls.").pack(fill="x", pady=(2, 0))

        self.note_box, _row = self.field(self.body, "Note", 34, action["note"],
                                         hint="")
        self._swap()
        self.footer(self._save)
        self.win.after(10, self.name.focus_set)

    def _swap(self):
        """Show the half that belongs to the kind that is selected. Damage is
        on both, so it stays put and only moves down the order."""
        self.attack_box.pack_forget()
        self.save_box.pack_forget()
        self.damage_box.pack_forget()
        if self.kind.get() == "attack":
            self.attack_box.pack(fill="x", before=self.note_box.master)
        else:
            self.save_box.pack(fill="x", before=self.note_box.master)
        self.damage_box.pack(fill="x", before=self.note_box.master)

    def _save(self):
        name = self.name.get().strip()
        if not name:
            messagebox.showinfo("Action", "Give it a name first.",
                                parent=self.win)
            return
        hit_ability = self.hit_ability.get()
        dmg_ability = self.dmg_ability.get()
        dc_ability = self.dc_ability.get()
        self.on_save(_clean_action({
            "kind": self.kind.get(),
            "name": name,
            "hit": self.hit.get().strip(),
            "hit_ability": "" if hit_ability == "-" else hit_ability,
            "dice": self.dice.get().strip(),
            "dmg_ability": "" if dmg_ability == "-" else dmg_ability,
            "dmg_type": self.dmg_type.get().strip(),
            "dc": self.dc.get().strip(),
            "dc_ability": "" if dc_ability == "-" else dc_ability,
            "on_fail": self.on_fail.get().strip(),
            "on_save": self.on_pass.get().strip(),
            "note": self.note_box.get().strip(),
        }))
        self.win.destroy()


class _SystemDialog(_Dialog):
    """A game's numbers: which ability scores it has, what a score is worth,
    and what a creature made from scratch starts with."""

    def __init__(self, owner, system, new, on_save):
        super().__init__(owner, "New system" if new else "System")
        self.on_save = on_save
        self.was = system

        self.name, _row = self.field(self.body, "Name", 26,
                                     "" if new else system["name"],
                                     hint="Dungeons & Dragons, Traveller")

        rule = tk.Frame(self.body, bg=self.t["bg"])
        rule.pack(fill="x", pady=(10, 2))
        tk.Label(rule, text="Scores", font=self.f["label"], bg=self.t["bg"],
                 fg=self.t["muted"], width=10, anchor="w").pack(side="left",
                                                                anchor="n")
        choices = tk.Frame(rule, bg=self.t["bg"])
        choices.pack(side="left", fill="x")
        self.rule = tk.StringVar(value=system.get("rule", "dnd"))
        for value, text in (
                ("dnd", "are ability scores - 10 is +0, 19 is +4"),
                ("flat", "are the modifier, exactly as typed")):
            tk.Radiobutton(choices, text=text, value=value, variable=self.rule,
                           font=self.f["label"], bg=self.t["bg"],
                           fg=self.t["fg"], activebackground=self.t["bg"],
                           activeforeground=self.t["accent"],
                           selectcolor=self.t["panel"], relief="flat", bd=0,
                           highlightthickness=0, anchor="w",
                           cursor="hand2").pack(fill="x")

        self.heading(self.body, "ABILITY SCORES").pack(fill="x", pady=(12, 2))
        self.ability_rows = tk.Frame(self.body, bg=self.t["bg"])
        self.ability_rows.pack(fill="x")
        self.abilities = []
        for key in system.get("abilities", []):
            self._add_ability(key)
        self.button(self.body, "+ add an ability",
                    lambda: self._add_ability(""),
                    fg=self.t["accent"]).pack(anchor="w", pady=(2, 0))

        self.heading(self.body, "A NEW CREATURE STARTS WITH").pack(
            fill="x", pady=(12, 2))
        self.stat_rows = tk.Frame(self.body, bg=self.t["bg"])
        self.stat_rows.pack(fill="x")
        self.stats = []
        for name, value in system.get("stats", []):
            self._add_stat(name, value)
        self.button(self.body, "+ add a stat", lambda: self._add_stat("", ""),
                    fg=self.t["accent"]).pack(anchor="w", pady=(2, 0))

        self.footer(self._save)

    def _add_ability(self, key):
        row = tk.Frame(self.ability_rows, bg=self.t["bg"])
        row.pack(fill="x", pady=1)
        box = self.entry(row, 10, key)
        box.pack(side="left", ipady=2)
        self.button(row, "remove", lambda: self._drop(row, self.abilities),
                    fg=self.t["muted"]).pack(side="left", padx=(6, 0))
        self.abilities.append((row, box))

    def _add_stat(self, name, value):
        row = tk.Frame(self.stat_rows, bg=self.t["bg"])
        row.pack(fill="x", pady=1)
        name_box = self.entry(row, 14, name)
        name_box.pack(side="left", ipady=2)
        value_box = self.entry(row, 10, value)
        value_box.pack(side="left", padx=(6, 0), ipady=2)
        self.button(row, "remove", lambda: self._drop(row, self.stats),
                    fg=self.t["muted"]).pack(side="left", padx=(6, 0))
        self.stats.append((row, name_box, value_box))

    def _drop(self, row, holder):
        for entry in list(holder):
            if entry[0] is row:
                holder.remove(entry)
        row.destroy()

    def _save(self):
        name = self.name.get().strip()
        if not name:
            messagebox.showinfo("System", "Give the system a name first.",
                                parent=self.win)
            return
        abilities = []
        for _row, box in self.abilities:
            key = box.get().strip()
            if key and key not in abilities:
                abilities.append(key)
        stats = []
        for _row, name_box, value_box in self.stats:
            stat = name_box.get().strip()
            if stat:
                stats.append([stat, value_box.get().strip()])
        self.on_save(_clean_system({"name": name, "rule": self.rule.get(),
                                    "abilities": abilities, "stats": stats}))
        self.win.destroy()


class _SaveDialog(_Dialog):
    """A name for the encounter, and who gets to see it.

    Both questions at once: asking for the name and then asking about sharing
    is two boxes for one decision, and the answer to the second is usually
    obvious as the first is being typed.
    """

    def __init__(self, owner, current, on_save):
        super().__init__(owner, "Save encounter")
        self.on_save = on_save

        self.name, _row = self.field(self.body, "Name", 30,
                                     current.get("name", ""),
                                     hint="Ambush at the Mill")
        self.note(self.body, "What you will be looking for when you come back "
                  "to it - where it happens, or who is in it.").pack(
                      fill="x", pady=(2, 10))

        self.shared = tk.BooleanVar(value=bool(current.get("shared")))
        tk.Checkbutton(self.body, text="Save it for every campaign",
                       variable=self.shared, font=self.f["label"],
                       bg=self.t["bg"], fg=self.t["fg"],
                       activebackground=self.t["bg"],
                       activeforeground=self.t["accent"],
                       selectcolor=self.t["panel"], relief="flat", bd=0,
                       highlightthickness=0, anchor="w",
                       cursor="hand2").pack(fill="x")
        self.note(self.body, "A bar fight or a patrol you will want again in "
                  "the next game. Left off, it stays with this campaign.").pack(
                      fill="x", pady=(2, 0))

        self.footer(self._save)
        # Modal: the caller waits on this window, and the board must not be
        # changed underneath the answer.
        self.win.grab_set()
        self.win.after(10, self.name.focus_set)

    def _save(self):
        name = self.name.get().strip()
        if not name:
            messagebox.showinfo("Save encounter", "Give it a name first.",
                                parent=self.win)
            return
        if self.on_save(name, bool(self.shared.get())):
            self.win.destroy()


class _ShelfDialog(_Dialog):
    """Everything saved, and what can be done to it.

    The File menu loads one in a click; this is for the rest - renaming one
    whose name stopped making sense, copying one to change a little, moving
    one out to every campaign, and throwing one away.
    """

    def __init__(self, owner):
        super().__init__(owner, "Saved encounters")
        self.win.resizable(False, True)
        self.picked = None      # (name, shared)

        outer, self.rows, self.canvas = owner._scroller(self.body)
        outer.configure(bg=self.t["bg"])
        outer.pack(fill="both", expand=True)
        outer.configure(width=420, height=260)
        outer.pack_propagate(False)

        bar = tk.Frame(self.body, bg=self.t["bg"])
        bar.pack(fill="x", pady=(10, 0))
        self.buttons = {}
        for key, label, command in (
                ("load", "Load", self._load),
                ("rename", "Rename...", self._rename),
                ("copy", "Duplicate", self._copy),
                ("share", "Share", self._share),
                ("delete", "Delete", self._delete)):
            button = self.button(bar, label, command, fg=self.t["muted"])
            button.pack(side="left", padx=(0, 6), ipadx=4, ipady=3)
            self.buttons[key] = button
        self.button(bar, "Close", self.win.destroy,
                    fg=self.t["muted"]).pack(side="right", ipadx=6, ipady=3)

        self._render()

    # -- the list ----------------------------------------------------------
    def _shelves(self):
        """Everything on both shelves, the campaign's first."""
        found = [(entry, False) for entry in self.owner.saved]
        found += [(entry, True) for entry in load_shared()]
        return found

    def _render(self):
        for child in self.rows.winfo_children():
            child.destroy()
        self.rows.configure(bg=self.t["bg"])
        self.canvas.configure(bg=self.t["bg"])

        entries = self._shelves()
        if not entries:
            tk.Label(self.rows, text="Nothing saved yet. Build a fight, then "
                     "File > Save encounter as...", font=self.f["label"],
                     bg=self.t["bg"], fg=self.t["muted"], anchor="w",
                     wraplength=380, justify="left").pack(fill="x", padx=8,
                                                          pady=8)
            self._sync()
            return

        section = None
        for entry, shared in entries:
            if shared != section:
                section = shared
                tk.Label(self.rows,
                         text="EVERY CAMPAIGN" if shared else "THIS CAMPAIGN",
                         font=self.f["label"], bg=self.t["bg"],
                         fg=self.t["muted"], anchor="w").pack(
                             fill="x", padx=8, pady=(8, 2))

            key = (entry["name"], shared)
            picked = key == self.picked
            row_bg = self.t["panel"] if picked else self.t["bg"]
            fg = self.t["accent"] if picked else self.t["fg"]
            row = tk.Frame(self.rows, bg=row_bg)
            row.pack(fill="x", pady=1)
            open_now = self.owner._is_open(entry["name"], shared)
            label = tk.Label(row,
                             text=("> " if open_now else "   ")
                             + entry["name"], font=self.f["label"],
                             bg=row_bg, fg=fg, anchor="w")
            label.pack(side="left", fill="x", expand=True, padx=(6, 2), pady=3)
            count = len(entry["creatures"])
            glance = tk.Label(row, text=f"{count} creature"
                              + ("" if count == 1 else "s"),
                              font=self.f["label"], bg=row_bg,
                              fg=self.t["muted"], anchor="e")
            glance.pack(side="right", padx=(2, 8))
            for widget in (row, label, glance):
                widget.bind("<Button-1>", lambda _e, k=key: self._pick(k))
                widget.bind("<Double-Button-1>",
                            lambda _e, k=key: self._pick_and_load(k))
        self.owner._bind_wheel(self.rows, self.canvas)
        self._sync()

    def _pick(self, key):
        self.picked = key
        self._render()

    def _pick_and_load(self, key):
        self.picked = key
        self._load()

    def _sync(self):
        """Buttons do nothing until there is something to do them to."""
        state = "normal" if self.picked else "disabled"
        for key, button in self.buttons.items():
            button.configure(state=state)
            if key == "share" and self.picked:
                button.configure(text="Keep here" if self.picked[1]
                                 else "Share")

    # -- the buttons -------------------------------------------------------
    def _load(self):
        if not self.picked:
            return
        name, shared = self.picked
        self.win.destroy()
        self.owner._load_encounter(name, shared)

    def _rename(self):
        if not self.picked:
            return
        name, shared = self.picked
        into = simpledialog.askstring("Rename encounter", "Name:",
                                      initialvalue=name, parent=self.win)
        if into and self.owner._rename_encounter(name, shared, into):
            self.picked = (into.strip(), shared)
        self._render()

    def _copy(self):
        if not self.picked:
            return
        name, shared = self.picked
        made = self.owner._copy_encounter(name, shared)
        if made:
            self.picked = (made, shared)
        self._render()

    def _share(self):
        if not self.picked:
            return
        name, shared = self.picked
        moved = self.owner._share_encounter(name, shared)
        if moved is not None:
            self.picked = (name, moved)
        self._render()

    def _delete(self):
        if not self.picked:
            return
        name, shared = self.picked
        if self.owner._delete_encounter(name, shared):
            self.picked = None
        self._render()
