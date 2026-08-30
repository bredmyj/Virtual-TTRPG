"""Game Map - a tile map for running a dungeon, in its own window.

Opens from Tools > Game Map. Two ways to look at the same map:

  * GM mode     - everything, revealed or not. Unrevealed rooms are dimmed
                  and hatched, hidden creatures are ghosted, notes show.
  * Player mode - only what the party has actually seen. Nothing that is
                  still secret is drawn at all, so the window can be turned
                  round and shown to the table.

The map is a tile grid. Rooms and corridors are prefabs dropped onto it from
the Room tab, creatures stand on single tiles, and the grid overlay is the
same tile system underneath - toggling it changes nothing but whether you can
see the lines.

Everything belongs to the campaign that is currently open, so each save file
has its own map.
"""

import copy
import json
import os
import random
import shutil
import time
import tkinter as tk
from tkinter import font as tkfont
from tkinter import filedialog, messagebox, simpledialog

import crop
import dice_api

# Portraits need real image work - decoding a JPEG, cropping to a square,
# resizing smoothly and punching a round hole in the alpha. Tk's own
# PhotoImage does none of that, so Pillow carries it. Without Pillow the rest
# of the map still runs; only the portrait menu entries go quiet.
try:
    from PIL import Image, ImageDraw, ImageTk
    PORTRAITS_OK = True
except ImportError:                                  # pragma: no cover
    Image = ImageDraw = ImageTk = None
    PORTRAITS_OK = False

PLUGIN = {
    "name": "Game Map",
    "version": "1.0",
    "description": "Tile map with prefab rooms, creature tokens and a GM / player view.",
    "author": "bundled",
}

rng = random.SystemRandom()

TILE = 32                  # one tile, in pixels - the grid draws on these lines
MAP_W, MAP_H = 80, 60      # the map is this many tiles, ~2560x1920px of room

# How many creatures a room of each size can hold. "Generate creatures" rolls
# somewhere in this range; the room refuses to hold more than the top of it.
CAPACITY = {
    "small": (0, 1),
    "medium": (0, 3),
    "large": (0, 4),
    "corridor": (0, 1),
}

CATEGORIES = ["Sewer", "Prison", "Mines", "Dwarven Ruins", "Deep Dark"]


def _rect(w, h):
    """Tile offsets for a solid w x h block."""
    return [(x, y) for y in range(h) for x in range(w)]


def _elbow(arm):
    """An L, `arm` tiles long each way, turning at the bottom left."""
    down = [(0, y) for y in range(arm)]
    across = [(x, arm - 1) for x in range(1, arm)]
    return down + across


# Room prefabs, by category. `tiles` is the footprint in tile offsets from the
# room's top-left corner, so a room can be any shape - see the L corridor.
# Only Sewer is filled in; the other categories are listed so the tab shows
# what is coming, and adding to them is just adding dicts here.
BLUEPRINTS = {
    "Sewer": [
        {"code": "S1", "name": "Small Cistern", "size": "small",
         "tiles": _rect(3, 3)},
        {"code": "S2", "name": "Sluice Chamber", "size": "medium",
         "tiles": _rect(5, 4)},
        {"code": "S3", "name": "Great Outfall", "size": "large",
         "tiles": _rect(7, 6)},
        {"code": "SC1", "name": "Short Corridor", "size": "corridor",
         "tiles": _rect(3, 1)},
        {"code": "SC2", "name": "Long Corridor", "size": "corridor",
         "tiles": _rect(8, 1)},
        {"code": "SC3", "name": "Curved Corridor", "size": "corridor",
         "tiles": _elbow(4)},
    ],
    "Prison": [],
    "Mines": [],
    "Dwarven Ruins": [],
    "Deep Dark": [],
}

# Floor / wall colours per category, so a sewer reads differently to a mine.
PALETTE = {
    "Sewer": ("#2b3a3a", "#4d6a66"),
    "Prison": ("#332f36", "#5f5766"),
    "Mines": ("#3a3129", "#6b5844"),
    "Dwarven Ruins": ("#33313c", "#6a6480"),
    "Deep Dark": ("#232a33", "#455266"),
}
DEFAULT_PALETTE = ("#2e2f38", "#5a5c6b")

# What "generate creatures" can roll up, by region.
BESTIARY = {
    "Sewer": ["Giant Rat", "Sewer Snake", "Kobold", "Poison Puddle"],
    "Prison": ["Guard", "Feral Prisoner", "Torturer", "Wight", "Mastiff"],
    "Mines": ["Kobold Miner", "Rockslide Elemental", "Bat Swarm", "Duergar"],
    "Dwarven Ruins": ["Stone Guardian", "Forge Wraith", "Ancestor Shade"],
    "Deep Dark": ["Grimlock", "Cloaker", "Hook Horror", "Drow Scout"],
}

# What can be sitting on a tile, and how each one is drawn.
#   loot  - can Generate Contents roll it up? (default yes)
#   trap  - does it belong on the Traps picker rather than the Object one?
#   mark  - a small symbol drawn inside a scroll
OBJECTS = {
    "Red Potion":   {"color": "#e2585f", "shape": "flask", "group": "Potions"},
    "Blue Potion":  {"color": "#5aa9e6", "shape": "flask", "group": "Potions"},
    "Green Potion": {"color": "#5fd38d", "shape": "flask", "group": "Potions"},
    "Gold Potion":  {"color": "#f4d35e", "shape": "flask", "group": "Potions"},

    "Scroll":       {"color": "#ddd6b4", "shape": "scroll", "group": "Scrolls"},
    "Cross Scroll": {"color": "#ddd6b4", "shape": "scroll", "mark": "cross",
                     "group": "Scrolls"},
    "Ring Scroll":  {"color": "#ddd6b4", "shape": "scroll", "mark": "ring",
                     "group": "Scrolls"},
    "Arrow Scroll": {"color": "#ddd6b4", "shape": "scroll", "mark": "arrow",
                     "group": "Scrolls"},

    "Sword":        {"color": "#c9d1d9", "shape": "sword", "group": "Weapons"},
    "Dagger":       {"color": "#c9d1d9", "shape": "dagger", "group": "Weapons"},
    "Axe":          {"color": "#b6bec7", "shape": "axe", "group": "Weapons"},
    "Spear":        {"color": "#b6bec7", "shape": "spear", "group": "Weapons"},
    "Bow":          {"color": "#a9743f", "shape": "bow", "group": "Weapons"},

    "Leather Armour": {"color": "#8a5a2b", "shape": "armour", "group": "Armour"},
    "Chainmail":    {"color": "#9aa3ad", "shape": "armour", "group": "Armour"},
    "Plate Armour": {"color": "#d8dde3", "shape": "armour", "group": "Armour"},

    "Iron Ring":    {"color": "#8d94a6", "shape": "band", "group": "Rings"},
    "Silver Ring":  {"color": "#cfd8e3", "shape": "band", "group": "Rings"},
    "Gold Ring":    {"color": "#e0b64a", "shape": "band", "group": "Rings"},

    "Bone Wand":    {"color": "#e8e0cc", "shape": "wand", "group": "Wands"},
    "Oak Wand":     {"color": "#8b5e34", "shape": "wand", "group": "Wands"},
    "Crystal Wand": {"color": "#9ee8ff", "shape": "wand", "group": "Wands"},

    "Amulet":       {"color": "#b98cff", "shape": "amulet", "group": "Trinkets"},
    "Locket":       {"color": "#e0b64a", "shape": "locket", "group": "Trinkets"},
    "Idol":         {"color": "#86a68a", "shape": "idol", "group": "Trinkets"},
    "Runestone":    {"color": "#b98cff", "shape": "stone", "group": "Trinkets"},

    "Chest":        {"color": "#c8a24a", "shape": "chest", "group": "Treasure"},
    "Key":          {"color": "#8ec5d6", "shape": "key", "group": "Treasure"},
    # One key per colour of door. A plain key still opens anything.
    "Red Key":      {"color": "#e2585f", "shape": "key", "group": "Treasure",
                     "opens": "Red"},
    "Blue Key":     {"color": "#5aa9e6", "shape": "key", "group": "Treasure",
                     "opens": "Blue"},
    "Green Key":    {"color": "#5fd38d", "shape": "key", "group": "Treasure",
                     "opens": "Green"},
    "Violet Key":   {"color": "#b98cff", "shape": "key", "group": "Treasure",
                     "opens": "Violet"},
    "Gold Coins":   {"color": "#e8c34a", "shape": "coins", "group": "Treasure"},
    # Architecture rather than loot: placeable by hand, never rolled up by
    # Generate Contents - a chest turning up at random is fine, a staircase
    # appearing in the middle of a room is not.
    "Stairs":       {"color": "#c0c6d0", "shape": "stairs", "loot": False,
                     "blurb": "Steps leading away."},
    # Traps are the GM's to place, never found as treasure. Hollow shapes, so
    # whatever is underneath still shows through.
    "Circle Trap":  {"color": "#ff8c42", "shape": "ring", "loot": False,
                     "trap": True, "blurb": "Something is rigged here."},
    "Square Trap":  {"color": "#4cc9f0", "shape": "frame", "loot": False,
                     "trap": True, "blurb": "Something is rigged here."},
    "Cross Trap":   {"color": "#f72585", "shape": "cross", "loot": False,
                     "trap": True, "blurb": "Something is rigged here."},
    # Terrain: ground covering that everything else stands on. The number is
    # the layer - higher lies on top, so growth covers water rather than the
    # other way round.
    "Water":        {"color": "#2b5f75", "shape": "water", "loot": False,
                     "terrain": 1},
    "Tall Grass":   {"color": "#3f7a3a", "shape": "grass", "loot": False,
                     "terrain": 2, "growth": True, "blocks_sight": True,
                     "blurb": "High enough to crouch in."},
    "Moss":         {"color": "#7a8f4a", "shape": "moss", "loot": False,
                     "terrain": 2, "growth": True,
                     "blurb": "Deep and damp, and it muffles a footfall."},
    # A hole in the floor. It sits above the other ground coverings: grass
    # does not grow over an opening, and water drains into one.
    "Pit":          {"color": "#141519", "shape": "pit", "loot": False,
                     "terrain": 3,
                     "blurb": "A hole in the floor. No bottom in sight."},
}
PIT = "Pit"
WATER = "Water"

# Doors come in colours so a locked way on can say which key opens it. The
# plain one is what a door has always been, and stays first in the list.
DOOR_COLOURS = [("Door", None, "#c8a24a"),
                ("Red Door", "Red", "#e2585f"),
                ("Blue Door", "Blue", "#5aa9e6"),
                ("Green Door", "Green", "#5fd38d"),
                ("Violet Door", "Violet", "#b98cff")]
DOOR_TYPES = [name for name, _lock, _shade in DOOR_COLOURS]
DOOR_SHADE = {name: shade for name, _lock, shade in DOOR_COLOURS}
DOOR_LOCK = {name: lock for name, lock, _shade in DOOR_COLOURS}
LOCK_COLOURS = [lock for _name, lock, _shade in DOOR_COLOURS if lock]


def key_opens(name):
    """Which colour of lock this key turns. None means any of them."""
    return OBJECTS.get(name, {}).get("opens")


def is_key(name):
    return OBJECTS.get(name, {}).get("shape") == "key"

# What the party makes of water, by where they are standing. Whoever is
# looking at it says what they think it is, so a new region wants a line here
# or it falls back to the plain reading.
WATER_LINES = {
    "Sewer": ("Dirty sewage water", "Thick and slow, and it reeks."),
    "Prison": ("Cold standing water", "Seeped through the stone and gone stale."),
    "Mines": ("Murky runoff", "Clouded with grit from the workings."),
    "Dwarven Ruins": ("Still, clear water", "Held in a cut stone channel."),
    "Deep Dark": ("Black water", "No telling how deep it goes."),
}
PLAIN_WATER = ("Water", "Dark, and colder than it looks.")
# "Potion" was the only flask before there were four of them.
LEGACY_TYPES = {"Potion": "Red Potion", "Tall Moss": "Moss"}

OBJECT_TYPES = list(OBJECTS)
LOOT_TYPES = [name for name, spec in OBJECTS.items() if spec.get("loot", True)]
TRAP_TYPES = [name for name, spec in OBJECTS.items() if spec.get("trap")]
GROWTH_TYPES = [name for name, spec in OBJECTS.items() if spec.get("growth")]
# Tall enough to stop a view. Moss lies flat on the ground, so it does not.
SIGHT_BLOCKERS = [name for name, spec in OBJECTS.items()
                  if spec.get("blocks_sight")]


def loot_groups():
    """Loot sorted into its categories, in catalogue order.

    Twenty-nine things in one dropdown is a wall of text; by category it is
    a handful of entries with a few each.
    """
    groups = {}
    for name in LOOT_TYPES:
        groups.setdefault(OBJECTS[name].get("group", "Other"), []).append(name)
    return groups


def group_of(name):
    return OBJECTS.get(name, {}).get("group", "")


def terrain_rank(obj):
    """0 for anything that is not ground covering, otherwise its layer."""
    return OBJECTS.get(obj.get("type"), {}).get("terrain") or 0
# What is inside a chest. Not another chest, or opening one would just hand
# you the same puzzle again.
CHEST_CONTENTS = [name for name in LOOT_TYPES if name != "Chest"]

GOLD = "Gold Coins"
COIN_RANGE = (1, 75)        # what a pile is worth in the sewer
# Deeper places pay better. A new category needs a line here, or its coins
# fall back to sewer money.
WEALTH = {
    "Sewer": 1,
    "Prison": 2,
    "Mines": 3,
    "Dwarven Ruins": 4,
    "Deep Dark": 5,
}
CUSTOM_OBJECT = "Something else..."

# How much one roll may add. Not a ceiling on the room: rolling again adds
# again, so a GM can keep going until the room feels right rather than being
# told it is full.
OBJECT_CAPACITY = {
    "small": (0, 2),
    "medium": (0, 3),
    "large": (0, 4),
    "corridor": (0, 1),
}
TRAP_SPREAD = {
    "small": (0, 1),
    "medium": (0, 2),
    "large": (0, 2),
    "corridor": (0, 1),
}
# Ground covering is laid by the handful rather than the piece, so it is
# counted as a share of the room's floor instead of a flat number.
GROUND_SHARE = 0.35

# What the floor is made of, region by region, and how often each turns up.
# A region with nothing listed falls back to the first entry here.
ENVIRONMENT = {
    "Sewer": [("Water", 5), ("Moss", 4), ("Tall Grass", 2), ("Pit", 1)],
    "Prison": [("Water", 2), ("Moss", 4), ("Pit", 2)],
    "Mines": [("Water", 2), ("Pit", 4), ("Moss", 1)],
    "Dwarven Ruins": [("Water", 2), ("Moss", 3), ("Pit", 2)],
    "Deep Dark": [("Water", 3), ("Moss", 2), ("Tall Grass", 3), ("Pit", 4)],
}

# Which sort of loot turns up, and how often. Everyday things are common,
# the things that change a character are not.
LOOT_ODDS = {
    "Potions": 6,
    "Treasure": 5,
    "Scrolls": 4,
    "Trinkets": 4,
    "Weapons": 3,
    "Armour": 2,
    "Rings": 2,
    "Wands": 1,
}


def weighted_pick(pairs):
    """One (thing, weight) pair, chosen in proportion to its weight."""
    total = sum(weight for _thing, weight in pairs)
    if total <= 0:
        return None
    ticket = rng.randint(1, total)
    running = 0
    for thing, weight in pairs:
        running += weight
        if ticket <= running:
            return thing
    return pairs[-1][0]

# The Draw tab's tools, in the order they are shown. Object and Traps carry
# their own list of what to lay down; the rest lay down one thing.
DRAW_TOOLS = [("wall", "Wall"), ("stairs", "Stairs"), ("door", "Door"),
              ("foliage", "Foliage"), ("water", "Water"), ("pit", "Pit"),
              ("object", "Object"), ("traps", "Traps"), ("note", "Note")]

# How many squares a figure covers. A rat and a person take one; something
# worth running from takes rather more, and the map should show that.
TOKEN_SPANS = [(1, 1), (1, 2), (2, 2), (2, 3), (3, 3), (4, 4)]


def span_of(token):
    """(across, down) in squares. Anything without one is a single square."""
    try:
        wide = max(1, int(token.get("w") or 1))
        tall = max(1, int(token.get("h") or 1))
    except (TypeError, ValueError):
        return 1, 1
    return wide, tall


def span_label(wide, tall):
    return "%d x %d" % (wide, tall)


def tiles_of(token):
    """Every square the figure stands on."""
    wide, tall = span_of(token)
    return [(token["x"] + dx, token["y"] + dy)
            for dy in range(tall) for dx in range(wide)]


LEVEL_POOLS = ("rooms", "tokens", "objects", "walls", "notes")

# Sharing the map. The whole map goes over the wire rather than a list of
# changes: it is a few hundred small records, it cannot drift out of step
# with itself, and every one of the map's many ways to change something is
# covered without having to describe each one separately.
SHARE_MS = 90           # changes are gathered up for this long, then sent
CURSOR_MS = 70          # the fastest we tell anyone where our mouse is
CURSOR_GONE = 4.0       # a cursor that has not moved for this long is dropped
CURSOR_SWEEP_MS = 1000

UNDO_LIMIT = 40

# The ping ring: a colour used nowhere else, so it can never be mistaken for a
# selection outline or a placement ghost.
# How far a hidden thing is blended into the page for the GM. Far enough to
# read as "the players cannot see this", near enough to still make out.
GHOST_FADE = 0.62
# How far back ground the party has walked through but cannot see right now
# is drawn. Far enough to read as memory, near enough to still make out.
MEMORY_FADE = 0.68

# How many squares a figure can see, in every direction. A square reach, not
# a circle - it is a grid, and counting squares is what people do at a table.
SIGHT_DEFAULT = 20
SIGHT_STAT = "Sight"

# How many squares a figure walks in one move, unless its own stat says
# otherwise. Diagonals count as one, the usual grid rule.
MOVE_STAT = "Move"
MOVE_DEFAULT = 6

# What every character starts with. Temporary hit points sit beside the real
# ones because that is where they are read; Sight is here rather than being
# a setting of its own, because how far you can see is a thing about you.
TEMP_STAT = "Temp HP"
DEFAULT_STATS = [("HP", 10), (TEMP_STAT, 0), ("PD", 0), ("AD", 0),
                 ("AC", 10), (MOVE_STAT, MOVE_DEFAULT),
                 (SIGHT_STAT, SIGHT_DEFAULT)]
STAT_ORDER = [name for name, _value in DEFAULT_STATS]
STAT_FLOOR, STAT_CEILING = -999, 9999

# How wide a line of stats may run in the selection panel before it wraps.
# Narrow on purpose: this is meant to be taken in at a glance mid-fight, not
# read.
STAT_LINE_WIDTH = 28


def stat_summary(token, width=STAT_LINE_WIDTH):
    """Every stat as a small block, for reading at a glance.

    Temporary hit points drop out when there are none. A nought there is not
    news, and the whole point of this is to be short enough to take in
    without stopping to read it.
    """
    pairs = [(name, value) for name, value in stats_of(token)
             if value or name != TEMP_STAT]
    lines, row = [], []
    for name, value in pairs:
        chip = "%s %d" % (name, value)
        if row and len("   ".join(row + [chip])) > width:
            lines.append("   ".join(row))
            row = []
        row.append(chip)
    if row:
        lines.append("   ".join(row))
    return "\n".join(lines)


def tally(names):
    """Names counted rather than repeated.

    A sewer floor is a dozen patches of moss and half a dozen of grass.
    Listing every one fills the panel without telling anybody anything;
    "Moss x12" says the same in one line.
    """
    counts = {}
    for name in names:
        key = str(name)
        counts[key] = counts.get(key, 0) + 1
    return ["%s \u00d7%d" % (name, n) if n > 1 else name
            for name, n in sorted(counts.items())]


def stats_of(token):
    """Every stat this character has, in a settled order.

    The standard ones first, however few of them have been set, then any the
    GM has added - so the list never reshuffles under somebody reading it.
    """
    saved = token.get("stats") or {}
    out = []
    for name, fallback in DEFAULT_STATS:
        value = saved.get(name, fallback)
        try:
            out.append((name, int(value)))
        except (TypeError, ValueError):
            out.append((name, fallback))
    for name in saved:
        if name in STAT_ORDER:
            continue
        try:
            out.append((name, int(saved[name])))
        except (TypeError, ValueError):
            continue
    return out

# Things that are part of the building rather than lying in it. The party
# remembers where a doorway was; they do not remember a rat that has since
# wandered off, or a chest somebody may have taken.
ARCHITECTURE = ("Stairs",)

# Portraits are stored square, masked to a circle, at this size. Bigger than
# a token so they stay sharp, small enough to keep a campaign folder light.
# What the zoom buttons step through. 1.0 is TILE pixels to a tile.
ZOOMS = [0.5, 0.75, 1.0, 1.5, 2.0, 3.0]
ZOOM_DEFAULT = 2            # index of 1.0

PORTRAIT_STORE = 128
PORTRAIT_DIR = "portraits"
# How tall the stats-and-bag panel asks to be. It scrolls inside this, so
# the window can be short without the bottom of it being cut off.
PANEL_HEIGHT = 200

INVENTORY_COLUMNS = 4       # cells across in the carried-items grid
INVENTORY_CELL = 46         # pixels per cell

# The crop window is shared with the profile picture, so the numbers that
# describe it live there.
PORTRAIT_PREVIEW = crop.PREVIEW
PORTRAIT_ZOOM_STEP = crop.ZOOM_STEP
PORTRAIT_ZOOM_MAX = crop.ZOOM_MAX
PORTRAIT_KINDS = crop.KINDS

# Colours a player can take for their figure. The first four sit straight on
# the menu; the rest are one click further on, behind More Colours.
TOKEN_COLOURS = [
    ("Gold", "#c8a24a"), ("Crimson", "#e2585f"),
    ("Azure", "#5aa9e6"), ("Emerald", "#5fd38d"),
    ("Violet", "#b98cff"), ("Amber", "#e8a33d"),
    ("Rose", "#ef7ea8"), ("Teal", "#3fbfae"),
    ("Lime", "#a8d84a"), ("Cyan", "#6fd8ff"),
    ("Indigo", "#7d7bf0"), ("Coral", "#f08a5d"),
    ("Mint", "#8ee6c0"), ("Slate", "#8b90a0"),
    ("Sand", "#ddd6b4"), ("Plum", "#a55b9c"),
]
QUICK_COLOURS = 4

PING_COLOR = "#6fd8ff"
PING_STEPS = 14         # frames
PING_MS = 28            # milliseconds between them - about 0.4s in all
PING_MIN, PING_MAX = 5, 46      # radius in pixels, start to finish

# Walls and doors sit on a tile edge rather than in the tile, so a scroll of
# the wheel can walk them round the four sides.
SIDES = ("n", "e", "s", "w")


def edge_coords(x, y, side, tile=TILE):
    """Pixel ends of one tile edge, at the given tile size."""
    left, top = x * tile, y * tile
    right, bottom = left + tile, top + tile
    return {"n": (left, top, right, top),
            "e": (right, top, right, bottom),
            "s": (left, bottom, right, bottom),
            "w": (left, top, left, bottom)}[side]


SIDE_NAMES = {"n": "north", "e": "east", "s": "south", "w": "west"}
OPPOSITE = {"n": "s", "s": "n", "e": "w", "w": "e"}
STEP = {"n": (0, -1), "e": (1, 0), "s": (0, 1), "w": (-1, 0)}
SIDE_OF = {(0, -1): "n", (1, 0): "e", (0, 1): "s", (-1, 0): "w"}


def shift_index(index, source, target):
    """Follow one entry of a list through a move.

    Given where something was before `source` was pulled out and put back at
    `target`, this says where that same thing is now.
    """
    if index == source:
        return target
    if source < index <= target:
        return index - 1
    if target <= index < source:
        return index + 1
    return index


def steps_between(ax, ay, bx, by):
    """Squares moved, counting a diagonal as one - the usual grid rule."""
    return max(abs(ax - bx), abs(ay - by))


def setup(api):
    holder = {"map": None}

    def open_map():
        game_map = holder["map"]
        if game_map is not None and game_map.alive():
            game_map.win.deiconify()
            game_map.win.lift()
            game_map.win.focus_force()
            return
        holder["map"] = GameMap(api)

    def flush(_name=None):
        game_map = holder["map"]
        if game_map is not None and game_map.alive():
            game_map.save()

    api.add_menu_command("Tools", "Game Map...", open_map)
    api.on("save", flush)


def blank_level(name):
    return {"name": name, "rooms": [], "tokens": [], "objects": [],
            "walls": [], "notes": []}


def blueprint(code):
    """Find a prefab by its code, whatever category it lives in."""
    for entries in BLUEPRINTS.values():
        for entry in entries:
            if entry["code"] == code:
                return entry
    return None


def category_of(code):
    for name, entries in BLUEPRINTS.items():
        if any(e["code"] == code for e in entries):
            return name
    return "Sewer"


def rotate(tiles, turns):
    """Turn a footprint 90 degrees clockwise, `turns` times, back to 0,0."""
    out = [tuple(t) for t in tiles]
    for _ in range(turns % 4):
        height = max(y for _x, y in out)
        out = [(height - y, x) for x, y in out]
    left = min(x for x, _y in out)
    top = min(y for _x, y in out)
    return [(x - left, y - top) for x, y in out]


class GameMap:
    def __init__(self, api):
        self.api = api
        self.t = api.theme
        self.f = api.fonts

        self.mode = "gm"           # "gm" or "player"
        self.demoted = False        # put in player mode by losing the chair,
                                    # rather than by choosing to look
        self.zoom_index = ZOOM_DEFAULT
        self.tile = TILE           # drawn size of a tile, zoom included
        self._zoom_fonts = {}
        self.grid_on = True
        self.sight_on = True       # limit the party to what they can see
        self._sight_cache = None   # worked out once per redraw
        self.tool = "select"       # select | draw | room | creature
        self.select_mode = "select"    # what the Select tab does: select | pan
        self._space_pan = False        # space held down = pan for now
        self.armed = None          # blueprint code waiting to be placed
        self.turns = 0             # rotation of whatever is about to be placed
        self.draw_mode = "wall"    # what the Draw tab lays down
        self.token_kind = "creature"   # what the Creature tab drops
        self.token_span = (1, 1)       # and how many squares it will cover
        self.object_type = LOOT_TYPES[0]     # what the Object tool drops
        self.trap_type = TRAP_TYPES[0]       # and what the Traps tool drops
        self.growth_type = GROWTH_TYPES[0]   # and what the Foliage tool lays
        self.door_type = DOOR_TYPES[0]       # and which door the Door tool hangs
        self.category = "Sewer"

        self.players = []          # [{"id", "name"}] - who is at the table
        self.tags = {}             # catalogue key -> [tag, ...]
        self.query = ""            # what is in the search box
        self.last_tile = None      # the square the GM last clicked
        self.levels = [blank_level("Level 1")]
        self.level = 0             # the floor the GM is working on
        self.party_level = 0       # the floor the players are standing on
        self.next_id = 1

        self.selection = []        # [(kind, id), ...] - may hold many
        self.moving = None         # a token picked up by the Move menu item
        self.attacking = None      # a token looking for something to hit
        self.last_entered = []     # rooms the party walked into this render
        self.last_unlocked = []    # and any they opened with a key on the way
        self.inspect_note = None   # answer to an inspect that found nothing
        self.drag = None           # an object being dragged with Select
        self._portraits = {}       # (file, size, dim) -> PhotoImage, kept alive
        self._middle = None        # (x, y, moved) while the middle button is down
        self._ping_jobs = {}       # tag -> pending after() id
        self._ping_seq = 0
        self.attack_die = "d20"    # remembered between attacks
        self.attack_count = 1
        self.attack_mod = 0
        self.ghost = []            # canvas ids for the placement preview
        self.hover = (0, 0)
        self._save_job = None

        # Playing together. `session` is always there - on your own it is a
        # table of one, and everything below simply never fires.
        self.session = getattr(api, "session", None)
        self._adopting = False      # applying someone else's map right now
        self._share_job = None
        self.map_rev = 0            # which version of the map this is
        self._last_shared = None    # what we last put on the wire
        self._cursor_sent = 0.0
        self._peer_cursors = {}     # token -> [x, y, level, when]
        self._cursor_sweep = None
        self._handlers = []         # (kind, callback) to unhook on close

        self.undo_stack = []
        self.redo_stack = []

        self._load()
        self._build()
        self._render()

    # -- the catalogue, tags and searching ---------------------------------
    def _catalogue(self):
        """Everything placeable, as (key, label, kind).

        One list so the search box, the tag menus and the Tags tab all agree
        on what exists and what it is called.
        """
        entries = [(key, label, "tool") for key, label in DRAW_TOOLS
                   if key not in ("object", "traps", "foliage", "door")]
        entries += [(name, name, "door") for name in DOOR_TYPES]
        entries += [(name, name, "object") for name in LOOT_TYPES]
        entries += [(name, name, "trap") for name in TRAP_TYPES]
        entries += [(name, name, "growth") for name in GROWTH_TYPES]
        for category, specs in BLUEPRINTS.items():
            for spec in specs:
                entries.append((spec["code"],
                                "%s  %s" % (spec["code"], spec["name"]),
                                "room"))
        return entries

    def _tags_of(self, key):
        return self.tags.get(key) or []

    def _all_tags(self):
        """Every tag in use, with what carries it."""
        found = {}
        for key, label, kind in self._catalogue():
            for tag in self._tags_of(key):
                found.setdefault(tag, []).append((key, label, kind))
        return found

    def _add_tag(self, key):
        tag = simpledialog.askstring("Add tag", "Tag for %s:" % key,
                                     parent=self.win)
        if not tag:
            return
        tag = tag.strip().lower()
        if not tag:
            return
        self._push_undo()
        held = self.tags.setdefault(key, [])
        if tag not in held:
            held.append(tag)
        self.save()
        self._refresh_panel()
        self.status.config(text="%s tagged %s" % (key, tag))

    def _drop_tag(self, key, tag):
        self._push_undo()
        held = self.tags.get(key) or []
        if tag in held:
            held.remove(tag)
        if not held:
            self.tags.pop(key, None)
        self.save()
        self._refresh_panel()

    def _tag_menu_for(self, key):
        menu = self._menu()
        held = self._tags_of(key)
        menu.add_command(label=key if not held else "%s - %s"
                         % (key, ", ".join(held)), state="disabled")
        menu.add_separator()
        menu.add_command(label="Add Tag...", command=lambda: self._add_tag(key))
        if held:
            drop = self._menu()
            for tag in held:
                drop.add_command(label=tag,
                                 command=lambda t=tag: self._drop_tag(key, t))
            menu.add_cascade(label="Remove Tag", menu=drop)
        return menu

    def _matches(self, query):
        """Catalogue entries whose name or tags contain the query."""
        needle = query.strip().lower()
        if not needle:
            return []
        hits = []
        for key, label, kind in self._catalogue():
            tags = self._tags_of(key)
            group = group_of(key)
            if (needle in label.lower() or needle in group.lower()
                    or any(needle in t for t in tags)):
                hits.append((key, label, kind, tags))
        return hits

    def _reach_for(self, key, kind):
        """Make the panel ready to place whatever was searched for."""
        if kind == "room":
            self.category = category_of(key)
            self._pick_tab("room")
            self._arm(key)
        elif kind == "trap":
            self._pick_tab("draw")
            self._pick_trap_type(key)
        elif kind == "growth":
            self._pick_tab("draw")
            self._pick_growth_type(key)
        elif kind == "object":
            self._pick_tab("draw")
            self._pick_object_type(key)
        else:
            self._pick_tab("draw")
            self._pick_draw(key)
        self.status.config(text="ready to place %s" % key)

    def _refresh_panel(self):
        """Redraw whichever of the tab body or the search results is showing."""
        if self.query.strip():
            self._show_results()
        else:
            self._pick_tab(self.tool)

    # -- levels ------------------------------------------------------------
    def _view(self):
        """The level on screen. The GM sees the one they picked; the players
        only ever see the one the party is standing on."""
        index = self.level if self.mode == "gm" else self.party_level
        return max(0, min(len(self.levels) - 1, index))

    def _floor(self):
        return self.levels[self._view()]

    def _all_levels(self, pool):
        """Every record of one kind, from every floor."""
        for level in self.levels:
            for item in level[pool]:
                yield level, item

    @property
    def rooms(self):
        return self._floor()["rooms"]

    @rooms.setter
    def rooms(self, value):
        self._floor()["rooms"] = value

    @property
    def tokens(self):
        return self._floor()["tokens"]

    @tokens.setter
    def tokens(self, value):
        self._floor()["tokens"] = value

    @property
    def objects(self):
        return self._floor()["objects"]

    @objects.setter
    def objects(self, value):
        self._floor()["objects"] = value

    @property
    def walls(self):
        return self._floor()["walls"]

    @walls.setter
    def walls(self, value):
        self._floor()["walls"] = value

    @property
    def notes(self):
        return self._floor()["notes"]

    @notes.setter
    def notes(self, value):
        self._floor()["notes"] = value

    # -- data -------------------------------------------------------------
    def alive(self):
        try:
            return bool(self.win.winfo_exists())
        except tk.TclError:
            return False

    def _load(self):
        store = self.api.storage.get("map", {})
        self.players = [dict(p) for p in store.get("players", [])]
        self.tags = {key: list(value)
                     for key, value in (store.get("tags") or {}).items()
                     if value}
        if store.get("levels"):
            self.levels = [self._read_level(raw, "Level %d" % (n + 1))
                           for n, raw in enumerate(store["levels"])]
        else:
            # A map saved before there were levels is simply level one.
            self.levels = [self._read_level(store, "Level 1")]
        self.level = int(store.get("level", 0))
        self.party_level = int(store.get("party_level", 0))
        self.level = max(0, min(len(self.levels) - 1, self.level))
        self.party_level = max(0, min(len(self.levels) - 1, self.party_level))
        self.grid_on = bool(store.get("grid_on", True))
        self.zoom_index = max(0, min(len(ZOOMS) - 1,
                                     int(store.get("zoom", ZOOM_DEFAULT))))
        self.tile = self._tile_for(self.zoom_index)
        self.mode = store.get("mode", "gm")
        self.sight_on = bool(store.get("sight_on", True))
        self.category = store.get("category", "Sewer")
        if self.category not in BLUEPRINTS:
            self.category = "Sewer"
        self._migrate_types()
        # Ids have to stay unique across every floor, not just this one.
        known = [0] + [p["id"] for p in self.players]
        for pool in LEVEL_POOLS:
            known += [item["id"] for _level, item in self._all_levels(pool)]
        self.next_id = max(known) + 1

    def _read_level(self, raw, fallback):
        return {"name": raw.get("name") or fallback,
                "rooms": [dict(r) for r in raw.get("rooms", [])],
                "tokens": [dict(t) for t in raw.get("tokens", [])],
                "objects": [dict(o) for o in raw.get("objects", [])],
                "walls": [self._wall_record(w) for w in raw.get("walls", [])],
                "notes": [dict(n) for n in raw.get("notes", [])]}

    def _wall_record(self, raw):
        """Walls used to be stored as raw pixel ends. Turn those into the
        tile+side form so maps drawn before this still load."""
        if isinstance(raw, dict):
            return dict(raw)
        x0, y0, x1, y1 = raw
        x, y = int(min(x0, x1) // self.tile), int(min(y0, y1) // self.tile)
        if y0 == y1:
            side = "n" if int(y0 // self.tile) == y else "s"
        else:
            side = "w" if int(x0 // self.tile) == x else "e"
        return {"id": self.new_id(), "x": x, "y": y, "side": side}

    def _migrate_types(self):
        """Rename anything saved under an old type name."""
        def rename(record):
            new = LEGACY_TYPES.get(record.get("type"))
            if not new:
                return
            if record.get("text") == record["type"]:
                record["text"] = new
            record["type"] = new

        for _level, obj in self._all_levels("objects"):
            rename(obj)
        for _level, token in self._all_levels("tokens"):
            for entry in token.get("items") or []:
                rename(entry)

    def _world(self):
        """The parts of the map that belong to everyone.

        Zoom, which level you are looking at, whether the grid is on and
        whether you are in GM or player mode are all yours alone - two people
        can look at different floors at different sizes and still be playing
        on the same map.
        """
        return {"players": self.players, "tags": self.tags,
                "levels": self.levels, "party_level": self.party_level}

    def _adopt(self, world):
        """Take someone else's map as the truth and redraw.

        Where they were looking is left alone; only what is on the map
        changes.
        """
        self._adopting = True
        if self._share_job is not None:
            # A change of ours was queued to go out. It was made against the
            # map we are about to replace, so it is already gone.
            self._after_cancel(self._share_job)
            self._share_job = None
        try:
            self._cancel()          # anything mid-move points at old records
            self.players = copy.deepcopy(world.get("players", []))
            self.tags = copy.deepcopy(world.get("tags", {}))
            self.levels = copy.deepcopy(world.get("levels")) or self.levels
            self.party_level = world.get("party_level", self.party_level)
            self.level = max(0, min(len(self.levels) - 1, self.level))
            self.party_level = max(0, min(len(self.levels) - 1,
                                          self.party_level))
            self._clear_selection()
            self._render()
            self._sync_roster()
            self._sync_levels()
            self.save()
            self._last_shared = json.dumps(self._world(), sort_keys=True,
                                           default=str)
        finally:
            self._adopting = False

    def _share(self):
        """Tell everyone the map changed - once, shortly, not per keystroke.

        Dragging a room across the map is dozens of changes in a second; they
        are gathered up and sent as one.
        """
        if self._adopting or self.session is None or self.session.is_solo:
            return
        if self._share_job is not None:
            return
        if not self.alive():
            return
        self._share_job = self.win.after(SHARE_MS, self._send_world)

    def _send_world(self):
        self._share_job = None
        if self.session is None or self.session.is_solo or not self.alive():
            return
        world = self._world()
        packed = json.dumps(world, sort_keys=True, default=str)
        if packed == self._last_shared:
            return          # saved, but nothing anybody else needs to know
        self._last_shared = packed
        if self.session.is_host:
            self.map_rev += 1
        # A player sends the version their change was made against, so the
        # host can tell whether they were working from the current map.
        self.session.send({"kind": "map", "rev": self.map_rev, "world": world})

    def _map_from_network(self, message):
        """Somebody else's map.

        The host is the authority. Everyone else follows it, and a change
        made from an out-of-date copy is turned down and the sender put back
        in step - otherwise a save that was already on its way could quietly
        undo something the GM had just done.
        """
        if not self.alive():
            return
        world = message.get("world")
        if not world:
            return
        rev = message.get("rev", 0)

        if not self.session.is_host:
            if rev < self.map_rev:
                return              # older than what we already have
            self.map_rev = rev
            self._adopt(world)
            return

        if rev != self.map_rev:
            # They were working from an older map. Put them back in step
            # rather than letting it land on top of ours.
            self.session.send_to(message.get("from"),
                                 {"kind": "map", "rev": self.map_rev,
                                  "world": self._world()})
            return
        self.map_rev += 1
        self._adopt(world)
        # Everyone, the sender included, so all the copies agree on which
        # version they are now holding.
        self.session.send({"kind": "map", "rev": self.map_rev,
                           "world": world})

    def save(self):
        self.api.storage["map"] = {
            "players": self.players,
            "tags": self.tags,
            "levels": self.levels,
            "level": self.level,
            "party_level": self.party_level,
            "grid_on": self.grid_on,
            "sight_on": self.sight_on,
            "zoom": self.zoom_index,
            "mode": self.mode,
            "category": self.category,
        }
        self.api.save()
        self._share()

    def schedule_save(self):
        if self._save_job is not None:
            self.win.after_cancel(self._save_job)
        self._save_job = self.win.after(600, self._do_save)

    def _do_save(self):
        self._save_job = None
        if self.alive():
            self.save()

    def _cancel_jobs(self):
        """However the window goes, leave no timer pointing at it."""
        if self._save_job is not None:
            self._after_cancel(self._save_job)
            self._save_job = None
        if self._share_job is not None:
            self._after_cancel(self._share_job)
            self._share_job = None
        if self._cursor_sweep is not None:
            self._after_cancel(self._cursor_sweep)
            self._cursor_sweep = None
        for job in list(self._ping_jobs.values()):
            self._after_cancel(job)
        self._ping_jobs.clear()

    def _after_cancel(self, job):
        try:
            self.win.after_cancel(job)
        except tk.TclError:
            pass

    def _on_destroy(self, event):
        if event.widget is self.win:
            self._cancel_jobs()

    def _close(self):
        self._cancel_jobs()
        self.save()
        self._leave_session()
        self.win.destroy()

    def _edge(self, x, y, side):
        """Where a tile edge falls on screen, at the current zoom."""
        return edge_coords(x, y, side, self.tile)

    # -- zoom --------------------------------------------------------------
    def _tile_for(self, index):
        return max(6, int(round(TILE * ZOOMS[index])))

    def _s(self, size):
        """Scale a measurement written for a 32px tile.

        The sign is kept, because most of these are offsets from a shape's
        centre rather than lengths - clamping them to a minimum would fold
        every shape in on itself.
        """
        return int(round(size * self.tile / float(TILE)))

    def _w(self, width):
        """Scale a line width. A line that scaled to nothing would vanish."""
        return max(1, self._s(width))

    def _zoom_font(self, key):
        """The app's font at the current zoom. Cached per size, because Tk
        font objects are not free and this runs for every token drawn."""
        cached = self._zoom_fonts.get((key, self.tile))
        if cached is not None:
            return cached
        base = tkfont.Font(font=self.f[key])
        size = max(5, int(round(abs(base.cget("size"))
                                * self.tile / float(TILE))))
        made = tkfont.Font(family=base.cget("family"), size=size,
                           weight=base.cget("weight"))
        self._zoom_fonts[(key, self.tile)] = made
        return made

    def _zoom_by(self, step):
        index = max(0, min(len(ZOOMS) - 1, self.zoom_index + step))
        if index == self.zoom_index:
            self.status.config(text="%d%% is as far as it goes"
                                    % round(ZOOMS[self.zoom_index] * 100))
            return
        # Hold whatever is in the middle of the window still while the scale
        # changes underneath it, or zooming throws you across the map.
        middle = self._view_centre()
        self.zoom_index = index
        self.tile = self._tile_for(index)
        self._portraits.clear()        # they are built at the drawn size
        self.canvas.configure(scrollregion=(0, 0, MAP_W * self.tile,
                                            MAP_H * self.tile))
        self._render()
        self._centre_on(*middle)
        self.schedule_save()
        self.status.config(text="zoom %d%%" % round(ZOOMS[index] * 100))
        self._sync_zoom_label()

    def _view_centre(self):
        """Middle of the window, in tiles."""
        width = max(1, self.canvas.winfo_width())
        height = max(1, self.canvas.winfo_height())
        return (self.canvas.canvasx(width / 2.0) / float(self.tile),
                self.canvas.canvasy(height / 2.0) / float(self.tile))

    def _centre_on(self, tx, ty):
        width = max(1, self.canvas.winfo_width())
        height = max(1, self.canvas.winfo_height())
        full_w = float(MAP_W * self.tile)
        full_h = float(MAP_H * self.tile)
        self.canvas.xview_moveto(
            min(1.0, max(0.0, (tx * self.tile - width / 2.0) / full_w)))
        self.canvas.yview_moveto(
            min(1.0, max(0.0, (ty * self.tile - height / 2.0) / full_h)))

    def _sync_zoom_label(self):
        if hasattr(self, "zoom_label") and self.zoom_label.winfo_exists():
            self.zoom_label.config(text="%d%%"
                                        % round(ZOOMS[self.zoom_index] * 100))

    def new_id(self):
        value = self.next_id
        self.next_id += 1
        return value

    # -- undo / redo -------------------------------------------------------
    def _snapshot(self):
        """A deep copy, not a shallow one.

        A token carries a list of items; copying the dict alone would leave
        that list shared with the live record, so picking something up would
        silently rewrite the history as well.
        """
        return {"players": copy.deepcopy(self.players),
                "levels": copy.deepcopy(self.levels),
                "party_level": self.party_level}

    def _push_undo(self):
        """Call immediately BEFORE changing anything on the map."""
        snapshot = self._snapshot()
        if self.undo_stack and self.undo_stack[-1] == snapshot:
            return
        self.undo_stack.append(snapshot)
        if len(self.undo_stack) > UNDO_LIMIT:
            del self.undo_stack[0]
        self.redo_stack.clear()

    def undo(self, _event=None):
        if not self.undo_stack:
            return
        self.redo_stack.append(self._snapshot())
        self._apply(self.undo_stack.pop())

    def redo(self, _event=None):
        if not self.redo_stack:
            return
        self.undo_stack.append(self._snapshot())
        self._apply(self.redo_stack.pop())

    def _apply(self, snap):
        # Undo swaps in fresh dicts, so anything holding a reference to an old
        # one is now pointing at an orphan. Drop those before they are used.
        self._cancel()
        self.players = copy.deepcopy(snap.get("players", []))
        self.levels = copy.deepcopy(snap["levels"])
        self.party_level = snap.get("party_level", self.party_level)
        self.level = max(0, min(len(self.levels) - 1, self.level))
        self.party_level = max(0, min(len(self.levels) - 1, self.party_level))
        self._clear_selection()
        self._render()
        self.save()

    # -- widget helpers ----------------------------------------------------
    def _heading(self, parent, text):
        return tk.Label(parent, text=text, font=self.f["label"],
                        bg=self.t["panel"], fg=self.t["muted"], anchor="w")

    def _button(self, parent, text, command, fg=None, width=None, font=None,
                bg=None):
        return tk.Button(parent, text=text, font=font or self.f["label"],
                         bg=bg or self.t["bg"], fg=fg or self.t["fg"],
                         activebackground=self.t["accent"],
                         activeforeground=self.t["bg"], relief="flat", bd=0,
                         cursor="hand2", command=command, anchor="w",
                         padx=8, **({"width": width} if width else {}))

    def _menu(self):
        return tk.Menu(self.win, tearoff=0, bg=self.t["panel"],
                       fg=self.t["fg"], activebackground=self.t["accent"],
                       activeforeground=self.t["bg"], bd=0,
                       font=self.f["label"])

    # -- the window --------------------------------------------------------
    def _build(self):
        self.win = tk.Toplevel(self.api.app)
        self.win.title(f"Game Map - {self.api.save_name}")
        self.win.configure(bg=self.t["bg"])
        self.win.geometry("1400x900")
        self.win.minsize(1000, 640)
        self.win.protocol("WM_DELETE_WINDOW", self._close)
        self.win.bind("<Destroy>", self._on_destroy)

        self.win.columnconfigure(0, weight=1)
        self.win.rowconfigure(2, weight=1)

        self._build_topbar()
        self._build_levels()
        self._build_canvas()
        self._build_manager()
        self._apply_pointer()
        self._build_people_strip()
        self._join_session()

        self.win.bind("<Control-z>", self.undo)
        self.win.bind("<Control-Z>", self.redo)
        self.win.bind("<Control-y>", self.redo)
        self.win.bind("<Escape>", lambda _e: self._cancel())
        self.win.bind("<Delete>", self._delete_selected)
        self.win.bind("r", self._hotkey(self._rotate_ghost))
        self.win.bind("g", self._hotkey(self._toggle_grid))
        self.win.bind("v", self._hotkey(lambda: self._pick_select_mode("select")))
        self.win.bind("h", self._hotkey(lambda: self._pick_select_mode("pan")))
        self.win.bind("<KeyPress-space>", self._space_down)
        self.win.bind("<KeyRelease-space>", self._space_up)

    def _apply_pointer(self):
        """Your colour, on your own arrow, over the map as well.

        Only the window, not the canvas. The canvas puts its own cursor up
        while you are aiming or panning and clears it back to nothing when
        it is done - and nothing means whatever the window says, which is
        this. Setting it here too would be overwritten a moment later.
        """
        try:
            import pointer
        except ImportError:
            return
        pointer.apply_profile(self.win, self.session)

    def _build_people_strip(self):
        """The row of faces along the bottom - who else is looking at this."""
        self.roster_strip = None
        if self.session is None or self.session.is_solo:
            return
        try:
            import roster_bar
        except ImportError:
            return
        self.roster_strip = roster_bar.RosterBar(self.win, self.session)
        self.roster_strip.grid(row=3, column=0, columnspan=2, sticky="ew",
                               padx=8, pady=(0, 8))

    def _join_session(self):
        """Listen for the others, and stop listening when this window goes."""
        if self.session is None or self.session.is_solo:
            return
        for kind, handler in (("map", self._map_from_network),
                              ("cursor", self._cursor_from_network),
                              ("roster", self._session_changed)):
            self.session.on(kind, handler)
            self._handlers.append((kind, handler))
        self._session_changed()
        self._sweep_cursors()
        if not self.session.is_host:
            # Ask for the map as it stands, rather than showing whatever was
            # in this machine's own save until somebody moves something.
            self.session.send({"kind": "map_please"})
        else:
            self.session.on("map_please", self._send_map_to_asker)
            self._handlers.append(("map_please", self._send_map_to_asker))
            # Anyone who opened their map before this window existed asked
            # and got no answer, so say where things stand now.
            self._share()

    def _send_map_to_asker(self, message):
        if not self.alive():
            return
        who = message.get("from")
        if who:
            self.session.send_to(who, {"kind": "map", "rev": self.map_rev,
                                       "world": self._world()})

    def _leave_session(self):
        for kind, handler in self._handlers:
            self.session.off(kind, handler)
        self._handlers = []

    def _typing(self):
        """Is the keyboard busy filling in a field somewhere?"""
        try:
            widget = self.win.focus_get()
        except (KeyError, tk.TclError):
            return False
        return isinstance(widget, (tk.Entry, tk.Spinbox, tk.Text))

    def _hotkey(self, action):
        """A bare-letter shortcut must not fire while a name is being typed."""
        def fire(_event=None):
            if self._typing():
                return None
            action()
            return "break"
        return fire

    def _space_down(self, _event=None):
        if self._typing() or self._space_pan:
            return None            # auto-repeat, or the user is typing
        self._space_pan = True
        self._apply_cursor()
        return "break"

    def _space_up(self, _event=None):
        if not self._space_pan:
            return None
        self._space_pan = False
        if self.drag is not None and self.drag.get("mode") == "pan":
            self.drag = None
        self._apply_cursor()
        return "break"

    def _panning(self):
        """Space always pans, whatever tab is open; otherwise it is whether
        the Select tab is set to Pan."""
        return self._space_pan or (self.tool == "select"
                                   and self.select_mode == "pan")

    def _pick_select_mode(self, mode):
        self.select_mode = mode
        self._sync_select_button()
        self._pick_tab("select")
        self._apply_cursor()

    def _sync_select_button(self):
        button = getattr(self, "tab_buttons", {}).get("select")
        if button is None or not button.winfo_exists():
            return
        button.config(text=("Pan  \u25be" if self.select_mode == "pan"
                            else "Select  \u25be"))

    def _apply_cursor(self):
        if not self.alive():
            return
        if self._panning():
            cursor = "fleur"
        elif self.attacking is not None:
            cursor = "tcross"
        elif self.moving is not None:
            cursor = "fleur"
        else:
            cursor = ""
        self.canvas.config(cursor=cursor)

    def _build_topbar(self):
        bar = tk.Frame(self.win, bg=self.t["panel"])
        bar.grid(row=0, column=0, columnspan=2, sticky="ew", padx=8, pady=(8, 0))

        # Mode is the one control that changes what the window is for, so it
        # sits first and stays loud.
        self.mode_button = tk.Menubutton(
            bar, text="", font=self.f["die"], bg=self.t["accent"],
            fg=self.t["bg"], activebackground=self.t["accent_hot"],
            activeforeground=self.t["bg"], relief="flat", bd=0, padx=14,
            pady=4, cursor="hand2")
        self.mode_button.pack(side="left", padx=(2, 12), pady=6)
        # The menu has to be a child of the menubutton itself; hang it off the
        # window instead and the button draws its arrow but never posts.
        mode_menu = tk.Menu(self.mode_button, tearoff=0, bg=self.t["panel"],
                            fg=self.t["fg"],
                            activebackground=self.t["accent"],
                            activeforeground=self.t["bg"], bd=0,
                            font=self.f["label"])
        mode_menu.add_command(label="GM Mode",
                              command=lambda: self._set_mode("gm"))
        mode_menu.add_command(label="Player Mode",
                              command=lambda: self._set_mode("player"))
        self.mode_button.config(menu=mode_menu)

        self.grid_button = self._button(bar, "\u25a6  Grid", self._toggle_grid)
        self.grid_button.pack(side="left", padx=2, pady=6, ipady=3)
        self.sight_button = self._button(bar, "◉  Sight",
                                         self._toggle_sight)
        self.sight_button.pack(side="left", padx=2, pady=6, ipady=3)

        self._button(bar, "\u21ba", self.undo, width=2,
                     font=self.f["die"]).pack(side="left", padx=(12, 2), pady=6)
        self._button(bar, "\u21bb", self.redo, width=2,
                     font=self.f["die"]).pack(side="left", padx=2, pady=6)

        self._button(bar, "\u2212", lambda: self._zoom_by(-1), width=2,
                     font=self.f["die"]).pack(side="left", padx=(12, 2), pady=6)
        self.zoom_label = tk.Label(bar, text="", font=self.f["label"],
                                   bg=self.t["panel"], fg=self.t["muted"],
                                   width=5)
        self.zoom_label.pack(side="left", pady=6)
        self._button(bar, "+", lambda: self._zoom_by(1), width=2,
                     font=self.f["die"]).pack(side="left", padx=2, pady=6)

        self.status = tk.Label(bar, text="", font=self.f["label"],
                               bg=self.t["panel"], fg=self.t["muted"])
        self.status.pack(side="right", padx=10)
        self._sync_zoom_label()

    def _build_levels(self):
        """One button per floor, plus a way to add another.

        Only the GM sees this. Switching here changes what they are working
        on and nothing else - the party stays where it was until they are
        walked up, which is the whole point.
        """
        self.level_bar = tk.Frame(self.win, bg=self.t["panel"])
        self.level_bar.grid(row=1, column=0, columnspan=2, sticky="ew",
                            padx=8, pady=(4, 0))
        self.level_strip = tk.Frame(self.level_bar, bg=self.t["panel"])
        self.level_strip.pack(side="left", padx=(2, 0), pady=4)
        self._button(self.level_bar, "+ Add Level", self._add_level,
                     fg=self.t["accent"]).pack(side="left", padx=8, pady=4)
        self.level_hint = tk.Label(self.level_bar, text="", font=self.f["label"],
                                   bg=self.t["panel"], fg=self.t["muted"])
        self.level_hint.pack(side="right", padx=10)
        self._fill_levels()

    def _fill_levels(self):
        if not hasattr(self, "level_strip") or not self.level_strip.winfo_exists():
            return
        for child in self.level_strip.winfo_children():
            child.destroy()
        self.level_buttons = []
        for number, level in enumerate(self.levels):
            here = number == self.level
            party = number == self.party_level
            label = level["name"]
            if party:
                label += "  \u25c6"        # the party is standing on this one
            button = tk.Button(self.level_strip, text=label,
                               font=self.f["label"],
                               bg=self.t["accent"] if here else self.t["bg"],
                               fg=self.t["bg"] if here else (
                                   self.t["accent"] if party else self.t["fg"]),
                               activebackground=self.t["accent"],
                               activeforeground=self.t["bg"], relief="flat",
                               bd=0, cursor="hand2", padx=10, pady=3)
            button.pack(side="left", padx=1)
            # No `command`: press and release are handled here so that a
            # click can switch floors while a drag reorders them, and the
            # two never fire together.
            button.bind("<ButtonPress-1>",
                        lambda e, n=number: self._level_press(n))
            button.bind("<B1-Motion>", self._level_motion)
            button.bind("<ButtonRelease-1>",
                        lambda e, n=number: self._level_release(e, n))
            button.bind("<Button-3>",
                        lambda e, n=number: self._level_menu(n).tk_popup(
                            e.x_root, e.y_root))
            self.level_buttons.append(button)
        self.level_hint.config(
            text="the party is on %s" % self.levels[self.party_level]["name"])

    def _level_press(self, number):
        self._level_drag = {"from": number, "moved": False}

    def _level_motion(self, _event=None):
        drag = getattr(self, "_level_drag", None)
        if drag is None or drag["moved"]:
            return
        drag["moved"] = True
        self.status.config(text="drop it where you want it")

    def _level_release(self, event, number):
        """A click switches floor; a drag puts this one somewhere else."""
        drag = getattr(self, "_level_drag", None)
        self._level_drag = None
        if drag is None:
            return
        if not drag["moved"]:
            self._show_level(number)
            return
        target = self._level_drop_at(event)
        if target is None or target == drag["from"]:
            self.status.config(text="left where it was")
            return
        self._move_level(drag["from"], target)

    def _level_drop_at(self, event):
        """Which tab the pointer is over, or the near end if it is past them.

        Root coordinates, because the pointer will have left the tab it
        started on by the time it is dropped somewhere else.
        """
        where = event.x_root
        live = [(index, button)
                for index, button in enumerate(getattr(self, "level_buttons",
                                                       []))
                if button.winfo_exists()]
        if not live:
            return None
        for index, button in live:
            left = button.winfo_rootx()
            if left <= where < left + button.winfo_width():
                return index
        first, last = live[0][1], live[-1][1]
        if where < first.winfo_rootx():
            return live[0][0]
        if where >= last.winfo_rootx() + last.winfo_width():
            return live[-1][0]
        return None

    def _move_level(self, source, target):
        """Put one floor at another's place, everything else closing up."""
        if source == target or not (0 <= source < len(self.levels)):
            return
        target = max(0, min(len(self.levels) - 1, target))
        self._push_undo()
        moved = self.levels.pop(source)
        self.levels.insert(target, moved)
        # The floors themselves have not changed, only where they sit in the
        # row - so whoever was looking at one, and wherever the party is
        # standing, must follow it rather than stay on a number.
        self.level = shift_index(self.level, source, target)
        self.party_level = shift_index(self.party_level, source, target)
        self._render()
        self.save()
        self.status.config(text="%s moved to position %d"
                                % (moved["name"], target + 1))

    def _sync_levels(self):
        """The strip is the GM's; the players just get their own floor."""
        if not hasattr(self, "level_bar") or not self.level_bar.winfo_exists():
            return
        if self.mode == "gm":
            self.level_bar.grid()
        else:
            self.level_bar.grid_remove()
        self._fill_levels()

    def _show_level(self, number):
        """Look at another floor. Nothing about the party changes."""
        number = max(0, min(len(self.levels) - 1, number))
        if number == self.level:
            return
        self.level = number
        self._cancel()
        self._clear_selection()
        self._portraits.clear()
        self._fill_levels()
        self._render()
        self.schedule_save()
        self.status.config(text="working on %s" % self.levels[number]["name"])

    def _add_level(self):
        self._push_undo()
        self.levels.append(blank_level("Level %d" % (len(self.levels) + 1)))
        self.level = len(self.levels) - 1
        self._clear_selection()
        self._fill_levels()
        self._render()
        self.save()
        self.status.config(text="added %s" % self.levels[-1]["name"])

    def _level_menu(self, number):
        menu = self._menu()
        menu.add_command(label=self.levels[number]["name"], state="disabled")
        menu.add_separator()
        if number > 0:
            menu.add_command(label="Move Left",
                             command=lambda: self._move_level(number,
                                                              number - 1))
        if number < len(self.levels) - 1:
            menu.add_command(label="Move Right",
                             command=lambda: self._move_level(number,
                                                              number + 1))
        menu.add_separator()
        if number != self.party_level:
            menu.add_command(label="Move Party Here",
                             command=lambda: self._move_party(number))
        else:
            menu.add_command(label="The party is already here", state="disabled")
        menu.add_command(label="Rename...",
                         command=lambda: self._rename_level(number))
        if len(self.levels) > 1:
            menu.add_separator()
            menu.add_command(label="Remove Level",
                             command=lambda: self._remove_level(number))
        return menu

    def _move_party(self, number):
        """Carry every player figure up (or down) to another floor.

        They keep their tile, their kit and their colour - only the floor
        under them changes. This is also the moment the players' own view
        follows, which is why the GM has to ask for it rather than it
        happening whenever they flick through the levels.
        """
        if number == self.party_level:
            return
        moving = [t for t in self.levels[self.party_level]["tokens"]
                  if t.get("kind") == "player"]
        self._push_undo()
        for token in moving:
            self.levels[self.party_level]["tokens"].remove(token)
            self.levels[number]["tokens"].append(token)
        self.party_level = number
        self._clear_selection()
        self._fill_levels()
        self._render()
        self.save()
        self.status.config(
            text="the party is on %s now" % self.levels[number]["name"]
            if moving else
            "%s is the party's floor, but there are no figures to move"
            % self.levels[number]["name"])

    def _rename_level(self, number):
        name = simpledialog.askstring("Rename level", "Name:",
                                      initialvalue=self.levels[number]["name"],
                                      parent=self.win)
        if not name:
            return
        self._push_undo()
        self.levels[number]["name"] = name.strip()
        self._fill_levels()
        self.save()

    def _remove_level(self, number):
        if len(self.levels) <= 1:
            return
        level = self.levels[number]
        holds = sum(len(level[pool]) for pool in LEVEL_POOLS)
        if holds and not messagebox.askyesno(
                "Remove level",
                "%s still has %d things on it. Remove it anyway?"
                % (level["name"], holds), parent=self.win, icon="warning"):
            return
        self._push_undo()
        self.levels.pop(number)
        for attr in ("level", "party_level"):
            at = getattr(self, attr)
            if at > number:
                setattr(self, attr, at - 1)
            elif at == number:
                setattr(self, attr, min(at, len(self.levels) - 1))
        self._clear_selection()
        self._fill_levels()
        self._render()
        self.save()
        self.status.config(text="removed %s" % level["name"])

    def _build_canvas(self):
        wrap = tk.Frame(self.win, bg=self.t["panel"])
        wrap.grid(row=2, column=0, sticky="nsew", padx=(8, 4), pady=8)
        wrap.rowconfigure(0, weight=1)
        wrap.columnconfigure(0, weight=1)

        self.canvas = tk.Canvas(wrap, bg=self.t["bg"], highlightthickness=0,
                                bd=0, scrollregion=(0, 0, MAP_W * self.tile,
                                                    MAP_H * self.tile))
        self.canvas.grid(row=0, column=0, sticky="nsew")
        xbar = tk.Scrollbar(wrap, orient="horizontal", command=self.canvas.xview,
                            bg=self.t["panel"], troughcolor=self.t["bg"],
                            activebackground=self.t["accent"], relief="flat",
                            bd=0, width=10)
        ybar = tk.Scrollbar(wrap, orient="vertical", command=self.canvas.yview,
                            bg=self.t["panel"], troughcolor=self.t["bg"],
                            activebackground=self.t["accent"], relief="flat",
                            bd=0, width=10)
        xbar.grid(row=1, column=0, sticky="ew")
        ybar.grid(row=0, column=1, sticky="ns")
        self.canvas.configure(xscrollcommand=xbar.set, yscrollcommand=ybar.set)

        self.canvas.bind("<Button-1>", self._left_click)
        self.canvas.bind("<Control-Button-1>", self._ctrl_click)
        self.canvas.bind("<B1-Motion>", self._left_drag)
        self.canvas.bind("<ButtonRelease-1>", self._left_release)
        self.canvas.bind("<Button-3>", self._right_click)
        self.canvas.bind("<Motion>", self._motion)
        self.canvas.bind("<Leave>", lambda _e: self._clear_ghost())
        # Wheel scrolls, shift+wheel scrolls sideways - unless something is
        # waiting to be placed, in which case it turns it instead.
        self.canvas.bind("<MouseWheel>", self._wheel)
        self.canvas.bind("<Control-MouseWheel>",
                         lambda e: self._zoom_by(1 if e.delta > 0 else -1))
        self.canvas.bind("<Shift-MouseWheel>", lambda e: self.canvas.xview_scroll(
            -1 if e.delta > 0 else 1, "units"))
        # Middle button does double duty: a click pings where you are
        # pointing, a drag pans - which beats chasing scrollbars on a map
        # this size. They are told apart by whether the mouse actually moved.
        self.canvas.bind("<Button-2>", self._middle_down)
        self.canvas.bind("<B2-Motion>", self._middle_drag)
        self.canvas.bind("<ButtonRelease-2>", self._middle_up)

    def _build_manager(self):
        column = tk.Frame(self.win, bg=self.t["panel"], width=292)
        column.grid(row=2, column=1, sticky="ns", padx=(4, 8), pady=8)
        column.pack_propagate(False)

        hunt = tk.Frame(column, bg=self.t["panel"])
        hunt.pack(fill="x", padx=6, pady=(8, 2))
        self.query_var = tk.StringVar()
        self.query_box = tk.Entry(hunt, textvariable=self.query_var,
                                  font=self.f["label"], bg=self.t["bg"],
                                  fg=self.t["fg"],
                                  insertbackground=self.t["fg"], relief="flat",
                                  bd=0, highlightthickness=1,
                                  highlightbackground=self.t["panel"],
                                  highlightcolor=self.t["accent"])
        self.query_box.pack(side="left", fill="x", expand=True, ipady=4)
        self._button(hunt, "\u00d7", self._clear_query, width=2,
                     fg=self.t["muted"]).pack(side="left", padx=(4, 0))
        self.query_var.trace_add("write", lambda *_a: self._on_query())

        tabs = tk.Frame(column, bg=self.t["panel"])
        tabs.pack(fill="x", padx=6, pady=(2, 4))
        self.tab_buttons = {}
        for key, label in [("select", "Select"), ("draw", "Draw"),
                           ("room", "Room"), ("creature", "Creature"),
                           ("tags", "Tags")]:
            if key == "select":
                button = tk.Menubutton(tabs, text="", font=self.f["label"],
                                       bg=self.t["bg"], fg=self.t["fg"],
                                       relief="flat", bd=0, cursor="hand2",
                                       padx=2, pady=4,
                                       activebackground=self.t["accent"],
                                       activeforeground=self.t["bg"])
                # As with the mode button, the menu has to be a child of the
                # menubutton or it draws its arrow and never posts.
                picker = tk.Menu(button, tearoff=0, bg=self.t["panel"],
                                 fg=self.t["fg"],
                                 activebackground=self.t["accent"],
                                 activeforeground=self.t["bg"], bd=0,
                                 font=self.f["label"])
                picker.add_command(
                    label="Select Tool   V",
                    command=lambda: self._pick_select_mode("select"))
                picker.add_command(
                    label="Pan Tool   H",
                    command=lambda: self._pick_select_mode("pan"))
                button.config(menu=picker)
            else:
                button = tk.Button(tabs, text=label, font=self.f["label"],
                                   bg=self.t["bg"], fg=self.t["fg"],
                                   relief="flat", bd=0, cursor="hand2",
                                   padx=2, pady=4,
                                   activebackground=self.t["accent"],
                                   activeforeground=self.t["bg"],
                                   command=lambda k=key: self._pick_tab(k))
            button.pack(side="left", expand=True, fill="x", padx=1)
            self.tab_buttons[key] = button
        self._sync_select_button()

        self.tab_body = tk.Frame(column, bg=self.t["panel"])

        self._build_roster(column)
        self._build_inventory(column)

        self.hint = tk.Label(column, text="", font=self.f["label"],
                             bg=self.t["panel"], fg=self.t["muted"],
                             wraplength=230, justify="left", anchor="w")
        # Bottom-up: the hint, the bag, then the roster, each taking the room
        # it needs. The tab body is packed last and expanding, so it is the
        # one that gives way when the window is short - and it scrolls, so
        # nothing in it is lost either.
        self.hint.pack(side="bottom", fill="x", padx=8, pady=(0, 8))
        self.inventory.pack(side="bottom", fill="x", padx=6, pady=(0, 4))
        self.tab_body.pack(fill="both", expand=True, padx=6, pady=(4, 8))
        self._pick_tab(self.tool)
        self._sync_roster()
        self._fill_stats()
        self._fill_inventory()
        self._wheel_scrolls(self.panel_body)

    def _build_roster(self, column):
        """Who is at the table, and which figure on the map is theirs.

        It sits below the tabs rather than inside one, because it is about
        the party rather than about whatever tool is in hand.
        """
        self.roster = tk.Frame(column, bg=self.t["panel"])
        tk.Frame(self.roster, bg=self.t["bg"], height=1).pack(fill="x",
                                                              pady=(0, 6))
        head = tk.Frame(self.roster, bg=self.t["panel"])
        head.pack(fill="x")
        self._heading(head, "PLAYERS").pack(side="left")
        self._button(head, "+ Add Player", self._add_player,
                     fg=self.t["accent"]).pack(side="right")
        self.roster_list = self._scroll_list(self.roster, height=104)

    def _sync_roster(self):
        """Only the GM keeps the roster; players just see the map."""
        if not hasattr(self, "roster") or not self.roster.winfo_exists():
            return
        if self.mode == "gm":
            self.roster.pack(side="bottom", fill="x", padx=6, pady=(0, 4))
        else:
            self.roster.pack_forget()
        self._fill_roster()

    def _fill_roster(self):
        if not hasattr(self, "roster_list") or not self.roster_list.winfo_exists():
            return
        for child in self.roster_list.winfo_children():
            child.destroy()
        if not self.players:
            tk.Label(self.roster_list, text="nobody yet", font=self.f["label"],
                     bg=self.t["panel"], fg=self.t["muted"],
                     anchor="w").pack(fill="x", pady=4)
            return
        for player in self.players:
            owned = self._tokens_of(player)
            if owned:
                trail = ", ".join(t["name"] for t in owned)
                colour = self.t["fg"]
            else:
                trail = "no token yet"
                colour = self.t["muted"]
            row = self._button(self.roster_list,
                               "%s  -  %s" % (player["name"], trail),
                               lambda p=player: self._focus_player(p),
                               fg=colour)
            row.pack(fill="x", pady=1)
            row.bind("<Button-3>",
                     lambda e, p=player: self._player_row_menu(p).tk_popup(
                         e.x_root, e.y_root))

    def _tokens_of(self, player):
        return [t for _level, t in self._all_levels("tokens")
                if t.get("owner") == player["id"]]

    def _owner_of(self, token):
        for player in self.players:
            if player["id"] == token.get("owner"):
                return player
        return None

    def _add_player(self):
        name = simpledialog.askstring("Add player", "Player's name:",
                                      parent=self.win)
        if not name:
            return
        self._push_undo()
        self.players.append({"id": self.new_id(), "name": name.strip()})
        self._fill_roster()
        self.save()
        self.status.config(text="%s joined" % name.strip())

    def _rename_player(self, player):
        name = simpledialog.askstring("Rename", "Player's name:",
                                      initialvalue=player["name"],
                                      parent=self.win)
        if not name:
            return
        self._push_undo()
        player["name"] = name.strip()
        self._fill_roster()
        self.save()

    def _remove_player(self, player):
        self._push_undo()
        for token in self._tokens_of(player):
            token.pop("owner", None)      # the figure stays, it just has no one
        self.players.remove(player)
        self._fill_roster()
        self._render()
        self.save()

    def _player_row_menu(self, player):
        menu = self._menu()
        menu.add_command(label="Rename...",
                         command=lambda: self._rename_player(player))
        menu.add_separator()
        menu.add_command(label="Remove from the table",
                         command=lambda: self._remove_player(player))
        return menu

    def _focus_player(self, player):
        owned = self._tokens_of(player)
        if owned:
            # They may be on another floor; go to it before looking for them.
            for number, level in enumerate(self.levels):
                if owned[0] in level["tokens"] and number != self.level:
                    self._show_level(number)
                    break
        if not owned:
            self.status.config(
                text="%s has no figure yet - right-click one and use "
                     "Belongs To" % player["name"])
            return
        self._focus_token(owned[0])

    def _assign_token(self, token, player):
        self._push_undo()
        if player is None:
            token.pop("owner", None)
            self.status.config(text="%s belongs to nobody" % token["name"])
        else:
            token["owner"] = player["id"]
            self.status.config(text="%s is %s's"
                                    % (token["name"], player["name"]))
        self._fill_roster()
        self._render()
        self.save()

    def _scroll_list(self, parent, height=None):
        """A scrollable strip - room lists outgrow the panel quickly.

        With a height it keeps to that and does not fight the tab body for
        the column; without one it fills whatever it is given.
        """
        holder = tk.Frame(parent, bg=self.t["panel"])
        holder.pack(fill="both" if height is None else "x",
                    expand=height is None)
        canvas = tk.Canvas(holder, bg=self.t["panel"], highlightthickness=0,
                           bd=0, **({} if height is None else {"height": height}))
        bar = tk.Scrollbar(holder, orient="vertical", command=canvas.yview,
                           bg=self.t["panel"], troughcolor=self.t["bg"],
                           activebackground=self.t["accent"], relief="flat",
                           bd=0, width=8)
        canvas.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        inner = tk.Frame(canvas, bg=self.t["panel"])
        window = canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>",
                   lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>",
                    lambda e: canvas.itemconfigure(window, width=e.width))
        canvas.bind("<MouseWheel>", lambda e: canvas.yview_scroll(
            -1 if e.delta > 0 else 1, "units"))
        # Kept on the frame so anything filled into it later can find the
        # canvas it needs to scroll.
        inner._scroll_canvas = canvas
        self._wheel_scrolls(inner)
        return inner

    def _wheel_scrolls(self, container):
        """Let the wheel scroll the strip from anywhere inside it.

        Tk sends a wheel event only to the widget under the pointer, and it
        does not travel up to the canvas doing the scrolling - so over a
        label or a button the wheel would do nothing at all unless every
        child is told where to send it.
        """
        canvas = getattr(container, "_scroll_canvas", None)
        if canvas is None:
            return

        def roll(event):
            canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")
            return "break"

        def teach(widget):
            try:
                widget.bind("<MouseWheel>", roll)
                for child in widget.winfo_children():
                    teach(child)
            except tk.TclError:
                pass            # it went away mid-sweep

        teach(container)

    # -- the manager tabs --------------------------------------------------
    def _on_query(self):
        self.query = self.query_var.get()
        if self.query.strip():
            self._show_results()
        else:
            self._pick_tab(self.tool)

    def _clear_query(self):
        self.query_var.set("")
        self.query_box.focus_set()

    def _show_results(self):
        """Search results stand in for the tab body until the box is cleared."""
        for child in self.tab_body.winfo_children():
            child.destroy()
        self.room_cards = {}
        self.draw_buttons = {}
        hits = self._matches(self.query)
        self._heading(self.tab_body,
                      "%d MATCH%s" % (len(hits), "" if len(hits) == 1
                                      else "ES")).pack(fill="x", pady=(2, 6))
        if not hits:
            tk.Label(self.tab_body, text="nothing called that, and no such tag",
                     font=self.f["label"], bg=self.t["panel"],
                     fg=self.t["muted"], anchor="w",
                     wraplength=250).pack(fill="x")
            self.hint.config(text="clear the box to get the tools back")
            return
        listing = self._scroll_list(self.tab_body)
        for key, label, kind, tags in hits:
            trail = ("  -  " + ", ".join(tags)) if tags else ""
            row = self._button(listing, "%s   [%s]%s" % (label, kind, trail),
                               lambda k=key, n=kind: self._reach_for(k, n))
            row.pack(fill="x", pady=1)
            row.bind("<Button-3>",
                     lambda e, k=key: self._tag_menu_for(k).tk_popup(
                         e.x_root, e.y_root))
        self.hint.config(text="click one to get ready to place it - "
                              "right-click to tag it")

    def _tab_tags(self, parent):
        self._heading(parent, "TAGS IN USE").pack(fill="x", pady=(2, 6))
        found = self._all_tags()
        if not found:
            tk.Label(parent, text="none yet - right-click anything in Draw or "
                                  "Room and choose Add Tag",
                     font=self.f["label"], bg=self.t["panel"],
                     fg=self.t["muted"], anchor="w", justify="left",
                     wraplength=250).pack(fill="x")
            return
        listing = self._scroll_list(parent)
        for tag in sorted(found):
            carriers = found[tag]
            row = self._button(listing, "%s   (%d)" % (tag, len(carriers)),
                               lambda t=tag: self.query_var.set(t))
            row.pack(fill="x", pady=1)
            tk.Label(listing, text="   " + ", ".join(l for _k, l, _n in carriers),
                     font=self.f["label"], bg=self.t["panel"],
                     fg=self.t["muted"], anchor="w", justify="left",
                     wraplength=250).pack(fill="x", pady=(0, 4))

    def _pick_tab(self, key):
        if self.mode == "player" and key != "select":
            return
        self.tool = key
        if key != "room":
            self._disarm()
        for name, button in self.tab_buttons.items():
            on = name == key
            button.config(bg=self.t["accent"] if on else self.t["bg"],
                          fg=self.t["bg"] if on else self.t["fg"])
        for child in self.tab_body.winfo_children():
            child.destroy()
        self.room_cards = {}
        self.draw_buttons = {}
        builder = {"select": self._tab_select, "draw": self._tab_draw,
                   "room": self._tab_room, "creature": self._tab_creature,
                   "tags": self._tab_tags}[key]
        builder(self.tab_body)
        if self.mode == "player":
            self.hint.config(text="right-click one of your figures to move it")
        else:
            self.hint.config(text={
                "select": ("drag the map about - V for the select tool"
                       if self.select_mode == "pan" else
                       "drag empty ground to box-select, ctrl-click to add - "
                       "right-click a group to act on all of it"),
                "draw": "click the map to lay down what is picked below",
                "room": "pick a room, then click the map to place it - scroll "
                        "to rotate, Esc cancels",
                "creature": "click the map to drop what is picked above",
                "tags": "click a tag to search it",
            }[key])
        self._clear_ghost()

    def _tab_select(self, parent):
        self.select_heading = self._heading(parent, "SELECTION")
        self.select_heading.pack(fill="x", pady=(2, 6))
        self.select_info = tk.Label(parent, text="", font=self.f["label"],
                                    bg=self.t["panel"], fg=self.t["fg"],
                                    justify="left", anchor="nw",
                                    wraplength=225)
        self.select_info.pack(fill="x")
        tk.Frame(parent, bg=self.t["bg"], height=1).pack(fill="x", pady=10)
        self.tally_heading = self._heading(parent, "ON THE MAP")
        self.tally_heading.pack(fill="x", pady=(0, 4))
        self.tally = tk.Label(parent, text="", font=self.f["label"],
                              bg=self.t["panel"], fg=self.t["muted"],
                              justify="left", anchor="nw")
        self.tally.pack(fill="x")
        self._refresh_select_tab()

    def _refresh_select_tab(self):
        if not hasattr(self, "tally") or not self.tally.winfo_exists():
            return
        if self.mode == "player":
            self._refresh_player_tab()
            return
        self.select_heading.config(text="SELECTION")
        self.tally_heading.config(text="ON THE MAP")
        hidden = sum(1 for t in self.tokens if t.get("hidden"))
        unseen = sum(1 for r in self.rooms if not r.get("revealed"))
        self.tally.config(text=(
            "%d rooms  (%d unrevealed)\n%d creatures  (%d hidden)\n"
            "%d objects\n%d notes" % (len(self.rooms), unseen, len(self.tokens),
                                      hidden, len(self.objects), len(self.notes))))
        if len(self.selection) > 1:
            kinds = {}
            for kind, _item in self._selected_things():
                kinds[kind] = kinds.get(kind, 0) + 1
            summary = ", ".join("%d %s%s" % (n, k, "" if n == 1 else "s")
                                for k, n in sorted(kinds.items()))
            self.select_info.config(
                fg=self.t["fg"],
                text="%d things selected\n%s\n\ndrag any of them to move "
                     "them together" % (len(self.selection), summary))
            return
        thing = self._selected_thing()
        if thing is None:
            self.select_info.config(text="nothing selected", fg=self.t["muted"])
            return
        kind, item = thing
        detail = self._selection_detail(kind, item)
        # Everything else sharing that square, so a chest sitting in water on
        # a room floor reads as all three rather than only the top one.
        if self.last_tile is not None:
            listing = self._square_listing(*self.last_tile, chosen=item)
            if len(listing) > 1:
                detail += "\n\nON THIS SQUARE\n" + "\n".join(listing)
        self.select_info.config(fg=self.t["fg"], text=detail)

    def _selection_detail(self, kind, item):
        if kind == "room":
            spec = blueprint(item["code"]) or {}
            low, high = CAPACITY.get(spec.get("size", "small"), (0, 0))
            here = len(self._tokens_in(item))
            state = "revealed" if item.get("revealed") else "not revealed"
            if item.get("locked"):
                state += ", locked"
                if item.get("lock_colour"):
                    state += " (%s key)" % item["lock_colour"].lower()
            return ("%s  %s\n%s - holds %d-%d creatures\n%d here now\n%s"
                    % (item["code"], spec.get("name", "?"),
                       spec.get("size", "?"), low, high, here, state))
        if kind == "token":
            state = "defeated" if item.get("defeated") else "active"
            if item.get("hidden"):
                state += ", hidden"
            owner = self._owner_of(item)
            line = "%s\ntile %d, %d\n%s" % (item["name"], item["x"],
                                             item["y"], state)
            if owner is not None:
                line += "\n%s's figure" % owner["name"]
            # Creature or character alike: everything about the figure in
            # one place, rather than making the GM open a window mid-fight to
            # check a number.
            line += "\n\n" + stat_summary(item)
            return line
        else:
            label = item.get("text", kind)
            if item.get("type") == WATER:
                # Show the GM the same reading the party would get.
                room = self._room_at(item["x"], item["y"])
                where = room.get("category") if room else None
                label = WATER_LINES.get(where, PLAIN_WATER)[0]
            if item.get("type") == GOLD:
                # The GM should be able to just click a pile and read it,
                # rather than going through Inspect or Change Value.
                worth = item.get("value") or 0
                label += (("\n%d coins" % worth) if worth
                          else "\nno amount set yet")
            if item.get("hidden"):
                label += "\nhidden from the players"
            return label

    def _refresh_player_tab(self):
        """The players see this panel, so it may only ever count things they
        have already found - a total of unrevealed rooms would tell them
        exactly how much dungeon is left."""
        self.select_heading.config(text="INSPECT")
        self.tally_heading.config(text="SO FAR")
        explored = sum(1 for r in self.rooms if self._visible_room(r))
        in_sight = sum(1 for t in self.tokens
                       if t.get("kind") != "player" and self._visible_token(t))
        party = len(self._players())
        self.tally.config(text=(
            "%d room%s explored\n%d creature%s in sight\n%d in your party"
            % (explored, "" if explored == 1 else "s",
               in_sight, "" if in_sight == 1 else "s", party)))
        thing = self._selected_thing()
        if thing is None or not self._player_can_see(*thing):
            self.select_info.config(
                text=self.inspect_note or "right-click anything to look at it",
                fg=self.t["fg"] if self.inspect_note else self.t["muted"])
            return
        self.select_info.config(fg=self.t["fg"], text=self._describe(*thing))

    def _tab_draw(self, parent):
        self._heading(parent, "LAY DOWN").pack(fill="x", pady=(2, 6))
        self.draw_buttons = {}
        for key, label in DRAW_TOOLS:
            if key == "object":
                button = self._tool_picker(parent, key, "Object",
                                           self._object_choices(),
                                           self._pick_object_type)
            elif key == "traps":
                button = self._tool_picker(parent, key, "Traps", TRAP_TYPES,
                                           self._pick_trap_type)
            elif key == "foliage":
                button = self._tool_picker(parent, key, "Foliage",
                                           GROWTH_TYPES,
                                           self._pick_growth_type)
            elif key == "door":
                button = self._tool_picker(parent, key, "Door", DOOR_TYPES,
                                           self._pick_door_type)
            else:
                button = self._button(parent, label,
                                      lambda k=key: self._pick_draw(k))
            button.pack(fill="x", pady=1, ipady=3)
            button.bind("<Button-3>",
                        lambda e, k=key: self._tag_menu_for(k).tk_popup(
                            e.x_root, e.y_root))
            self.draw_buttons[key] = button

        tk.Frame(parent, bg=self.t["bg"], height=1).pack(fill="x", pady=8)
        erase = self._button(parent, "Erase", lambda: self._pick_draw("erase"),
                             fg=self.t["fumble"])
        erase.pack(fill="x", pady=1, ipady=3)
        self.draw_buttons["erase"] = erase
        self._pick_draw(self.draw_mode)

    def _tool_picker(self, parent, key, label, choices, chosen):
        """A tool that carries its own list.

        Clicking it drops the choices and picking one both selects the tool
        and sets what it lays down - one control instead of a button beside a
        dropdown that did half the job each.
        """
        button = tk.Menubutton(parent, text="", font=self.f["label"],
                               bg=self.t["bg"], fg=self.t["fg"],
                               activebackground=self.t["accent"],
                               activeforeground=self.t["bg"], relief="flat",
                               bd=0, cursor="hand2", anchor="w", padx=8)
        # As everywhere else, the menu must be a child of its own button.
        menu = tk.Menu(button, tearoff=0, bg=self.t["panel"], fg=self.t["fg"],
                       activebackground=self.t["accent"],
                       activeforeground=self.t["bg"], bd=0,
                       font=self.f["label"])
        self._fill_choices(menu, choices, chosen)
        button.config(menu=menu)
        self._tool_labels = getattr(self, "_tool_labels", {})
        self._tool_labels[key] = label
        return button

    def _fill_choices(self, menu, choices, chosen):
        """Flat list, or a dict of category -> names as a set of cascades."""
        if isinstance(choices, dict):
            for group, names in choices.items():
                sub = tk.Menu(menu, tearoff=0, bg=self.t["panel"],
                              fg=self.t["fg"],
                              activebackground=self.t["accent"],
                              activeforeground=self.t["bg"], bd=0,
                              font=self.f["label"])
                for name in names:
                    sub.add_command(label=name,
                                    command=lambda n=name: chosen(n))
                menu.add_cascade(label=group, menu=sub)
            return
        for name in choices:
            menu.add_command(label=name, command=lambda n=name: chosen(n))

    def _object_choices(self):
        picks = loot_groups()
        picks[CUSTOM_OBJECT] = [CUSTOM_OBJECT]
        return picks

    def _sync_tool_labels(self):
        """Each picker says what it will lay down next."""
        picks = {"object": self.object_type, "traps": self.trap_type,
                 "foliage": self.growth_type, "door": self.door_type}
        for key, chosen in picks.items():
            button = getattr(self, "draw_buttons", {}).get(key)
            if button is None or not button.winfo_exists():
                continue
            button.config(text="%s:  %s" % (self._tool_labels[key], chosen))

    def _pick_object_type(self, name):
        self.object_type = name
        self._sync_tool_labels()
        self._pick_draw("object")

    def _pick_trap_type(self, name):
        self.trap_type = name
        self._sync_tool_labels()
        self._pick_draw("traps")

    def _pick_growth_type(self, name):
        self.growth_type = name
        self._sync_tool_labels()
        self._pick_draw("foliage")

    def _pick_draw(self, key):
        self.draw_mode = key
        self._sync_tool_labels()
        # The buttons only exist while the Draw tab is built, so this has to
        # cope with being called before or after it.
        for name, button in list(getattr(self, "draw_buttons", {}).items()):
            if not button.winfo_exists():
                continue
            on = name == key
            if on:
                back = self.t["fumble"] if name == "erase" else self.t["accent"]
                button.config(bg=back, fg=self.t["bg"])
            else:
                button.config(bg=self.t["bg"],
                              fg=self.t["fumble"] if name == "erase"
                              else self.t["fg"])
            if isinstance(button, tk.Menubutton):
                # A menubutton keeps its own idea of the highlight colour.
                button.config(activebackground=self.t["accent"],
                              activeforeground=self.t["bg"])
        self._clear_ghost()
        if hasattr(self, "hint") and self.hint.winfo_exists():
            self.hint.config(text={
                    "wall": "click a tile edge to build a wall - wheel turns it",
                "stairs": "click a tile to lay a flight of stairs",
                "door": "click to drop a door - wheel turns it to another edge",
                "object": "click a tile to place the object picked below",
                "traps": "click a tile to set the trap picked below",
                "water": "drag across the map to flood tiles",
                "pit": "drag across the map to open pits in the floor",
                "foliage": "drag across the map to grow what is picked below",
                "note": "click a tile to pin a note - GM only, never shown "
                        "to players",
                "erase": "click anything to remove it - Ctrl+Z puts it back",
            }[key])

    def _tab_room(self, parent):
        self._heading(parent, "CATEGORY").pack(fill="x", pady=(2, 4))
        self.category_var = tk.StringVar(value=self.category)
        picker = tk.OptionMenu(parent, self.category_var, *CATEGORIES,
                               command=self._pick_category)
        picker.config(font=self.f["label"], bg=self.t["bg"], fg=self.t["fg"],
                      activebackground=self.t["accent"],
                      activeforeground=self.t["bg"], relief="flat", bd=0,
                      highlightthickness=0, anchor="w", cursor="hand2")
        picker["menu"].config(bg=self.t["panel"], fg=self.t["fg"],
                              activebackground=self.t["accent"],
                              activeforeground=self.t["bg"],
                              font=self.f["label"], bd=0)
        picker.pack(fill="x", pady=(0, 8))
        self.room_list = self._scroll_list(parent)
        self._fill_room_list()

    def _pick_category(self, name):
        self.category = name
        self._disarm()
        self._fill_room_list()
        self.schedule_save()

    def _fill_room_list(self):
        for child in self.room_list.winfo_children():
            child.destroy()
        self.room_cards = {}
        entries = BLUEPRINTS.get(self.category, [])
        if not entries:
            tk.Label(self.room_list, text="Nothing here yet.",
                     font=self.f["label"], bg=self.t["panel"],
                     fg=self.t["muted"], anchor="w").pack(fill="x", pady=6)
            return
        for spec in entries:
            self._room_card(spec)
        self._sync_room_cards()

    def _room_card(self, spec):
        """One row: a thumbnail of the footprint, its code, and what it holds."""
        card = tk.Frame(self.room_list, bg=self.t["bg"], cursor="hand2")
        card.pack(fill="x", pady=2)
        thumb = tk.Canvas(card, width=52, height=46, bg=self.t["bg"],
                          highlightthickness=0, bd=0, cursor="hand2")
        thumb.pack(side="left", padx=(6, 8), pady=6)
        self._draw_thumb(thumb, spec)

        text = tk.Frame(card, bg=self.t["bg"])
        text.pack(side="left", fill="x", expand=True, pady=6)
        low, high = CAPACITY.get(spec["size"], (0, 0))
        wide = max(x for x, _y in spec["tiles"]) + 1
        tall = max(y for _x, y in spec["tiles"]) + 1
        title = tk.Label(text, text="%s  %s" % (spec["code"], spec["name"]),
                         font=self.f["label"], bg=self.t["bg"],
                         fg=self.t["fg"], anchor="w")
        title.pack(fill="x")
        sub = tk.Label(text, text="%s - %dx%d tiles - %d-%d creatures"
                                  % (spec["size"], wide, tall, low, high),
                       font=self.f["label"], bg=self.t["bg"],
                       fg=self.t["muted"], anchor="w")
        sub.pack(fill="x")
        for widget in (card, thumb, text, title, sub):
            widget.bind("<Button-1>", lambda _e, c=spec["code"]: self._arm(c))
            widget.bind("<Button-3>",
                        lambda e, c=spec["code"]:
                        self._tag_menu_for(c).tk_popup(e.x_root, e.y_root))
        self.room_cards[spec["code"]] = (card, thumb, text, title, sub)

    def _draw_thumb(self, thumb, spec):
        floor, wall = PALETTE.get(self.category, DEFAULT_PALETTE)
        tiles = spec["tiles"]
        wide = max(x for x, _y in tiles) + 1
        tall = max(y for _x, y in tiles) + 1
        step = max(min(46 // max(wide, 1), 40 // max(tall, 1), 8), 3)
        ox = (52 - wide * step) // 2
        oy = (46 - tall * step) // 2
        for x, y in tiles:
            thumb.create_rectangle(ox + x * step, oy + y * step,
                                   ox + (x + 1) * step, oy + (y + 1) * step,
                                   fill=floor, outline=wall)

    def _sync_room_cards(self):
        for code, widgets in list(getattr(self, "room_cards", {}).items()):
            if not widgets[0].winfo_exists():
                continue
            on = code == self.armed
            back = self.t["accent"] if on else self.t["bg"]
            fore = self.t["bg"] if on else self.t["fg"]
            muted = self.t["bg"] if on else self.t["muted"]
            card, thumb, text, title, sub = widgets
            for widget in (card, thumb, text):
                widget.config(bg=back)
            title.config(bg=back, fg=fore)
            sub.config(bg=back, fg=muted)

    def _tab_creature(self, parent):
        self._heading(parent, "PLACE").pack(fill="x", pady=(2, 4))
        row = tk.Frame(parent, bg=self.t["panel"])
        row.pack(fill="x", pady=(0, 8))
        self.kind_buttons = {}
        for key, label in [("creature", "Creature"), ("player", "Player")]:
            button = tk.Button(row, text=label, font=self.f["label"],
                               bg=self.t["bg"], fg=self.t["fg"], relief="flat",
                               bd=0, cursor="hand2", pady=4,
                               activebackground=self.t["accent"],
                               activeforeground=self.t["bg"],
                               command=lambda k=key: self._pick_kind(k))
            button.pack(side="left", expand=True, fill="x", padx=1)
            self.kind_buttons[key] = button

        self.creature_name = tk.Entry(parent, font=self.f["label"],
                                      bg=self.t["bg"], fg=self.t["fg"],
                                      insertbackground=self.t["fg"],
                                      relief="flat", bd=0, highlightthickness=1,
                                      highlightbackground=self.t["panel"],
                                      highlightcolor=self.t["accent"])
        self.creature_name.pack(fill="x", ipady=4)
        self.creature_name.insert(0, "Giant Rat")

        self._heading(parent, "SQUARES IT COVERS").pack(fill="x", pady=(8, 2))
        self.span_button = tk.Menubutton(
            parent, text="", font=self.f["label"], bg=self.t["bg"],
            fg=self.t["fg"], activebackground=self.t["accent"],
            activeforeground=self.t["bg"], relief="flat", bd=0,
            cursor="hand2", anchor="w", padx=8, pady=4)
        # The menu has to be a child of the button, or Tk draws the arrow
        # and never opens anything.
        picker = tk.Menu(self.span_button, tearoff=0, bg=self.t["panel"],
                         fg=self.t["fg"], activebackground=self.t["accent"],
                         activeforeground=self.t["bg"], bd=0,
                         font=self.f["label"])
        for wide, tall in TOKEN_SPANS:
            picker.add_command(label=span_label(wide, tall),
                               command=lambda w=wide, h=tall:
                                   self._pick_span(w, h))
        self.span_button.config(menu=picker)
        self.span_button.pack(fill="x", pady=(0, 2))
        self._sync_span_button()

        self._pick_kind(self.token_kind)
        tk.Label(parent, text="then click a tile  -  scroll to turn it",
                 font=self.f["label"], bg=self.t["panel"],
                 fg=self.t["muted"], anchor="w").pack(fill="x", pady=(4, 10))
        tk.Frame(parent, bg=self.t["bg"], height=1).pack(fill="x", pady=(0, 8))
        self._heading(parent, "ON THE MAP").pack(fill="x", pady=(0, 4))
        self.creature_list = self._scroll_list(parent)
        self._fill_creature_list()

    def _pick_span(self, wide, tall):
        self.token_span = (wide, tall)
        self._sync_span_button()
        self._clear_ghost()

    def _sync_span_button(self):
        button = getattr(self, "span_button", None)
        if button is None or not button.winfo_exists():
            return
        button.config(text="Size:  %s" % span_label(*self.token_span))

    def _pick_door_type(self, name):
        self.door_type = name
        self._pick_draw("door")
        self._sync_tool_labels()

    def _pick_kind(self, key):
        """Player figures are the only thing player mode can touch, so which
        of the two you are dropping matters more than it looks."""
        self.token_kind = key
        for name, button in self.kind_buttons.items():
            on = name == key
            button.config(bg=self.t["accent"] if on else self.t["bg"],
                          fg=self.t["bg"] if on else self.t["fg"])
        if hasattr(self, "creature_name") and self.creature_name.winfo_exists():
            current = self.creature_name.get().strip()
            if current in ("", "Giant Rat", "Player"):
                self.creature_name.delete(0, "end")
                self.creature_name.insert(
                    0, "Player" if key == "player" else "Giant Rat")

    def _fill_creature_list(self):
        if not hasattr(self, "creature_list") or not self.creature_list.winfo_exists():
            return
        for child in self.creature_list.winfo_children():
            child.destroy()
        if not self.tokens:
            tk.Label(self.creature_list, text="none placed",
                     font=self.f["label"], bg=self.t["panel"],
                     fg=self.t["muted"], anchor="w").pack(fill="x", pady=4)
            return
        for token in self.tokens:
            marks = []
            if token.get("defeated"):
                marks.append("defeated")
            if token.get("hidden"):
                marks.append("hidden")
            player = token.get("kind") == "player"
            label = ("\u25c6 " if player else "") + token["name"]
            wide, tall = span_of(token)
            if (wide, tall) != (1, 1):
                label += "  " + span_label(wide, tall)
            if marks:
                label += "  (" + ", ".join(marks) + ")"
            colour = self.t["muted"] if marks else (
                self.t["accent"] if player else self.t["fg"])
            row = self._button(self.creature_list, label,
                               lambda t=token: self._focus_token(t), fg=colour)
            row.pack(fill="x", pady=1)
            # Right-click a name to resize it without hunting for it first.
            row.bind("<Button-3>",
                     lambda e, t=token: self._creature_row_menu(t, e))

    def _resize_token(self, token, wide, tall):
        """Grow or shrink a figure where it stands."""
        if span_of(token) == (wide, tall):
            return
        if not self._span_clear(token["x"], token["y"], wide, tall,
                                ignore=token):
            self.status.config(
                text="no room to make %s that big" % token["name"])
            return
        self._push_undo()
        token["w"], token["h"] = wide, tall
        self._render()
        self.save()
        self.status.config(text="%s is now %s"
                                % (token["name"], span_label(wide, tall)))

    def _turn_token(self, token):
        """A quarter turn, in place. A 2x3 becomes a 3x2."""
        wide, tall = span_of(token)
        if wide == tall:
            self.status.config(
                text="%s is square - turning it changes nothing"
                     % token["name"])
            return
        if not self._span_clear(token["x"], token["y"], tall, wide,
                                ignore=token):
            self.status.config(text="no room to turn %s there" % token["name"])
            return
        self._push_undo()
        token["w"], token["h"] = tall, wide
        self._render()
        self.save()
        self.status.config(text="%s turned - now %s"
                                % (token["name"], span_label(tall, wide)))

    def _size_menu(self, token, menu=None):
        """The list of footprints, ticked at whatever it is now."""
        into = menu if menu is not None else self._menu()
        current = span_of(token)
        for wide, tall in TOKEN_SPANS:
            mark = "\u2022 " if (wide, tall) == current else "   "
            into.add_command(
                label=mark + span_label(wide, tall),
                command=lambda w=wide, h=tall: self._resize_token(token, w, h))
        return into

    def _creature_row_menu(self, token, event):
        menu = self._menu()
        menu.add_command(label=token["name"], state="disabled")
        menu.add_separator()
        menu.add_cascade(label="Size", menu=self._size_menu(token,
                                                            self._menu()))
        menu.add_command(label="Turn",
                         command=lambda: self._turn_token(token))
        menu.add_command(label="Find on the map",
                         command=lambda: self._focus_token(token))
        menu.tk_popup(event.x_root, event.y_root)

    def _focus_token(self, token):
        self._select_only("token", token)
        self.canvas.xview_moveto(max(0.0, (token["x"] - 8) / float(MAP_W)))
        self.canvas.yview_moveto(max(0.0, (token["y"] - 6) / float(MAP_H)))
        self._render()

    # -- mode and grid -----------------------------------------------------
    def _can_gm(self):
        """Only the GM builds. Alone, or hosting, that is you."""
        if self.session is None or self.session.is_solo:
            return True
        return self.session.am_gm()

    def _is_mine(self, token):
        """Is this figure ours to move?

        On one machine every player figure is fair game - there is only one
        person at the keyboard. In a shared game a figure belongs to whoever
        is sitting in the seat it is registered to.
        """
        if self.session is None or self.session.is_solo or self._can_gm():
            return True
        owner = self._owner_of(token)
        if owner is None:
            return False
        return owner.get("seat") == self.session.my_token

    def _my_seat(self):
        """The player list entry belonging to whoever is sitting here."""
        if self.session is None or self.session.is_solo:
            return None
        for player in self.players:
            if player.get("seat") == self.session.my_token:
                return player
        return None

    def _unclaimed(self, token):
        """Is this figure going spare?"""
        if token.get("kind") != "player":
            return False
        owner = self._owner_of(token)
        if owner is None:
            return True
        # Registered to a name nobody at the table is sitting under.
        return not owner.get("seat")

    def _claim_token(self, token):
        """Make a spare figure yours.

        Only a figure nobody has taken, and only for somebody actually at
        the table - it is how a player picks up their character rather than
        waiting for the GM to hand it over.
        """
        if self.session is None or self.session.is_solo:
            return
        if not self._unclaimed(token):
            self.status.config(text="%s already belongs to somebody"
                                    % token["name"])
            return
        seat = self._my_seat()
        if seat is None:
            seat = {"id": self.new_id(),
                    "name": (self.session.person(self.session.my_token)
                             or {}).get("name", "Player"),
                    "seat": self.session.my_token}
            self.players.append(seat)
        self._push_undo()
        token["owner"] = seat["id"]
        self._select_only("token", token)
        self._render()
        self.save()
        self.status.config(text="%s is yours now" % token["name"])

    def _seat_players(self):
        """Give everyone who joins a place in the player list.

        The GM registers figures to players by name, so a person who has
        turned up needs to be in that list before their figure can be theirs.
        Nobody is removed when they leave - their figure stays on the map.
        """
        if self.session is None or not self.session.is_host:
            return False
        changed = False
        seated = {p.get("seat") for p in self.players if p.get("seat")}
        for card in self.session.people():
            token = card.get("token")
            if not token or token in seated or card.get("host"):
                continue
            self.players.append({"id": self.new_id(),
                                 "name": card.get("name", "Player"),
                                 "seat": token})
            changed = True
        return changed

    def _session_changed(self, _message=None):
        """Somebody joined, left, or was given a different role."""
        if not self.alive():
            return
        if self._seat_players():
            self.save()
        if not self._can_gm() and self.mode != "player":
            # A player cannot be left holding the building tools.
            self.demoted = True
            self._set_mode("player")
        elif self._can_gm() and self.demoted:
            # And being handed the chair back hands the tools back with it,
            # rather than leaving the new GM looking at a player's screen
            # wondering why nothing works.
            self.demoted = False
            self._set_mode("gm")
        self._sync_mode_button()
        self._sync_roster()
        self._render()

    def _set_mode(self, mode):
        """GM mode is the whole toolset. Player mode is the party's own
        figures and nothing else - no building, no secrets."""
        if mode == "gm" and not self._can_gm():
            self.status.config(text="the GM decides what is on the map")
            return
        if mode == "player" and self._can_gm():
            # A GM looking at the players' view chose to: leave them there
            # when the roster next changes.
            self.demoted = False
        self.mode = mode
        if mode == "player":
            self._cancel()
            self._clear_selection()
            if self.tool != "select":
                self._pick_tab("select")
        self.status.config(
            text="" if mode == "gm" else "players are looking - secrets are hidden")
        self._sync_mode_button()
        self._sync_tabs()
        self._sync_roster()
        self._sync_levels()
        self._render()
        if mode == "player" and self.last_unlocked:
            self.status.config(text="unlocked %s" % ", ".join(
                "%s with the %s" % (code, key.lower())
                for _who, code, key in self.last_unlocked))
        elif mode == "player" and self.last_entered:
            self.status.config(text="entered %s" % ", ".join(self.last_entered))
        self.schedule_save()

    def _sync_tabs(self):
        """Grey out the building tabs when the players are looking."""
        if not hasattr(self, "tab_buttons"):
            return
        for name, button in self.tab_buttons.items():
            locked = self.mode == "player" and name != "select"
            button.config(state="disabled" if locked else "normal",
                          disabledforeground=self.t["muted"])

    def _sync_mode_button(self):
        gm = self.mode == "gm"
        self.mode_button.config(
            text="GM Mode  ▾" if gm else "Player Mode  ▾",
            bg=self.t["accent"] if gm else self.t["crit"],
            state="normal" if self._can_gm() else "disabled")
        # Don't wipe the status on every redraw - a message about what just
        # happened is worth more than a blank line, and the player-mode
        # warning is put back by _motion and by _set_mode anyway.
        if not gm and not self.status.cget("text"):
            self.status.config(text="players are looking - secrets are hidden")

    def _toggle_grid(self):
        self.grid_on = not self.grid_on
        self._render()
        self.schedule_save()

    def _sync_grid_button(self):
        on = self.grid_on
        self.grid_button.config(bg=self.t["accent"] if on else self.t["bg"],
                                fg=self.t["bg"] if on else self.t["fg"])
        button = getattr(self, "sight_button", None)
        if button is not None and button.winfo_exists():
            lit = self.sight_on
            button.config(bg=self.t["accent"] if lit else self.t["bg"],
                          fg=self.t["bg"] if lit else self.t["fg"])

    def _toggle_sight(self):
        """Whether the party is held to what it can actually see.

        Turned off, the map goes back to plain room fog: everything they have
        explored stays lit whether or not there is a clear view to it.
        """
        self.sight_on = not self.sight_on
        self._sight_cache = None
        self._render()
        self.save()
        self.status.config(
            text="line of sight on - the party sees only what is in view"
                 if self.sight_on else
                 "line of sight off - explored ground all stays lit")

    def _draw_grid(self):
        """The overlay sits on the same tile lines everything else snaps to,
        so turning it off changes nothing but whether you can see them."""
        self.canvas.delete("grid")
        if not self.grid_on:
            return
        width, height = MAP_W * self.tile, MAP_H * self.tile
        for tx in range(MAP_W + 1):
            heavy = tx % 5 == 0
            self.canvas.create_line(tx * self.tile, 0, tx * self.tile, height,
                                    fill="#3a3d47" if heavy else "#2a2d35",
                                    tags="grid")
        for ty in range(MAP_H + 1):
            heavy = ty % 5 == 0
            self.canvas.create_line(0, ty * self.tile, width, ty * self.tile,
                                    fill="#3a3d47" if heavy else "#2a2d35",
                                    tags="grid")

    # -- geometry ----------------------------------------------------------
    def _tile_at(self, event):
        """Screen point -> tile, through the scroll offset."""
        x = int(self.canvas.canvasx(event.x) // self.tile)
        y = int(self.canvas.canvasy(event.y) // self.tile)
        return max(0, min(MAP_W - 1, x)), max(0, min(MAP_H - 1, y))

    def room_tiles(self, room):
        """Absolute tiles a placed room covers, rotation included."""
        spec = blueprint(room["code"])
        if spec is None:
            return []
        turned = rotate(spec["tiles"], room.get("turns", 0))
        return [(room["x"] + dx, room["y"] + dy) for dx, dy in turned]

    def _room_at(self, tx, ty):
        for room in reversed(self.rooms):
            if (tx, ty) in self.room_tiles(room):
                return room
        return None

    def _token_at(self, tx, ty):
        """Whatever is standing on this square, big ones included.

        A four-square creature answers to any of its squares, so it can be
        clicked anywhere on its body rather than only its top-left corner.
        """
        for token in reversed(self.tokens):
            if (tx, ty) in tiles_of(token):
                return token
        return None

    def _span_clear(self, tx, ty, wide, tall, ignore=None):
        """Is there room to stand here?

        Off the edge of the map does not count, and neither does any square
        another figure is already on.
        """
        if tx < 0 or ty < 0 or tx + wide > MAP_W or ty + tall > MAP_H:
            return False
        wanted = {(tx + dx, ty + dy)
                  for dy in range(tall) for dx in range(wide)}
        for token in self.tokens:
            if token is ignore:
                continue
            if wanted & set(tiles_of(token)):
                return False
        return True

    def _object_at(self, tx, ty):
        """Topmost object on a tile, terrain excepted.

        Water is scenery the rest of the map stands in, so it never wins a
        click while anything else is on the square. `_water_at` is how you
        ask for it deliberately.
        """
        for obj in reversed(self.objects):
            if (obj["x"], obj["y"]) != (tx, ty):
                continue
            if OBJECTS.get(obj.get("type"), {}).get("terrain"):
                continue
            return obj
        return None

    def _note_at(self, tx, ty):
        for note in reversed(self.notes):
            if (note["x"], note["y"]) == (tx, ty):
                return note
        return None

    def _wall_at(self, tx, ty):
        for wall in reversed(self.walls):
            if (wall["x"], wall["y"]) == (tx, ty):
                return wall
        return None

    def _players(self):
        return [t for t in self.tokens if t.get("kind") == "player"]

    def _tokens_in(self, room):
        tiles = set(self.room_tiles(room))
        return [t for t in self.tokens if (t["x"], t["y"]) in tiles]

    def _room_of(self, token):
        return self._room_at(token["x"], token["y"])

    def _pools(self):
        return {"room": self.rooms, "token": self.tokens,
                "object": self.objects, "note": self.notes,
                "wall": self.walls}

    def _selected_things(self):
        """Resolve the selection to live records, dropping anything deleted
        since it was selected. Ids are unique across every pool."""
        pools = self._pools()
        out = []
        for kind, ident in self.selection:
            for item in pools.get(kind, []):
                if item["id"] == ident:
                    out.append((kind, item))
                    break
        return out

    def _selected_thing(self):
        """The one thing the panel and Inspect talk about - the first."""
        things = self._selected_things()
        return things[0] if things else None

    def _select_only(self, kind, item):
        self.selection = [(kind, item["id"])]

    def _clear_selection(self):
        self.selection = []

    def _is_selected(self, item):
        return any(ident == item["id"] for _kind, ident in self.selection)

    def _drop_from_selection(self, item):
        self.selection = [(k, i) for k, i in self.selection
                          if i != item["id"]]

    def _fits(self, code, tx, ty, turns, ignore=None):
        """Rooms may not hang off the map or overlap one already down.

        `ignore` leaves one room out of the collision check - a room being
        dragged would otherwise always be blocked by where it currently is.
        """
        spec = blueprint(code)
        if spec is None:
            return False
        taken = set()
        for room in self.rooms:
            if room is ignore:
                continue
            taken.update(self.room_tiles(room))
        for dx, dy in rotate(spec["tiles"], turns):
            x, y = tx + dx, ty + dy
            if not (0 <= x < MAP_W and 0 <= y < MAP_H) or (x, y) in taken:
                return False
        return True

    # -- what the players may see -----------------------------------------
    def _visible_room(self, room):
        return self.mode == "gm" or room.get("revealed")

    def _tile_seen(self, tx, ty):
        """Player mode: a tile is on the table once its room is revealed.
        Bare floor outside every room counts as unexplored, so nothing the GM
        has parked out there gives the shape of the map away."""
        room = self._room_at(tx, ty)
        return room is not None and bool(room.get("revealed"))

    def _edge_seen(self, tx, ty, side):
        """Walls and doors sit between two tiles. Either side having been seen
        is enough - otherwise the door you just walked through would vanish
        along with the room on the far side of it."""
        if self._tile_seen(tx, ty):
            return True
        ahead = {"n": (tx, ty - 1), "s": (tx, ty + 1),
                 "e": (tx + 1, ty), "w": (tx - 1, ty)}[side]
        return self._tile_seen(*ahead)

    def _visible_token(self, token):
        if self.mode == "gm":
            return True
        if token.get("kind") == "player":
            return True     # the party always knows where the party is
        if token.get("hidden"):
            return False
        # A creature is only there while it is being looked at. The room may
        # be remembered; what has wandered into it since is not.
        return any(self._tile_seen(x, y) and self._in_sight(x, y)
                   for x, y in tiles_of(token))

    def _room_index(self):
        """tile -> the room standing on it. Built once per sweep; walking
        every room for every tile would be quadratic for no reason."""
        index = {}
        for room in self.rooms:
            for tile in self.room_tiles(room):
                index[tile] = room
        return index

    def move_of(self, token):
        """How many squares this figure gets in one move."""
        stats = token.get("stats") or {}
        try:
            return max(0, int(stats.get(MOVE_STAT, MOVE_DEFAULT)))
        except (TypeError, ValueError):
            return MOVE_DEFAULT

    def sight_of(self, token):
        """How far this figure can see, in squares."""
        stats = token.get("stats") or {}
        try:
            return max(0, int(stats.get(SIGHT_STAT, SIGHT_DEFAULT)))
        except (TypeError, ValueError):
            return SIGHT_DEFAULT

    def _sight_opaque(self):
        """Squares you cannot see past.

        Only growth tall enough to stand behind. Moss lies flat, and water,
        pits and loot are all things you can see over.
        """
        return {(o["x"], o["y"]) for o in self.objects
                if OBJECTS.get(o.get("type"), {}).get("blocks_sight")}

    def _view_reaches(self, x0, y0, x1, y1, floor, barriers, opaque):
        """Can a figure at one square see another?

        A straight line between the two, refused if it would have to pass
        through a wall, a door, tall growth, or the bare ground between two
        rooms that do not touch. Corners are checked both ways round, so a
        view squeezes past a diagonal gap only if there is really a gap.
        """
        dx, dy = abs(x1 - x0), abs(y1 - y0)
        sx = 1 if x1 > x0 else -1
        sy = 1 if y1 > y0 else -1
        err = dx - dy
        x, y = x0, y0
        while (x, y) != (x1, y1):
            doubled = 2 * err
            step_x = step_y = 0
            if doubled > -dy:
                err -= dy
                step_x = sx
            if doubled < dx:
                err += dx
                step_y = sy
            nx, ny = x + step_x, y + step_y

            if step_x and step_y:
                if not self._corner_open(x, y, nx, ny, floor, barriers,
                                         opaque):
                    return False
            elif (x, y, SIDE_OF[(step_x, step_y)]) in barriers:
                return False

            x, y = nx, ny
            if (x, y) == (x1, y1):
                return True
            # Standing on the far side of this square is what matters; you
            # can see the grass itself, just not what is behind it.
            if (x, y) not in floor or (x, y) in opaque:
                return False
        return True

    def _corner_open(self, x, y, nx, ny, floor, barriers, opaque):
        """A diagonal step, taken as two straight ones - either way round."""
        for corner in ((x, ny), (nx, y)):
            first = SIDE_OF[(corner[0] - x, corner[1] - y)]
            if (x, y, first) in barriers:
                continue
            if corner not in floor or corner in opaque:
                continue
            second = SIDE_OF[(nx - corner[0], ny - corner[1])]
            if (corner[0], corner[1], second) in barriers:
                continue
            return True
        return False

    def _party_sight(self):
        """Every square the party can see from where its figures stand.

        Worked out once per redraw and kept, because it is asked for again
        for every room, object and figure that gets drawn.
        """
        if self._sight_cache is not None:
            return self._sight_cache
        floor = set(self._room_index())
        barriers = self._barriers()
        opaque = self._sight_opaque()
        visible = set()
        for token in self.tokens:
            if token.get("kind") != "player":
                continue
            standing = tiles_of(token)
            visible.update(standing)
            reach = self.sight_of(token)
            if not reach:
                continue
            for spot in floor:
                if spot in visible:
                    continue
                near = min(max(abs(spot[0] - ox), abs(spot[1] - oy))
                           for ox, oy in standing)
                if near > reach:
                    continue
                for ox, oy in standing:
                    if self._view_reaches(ox, oy, spot[0], spot[1], floor,
                                          barriers, opaque):
                        visible.add(spot)
                        break
        self._sight_cache = visible
        return visible

    def _has_eyes(self):
        """Is there anybody on this floor to do the seeing?"""
        return any(t.get("kind") == "player" for t in self.tokens)

    def _in_sight(self, tx, ty):
        """Can the party see this square right now?"""
        if not self.sight_on:
            return True         # sight turned off: memory is all there is
        if not self._has_eyes():
            # No party figures down here yet. Sight cannot mean anything
            # without somebody to look, and a blank map would just read as
            # broken, so fall back to plain room fog.
            return True
        return (tx, ty) in self._party_sight()

    def _lit(self, tx, ty):
        """Player mode: is this square remembered and currently in view?"""
        return self._tile_seen(tx, ty) and self._in_sight(tx, ty)

    def _barriers(self):
        """Every tile edge carrying a wall or a door.

        One physical edge has two names - the east side of a tile is the west
        side of its neighbour - so both are recorded and a lookup from either
        tile finds it.
        """
        edges = set()
        for wall in self.walls:
            edges.add((wall["x"], wall["y"], wall["side"]))
        for obj in self.objects:
            if obj.get("kind") == "door" and not obj.get("open"):
                # An open door is a doorway: you can see through it, and the
                # rooms either side of it are one space again.
                edges.add((obj["x"], obj["y"], obj.get("side", "n")))
        both = set(edges)
        for x, y, side in edges:
            dx, dy = STEP[side]
            both.add((x + dx, y + dy, OPPOSITE[side]))
        return both

    def _connected_group(self, room, index=None, barriers=None):
        """Every room reachable from this one without crossing a wall or door.

        Two prefabs that share an open edge are one space - drop two corridors
        end to end and the party walking into either lights up both. A wall or
        a door on the shared edge is what makes them separate places again.
        The wall a prefab draws round itself is only decoration; it is the
        wall and door objects the GM places that divide.
        """
        if index is None:
            index = self._room_index()
        if barriers is None:
            barriers = self._barriers()
        group = [room]
        seen = {id(room)}
        queue = [room]
        while queue:
            current = queue.pop()
            tiles = set(self.room_tiles(current))
            for x, y in tiles:
                for (dx, dy), side in SIDE_OF.items():
                    step = (x + dx, y + dy)
                    if step in tiles:
                        continue
                    other = index.get(step)
                    if other is None or id(other) in seen:
                        continue
                    if (x, y, side) in barriers:
                        continue        # a wall or door keeps them apart
                    if other.get("locked"):
                        continue        # and a locked room is sealed outright
                    seen.add(id(other))
                    group.append(other)
                    queue.append(other)
        return group

    def _explore(self):
        """Standing in a room reveals it, and everything joined to it, for
        good - the map fills in behind the party as they go. Anything walled
        or doored off stays dark until they go through.

        A locked room reveals nothing, even with the party standing in it,
        and nothing beyond it can be seen through it - unless whoever walked
        in is carrying a key, which turns in the lock and is used up. Without
        one that blank space is the signal to go and find it. Only runs in
        player mode; the GM reveals by hand, and a manual reveal still wins
        over a lock.
        """
        entered = []
        unlocked = []
        index = barriers = None
        if any(room.get("resealed") for room in self.rooms):
            index, barriers = self._room_index(), self._barriers()
            self._unseal_empty(index, barriers)
        for token in self.tokens:
            if token.get("kind") != "player":
                continue
            room = self._room_at(token["x"], token["y"])
            if room is None:
                continue
            if room.get("locked"):
                used = self._turn_key(token, room)
                if not used:
                    continue           # no key: the room stays shut and dark
                unlocked.append((token["name"], room["code"], used))
            if index is None:
                index, barriers = self._room_index(), self._barriers()
            for part in self._connected_group(room, index, barriers):
                if part.get("resealed"):
                    continue        # the GM took this one back off the map
                if not part.get("revealed"):
                    part["revealed"] = True
                    entered.append(part["code"])
        self.last_entered = entered
        self.last_unlocked = unlocked
        return entered

    def _stat_value(self, token, name):
        return dict(stats_of(token)).get(name, 0)

    def _set_stat(self, token, name, value):
        """Write one stat down. Sight changes what the party can see, so the
        map is redrawn rather than just the panel."""
        self._push_undo()
        stats = token.setdefault("stats", {})
        stats[name] = int(value)
        self._sight_cache = None
        self._render()
        self.save()
        self.status.config(text="%s: %s is now %d"
                                % (token["name"], name, int(value)))

    def _edit_stat(self, token, name):
        """Ask for a new number for one stat."""
        current = self._stat_value(token, name)
        note = None
        if name == SIGHT_STAT:
            note = "how many squares this character can see, in every direction"
        box = AmountDialog(self, "%s - %s" % (token["name"], name),
                           "%s:" % name, current, STAT_FLOOR, STAT_CEILING,
                           note=note)
        # The window does not block on its own - without this the answer is
        # read before anybody has had the chance to give one.
        self._wait_for(box)
        if not box.accepted or box.value is None:
            return
        self._set_stat(token, name, box.value)

    def _add_stat(self, token):
        """A stat of the GM's own, for whatever this game tracks."""
        name = simpledialog.askstring("Add stat", "What is it called?",
                                      parent=self.win)
        if not name or not name.strip():
            return
        name = name.strip()[:16]
        if name in dict(stats_of(token)):
            self.status.config(text="%s already has a %s" % (token["name"],
                                                             name))
            return
        box = AmountDialog(self, "%s - %s" % (token["name"], name),
                           "%s:" % name, 0, STAT_FLOOR, STAT_CEILING)
        self._wait_for(box)
        if not box.accepted or box.value is None:
            return
        self._set_stat(token, name, box.value)

    def _remove_stat(self, token, name):
        if name in STAT_ORDER:
            return          # the standard ones are always there
        self._push_undo()
        (token.get("stats") or {}).pop(name, None)
        self._render()
        self.save()

    def _stats_window(self, token):
        """The character sheet: every stat, each one a click from changing."""
        return StatsDialog(self, token)

    def _walls_only(self):
        """Edges a figure cannot cross.

        Walls, but not doors - a door is a way through, which is the whole
        point of one. Locked doors are handled by the room being locked.
        """
        edges = set()
        for wall in self.walls:
            edges.add((wall["x"], wall["y"], wall["side"]))
        both = set(edges)
        for x, y, side in edges:
            dx, dy = STEP[side]
            both.add((x + dx, y + dy, OPPOSITE[side]))
        return both

    def _walkable(self, token, index):
        """Which squares this figure is allowed to stand on.

        Room floor only - the bare ground between two rooms that do not
        touch is not something you can walk across, so an unconnected room
        stays out of reach until there is a way through. A locked room is
        floor only to somebody carrying the key for it.
        """
        allowed = set()
        shut = {}
        for spot, room in index.items():
            if room.get("locked"):
                key = id(room)
                if key not in shut:
                    shut[key] = self._matching_key(token, room) is not None
                if not shut[key]:
                    continue
            allowed.add(spot)
        return allowed

    def _reachable(self, token):
        """Every square this figure could move to, and what it costs.

        Counted outwards a step at a time, so the number against a square is
        the shortest way there rather than the distance as the crow flies -
        walking round a wall really does cost more.
        """
        reach = self.move_of(token)
        index = self._room_index()
        floor = self._walkable(token, index)
        if (token["x"], token["y"]) not in floor:
            # Standing off the map altogether - parked on bare ground by the
            # GM, most likely. Held to the floor it would not be able to move
            # at all, so let it walk on and pick the rules up from there.
            floor = floor | {(x, y)
                             for x in range(MAP_W) for y in range(MAP_H)}
        blocked = self._walls_only()
        taken = set()
        for other in self.tokens:
            if other is not token:
                taken.update(tiles_of(other))

        wide, tall = span_of(token)
        start = (token["x"], token["y"])
        costs = {start: 0}
        edge = [start]
        while edge:
            following = []
            for x, y in edge:
                step = costs[(x, y)] + 1
                if step > reach:
                    continue
                for dx in (-1, 0, 1):
                    for dy in (-1, 0, 1):
                        if not dx and not dy:
                            continue
                        spot = (x + dx, y + dy)
                        if spot in costs:
                            continue
                        if not self._step_open(x, y, dx, dy, floor, blocked):
                            continue    # a wall, or squeezing past a corner
                        if not self._room_fits(spot, wide, tall, floor):
                            continue    # off the floor, or half off it
                        if self._span_hits(spot, wide, tall, taken):
                            continue    # somebody is standing there
                        costs[spot] = step
                        following.append(spot)
            edge = following
        del costs[start]
        return costs

    def _step_open(self, x, y, dx, dy, floor, blocked):
        """Can a figure step from one square to the next?

        Diagonals count as one square, the same as the measured move has
        always shown - but only if there is really a way round: a corner
        with walls on both sides cannot be squeezed through.
        """
        if not dx or not dy:
            return (x, y, SIDE_OF[(dx, dy)]) not in blocked
        for corner in ((x, y + dy), (x + dx, y)):
            first = SIDE_OF[(corner[0] - x, corner[1] - y)]
            if (x, y, first) in blocked:
                continue
            if corner not in floor:
                continue
            second = SIDE_OF[(x + dx - corner[0], y + dy - corner[1])]
            if (corner[0], corner[1], second) in blocked:
                continue
            return True
        return False

    def _room_fits(self, spot, wide, tall, floor):
        """Does a figure this size stand entirely on the floor here?"""
        for dy in range(tall):
            for dx in range(wide):
                if (spot[0] + dx, spot[1] + dy) not in floor:
                    return False
        return True

    def _span_hits(self, spot, wide, tall, taken):
        for dy in range(tall):
            for dx in range(wide):
                if (spot[0] + dx, spot[1] + dy) in taken:
                    return True
        return False

    def _matching_key(self, token, room):
        """Where in this figure's bag the key for this room is, if at all.

        Key and lock have to be the same kind: the plain key opens any plain
        lock, a coloured one only its own colour.
        """
        wanted = room.get("lock_colour")
        for index, entry in enumerate(token.get("items") or []):
            if not is_key(entry.get("type")):
                continue
            if key_opens(entry.get("type")) != wanted:
                continue
            return index, entry
        return None

    def _barred(self, token, tiles):
        """The locked room in the way, if the figure cannot open it.

        A locked door is a door: without the key the party does not walk
        through it and find the room dark - they do not get in at all.
        """
        for tx, ty in tiles:
            room = self._room_at(tx, ty)
            if room is None or not room.get("locked"):
                continue
            if self._matching_key(token, room) is None:
                return room
        return None

    def _unseal_empty(self, index, barriers):
        """A room the GM hid stays hidden until the party has left the area.

        Walking back in afterwards discovers it again, from nothing - which
        is the point of hiding it.
        """
        standing = []
        for token in self.tokens:
            if token.get("kind") != "player":
                continue
            room = index.get((token["x"], token["y"]))
            if room is not None:
                standing.append(room)
        for room in self.rooms:
            if not room.get("resealed"):
                continue
            group = self._connected_group(room, index, barriers)
            if not any(any(here is part for part in group)
                       for here in standing):
                room.pop("resealed", None)

    def _turn_key(self, token, room):
        """Spend one key out of the figure's bag to open a room.

        Nothing here pushes an undo step: the move that walked them in
        already took one, so stepping back puts both the key and the lock
        where they were.
        """
        found = self._matching_key(token, room)
        if found is None:
            return None
        index, entry = found
        items = token.get("items") or []
        left = entry.get("count", 1) - 1
        if left <= 0:
            items.pop(index)
        else:
            entry["count"] = left
        room["locked"] = False
        return entry.get("type") or "Key"

    def _fixture(self, obj):
        """Part of the building, so remembered rather than only seen.

        A doorway, a flight of stairs, water, growth and a hole in the floor
        all stay where they are. A chest might not.
        """
        if obj.get("kind") == "door":
            return True
        if terrain_rank(obj):
            return True
        return obj.get("type") in ARCHITECTURE

    def _visible_object(self, obj):
        if self.mode == "gm":
            return True
        if obj.get("hidden"):
            return False
        if obj.get("kind") == "door":
            return self._edge_seen(obj["x"], obj["y"], obj.get("side", "n"))
        if not self._tile_seen(obj["x"], obj["y"]):
            return False
        if self._fixture(obj):
            return True
        return self._in_sight(obj["x"], obj["y"])

    def _visible_wall(self, wall):
        if self.mode == "gm":
            return True
        if wall.get("hidden"):
            return False
        return self._edge_seen(wall["x"], wall["y"], wall["side"])

    def _player_can_see(self, kind, item):
        return {"token": self._visible_token, "object": self._visible_object,
                "wall": self._visible_wall, "room": self._visible_room,
                "note": lambda _n: False}.get(kind, lambda _i: False)(item)

    def _player_target(self, tx, ty):
        """Topmost thing on this tile that the party can actually see."""
        for kind, item in self._tile_contents(tx, ty):
            if kind != "note" and self._player_can_see(kind, item):
                return kind, item
        return None, None

    def _short_name(self, kind, item):
        if kind == "token":
            return item["name"]
        if kind == "object":
            if item.get("kind") == "door":
                return "the door"
            if item.get("type") == WATER:
                return "the water"
            return item.get("text", "the object")
        if kind == "wall":
            return "the wall"
        if kind == "room":
            spec = blueprint(item["code"]) or {}
            return ("this corridor" if spec.get("size") == "corridor"
                    else "this room")
        return "this"

    def _describe(self, kind, item):
        """Plain words for the players - never GM bookkeeping."""
        if item is None:
            return "There is nothing here."
        if kind == "token":
            if item.get("kind") == "player":
                return "%s\nOne of your own party." % item["name"]
            state = ("It has been defeated." if item.get("defeated")
                     else "It is still standing.")
            return "%s\n%s" % (item["name"], state)
        if kind == "object":
            side = SIDE_NAMES.get(item.get("side", "n"), "near")
            if item.get("kind") == "door":
                return "A door.\nSet into the %s side of this square." % side
            spec = OBJECTS.get(item.get("type")) or {}
            if item.get("type") == WATER:
                room = self._room_at(item["x"], item["y"])
                where = room.get("category") if room else None
                name, detail = WATER_LINES.get(where, PLAIN_WATER)
                return "%s\n%s" % (name, detail)
            if item.get("type") == GOLD:
                return "%s\n%d coins." % (item.get("text", GOLD),
                                          item.get("value", 0))
            return "%s\n%s" % (item.get("text", "An object"),
                               spec.get("blurb", "Something left here."))
        if kind == "wall":
            side = SIDE_NAMES.get(item.get("side", "n"), "near")
            return "A wall.\nSolid along the %s side of this square." % side
        if kind == "room":
            spec = blueprint(item["code"]) or {}
            where = item.get("category", "").lower()
            name = spec.get("name", item["code"])
            size = spec.get("size", "")
            if size == "corridor":
                what = "A corridor in the %s." % where
            else:
                what = "A %s room in the %s." % (size, where)
            lines = [name, what]
            if item.get("locked"):
                shade = item.get("lock_colour")
                lines.append("The way on is locked."
                             if not shade else
                             "The way on is locked - it wants the %s key."
                             % shade.lower())
            contents = tally(o.get("text", "something")
                             for o in self._objects_in(item)
                             if self._visible_object(o))
            if contents:
                lines.append("")
                lines.append("You find:")
                lines.extend("  - " + line for line in contents)
            else:
                lines.append("")
                lines.append("Nothing else catches your eye.")
            return "\n".join(lines)
        return "You are not sure what this is."

    def _inspect(self, kind, item):
        """The answer goes to the INSPECT panel and the status line. No
        popup - the panel is already on screen in player mode saying the
        same thing, so a window would only be something else to dismiss.
        """
        answer = self._describe(kind, item)
        self._select_only(kind, item) if item is not None else self._clear_selection()
        # With nothing to select there is nothing for the panel to describe,
        # so hold the answer here and let the panel show that instead.
        self.inspect_note = None if item is not None else answer
        self._render()
        headline = answer.splitlines()
        self.status.config(text=headline[0] if headline else "")

    # -- drawing the map ---------------------------------------------------
    def _render(self):
        """Painted in layers, because the grid has to land between them: over
        the room floors so you can count squares inside a room, under the
        walls and tokens so it never cuts across them."""
        # Figures move, so what can be seen is worked out again every time.
        self._sight_cache = None
        if self.mode == "player" and self._explore():
            self.schedule_save()
        # Whatever is drawn below lands on top of the other players' cursors,
        # so they are drawn again at the end of this.
        self.win.after_idle(self._draw_peer_cursors)
        self.canvas.delete("map")
        visible = [r for r in self.rooms if self._visible_room(r)]
        for room in visible:
            self._draw_room_floor(room)
        # Terrain goes down with the floor - under the grid, under the walls,
        # under anything standing on it. Lowest layer first, so growth is
        # drawn over the water it is standing in.
        ground = sorted((o for o in self.objects if terrain_rank(o)),
                        key=terrain_rank)
        for obj in ground:
            if self._visible_object(obj):
                self._draw_object(obj)
        self._draw_grid()
        for room in visible:
            self._draw_room_walls(room)
        for wall in self.walls:
            if not self._visible_wall(wall):
                continue
            colour = "#8d94a6"
            if wall.get("hidden"):
                colour = self._ghosted(colour)
            self.canvas.create_line(*self._edge(wall["x"], wall["y"],
                                                 wall["side"]),
                                    fill=colour, width=self._w(5),
                                    capstyle="round", tags="map")
        for obj in self.objects:
            if not terrain_rank(obj) and self._visible_object(obj):
                self._draw_object(obj)
        for token in self.tokens:
            if self._visible_token(token):
                self._draw_token(token)
        if self.mode == "gm":
            for note in self.notes:
                self._draw_note(note)
        self._draw_selection()
        self._sync_mode_button()
        self._sync_grid_button()
        self._refresh_select_tab()
        self._fill_creature_list()
        self._fill_roster()
        self._fill_stats()
        self._fill_inventory()
        self._wheel_scrolls(getattr(self, "panel_body", None) or self.win)
        self._fill_levels()
        self._sync_tabs()

    def _draw_room_floor(self, room):
        floor, _wall = PALETTE.get(room.get("category", "Sewer"), DEFAULT_PALETTE)
        unseen = self.mode == "gm" and not room.get("revealed")
        dark = self._remembered(floor)
        players = self.mode == "player"
        for x, y in self.room_tiles(room):
            left, top = x * self.tile, y * self.tile
            shade = floor
            if players and not self._in_sight(x, y):
                shade = dark        # been here, cannot see it from here
            self.canvas.create_rectangle(left, top, left + self.tile, top + self.tile,
                                         fill=shade, outline="", tags="map")
            if unseen:
                # Hatching is what tells the GM at a glance what the party
                # has not walked into yet.
                self.canvas.create_line(left, top + self.tile, left + self.tile, top,
                                        fill="#000000", width=1, tags="map")

    def _draw_room_walls(self, room):
        _floor, wall = PALETTE.get(room.get("category", "Sewer"), DEFAULT_PALETTE)
        tiles = set(self.room_tiles(room))
        players = self.mode == "player"
        faded = self._remembered(wall)
        # Only the outside edges get a wall, so a room reads as one space.
        for x, y in tiles:
            left, top = x * self.tile, y * self.tile
            # A wall the party cannot see from here is remembered, not lit.
            shade = faded if players and not self._in_sight(x, y) else wall
            if (x, y - 1) not in tiles:
                self.canvas.create_line(left, top, left + self.tile, top,
                                        fill=shade, width=self._w(3), tags="map")
            if (x, y + 1) not in tiles:
                self.canvas.create_line(left, top + self.tile, left + self.tile,
                                        top + self.tile, fill=shade,
                                        width=self._w(3), tags="map")
            if (x - 1, y) not in tiles:
                self.canvas.create_line(left, top, left, top + self.tile,
                                        fill=shade, width=self._w(3), tags="map")
            if (x + 1, y) not in tiles:
                self.canvas.create_line(left + self.tile, top, left + self.tile,
                                        top + self.tile, fill=shade,
                                        width=self._w(3), tags="map")
        if self.mode == "gm":
            x, y = min(tiles, key=lambda p: (p[1], p[0]))
            label = room["code"]
            if room.get("locked"):
                label += " \U0001f512"
            self.canvas.create_text(x * self.tile + self._s(4),
                                    y * self.tile + self._s(3), text=label,
                                    anchor="nw", fill=self.t["muted"],
                                    font=self._zoom_font("label"), tags="map")

    def _draw_token(self, token):
        wide, tall = span_of(token)
        left, top = token["x"] * self.tile, token["y"] * self.tile
        across, down = wide * self.tile, tall * self.tile
        middle_x, middle_y = left + across // 2, top + down // 2
        pad = self._w(3)
        player = token.get("kind") == "player"
        chosen = token.get("color") if player else None
        if player:
            colour, outline = chosen or self.t["accent"], self.t["fg"]
        else:
            colour = (self.t["muted"] if token.get("defeated")
                      else self.t["fumble"])
            outline = self.t["fg"]
        if token.get("hidden"):
            colour, outline = self.t["panel"], self.t["muted"]
        width = self._s(3) if player else self._s(2)
        self.canvas.create_oval(left + pad, top + pad, left + across - pad,
                                top + down - pad, fill=colour,
                                outline=outline, width=width, tags="map")
        face = None
        if token.get("portrait"):
            # Square, so a picture is not stretched on an oblong figure.
            face = self._portrait_image(token["portrait"],
                                        min(across, down) - 2 * pad,
                                        dim=bool(token.get("hidden")))
        if face is not None:
            # The picture fills the circle; the ring is drawn again on top so
            # the token still reads as gold for the party, red for a monster.
            self.canvas.create_image(middle_x, middle_y, image=face,
                                     tags="map")
            # With a picture covering the fill, the chosen colour has to live
            # in the ring or it would be invisible.
            self.canvas.create_oval(left + pad, top + pad, left + across - pad,
                                    top + down - pad,
                                    outline=(chosen or outline)
                                    if not token.get("hidden") else outline,
                                    width=width, tags="map")
        else:
            if player:
                # A second ring marks the party out from the monsters.
                self.canvas.create_oval(left + pad + self._s(4),
                                        top + pad + self._s(4),
                                        left + across - pad - self._s(4),
                                        top + down - pad - self._s(4),
                                        outline=self.t["bg"], width=1,
                                        tags="map")
            initial = (token["name"] or "?").strip()[:1].upper()
            self.canvas.create_text(middle_x, middle_y, text=initial,
                                    fill=self.t["bg"],
                                    font=self._zoom_font("die"), tags="map")
        if token.get("defeated"):
            nick = self._w(5)
            self.canvas.create_line(left + nick, top + nick,
                                    left + across - nick, top + down - nick,
                                    fill=self.t["fumble"], width=self._w(3),
                                    tags="map")
            self.canvas.create_line(left + across - nick, top + nick,
                                    left + nick, top + down - nick,
                                    fill=self.t["fumble"], width=self._w(3),
                                    tags="map")

    def _draw_object(self, obj):
        left, top = obj["x"] * self.tile, obj["y"] * self.tile
        hidden = bool(obj.get("hidden"))
        # To the party, a doorway they cannot see right now looks the same as
        # anything else they are only remembering.
        if (self.mode == "player" and not hidden
                and not self._in_sight(obj["x"], obj["y"])):
            hidden = True
        if obj.get("kind") == "door":
            # A door lies along a tile edge, so it turns with the wheel too.
            x0, y0, x1, y1 = self._edge(obj["x"], obj["y"],
                                         obj.get("side", "n"))
            jamb = self._s(5)
            if y0 == y1:
                box = (x0 + jamb, y0 - jamb, x1 - jamb, y0 + jamb)
            else:
                box = (x0 - jamb, y0 + jamb, x0 + jamb, y1 - jamb)
            colour = DOOR_SHADE.get(obj.get("type"), self.t["accent"])
            fill = self._ghosted(colour) if hidden else colour
            edge = self.t["muted"] if hidden else self.t["bg"]
            if obj.get("open"):
                # Only the frame, with the way through left clear - so an
                # open door reads as a gap rather than a thinner door.
                left, top, right, bottom = box
                if y0 == y1:
                    stud = (right - left) * 0.3
                    parts = [(left, top, left + stud, bottom),
                             (right - stud, top, right, bottom)]
                else:
                    stud = (bottom - top) * 0.3
                    parts = [(left, top, right, top + stud),
                             (left, bottom - stud, right, bottom)]
                for part in parts:
                    self.canvas.create_rectangle(*part, fill=fill,
                                                 outline=edge, width=1,
                                                 tags="map")
            else:
                self.canvas.create_rectangle(*box, fill=fill, outline=edge,
                                             width=2, tags="map")
        else:
            self._draw_thing(obj, left, top)

    def _draw_thing(self, obj, left, top):
        """One piece of loot on the map, in the middle of its tile."""
        self._paint_shape(self.canvas, obj,
                          left + self.tile // 2, top + self.tile // 2,
                          self.tile / float(TILE), tags="map")

    def _paint_shape(self, canvas, obj, cx, cy, scale, tags="map"):
        """Draw an object's silhouette centred on a point.

        Written against a 32px tile and scaled from there, so the same code
        draws it on the map at any zoom and in an inventory cell.
        """
        spec = OBJECTS.get(obj.get("type"))
        colour = spec["color"] if spec else self.t["crit"]
        shape = spec["shape"] if spec else "box"
        edge = self.t["bg"]
        if obj.get("hidden"):
            colour = self._ghosted(colour)
            edge = self.t["muted"]

        def s(size):
            return int(round(size * scale))

        def w(width):
            return max(1, s(width))

        def box(x0, y0, x1, y1, width=2):
            canvas.create_rectangle(cx + s(x0), cy + s(y0), cx + s(x1),
                                    cy + s(y1), fill=colour, outline=edge,
                                    width=w(width), tags=tags)

        def disc(x0, y0, x1, y1, width=2):
            canvas.create_oval(cx + s(x0), cy + s(y0), cx + s(x1), cy + s(y1),
                               fill=colour, outline=edge, width=w(width),
                               tags=tags)

        if shape == "flask":
            box(-2, -10, 2, -4, width=1)
            disc(-7, -5, 7, 9)
        elif shape == "scroll":
            box(-9, -6, 9, 6)
            for dx in (-9, 9):
                canvas.create_line(cx + s(dx), cy + s(-7), cx + s(dx),
                                   cy + s(7), fill=edge, width=w(3), tags=tags)
            mark = spec.get("mark") if spec else None
            if mark == "cross":
                canvas.create_line(cx + s(-4), cy + s(-4), cx + s(4), cy + s(4),
                                   fill=edge, width=w(2), tags=tags)
                canvas.create_line(cx + s(4), cy + s(-4), cx + s(-4), cy + s(4),
                                   fill=edge, width=w(2), tags=tags)
            elif mark == "ring":
                canvas.create_oval(cx + s(-4), cy + s(-4), cx + s(4), cy + s(4),
                                   outline=edge, fill="", width=w(2), tags=tags)
            elif mark == "arrow":
                canvas.create_line(cx, cy + s(5), cx, cy + s(-5), fill=edge,
                                   width=w(2), arrow="last", tags=tags)
        elif shape == "stone":
            canvas.create_polygon(cx, cy + s(-10), cx + s(8), cy,
                                  cx, cy + s(10), cx + s(-8), cy,
                                  fill=colour, outline=edge, width=w(2),
                                  tags=tags)
        elif shape == "pit":
            # The whole tile, edge to edge, and nothing else. A pit is an
            # absence - a border or an inner shape would make it look like
            # an object sitting on the floor rather than a gap in it.
            canvas.create_rectangle(cx + s(-16), cy + s(-16),
                                    cx + s(16), cy + s(16), fill=colour,
                                    outline="", tags=tags)
        elif shape == "water":
            canvas.create_rectangle(cx + s(-16), cy + s(-16),
                                    cx + s(16), cy + s(16), fill=colour,
                                    outline="", tags=tags)
            # A couple of lighter streaks so it reads as water rather than
            # a flat block of colour.
            for dy, run in ((-5, 7), (4, 5)):
                canvas.create_line(cx + s(-run), cy + s(dy),
                                   cx + s(run), cy + s(dy),
                                   fill="#4d8ea3", width=w(2), tags=tags)
        elif shape == "sword":
            canvas.create_polygon(cx, cy + s(-12), cx + s(3), cy + s(-6),
                                  cx + s(3), cy + s(4), cx + s(-3), cy + s(4),
                                  cx + s(-3), cy + s(-6), fill=colour,
                                  outline=edge, width=w(1), tags=tags)
            box(-7, 4, 7, 6, width=1)
            canvas.create_rectangle(cx + s(-2), cy + s(6), cx + s(2),
                                    cy + s(12), fill=edge, outline=edge,
                                    width=w(1), tags=tags)
        elif shape == "dagger":
            canvas.create_polygon(cx, cy + s(-9), cx + s(3), cy + s(-4),
                                  cx + s(3), cy + s(2), cx + s(-3), cy + s(2),
                                  cx + s(-3), cy + s(-4), fill=colour,
                                  outline=edge, width=w(1), tags=tags)
            box(-5, 2, 5, 4, width=1)
            canvas.create_rectangle(cx + s(-2), cy + s(4), cx + s(2), cy + s(9),
                                    fill=edge, outline=edge, width=w(1),
                                    tags=tags)
        elif shape == "axe":
            canvas.create_rectangle(cx + s(-7), cy + s(-11), cx + s(-3),
                                    cy + s(12), fill="#7a5230", outline=edge,
                                    width=w(1), tags=tags)
            canvas.create_polygon(cx + s(-3), cy + s(-10), cx + s(6), cy + s(-6),
                                  cx + s(6), cy + s(1), cx + s(-3), cy + s(-2),
                                  fill=colour, outline=edge, width=w(1),
                                  tags=tags)
        elif shape == "spear":
            canvas.create_rectangle(cx + s(-1), cy + s(-4), cx + s(1),
                                    cy + s(13), fill="#7a5230", outline=edge,
                                    width=w(1), tags=tags)
            canvas.create_polygon(cx, cy + s(-13), cx + s(4), cy + s(-4),
                                  cx + s(-4), cy + s(-4), fill=colour,
                                  outline=edge, width=w(1), tags=tags)
        elif shape == "bow":
            canvas.create_arc(cx + s(-9), cy + s(-12), cx + s(9), cy + s(12),
                              start=90, extent=180, style="arc",
                              outline=colour, width=w(3), tags=tags)
            canvas.create_line(cx + s(-5), cy + s(-11), cx + s(-5), cy + s(11),
                               fill=edge, width=w(1), tags=tags)
        elif shape == "armour":
            canvas.create_polygon(cx + s(-8), cy + s(-8), cx + s(-3), cy + s(-11),
                                  cx + s(3), cy + s(-11), cx + s(8), cy + s(-8),
                                  cx + s(7), cy + s(9), cx, cy + s(12),
                                  cx + s(-7), cy + s(9), fill=colour,
                                  outline=edge, width=w(1), tags=tags)
            canvas.create_line(cx, cy + s(-9), cx, cy + s(11), fill=edge,
                               width=w(1), tags=tags)
        elif shape == "band":
            canvas.create_oval(cx + s(-7), cy + s(-4), cx + s(7), cy + s(10),
                               outline=colour, fill="", width=w(3), tags=tags)
            disc(-3, -10, 3, -4, width=1)
        elif shape == "wand":
            canvas.create_line(cx + s(-8), cy + s(9), cx + s(6), cy + s(-7),
                               fill=colour, width=w(3), capstyle="round",
                               tags=tags)
            disc(4, -11, 10, -5, width=1)
        elif shape == "amulet":
            canvas.create_arc(cx + s(-8), cy + s(-12), cx + s(8), cy + s(2),
                              start=200, extent=140, style="arc", outline=edge,
                              width=w(2), tags=tags)
            canvas.create_polygon(cx, cy + s(11), cx + s(6), cy + s(2),
                                  cx, cy + s(-3), cx + s(-6), cy + s(2),
                                  fill=colour, outline=edge, width=w(1),
                                  tags=tags)
        elif shape == "locket":
            disc(-7, -9, 7, 9)
            canvas.create_line(cx + s(-7), cy, cx + s(7), cy, fill=edge,
                               width=w(1), tags=tags)
        elif shape == "idol":
            disc(-4, -11, 4, -3, width=1)
            canvas.create_polygon(cx + s(-6), cy + s(11), cx + s(-5), cy + s(-2),
                                  cx + s(5), cy + s(-2), cx + s(6), cy + s(11),
                                  fill=colour, outline=edge, width=w(1),
                                  tags=tags)
        elif shape == "grass":
            # Blades rather than a fill, so water underneath still shows.
            for foot, tip, lean in ((-12, -2, -3), (-7, -9, 2), (-2, -4, -2),
                                    (3, -10, 3), (8, -3, -2), (12, -8, 2)):
                canvas.create_line(cx + s(foot), cy + s(13),
                                   cx + s(foot + lean), cy + s(tip),
                                   fill=colour, width=w(2), capstyle="round",
                                   tags=tags)
        elif shape == "moss":
            for mx, my, r in ((-9, 4, 5), (-2, -3, 6), (5, 5, 5),
                              (9, -5, 4), (0, 9, 4)):
                canvas.create_oval(cx + s(mx - r), cy + s(my - r),
                                   cx + s(mx + r), cy + s(my + r),
                                   fill=colour, outline="", tags=tags)
        elif shape == "ring":
            # Hollow, so the floor and anything on it still reads through.
            canvas.create_oval(cx + s(-9), cy + s(-9), cx + s(9), cy + s(9),
                               outline=colour, fill="", width=w(3), tags=tags)
        elif shape == "frame":
            canvas.create_rectangle(cx + s(-9), cy + s(-9), cx + s(9), cy + s(9),
                                    outline=colour, fill="", width=w(3),
                                    tags=tags)
        elif shape == "cross":
            for x0, x1 in ((-8, 8), (8, -8)):
                canvas.create_line(cx + s(x0), cy + s(-8), cx + s(x1), cy + s(8),
                                   fill=colour, width=w(4), capstyle="round",
                                   tags=tags)
        elif shape == "stairs":
            canvas.create_polygon(
                cx + s(-10), cy + s(10), cx + s(-10), cy + s(5),
                cx + s(-5), cy + s(5), cx + s(-5), cy, cx, cy,
                cx, cy + s(-5), cx + s(5), cy + s(-5), cx + s(5), cy + s(-10),
                cx + s(10), cy + s(-10), cx + s(10), cy + s(10),
                fill=colour, outline=edge, width=w(1), tags=tags)
        elif shape == "coins":
            # Two down, one leaning on top, none of them lined up - it reads
            # as a heap rather than a neat stack.
            for ox, oy, r in ((-5, 4, 6), (5, 3, 6), (0, -4, 6)):
                disc(ox - r, oy - r + 1, ox + r, oy + r - 1, width=1)
        elif shape == "key":
            disc(-11, -6, -2, 3)
            box(-5, -3, 10, 0, width=1)
            for dx in (4, 8):
                box(dx, 0, dx + 2, 6, width=1)
        elif shape == "chest":
            box(-9, -7, 9, 8)
            canvas.create_line(cx + s(-9), cy, cx + s(9), cy, fill=edge,
                               width=w(2), tags=tags)
        else:
            box(-7, -7, 7, 7)

    def _draw_note(self, note):
        """A pinned page with a dog-eared corner and a few ruled lines.

        The old marker was an 8px triangle in the corner and was simply too
        easy to walk past. This is only ever drawn for the GM, so it can
        afford to be loud without giving anything away at the table. It sits
        top-right rather than centred so it does not bury whatever else is
        standing on the tile.
        """
        scale = self._s
        right = note["x"] * self.tile + self.tile - scale(3)
        left = right - scale(14)
        top = note["y"] * self.tile + scale(3)
        bottom = top + scale(17)
        fold = scale(5)
        ink = self.t["bg"]

        self.canvas.create_polygon(left, top, right - fold, top,
                                   right, top + fold, right, bottom,
                                   left, bottom, fill=self.t["accent"],
                                   outline=ink, width=self._w(1), tags="map")
        self.canvas.create_polygon(right - fold, top, right, top + fold,
                                   right - fold, top + fold, fill=ink,
                                   outline="", tags="map")
        for n in range(3):
            ruled = top + fold + scale(3) + n * scale(4)
            if ruled > bottom - scale(2):
                break
            self.canvas.create_line(left + scale(3), ruled,
                                    right - scale(3), ruled, fill=ink,
                                    width=self._w(1), tags="map")

    def _draw_selection(self):
        for kind, item in self._selected_things():
            self._outline(kind, item)

    def _outline(self, kind, item):
        # In player mode an outline may only sit on something they can see -
        # otherwise selecting would trace out what is still in the dark.
        if self.mode == "player" and not self._player_can_see(kind, item):
            return
        if kind == "wall":
            self.canvas.create_line(*self._edge(item["x"], item["y"],
                                                 item["side"]),
                                    fill=self.t["accent"], width=self._w(5),
                                    capstyle="round", tags="map")
            return
        if kind == "room":
            tiles = self.room_tiles(item)
        elif kind == "token":
            tiles = tiles_of(item)
        else:
            tiles = [(item["x"], item["y"])]
        inset = self._s(1)
        for x, y in tiles:
            self.canvas.create_rectangle(x * self.tile + inset,
                                         y * self.tile + inset,
                                         (x + 1) * self.tile - inset,
                                         (y + 1) * self.tile - inset,
                                         outline=self.t["accent"],
                                         width=self._w(2), tags="map")

    # -- arming a prefab ---------------------------------------------------
    def _arm(self, code):
        if self.mode == "player":
            return
        self.armed = None if self.armed == code else code
        self.turns = 0
        self._sync_room_cards()
        self._clear_ghost()
        if self.armed:
            self.hint.config(text="click the map to place %s - scroll to "
                                  "rotate, Esc cancels" % code)

    def _disarm(self):
        self.armed = None
        self.turns = 0
        self._clear_ghost()
        self._sync_room_cards()

    def _cancel(self):
        """Escape backs out of whatever is half-done - placing, moving or
        picking a target."""
        self._disarm()
        if self.moving is not None:
            self.moving = None
            self.canvas.config(cursor="")
            self.canvas.delete("move")
            self.status.config(text="move cancelled")
        if self.attacking is not None:
            self.attacking = None
            self.canvas.config(cursor="")
            self.canvas.delete("aim")
            self.status.config(text="attack cancelled")
        if self.drag is not None:
            self.drag = None
            self.canvas.delete("marquee")
            self._apply_cursor()

    def _rotatable(self):
        """Is there something under the cursor that a turn would change?"""
        if self.armed:
            return True
        if self.tool == "creature":
            # A 2x3 turns into a 3x2. A square one looks the same either
            # way, so the wheel is left to scroll the map instead.
            return self.token_span[0] != self.token_span[1]
        return self.tool == "draw" and self.draw_mode in ("wall", "door")

    def _wheel(self, event):
        """A notch turns the pending piece 90 degrees; with nothing pending
        the wheel goes back to being a scroll wheel."""
        if self.mode == "gm" and self._rotatable():
            if self.tool == "creature":
                self._turn_span()
                return "break"
            self.turns = (self.turns + (1 if event.delta < 0 else -1)) % 4
            self._draw_ghost(*self.hover)
            if not self.armed:
                self.status.config(text="edge: %s" % SIDES[self.turns])
            return "break"
        self.canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")

    def _rotate_ghost(self):
        if not self._rotatable():
            return
        if self.tool == "creature":
            self._turn_span()
            return
        self.turns = (self.turns + 1) % 4
        self._draw_ghost(*self.hover)

    def _turn_span(self):
        """Turn whatever is about to be placed end for end."""
        wide, tall = self.token_span
        if wide == tall:
            return False
        self.token_span = (tall, wide)
        self._sync_span_button()
        self._draw_ghost(*self.hover)
        self.status.config(text="placing a %s figure"
                                % span_label(tall, wide))
        return True

    def _clear_ghost(self):
        self.canvas.delete("ghost")

    def _draw_ghost(self, tx, ty):
        """Preview whatever the next click would do, at the hovered tile."""
        self._clear_ghost()
        if self.mode != "gm":
            return
        if self.armed:
            self._ghost_room(tx, ty)
        elif self.tool == "creature":
            wide, tall = self.token_span
            room = self._span_clear(tx, ty, wide, tall)
            for dy in range(tall):
                for dx in range(wide):
                    self._ghost_tile(tx + dx, ty + dy, room)
        elif self.tool == "draw":
            if self.draw_mode in ("wall", "door"):
                self._ghost_edge(tx, ty)
            elif self.draw_mode == "erase":
                self._ghost_erase(tx, ty)
            else:
                self._ghost_tile(tx, ty, True)

    def _ghost_room(self, tx, ty):
        spec = blueprint(self.armed)
        if spec is None:
            return
        ok = self._fits(self.armed, tx, ty, self.turns)
        colour = self.t["crit"] if ok else self.t["fumble"]
        for dx, dy in rotate(spec["tiles"], self.turns):
            left, top = (tx + dx) * self.tile, (ty + dy) * self.tile
            inset = self._s(1)
            self.canvas.create_rectangle(left + inset, top + inset,
                                         left + self.tile - inset,
                                         top + self.tile - inset,
                                         outline=colour, width=self._w(2),
                                         tags="ghost")

    def _ghost_tile(self, tx, ty, ok):
        colour = self.t["crit"] if ok else self.t["fumble"]
        inset = self._s(1)
        self.canvas.create_rectangle(tx * self.tile + inset,
                                     ty * self.tile + inset,
                                     (tx + 1) * self.tile - inset,
                                     (ty + 1) * self.tile - inset,
                                     outline=colour, width=self._w(2),
                                     tags="ghost")

    def _ghost_edge(self, tx, ty):
        side = SIDES[self.turns]
        x0, y0, x1, y1 = self._edge(tx, ty, side)
        self.canvas.create_line(x0, y0, x1, y1, fill=self.t["crit"],
                                width=self._w(5), capstyle="round",
                                tags="ghost")
        # A faint box round the tile the edge belongs to, so it is obvious
        # which of the two tiles sharing that line is being worked on.
        self.canvas.create_rectangle(tx * self.tile + 2, ty * self.tile + 2,
                                     (tx + 1) * self.tile - 2, (ty + 1) * self.tile - 2,
                                     outline=self.t["muted"], width=1,
                                     dash=(2, 3), tags="ghost")

    def _ghost_erase(self, tx, ty):
        target = self._erase_target(tx, ty)
        if target is None:
            self._ghost_tile(tx, ty, False)
            return
        kind, item = target
        if kind == "room":
            tiles = self.room_tiles(item)
        elif kind == "wall":
            x0, y0, x1, y1 = self._edge(item["x"], item["y"], item["side"])
            self.canvas.create_line(x0, y0, x1, y1, fill=self.t["fumble"],
                                    width=6, capstyle="round", tags="ghost")
            tiles = []
        else:
            tiles = [(item["x"], item["y"])]
        for x, y in tiles:
            inset = self._s(1)
            self.canvas.create_rectangle(x * self.tile + inset,
                                         y * self.tile + inset,
                                         (x + 1) * self.tile - inset,
                                         (y + 1) * self.tile - inset,
                                         outline=self.t["fumble"],
                                         width=self._w(2), tags="ghost")

    def _send_cursor(self, event):
        """Where our mouse is, in map squares - not pixels.

        Everyone is at a different zoom and scrolled somewhere different, so
        a pixel position would land nowhere near the same square.
        """
        if self.session is None or self.session.is_solo:
            return
        now = time.time()
        if now - self._cursor_sent < CURSOR_MS / 1000.0:
            return
        self._cursor_sent = now
        # Say who it is. The host stamps a sender onto anything a player
        # sends it, but nothing stamps the host's own messages - so without
        # this, everyone else drops the GM's cursor as coming from nobody.
        self.session.send({"kind": "cursor", "token": self.session.my_token,
                           "x": self.canvas.canvasx(event.x) / float(self.tile),
                           "y": self.canvas.canvasy(event.y) / float(self.tile),
                           "level": self._view()})

    def _cursor_from_network(self, message):
        if not self.alive():
            return
        token = message.get("from") or message.get("token")
        if token is None or token == self.session.my_token:
            return
        self._peer_cursors[token] = [message.get("x", 0), message.get("y", 0),
                                     message.get("level", 0), time.time()]
        if self.session.is_host:
            self.session.relay(dict(message, token=token), skip=token)
        self._draw_peer_cursors()

    def _draw_peer_cursors(self):
        """A little arrow and a name for everyone else, in their own colour."""
        if not self.alive():
            return
        self.canvas.delete("peers")
        if self.session is None or self.session.is_solo:
            return
        here = self._view()
        cards = {c.get("token"): c for c in self.session.people()}
        for token, (tx, ty, level, _when) in self._peer_cursors.items():
            card = cards.get(token)
            if card is None or level != here:
                continue        # they are looking at another floor
            colour = card.get("colour") or self.t["accent"]
            x, y = tx * self.tile, ty * self.tile
            size = max(9, self._s(13))
            # A plain pointer, outlined in the dark background so it stays
            # visible over pale floors as well as dark ones.
            self.canvas.create_polygon(
                x, y, x, y + size, x + size * 0.30, y + size * 0.74,
                x + size * 0.46, y + size * 1.04, x + size * 0.62,
                y + size * 0.96, x + size * 0.46, y + size * 0.66,
                x + size * 0.78, y + size * 0.62,
                fill=colour, outline=self.t["bg"], width=1, tags="peers")
            name = card.get("name", "?")
            self.canvas.create_text(x + size * 0.9 + 1, y + size + 1,
                                    text=name, anchor="nw", fill=self.t["bg"],
                                    font=self._zoom_font("label"), tags="peers")
            self.canvas.create_text(x + size * 0.9, y + size, text=name,
                                    anchor="nw", fill=colour,
                                    font=self._zoom_font("label"), tags="peers")
        self.canvas.tag_raise("peers")

    def _sweep_cursors(self):
        """Drop cursors that have stopped arriving - someone alt-tabbed away,
        or their window is closed."""
        self._cursor_sweep = None
        if not self.alive():
            return
        cutoff = time.time() - CURSOR_GONE
        stale = [t for t, seen in self._peer_cursors.items() if seen[3] < cutoff]
        for token in stale:
            del self._peer_cursors[token]
        if stale:
            self._draw_peer_cursors()
        self._cursor_sweep = self.win.after(CURSOR_SWEEP_MS,
                                            self._sweep_cursors)

    def _motion(self, event):
        self._send_cursor(event)
        tile = self._tile_at(event)
        if tile == self.hover:
            return
        self.hover = tile
        if self.moving is not None:
            self._draw_move_preview(*tile)
            return
        if self.attacking is not None:
            self._draw_aim_preview(*tile)
            return
        self.status.config(text="tile %d, %d" % tile
                           if self.mode == "gm"
                           else "players are looking - secrets are hidden")
        self._draw_ghost(*tile)

    # -- moving a token ----------------------------------------------------
    def _draw_move_preview(self, tx, ty):
        """A line from the figure to the cursor, with the squares it costs."""
        self.canvas.delete("move")
        token = self.moving
        if token is None:
            return
        # In player mode the squares within reach are shaded, so nobody has
        # to guess how far their Move gets them or where a wall stops them.
        allowed = self._reachable(token) if self.mode == "player" else None
        if allowed is not None:
            for (ax, ay), _cost in allowed.items():
                self.canvas.create_rectangle(
                    ax * self.tile + 1, ay * self.tile + 1,
                    (ax + 1) * self.tile - 1, (ay + 1) * self.tile - 1,
                    outline="", fill=self._blend(self.t["accent"],
                                                 self.t["bg"], 0.72),
                    tags="move")
            self.canvas.tag_lower("move", "map")
        x0 = token["x"] * self.tile + self.tile // 2
        y0 = token["y"] * self.tile + self.tile // 2
        x1 = tx * self.tile + self.tile // 2
        y1 = ty * self.tile + self.tile // 2
        steps = steps_between(token["x"], token["y"], tx, ty)
        reachable = allowed is None or (tx, ty) in allowed
        if allowed is not None and (tx, ty) in allowed:
            steps = allowed[(tx, ty)]
        shade = self.t["accent"] if reachable else self.t["fumble"]
        self.canvas.create_rectangle(tx * self.tile + 1, ty * self.tile + 1,
                                     (tx + 1) * self.tile - 1, (ty + 1) * self.tile - 1,
                                     outline=shade, width=2,
                                     tags="move")
        self.canvas.create_line(x0, y0, x1, y1, fill=shade, width=2,
                                dash=(6, 4), arrow="last", tags="move")
        if steps:
            bx = x1 + self.tile // 2 + self._s(2)
            by = y1 - self.tile // 2 - self._s(2)
            wide, tall = self._s(13), self._s(11)
            self.canvas.create_oval(bx - wide, by - tall, bx + wide, by + tall,
                                    fill=self.t["accent"], outline=self.t["bg"],
                                    width=self._w(2), tags="move")
            self.canvas.create_text(bx, by, text=str(steps), fill=self.t["bg"],
                                    font=self._zoom_font("die"), tags="move")
        self.status.config(text="%s - %d square%s" % (token["name"], steps,
                                                      "" if steps == 1 else "s"))

    # -- aiming an attack --------------------------------------------------
    def _begin_attack(self, token):
        """Arm the attack. The next click has to land on something to hit -
        it does not fall through to whatever tool the panel is on."""
        self._cancel()
        self.attacking = token
        self._select_only("token", token)
        self.canvas.config(cursor="tcross")
        self._clear_ghost()
        self._draw_aim_preview(*self.hover)

    def _draw_aim_preview(self, tx, ty):
        self.canvas.delete("aim")
        token = self.attacking
        if token is None:
            return
        x0 = token["x"] * self.tile + self.tile // 2
        y0 = token["y"] * self.tile + self.tile // 2
        x1 = tx * self.tile + self.tile // 2
        y1 = ty * self.tile + self.tile // 2
        target = self._attack_target_at(tx, ty)
        live = target is not None
        colour = self.t["fumble"] if live else self.t["muted"]
        self.canvas.create_line(x0, y0, x1, y1, fill=colour, width=2,
                                dash=(4, 4), arrow="last", tags="aim")
        if live:
            inset = self._s(2)
            self.canvas.create_oval(tx * self.tile + inset,
                                    ty * self.tile + inset,
                                    (tx + 1) * self.tile - inset,
                                    (ty + 1) * self.tile - inset,
                                    outline=self.t["fumble"], width=self._w(3),
                                    tags="aim")
        reach = steps_between(token["x"], token["y"], tx, ty)
        self.status.config(
            text="%s attacks %s - %d square%s away"
                 % (token["name"], target["name"], reach,
                    "" if reach == 1 else "s")
            if live else "%s: pick something to attack (Esc cancels)"
                         % token["name"])

    def _attack_target_at(self, tx, ty):
        """A legal thing to swing at. Player mode may not reach for a creature
        it cannot see, or the aiming line would give the monster away."""
        token = self._token_at(tx, ty)
        if token is None or token is self.attacking:
            return None
        if self.mode == "player" and not self._visible_token(token):
            return None
        return token

    def _finish_attack(self, tx, ty):
        attacker = self.attacking
        target = self._attack_target_at(tx, ty)
        if target is None:
            self.status.config(text="pick a creature to attack, or Esc to stop")
            return                      # stay armed rather than doing something else
        self.attacking = None
        self.canvas.config(cursor="")
        self.canvas.delete("aim")
        self._render()
        AttackDialog(self, attacker, target)

    def _finish_move(self, tx, ty):
        token = self.moving
        steps = steps_between(token["x"], token["y"], tx, ty)
        wide, tall = span_of(token)
        if self.mode == "player":
            landing = [(tx + dx, ty + dy)
                       for dy in range(tall) for dx in range(wide)]
            shut = self._barred(token, landing)
            if shut is not None:
                shade = shut.get("lock_colour")
                self.status.config(
                    text="that way is locked - you need the %s"
                         % ("%s key" % shade.lower() if shade else "key"))
                return
            # Walk it, rather than teleport: the square has to be one this
            # figure could actually reach on its own feet this turn.
            allowed = self._reachable(token)
            if (tx, ty) not in allowed:
                reach = self.move_of(token)
                self.status.config(
                    text="%s cannot get there - %d square%s a move, and no "
                         "walking through walls" % (token["name"], reach,
                                                    "" if reach == 1 else "s"))
                return
            steps = allowed[(tx, ty)]
        # A big figure needs the whole of its footprint free, not just the
        # square its corner lands on.
        if not self._span_clear(tx, ty, wide, tall, ignore=token):
            self.status.config(text="something is already standing there"
                                    if (wide, tall) == (1, 1)
                                    else "not enough room for %s there"
                                         % token["name"])
            return
        self._push_undo()
        token["x"], token["y"] = tx, ty
        self.moving = None
        self.canvas.config(cursor="")
        self.canvas.delete("move")
        self._render()
        self.save()
        message = "%s moved %d square%s" % (token["name"], steps,
                                            "" if steps == 1 else "s")
        if self.last_unlocked:
            message += " - unlocked %s" % ", ".join(
                "%s with the %s" % (code, key.lower())
                for _who, code, key in self.last_unlocked)
        elif self.last_entered:
            message += " - entered %s" % ", ".join(self.last_entered)
        self.status.config(text=message)

    # -- clicking ----------------------------------------------------------
    def _left_click(self, event):
        self.canvas.focus_set()
        if self._panning():
            # Grab the paper and shove it about.
            self.canvas.scan_mark(event.x, event.y)
            self.drag = {"mode": "pan"}
            return
        tx, ty = self._tile_at(event)

        if self.moving is not None:     # a figure picked up from its menu
            self._finish_move(tx, ty)
            return

        if self.attacking is not None:  # aiming - never falls through
            self._finish_attack(tx, ty)
            return

        if self.mode == "player":
            # Players get their own figures and nothing else.
            token = self._token_at(tx, ty)
            self.inspect_note = None
            if (token is not None and token.get("kind") == "player"
                    and self._is_mine(token)):
                self._select_only("token", token)
            else:
                self._clear_selection()
            self._render()
            return

        if self.armed:
            self._place_room(tx, ty)
            return

        if self.tool == "creature":
            name = (self.creature_name.get().strip()
                    if hasattr(self, "creature_name") else "")
            default = "Player" if self.token_kind == "player" else "Creature"
            self._place_token(tx, ty, name or default, self.token_kind)
            return

        if self.tool == "draw":
            self._draw_click(tx, ty)
            return

        self.last_tile = (tx, ty)
        hit = self._thing_at(tx, ty)
        if hit is None:
            # Nothing under the cursor: draw a box instead.
            self._clear_selection()
            self._render()
            self.drag = {"mode": "marquee",
                         "start": (self.canvas.canvasx(event.x),
                                   self.canvas.canvasy(event.y))}
            return
        kind, item = hit
        held = self._is_selected(item)
        if not held:
            self._select_only(kind, item)
        self._render()
        # Whatever is selected can be dragged straight away; the drag only
        # counts once the cursor actually leaves the tile it started on.
        # Pressing something already in a group keeps the group, so the whole
        # lot can be dragged - but letting go without moving means they were
        # picking this one out, so the group collapses to it on release.
        self.drag = {"mode": "move", "grab": (tx, ty), "applied": (0, 0),
                     "moved": False,
                     "narrow": (kind, item) if held and len(self.selection) > 1
                     else None}

    def _ctrl_click(self, event):
        """Add to or drop from the selection without losing the rest of it."""
        self.canvas.focus_set()
        if self.mode != "gm" or self.tool != "select" or self._panning():
            return self._left_click(event)      # nothing to add to
        tx, ty = self._tile_at(event)
        self.last_tile = (tx, ty)
        hit = self._thing_at(tx, ty)
        if hit is None:
            # From bare ground, a ctrl-drag boxes more things in on top of
            # what is already held.
            self.drag = {"mode": "marquee", "add": True,
                         "start": (self.canvas.canvasx(event.x),
                                   self.canvas.canvasy(event.y))}
            return
        kind, item = hit
        if self._is_selected(item):
            self._drop_from_selection(item)
        else:
            self.selection.append((kind, item["id"]))
        # Deliberately no drag armed: ctrl-click is for building the group,
        # and a stray wobble should not shove it around.
        self.drag = None
        self._render()
        count = len(self.selection)
        self.status.config(text="%d selected" % count if count
                                else "nothing selected")

    def _layers_at(self, tx, ty, walls=False):
        """The topmost thing a click should land on, by layer.

        Creatures first, then what is lying about, then notes; terrain and
        the room floor are last, because they are what everything else is
        standing on.
        """
        order = [("token", self._token_at), ("object", self._object_at),
                 ("note", self._note_at)]
        if walls:
            order.append(("wall", self._wall_at))
        order += [("object", self._terrain_at), ("room", self._room_at)]
        for kind, finder in order:
            found = finder(tx, ty)
            if found is not None:
                return kind, found
        return None

    def _thing_at(self, tx, ty):
        """What a click picks up.

        Walls are left out on purpose: one sits on a tile edge, so letting it
        win the click would make any room tile with a wall on it impossible
        to grab. The marquee still gathers them.
        """
        return self._layers_at(tx, ty)

    def _left_drag(self, event):
        """Whatever the left button started, continue it."""
        if self.drag is None:
            return
        mode = self.drag["mode"]
        if mode == "pan":
            self.canvas.scan_dragto(event.x, event.y, gain=1)
            return
        if mode == "marquee":
            self._drag_marquee(event)
            return
        if mode == "paint":
            if self._spread(*self._tile_at(event), self.drag["laying"]):
                self.drag["moved"] = True
                self._render()
            return
        self._drag_selection(*self._tile_at(event))

    def _drag_marquee(self, event):
        x0, y0 = self.drag["start"]
        x1 = self.canvas.canvasx(event.x)
        y1 = self.canvas.canvasy(event.y)
        self.canvas.delete("marquee")
        self.canvas.create_rectangle(x0, y0, x1, y1, outline=self.t["accent"],
                                     dash=(4, 3), width=1, tags="marquee")

    def _finish_marquee(self, event):
        self.canvas.delete("marquee")
        x0, y0 = self.drag["start"]
        x1 = self.canvas.canvasx(event.x)
        y1 = self.canvas.canvasy(event.y)
        left, right = sorted((x0, x1))
        top, bottom = sorted((y0, y1))
        box = {(x, y)
               for x in range(int(left // self.tile), int(right // self.tile) + 1)
               for y in range(int(top // self.tile), int(bottom // self.tile) + 1)}
        picked = list(self.selection) if self.drag.get("add") else []
        for kind, pool in (("token", self.tokens), ("object", self.objects),
                           ("note", self.notes), ("wall", self.walls)):
            for item in pool:
                if (item["x"], item["y"]) in box and (kind, item["id"]) not in picked:
                    picked.append((kind, item["id"]))
        for room in self.rooms:
            # A room joins only if the box holds all of it. Catching one
            # corner would otherwise drag a whole chamber along when the GM
            # only meant to lasso the chests inside it.
            if (set(self.room_tiles(room)) <= box
                    and ("room", room["id"]) not in picked):
                picked.append(("room", room["id"]))
        self.selection = picked
        self._render()
        self.status.config(text="%d selected" % len(picked) if picked
                                else "nothing in the box")

    def _drag_selection(self, tx, ty):
        gx, gy = self.drag["grab"]
        want = (tx - gx, ty - gy)
        done = self.drag["applied"]
        step = (want[0] - done[0], want[1] - done[1])
        if step == (0, 0):
            return
        if not self._selection_fits(*step):
            self.status.config(text="will not fit there")
            return
        self._begin_drag_step()
        self._shift_selection(*step)
        self.drag["applied"] = want
        self._render()

    def _selection_parts(self):
        """Split the selection into rooms, and the loose things that are not
        already riding on one of those rooms."""
        things = self._selected_things()
        rooms = [item for kind, item in things if kind == "room"]
        covered = set()
        for room in rooms:
            covered |= set(self.room_tiles(room))
        loose = [item for kind, item in things
                 if kind != "room" and (item["x"], item["y"]) not in covered]
        return rooms, loose

    def _selection_fits(self, dx, dy):
        rooms, loose = self._selection_parts()
        moving = {room["id"] for room in rooms}
        blocked = set()
        for room in self.rooms:
            if room["id"] not in moving:
                blocked |= set(self.room_tiles(room))
        for room in rooms:
            for x, y in self.room_tiles(room):
                spot = (x + dx, y + dy)
                if not (0 <= spot[0] < MAP_W and 0 <= spot[1] < MAP_H):
                    return False
                if spot in blocked:
                    return False
        for item in loose:
            x, y = item["x"] + dx, item["y"] + dy
            if not (0 <= x < MAP_W and 0 <= y < MAP_H):
                return False
            # A figure covering several squares has to fit by all of them.
            wide, tall = span_of(item)
            if x + wide > MAP_W or y + tall > MAP_H:
                return False
        return True

    def _shift_selection(self, dx, dy):
        """Work out everything that moves first, then move it once.

        Doing it room by room would double-shift anything standing on a tile
        that another selected room has already slid onto.
        """
        rooms, loose = self._selection_parts()
        covered = set()
        for room in rooms:
            covered |= set(self.room_tiles(room))
        movers = []
        for pool in (self.tokens, self.objects, self.notes, self.walls):
            for item in pool:
                if (item["x"], item["y"]) in covered:
                    movers.append(item)
        seen = set()
        for item in movers + loose:
            if id(item) in seen:
                continue
            seen.add(id(item))
            item["x"] += dx
            item["y"] += dy
        for room in rooms:
            room["x"] += dx
            room["y"] += dy

    def _begin_drag_step(self):
        """One undo step for the whole drag, taken as it actually starts."""
        if not self.drag["moved"]:
            self._push_undo()
            self.drag["moved"] = True
            self.canvas.config(cursor="fleur")

    def _moved_report(self):
        """One thing gets named and placed; a group gets counted."""
        things = self._selected_things()
        if len(things) == 1:
            kind, item = things[0]
            name = (item["code"] if kind == "room"
                    else item.get("name") or item.get("text") or kind)
            return "%s moved to %d, %d" % (name, item["x"], item["y"])
        dx, dy = self.drag["applied"]
        return "%d things moved %+d, %+d" % (len(things), dx, dy)

    def _drag_room(self, tx, ty):      # kept for the older single-room path
        self._drag_selection(tx, ty)

    def _drag_room(self, tx, ty):
        """A room moves by how far the cursor has come from where it was
        grabbed, so it does not jump its corner to the pointer."""
        room = self.drag["item"]
        gx, gy = self.drag["grab"]
        ox, oy = self.drag["origin"]
        nx, ny = ox + (tx - gx), oy + (ty - gy)
        if (room["x"], room["y"]) == (nx, ny):
            return
        if not self._fits(room["code"], nx, ny, room.get("turns", 0),
                          ignore=room):
            self.status.config(text="%s will not fit there" % room["code"])
            return
        self._begin_drag_step()
        self._shift_room(room, nx - room["x"], ny - room["y"])
        self._render()
        self.status.config(text="%s at %d, %d" % (room["code"], nx, ny))

    def _shift_room(self, room, dx, dy):
        """Move a room and everything standing on it. Leaving the creatures
        and the loot behind on bare floor would only make a mess to tidy."""
        tiles = set(self.room_tiles(room))       # before it moves
        for pool in (self.tokens, self.objects, self.notes, self.walls):
            for item in pool:
                if (item["x"], item["y"]) in tiles:
                    item["x"] += dx
                    item["y"] += dy
        room["x"] += dx
        room["y"] += dy

    def _left_release(self, event):
        if self.drag is None:
            return
        mode = self.drag["mode"]
        if mode == "paint":
            self._render()
            self.save()
            self.drag = None
            self._apply_cursor()
            return
        if mode == "marquee":
            self._finish_marquee(event)
        elif mode == "move" and self.drag["moved"]:
            self.save()
            self.status.config(text=self._moved_report())
        elif mode == "move" and self.drag.get("narrow"):
            kind, item = self.drag["narrow"]
            self._select_only(kind, item)
            self._render()
        self.drag = None
        self._apply_cursor()

    # -- portraits ---------------------------------------------------------
    def _portrait_dir(self):
        """Inside the campaign folder, so a save carries its own faces."""
        return os.path.join(dice_api.save_path(), PORTRAIT_DIR)

    def _portrait_path(self, name):
        return os.path.join(self._portrait_dir(), name)

    def _choose_portrait(self, token):
        if not PORTRAITS_OK:
            messagebox.showinfo(
                "Portraits", "Portraits need the Pillow library:\n\n"
                             "    python -m pip install pillow\n\n"
                             "Then reopen the map.", parent=self.win)
            return
        path = filedialog.askopenfilename(parent=self.win,
                                          title="Portrait for %s" % token["name"],
                                          filetypes=PORTRAIT_KINDS)
        if not path:
            return                       # they thought better of it
        try:
            PortraitDialog(self, token, path)
        except Exception as exc:         # a broken file, a bad format
            messagebox.showerror("Portrait",
                                 "Could not use that image:\n%s" % exc,
                                 parent=self.win)

    def _apply_portrait(self, token, picture):
        """Called by the crop window once the framing is settled."""
        try:
            name = self._store_portrait(token, picture)
        except Exception as exc:
            messagebox.showerror("Portrait",
                                 "Could not save that image:\n%s" % exc,
                                 parent=self.win)
            return
        self._push_undo()
        token["portrait"] = name
        self._render()
        self.save()
        self.status.config(text="portrait set for %s" % token["name"])

    def _store_portrait(self, token, source):
        """Mask to a circle and keep a copy of our own.

        `source` is either a path - in which case the middle square is taken,
        which is what an unframed image should default to - or an already
        cropped square Image from the crop window.

        Copying rather than remembering where the file was means the campaign
        keeps working after the original is moved, renamed or deleted.
        """
        if isinstance(source, str):
            picture = Image.open(source).convert("RGBA")
            side = min(picture.size)
            left = (picture.width - side) // 2
            top = (picture.height - side) // 2
            picture = picture.crop((left, top, left + side, top + side))
        else:
            picture = source.convert("RGBA")
        picture = picture.resize((PORTRAIT_STORE, PORTRAIT_STORE),
                                 Image.LANCZOS)
        mask = Image.new("L", (PORTRAIT_STORE, PORTRAIT_STORE), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, PORTRAIT_STORE - 1,
                                      PORTRAIT_STORE - 1), fill=255)
        picture.putalpha(mask)
        folder = self._portrait_dir()
        os.makedirs(folder, exist_ok=True)
        name = "%d.png" % token["id"]
        picture.save(os.path.join(folder, name), "PNG")
        self._portraits = {k: v for k, v in self._portraits.items()
                           if k[0] != name}          # a replacement, not a hit
        return name

    def _portrait_image(self, name, size, dim=False):
        """A token-sized PhotoImage, built once and held onto.

        Tk drops an image the moment nothing in Python refers to it, so the
        cache is not an optimisation - without it portraits flicker away.
        """
        key = (name, size, dim)
        if key in self._portraits:
            return self._portraits[key]
        if not PORTRAITS_OK:
            return None
        try:
            picture = Image.open(self._portrait_path(name)).convert("RGBA")
        except (OSError, ValueError):
            return None                  # deleted or corrupt: fall back
        picture = picture.resize((size, size), Image.LANCZOS)
        if dim:
            # Hidden tokens fade like everything else the players cannot see.
            # Blending flattens the alpha, so put the round mask back after.
            mask = picture.getchannel("A")
            page = Image.new("RGBA", picture.size, self._rgba(self.t["bg"]))
            picture = Image.blend(picture, page, GHOST_FADE)
            picture.putalpha(mask)
        photo = ImageTk.PhotoImage(picture, master=self.canvas)
        self._portraits[key] = photo
        return photo

    def _rgba(self, colour):
        try:
            r, g, b = self.canvas.winfo_rgb(colour)
        except tk.TclError:
            return (0, 0, 0, 255)
        return (r // 256, g // 256, b // 256, 255)

    def _clear_portrait(self, token):
        self._push_undo()
        token.pop("portrait", None)
        self._render()
        self.save()
        self.status.config(text="portrait cleared for %s" % token["name"])

    # -- the middle button -------------------------------------------------
    def _middle_down(self, event):
        self.canvas.scan_mark(event.x, event.y)
        self._middle = (event.x, event.y, False)

    def _middle_drag(self, event):
        if self._middle is None:
            return
        x, y, moved = self._middle
        if not moved and (abs(event.x - x) > 3 or abs(event.y - y) > 3):
            moved = True                      # a real drag, not a shaky click
            self._middle = (x, y, True)
        if moved:
            self.canvas.scan_dragto(event.x, event.y, gain=1)

    def _middle_up(self, event):
        if self._middle is None:
            return
        moved = self._middle[2]
        self._middle = None
        if not moved:
            self._ping(*self._tile_at(event))

    # -- ping --------------------------------------------------------------
    def _ping(self, tx, ty):
        """A ring that swells out of a tile and fades. Nothing is stored and
        nothing on the map changes - it is only a way of pointing at
        something, and it works the same in either mode."""
        self._ping_seq += 1
        tag = "ping%d" % self._ping_seq
        self._ping_frame(tag, tx * self.tile + self.tile // 2, ty * self.tile + self.tile // 2, 0)

    def _ping_frame(self, tag, cx, cy, step):
        if not self.alive():
            return
        self.canvas.delete(tag)
        if step >= PING_STEPS:
            self._ping_jobs.pop(tag, None)
            return
        along = step / float(PING_STEPS - 1)
        radius = self._s(PING_MIN + (PING_MAX - PING_MIN) * along)
        width = max(1, self._s(4 - 3 * along))
        self.canvas.create_oval(cx - radius, cy - radius, cx + radius,
                                cy + radius, outline=self._fade(along),
                                width=width, tags=tag)
        # A redraw part-way through would otherwise bury the ring.
        self.canvas.tag_raise(tag)
        self._ping_jobs[tag] = self.win.after(PING_MS, self._ping_frame,
                                              tag, cx, cy, step + 1)

    def _blend(self, colour, towards, along):
        try:
            near = self.canvas.winfo_rgb(colour)
            far = self.canvas.winfo_rgb(towards)
        except tk.TclError:
            return colour
        mixed = [int((n + (f - n) * along) / 256) for n, f in zip(near, far)]
        return "#%02x%02x%02x" % tuple(max(0, min(255, c)) for c in mixed)

    def _fade(self, along):
        """The ping ring, blended towards the page as it grows."""
        return self._blend(PING_COLOR, self.t["bg"], along)

    def _ghosted(self, colour):
        """How a hidden thing looks to the GM: still there, faded back."""
        return self._blend(colour, self.t["bg"], GHOST_FADE)

    def _remembered(self, colour):
        """How ground the party has walked but cannot see now is drawn."""
        return self._blend(colour, self.t["bg"], MEMORY_FADE)

    def _draw_click(self, tx, ty):
        if self.draw_mode == "door":
            self._place_object(tx, ty, "door")
        elif self.draw_mode == "object":
            self._place_object(tx, ty, "object")
        elif self.draw_mode == "stairs":
            self._place_object(tx, ty, "object", "Stairs")
        elif self.draw_mode == "traps":
            self._place_object(tx, ty, "object", self.trap_type)
        elif self.draw_mode in ("water", "foliage", "pit"):
            # A stroke rather than a click: one undo step covers the lot.
            laying = {"water": WATER, "pit": PIT}.get(self.draw_mode,
                                                      self.growth_type)
            self.drag = {"mode": "paint", "moved": False, "laying": laying}
            self._push_undo()
            self._spread(tx, ty, laying)
        elif self.draw_mode == "note":
            self._add_note(tx, ty)
        elif self.draw_mode == "erase":
            self._erase_at(tx, ty)
        elif self.draw_mode == "wall":
            self._push_undo()
            self.walls.append({"id": self.new_id(), "x": tx, "y": ty,
                               "side": SIDES[self.turns]})
            self._render()
            self.save()

    # -- erasing -----------------------------------------------------------
    def _erase_target(self, tx, ty):
        """The one thing a click here would take off, nearest layer first."""
        return self._layers_at(tx, ty, walls=True)

    def _tile_contents(self, tx, ty):
        """Everything on one square, top layer first.

        The same order things are drawn in, reversed: whoever is standing
        there, then what is lying about, then notes and walls, then the water
        and the room underneath it all.
        """
        found = []
        for token in reversed(self.tokens):
            if (token["x"], token["y"]) == (tx, ty):
                found.append(("token", token))
        for obj in reversed(self.objects):
            if obj.get("type") == WATER:
                continue                    # terrain, dealt with below
            if (obj["x"], obj["y"]) == (tx, ty):
                found.append(("object", obj))
        for note in reversed(self.notes):
            if (note["x"], note["y"]) == (tx, ty):
                found.append(("note", note))
        for wall in reversed(self.walls):
            if (wall["x"], wall["y"]) == (tx, ty):
                found.append(("wall", wall))
        for obj in sorted((o for o in self.objects
                           if terrain_rank(o) and (o["x"], o["y"]) == (tx, ty)),
                          key=terrain_rank, reverse=True):
            found.append(("object", obj))
        room = self._room_at(tx, ty)
        if room is not None:
            found.append(("room", room))
        return found

    def _one_line(self, kind, item):
        """A layer boiled down to a single line for the GM's list."""
        if kind == "token":
            marks = []
            if item.get("defeated"):
                marks.append("defeated")
            if item.get("hidden"):
                marks.append("hidden")
            return item["name"] + (" (%s)" % ", ".join(marks) if marks else "")
        if kind == "room":
            spec = blueprint(item["code"]) or {}
            return "%s  %s" % (item["code"], spec.get("name", ""))
        if kind == "note":
            said = (item.get("text") or "").strip()
            return "Note: " + (said[:24] + "..." if len(said) > 24 else said)
        if kind == "wall":
            return "Wall (%s side)" % SIDE_NAMES.get(item.get("side"), "?")
        # objects
        if item.get("type") == WATER:
            room = self._room_at(item["x"], item["y"])
            where = room.get("category") if room else None
            line = WATER_LINES.get(where, PLAIN_WATER)[0]
        elif item.get("kind") == "door":
            line = "Door (%s side)" % SIDE_NAMES.get(item.get("side"), "?")
        elif item.get("type") == GOLD:
            worth = item.get("value") or 0
            line = "%s - %s" % (item.get("text", GOLD),
                                "%d coins" % worth if worth else "amount unset")
        else:
            line = item.get("text", "something")
        if item.get("hidden"):
            line += " (hidden)"
        return line

    def _square_listing(self, tx, ty, chosen=None):
        """The square's layers, one per line, with a mark against the one
        that is selected."""
        lines = []
        for kind, item in self._tile_contents(tx, ty):
            here = chosen is not None and item is chosen
            lines.append(("> " if here else "   ") + self._one_line(kind, item))
        return lines

    def _terrain_at(self, tx, ty, type_name=None):
        """Ground covering on a tile - the topmost layer, or one kind of it."""
        best, best_rank = None, -1
        for obj in self.objects:
            if (obj["x"], obj["y"]) != (tx, ty):
                continue
            rank = terrain_rank(obj)
            if not rank:
                continue
            if type_name is not None:
                if obj.get("type") == type_name:
                    return obj
                continue
            if rank >= best_rank:       # later of equal rank was painted on top
                best, best_rank = obj, rank
        return None if type_name is not None else best

    def _water_at(self, tx, ty):
        return self._terrain_at(tx, ty, WATER)

    def _spread(self, tx, ty, type_name):
        """Lay ground covering on a tile, unless that kind is already there.

        Different kinds stack happily - grass growing out of shallow water is
        the whole point of giving terrain layers.
        """
        if self._terrain_at(tx, ty, type_name) is not None:
            return False
        self.objects.append({"id": self.new_id(), "kind": "object",
                             "type": type_name, "text": type_name,
                             "side": "n", "x": tx, "y": ty})
        return True

    def _erase_at(self, tx, ty):
        target = self._erase_target(tx, ty)
        if target is None:
            self.status.config(text="nothing on that tile")
            return
        kind, item = target
        self._push_undo()
        {"token": self.tokens, "object": self.objects, "note": self.notes,
         "wall": self.walls, "room": self.rooms}[kind].remove(item)
        self._drop_from_selection(item)
        self._render()
        self._draw_ghost(tx, ty)
        self.save()
        name = item.get("name") or item.get("code") or item.get("text") or kind
        self.status.config(text="removed %s" % name)

    def _delete_selected(self, _event=None):
        things = self._selected_things()
        if not things or self.mode == "player":
            return
        self._push_undo()
        pools = self._pools()
        for kind, item in things:
            pool = pools.get(kind)
            if pool is not None and item in pool:
                pool.remove(item)
        self._clear_selection()
        self._render()
        self.save()
        if len(things) > 1:
            self.status.config(text="%d removed" % len(things))

    # -- placing things ----------------------------------------------------
    def _place_room(self, tx, ty):
        if not self._fits(self.armed, tx, ty, self.turns):
            self.status.config(text="that will not fit there")
            return
        self._push_undo()
        room = {"id": self.new_id(), "code": self.armed, "x": tx, "y": ty,
                "turns": self.turns, "category": category_of(self.armed),
                "revealed": False, "locked": False, "contents": [], "notes": []}
        self.rooms.append(room)
        self._select_only("room", room)
        self._render()
        self.save()

    def _place_token(self, tx, ty, name, kind="creature", span=None):
        wide, tall = span or self.token_span
        if not self._span_clear(tx, ty, wide, tall):
            self.status.config(
                text="no room for a %s figure there" % span_label(wide, tall)
                if (wide, tall) != (1, 1)
                else "a creature is already on that tile")
            return
        self._push_undo()
        token = {"id": self.new_id(), "name": name, "x": tx, "y": ty,
                 "w": wide, "h": tall,
                 "kind": kind, "hidden": False, "defeated": False, "notes": ""}
        self.tokens.append(token)
        self._select_only("token", token)
        self._render()
        self.save()

    def _place_object(self, tx, ty, kind, name=None):
        type_name = None
        if kind == "door":
            label = name or self.door_type
            if label not in DOOR_SHADE:
                label = DOOR_TYPES[0]
            type_name = label
        else:
            label = name or self.object_type
            if label == CUSTOM_OBJECT:
                label = simpledialog.askstring("Object", "What is it?",
                                               parent=self.win)
                if not label:
                    return
            if label in OBJECTS:
                type_name = label
        # Ask before anything is committed, so backing out of the window
        # leaves no half-placed pile and no undo step.
        coins = None
        if type_name == GOLD:
            coins = self._ask_coin_amount(tx, ty)
            if coins is None:
                return
        self._push_undo()
        record = {"id": self.new_id(), "kind": kind, "x": tx, "y": ty,
                  "text": label, "side": SIDES[self.turns]}
        if type_name:
            record["type"] = type_name
        if coins is not None:
            record["value"] = coins
        self.objects.append(record)
        self._render()
        self.save()

    def _add_note(self, tx, ty):
        text = simpledialog.askstring("Note", "Note:", parent=self.win)
        if not text:
            return
        self._push_undo()
        self.notes.append({"id": self.new_id(), "x": tx, "y": ty, "text": text})
        self._render()
        self.save()

    def _free_tiles(self, room, avoid_objects=False):
        taken = {(t["x"], t["y"]) for t in self.tokens}
        if avoid_objects:
            taken |= {(o["x"], o["y"]) for o in self.objects}
        return [tile for tile in self.room_tiles(room) if tile not in taken]

    def _terrain_on(self, tx, ty):
        """The ground covering on this square, if any."""
        return [o for o in self.objects
                if terrain_rank(o) and (o["x"], o["y"]) == (tx, ty)]

    def _pit_on(self, tx, ty):
        return any(o.get("type") == PIT for o in self._terrain_on(tx, ty))

    def _spawn_tiles(self, room, sort):
        """Squares a newly rolled thing of this sort could go on.

        Ground covering does not go down on top of ground covering - one
        layer of floor is enough. Everything else may lie on water, grass or
        moss, but never over a pit: there is nothing there to lie on.
        """
        taken = set()
        for token in self.tokens:
            taken.update(tiles_of(token))
        loose = {(o["x"], o["y"]) for o in self.objects
                 if o.get("kind") != "door" and not terrain_rank(o)}
        out = []
        for tile in self.room_tiles(room):
            if tile in taken:
                continue
            if sort == "ground":
                # Somewhere with no covering yet, and nothing standing on it
                # that a pit would swallow.
                if self._terrain_on(*tile) or tile in loose:
                    continue
            else:
                if tile in loose or self._pit_on(*tile):
                    continue
            out.append(tile)
        return out

    def _objects_in(self, room):
        """Loot standing in the room. Doors sit on its edges, not in it."""
        tiles = set(self.room_tiles(room))
        return [o for o in self.objects
                if o.get("kind") != "door" and (o["x"], o["y"]) in tiles]

    # -- right-click menus -------------------------------------------------
    def _right_click(self, event):
        tx, ty = self._tile_at(event)
        if self.mode == "player":
            menu = self._player_menu_at(tx, ty)
            self._add_ping(menu, tx, ty)
            menu.tk_popup(event.x_root, event.y_root)
            return
        # Nearest layer first, the same order Select and Erase use, so what
        # you click is what you get. Rooms come last: they are underneath
        # everything, and an object standing in one used to be unreachable.
        self.last_tile = (tx, ty)
        menu = None
        hit = self._thing_at(tx, ty)
        if (hit is not None and len(self.selection) > 1
                and self._is_selected(hit[1])):
            # Clicked one of a group: treat the whole group as the subject
            # rather than throwing the selection away.
            self._render()
            menu = self._group_menu()
        elif hit is not None:
            kind, found = hit
            self._select_only(kind, found)
            self._render()
            menu = {"token": self._token_menu,
                    "object": lambda o: self._object_menu(o, tx, ty),
                    "note": lambda n: self._note_menu(n, tx, ty),
                    "room": self._room_menu}[kind](found)
        if menu is None:
            self._clear_selection()
            self._render()
            menu = self._empty_menu(tx, ty)
        # A wall belongs to a tile edge, so it never gets to be the headline
        # act - but it still has to be reachable from the tile it sits on.
        wall = self._wall_at(tx, ty)
        if wall is not None:
            side = SIDE_NAMES.get(wall["side"], wall["side"])
            menu.add_separator()
            menu.add_command(
                label=("Unhide Wall (%s side)" if wall.get("hidden")
                       else "Hide Wall (%s side)") % side,
                command=lambda w=wall: self._toggle_flag(w, "hidden"))
            menu.add_command(label="Remove Wall (%s side)" % side,
                             command=lambda w=wall: self._remove_wall(w))
        self._add_ping(menu, tx, ty)
        menu.tk_popup(event.x_root, event.y_root)

    def _add_ping(self, menu, tx, ty):
        """Last entry on every menu, whoever is looking at the map."""
        menu.add_separator()
        menu.add_command(label="Ping", command=lambda: self._ping(tx, ty))

    # -- acting on a whole selection ---------------------------------------
    def _group_menu(self):
        things = self._selected_things()
        counts = {}
        for kind, _item in things:
            counts[kind] = counts.get(kind, 0) + 1
        menu = self._menu()
        menu.add_command(label=self._group_label(counts), state="disabled")
        menu.add_separator()
        menu.add_command(label="Hide All", command=lambda: self._group_hide(True))
        menu.add_command(label="Show All", command=lambda: self._group_hide(False))
        if counts.get("room"):
            menu.add_separator()
            menu.add_command(label="Lock All",
                             command=lambda: self._group_set("locked", True))
            menu.add_command(label="Unlock All",
                             command=lambda: self._group_set("locked", False))
        menu.add_separator()
        menu.add_command(label="Remove All", command=self._group_remove)
        return menu

    def _group_label(self, counts):
        if len(counts) == 1:
            kind, number = list(counts.items())[0]
            word = {"token": "creature", "object": "object", "note": "note",
                    "wall": "wall", "room": "room"}[kind]
            return "%d %s%s selected" % (number, word, "" if number == 1 else "s")
        return "%d things selected" % sum(counts.values())

    def _group_hide(self, hide):
        """One idea, two flags: a room goes dark by being unrevealed, while
        everything else has a hidden flag of its own."""
        things = self._selected_things()
        if not things:
            return
        self._push_undo()
        for kind, item in things:
            if kind == "room":
                self._set_revealed(item, not hide)
            else:
                item["hidden"] = hide
        self._render()
        self.save()
        self.status.config(text="%d %s" % (len(things),
                                           "hidden" if hide else "shown"))

    def _group_set(self, flag, value):
        things = [(k, i) for k, i in self._selected_things() if k == "room"]
        if not things:
            return
        self._push_undo()
        for _kind, item in things:
            item[flag] = value
        self._render()
        self.save()
        self.status.config(text="%d room%s %s%s"
                                % (len(things), "" if len(things) == 1 else "s",
                                   "" if value else "un", flag))

    def _group_remove(self):
        things = self._selected_things()
        if not things:
            return
        if not messagebox.askyesno(
                "Remove", "Take %d things off the map?" % len(things),
                parent=self.win, icon="warning"):
            return
        self._push_undo()
        pools = self._pools()
        for kind, item in things:
            pool = pools.get(kind)
            if pool is not None and item in pool:
                pool.remove(item)
        self._clear_selection()
        self._render()
        self.save()
        self.status.config(text="%d removed" % len(things))

    def _player_menu_at(self, tx, ty):
        """One menu for the table: act with your own figures, look at anything
        else you can see."""
        kind, item = self._player_target(tx, ty)
        token = item if kind == "token" else None
        if token is not None and token.get("kind") == "player":
            self._select_only("token", token)
            self._render()
            if not self._is_mine(token):
                # Somebody else's figure, or one going spare. Either way it
                # is not theirs to move, so the menu is a short one.
                menu = self._menu()
                if self._unclaimed(token):
                    menu.add_command(
                        label="This is my character",
                        command=lambda: self._claim_token(token))
                    menu.add_separator()
                self._add_inspect_items(menu, tx, ty)
                self._add_door_actions(
                    menu, [d for d in self._doors_touching(tx, ty)
                           if self._visible_object(d)])
                return menu
            menu = self._player_menu(token)
            # Standing on the doorway is the most likely place to be when
            # you want to open it, so the entry belongs on this menu too.
            self._add_door_actions(menu, [d for d in self._doors_touching(tx, ty)
                                          if self._visible_object(d)])
            return menu
        menu = self._menu()
        self._add_inspect_items(menu, tx, ty)
        self._add_square_actions(menu, tx, ty)
        return menu

    def _add_square_actions(self, menu, tx, ty):
        """Open and Take for every object on the square that allows it.

        Offering them only for whatever is on top meant a coin lying in
        water could be looked at but never picked up.
        """
        here = [i for k, i in self._tile_contents(tx, ty)
                if k == "object" and i.get("kind") != "door"
                and self._player_can_see(k, i)]
        # A door is a thing you open with your hands, so the party gets the
        # same entry the GM does.
        self._add_door_actions(menu, [d for d in self._doors_touching(tx, ty)
                                      if self._visible_object(d)])
        chests = [o for o in here if o.get("type") == "Chest"]
        loot = [o for o in here
                if o.get("type") is None or o.get("type") in LOOT_TYPES]
        if not chests and not loot:
            return
        menu.add_separator()
        for obj in chests:
            self._add_open(menu, obj,
                           None if len(chests) == 1 else obj.get("text"))
        for obj in loot:
            self._add_take(menu, obj,
                           None if len(loot) == 1 else obj.get("text"))

    def _add_inspect_items(self, menu, tx, ty):
        """One Inspect entry per thing the party can see on this square, so
        they choose what they are looking at rather than being handed
        whatever happens to be on top."""
        layers = [(k, i) for k, i in self._tile_contents(tx, ty)
                  if self._player_can_see(k, i)]
        if not layers:
            menu.add_command(label="Inspect",
                             command=lambda: self._inspect(None, None))
            return
        for kind, item in layers:
            menu.add_command(
                label="Inspect %s" % self._short_name(kind, item),
                command=lambda k=kind, i=item: self._inspect(k, i))

    def _player_menu(self, token):
        menu = self._menu()
        if self.moving is token:
            menu.add_command(label="Cancel Move", command=self._cancel)
        else:
            menu.add_command(label="Move",
                             command=lambda: self._begin_move(token))
        if self.attacking is token:
            menu.add_command(label="Cancel Attack", command=self._cancel)
        else:
            menu.add_command(label="Attack",
                             command=lambda: self._begin_attack(token))
        menu.add_cascade(label="Colour", menu=self._colour_menu(token))
        self._add_portrait_items(menu, token)
        menu.add_separator()
        self._add_inspect_items(menu, token["x"], token["y"])
        return menu

    def _empty_menu(self, tx, ty):
        menu = self._menu()
        rooms = self._menu()
        for name in CATEGORIES:
            entries = BLUEPRINTS.get(name, [])
            sub = self._menu()
            if not entries:
                sub.add_command(label="(nothing yet)", state="disabled")
            for spec in entries:
                sub.add_command(
                    label="%s  %s" % (spec["code"], spec["name"]),
                    command=lambda c=spec["code"], x=tx, y=ty:
                        self._menu_place_room(c, x, y))
            rooms.add_cascade(label=name, menu=sub)
        menu.add_cascade(label="Place Room", menu=rooms)
        menu.add_command(label="Place Creature",
                         command=lambda: self._menu_place_creature(tx, ty))
        menu.add_command(label="Place Player",
                         command=lambda: self._menu_place_creature(tx, ty,
                                                                   "player"))
        objects = self._menu()
        self._fill_choices(
            objects, self._object_choices(),
            lambda n: self._place_object(tx, ty, "object", n))
        menu.add_cascade(label="Place Object", menu=objects)
        snares = self._menu()
        for name in TRAP_TYPES:
            snares.add_command(
                label=name,
                command=lambda n=name: self._place_object(tx, ty, "object", n))
        menu.add_cascade(label="Place Trap", menu=snares)
        menu.add_separator()
        menu.add_command(label="Add Wall",
                         command=lambda: self._menu_add_wall(tx, ty))
        menu.add_command(label="Add Stairs",
                         command=lambda: self._place_object(tx, ty, "object",
                                                            "Stairs"))
        menu.add_command(label="Add Door",
                         command=lambda: self._place_object(tx, ty, "door"))
        menu.add_command(label="Add Note",
                         command=lambda: self._add_note(tx, ty))
        return menu

    def _menu_place_room(self, code, tx, ty):
        self.armed = code
        self.turns = 0
        self._sync_room_cards()
        self._place_room(tx, ty)
        self._disarm()

    def _menu_place_creature(self, tx, ty, kind="creature"):
        title = "Player" if kind == "player" else "Creature"
        name = simpledialog.askstring(title, "Name:", parent=self.win)
        if name:
            self._place_token(tx, ty, name, kind)

    def _menu_add_wall(self, tx, ty):
        self._push_undo()
        self.walls.append({"id": self.new_id(), "x": tx, "y": ty,
                           "side": SIDES[self.turns]})
        self._render()
        self.save()

    def _token_menu(self, token):
        menu = self._menu()
        menu.add_command(label="Move", command=lambda: self._begin_move(token))
        menu.add_command(label="Attack",
                         command=lambda: self._begin_attack(token))
        menu.add_command(label="Duplicate",
                         command=lambda: self._duplicate(token))
        menu.add_separator()
        menu.add_command(label="Unhide" if token.get("hidden") else "Hide",
                         command=lambda: self._toggle_flag(token, "hidden"))
        menu.add_command(
            label="Unmark Defeated" if token.get("defeated") else "Mark Defeated",
            command=lambda: self._toggle_flag(token, "defeated"))
        menu.add_command(label="View Stat Block",
                         command=lambda: self._stat_block(token))
        menu.add_command(label="Character Stats...",
                         command=lambda: self._stats_window(token))
        menu.add_cascade(label="Size", menu=self._size_menu(token, self._menu()))
        menu.add_command(label="Turn", command=lambda: self._turn_token(token))
        if token.get("kind") == "player":
            menu.add_cascade(label="Colour", menu=self._colour_menu(token))
            owner = self._owner_of(token)
            belongs = self._menu()
            for player in self.players:
                belongs.add_command(
                    label=("* " if player is owner else "   ") + player["name"],
                    command=lambda p=player: self._assign_token(token, p))
            if not self.players:
                belongs.add_command(label="(no players yet)", state="disabled")
            belongs.add_separator()
            belongs.add_command(label="Nobody",
                                command=lambda: self._assign_token(token, None))
            menu.add_cascade(label="Belongs To", menu=belongs)
        self._add_portrait_items(menu, token)
        menu.add_separator()
        menu.add_command(label="Remove", command=lambda: self._remove(token))
        return menu

    # -- carrying things ----------------------------------------------------
    def _coin_band(self, tx, ty):
        """What a pile lying here could be worth, given the region."""
        room = self._room_at(tx, ty)
        where = room.get("category") if room else self.category
        rate = WEALTH.get(where, 1)
        low, high = COIN_RANGE
        return low * rate, high * rate

    def _coin_value(self, tx, ty):
        """Rolled against wherever the pile is lying."""
        return rng.randint(*self._coin_band(tx, ty))

    def _ask_coin_amount(self, tx, ty):
        """How big a pile to put down. Blank rolls one for the region.

        Returns the number of coins, or None if they backed out - which is
        why the dialog has to say whether OK was pressed as well as what was
        in the box.
        """
        low, high = self._coin_band(tx, ty)
        dialog = AmountDialog(
            self, "Gold Coins", "How many coins?", None, 1, 999999,
            allow_blank=True,
            note="leave it blank for a random pile (%d-%d here)" % (low, high))
        self._wait_for(dialog)
        if not dialog.accepted:
            return None
        if dialog.value is None:
            return self._coin_value(tx, ty)
        return dialog.value

    def _wait_for(self, dialog):
        """Block until the window goes. It may already have, if something
        closed it before we got here."""
        try:
            self.win.wait_window(dialog.win)
        except tk.TclError:
            pass

    def _ask_amount(self, title, prompt, start, low, high):
        dialog = AmountDialog(self, title, prompt, start, low, high)
        self._wait_for(dialog)
        return dialog.value

    def _set_coin_value(self, obj):
        amount = self._ask_amount("Gold Coins", "How many coins in this pile?",
                                  obj.get("value", 0), 0, 999999)
        if amount is None:
            return
        self._push_undo()
        obj["value"] = amount
        self._render()
        self.save()
        self.status.config(text="that pile is worth %d gold" % amount)

    def _split_purse(self, token, index):
        items = token.get("items") or []
        if not 0 <= index < len(items):
            return
        entry = items[index]
        total = entry.get("value") or 0
        if total < 2:
            self.status.config(text="not enough there to split")
            return
        amount = self._ask_amount("Split", "How many coins to put down?",
                                  total // 2, 1, total - 1)
        if amount is None:
            return
        # The dialog already keeps this in range, but the rule that a purse
        # never splits down to nothing belongs here, not in a window.
        amount = max(1, min(int(amount), total - 1))
        self._push_undo()
        entry["value"] = total - amount
        # Both halves stay in the bag. Getting one onto the floor - to hand it
        # to somebody else - is what Put Down is for.
        items.insert(index + 1, {"text": GOLD, "type": GOLD, "count": 1,
                                 "value": amount})
        self._render()
        self.save()
        self.status.config(text="%s split %d gold off, keeping %d"
                                % (token["name"], amount, entry["value"]))

    def _add_open(self, menu, obj, name=None):
        if obj.get("type") == "Chest":
            menu.add_command(label="Open" if name is None else "Open %s" % name,
                             command=lambda: self._open_chest(obj))

    def _open_chest(self, obj):
        """The chest goes, and whatever was in it is left standing there."""
        self._push_undo()
        where = (obj["x"], obj["y"])
        hidden = bool(obj.get("hidden"))
        if obj in self.objects:
            self.objects.remove(obj)
        self._drop_from_selection(obj)
        name = rng.choice(CHEST_CONTENTS)
        found = {"id": self.new_id(), "kind": "object", "type": name,
                 "text": name, "x": where[0], "y": where[1], "side": "n"}
        if name == GOLD:
            found["value"] = self._coin_value(*where)
        if hidden:
            found["hidden"] = True      # a chest nobody could see stays secret
        self.objects.append(found)
        self._render()
        self.save()
        self.status.config(text="the chest held %s" % name)

    def _add_take(self, menu, obj, name=None):
        """Take goes to a figure. With one on the map that is unambiguous;
        with several the player has to say who is reaching for it.

        Only loot can be picked up - a staircase, a trap and a puddle stay
        where they are.
        """
        kind = obj.get("type")
        if kind is not None and kind not in LOOT_TYPES:
            return
        figures = self._players_on_map()
        if not figures:
            return
        label = "Take" if name is None else "Take %s" % name
        if len(figures) == 1:
            menu.add_command(label=label,
                             command=lambda: self._take(obj, figures[0]))
            return
        into = self._menu()
        for token in figures:
            into.add_command(label=token["name"],
                             command=lambda t=token: self._take(obj, t))
        menu.add_cascade(label=label, menu=into)

    def _players_on_map(self):
        return [t for t in self.tokens if t.get("kind") == "player"]

    def _take(self, obj, token):
        self._push_undo()
        if obj in self.objects:
            self.objects.remove(obj)
        self._drop_from_selection(obj)
        entry = self._stow(token, obj.get("text", "Something"),
                           obj.get("type"), obj.get("value"))
        self._render()
        self.save()
        self.status.config(text="%s took %s" % (token["name"],
                                                self._carried_label(entry)))

    def _stow(self, token, text, type_name, value=None):
        """Add to the bag, merging with what is already in it.

        Gold merges by what it is worth rather than by how many piles it came
        from - three separate handfuls are just one heavier purse.
        """
        items = token.setdefault("items", [])
        for entry in items:
            if entry["text"] == text and entry.get("type") == type_name:
                if type_name == GOLD:
                    entry["value"] = entry.get("value", 0) + (value or 0)
                else:
                    entry["count"] = entry.get("count", 1) + 1
                return entry
        entry = {"text": text, "type": type_name, "count": 1}
        if type_name == GOLD:
            entry["value"] = value or 0
        items.append(entry)
        return entry

    def _carried_label(self, entry):
        """How one bag entry reads: a purse by its worth, anything else by
        its name and how many of it there are."""
        if entry.get("type") == GOLD:
            # A purse saved before coins had a worth has nothing to show, and
            # "0 gold" would be a lie rather than a blank.
            worth = entry.get("value") or 0
            return "%d gold" % worth if worth else entry["text"]
        count = entry.get("count", 1)
        return entry["text"] if count == 1 else "%s x%d" % (entry["text"], count)

    def _put_down(self, token, index):
        """Back onto the figure's own tile, where they are standing.

        One at a time out of a stack; gold goes down as the whole purse,
        since splitting a number of coins is a decision for the table.
        """
        items = token.get("items") or []
        if not 0 <= index < len(items):
            return
        self._push_undo()
        item = items[index]
        record = {"id": self.new_id(), "kind": "object", "x": token["x"],
                  "y": token["y"], "text": item["text"], "side": "n"}
        if item.get("type"):
            record["type"] = item["type"]
        if item.get("type") == GOLD:
            record["value"] = item.get("value", 0)
            items.pop(index)
            dropped = "%d gold" % record["value"]
        else:
            left = item.get("count", 1) - 1
            if left <= 0:
                items.pop(index)
            else:
                item["count"] = left
            dropped = item["text"]
        self.objects.append(record)
        self._render()
        self.save()
        self.status.config(text="%s put down %s" % (token["name"], dropped))

    def _carrier(self):
        """Whose bag the panel is showing: the selected figure, or the only
        one there is anywhere."""
        for kind, item in self._selected_things():
            if kind == "token" and item.get("kind") == "player":
                return item
        everywhere = [t for _level, t in self._all_levels("tokens")
                      if t.get("kind") == "player"]
        return everywhere[0] if len(everywhere) == 1 else None

    def _build_inventory(self, column):
        self.inventory = tk.Frame(column, bg=self.t["panel"])
        tk.Frame(self.inventory, bg=self.t["bg"], height=1).pack(fill="x",
                                                                 pady=(0, 6))
        # Stats and the bag scroll together in one strip. Separately, a short
        # window cut the bottom off the bag with no way to reach it; this way
        # the panel asks for a fixed height and what does not fit scrolls,
        # by the bar at the side or by the wheel.
        self.panel_body = self._scroll_list(self.inventory,
                                            height=PANEL_HEIGHT)
        # Stats first: they are what gets looked at most often, and nobody
        # should have to open a window to read their own hit points.
        self.stats_heading = self._heading(self.panel_body, "STATS")
        self.stats_heading.pack(fill="x")
        self.stats_strip = tk.Frame(self.panel_body, bg=self.t["panel"])
        self.stats_strip.pack(fill="x", pady=(2, 8))
        self.inventory_heading = self._heading(self.panel_body, "CARRYING")
        self.inventory_heading.pack(fill="x")
        self.inventory_grid = tk.Frame(self.panel_body, bg=self.t["panel"])
        self.inventory_grid.pack(fill="x")

    def _fill_stats(self):
        """The selected figure's stats, laid out two to a line.

        Clickable, so a player can keep their own hit points up to date
        without going through the GM.
        """
        strip = getattr(self, "stats_strip", None)
        if strip is None or not strip.winfo_exists():
            return
        for child in strip.winfo_children():
            child.destroy()
        token = self._carrier()
        if token is None:
            self.stats_heading.config(text="STATS")
            tk.Label(strip, text="no figure picked", font=self.f["label"],
                     bg=self.t["panel"], fg=self.t["muted"],
                     anchor="w").pack(fill="x")
            return
        self.stats_heading.config(text="%s" % token["name"].upper())
        # The bare strip takes a right-click too, so a stat can be added
        # without having to aim at an existing one.
        strip.bind("<Button-3>", lambda e: self._blank_stat_menu(token, e))
        grid = tk.Frame(strip, bg=self.t["panel"])
        grid.pack(fill="x")
        grid.bind("<Button-3>", lambda e: self._blank_stat_menu(token, e))
        for index, (name, value) in enumerate(stats_of(token)):
            self._stat_chip(grid, token, name, value, index)
        grid.columnconfigure(0, weight=1)
        grid.columnconfigure(1, weight=1)

    def _stat_chip(self, grid, token, name, value, index):
        cell = tk.Frame(grid, bg=self.t["bg"], cursor="hand2")
        cell.grid(row=index // 2, column=index % 2, sticky="ew", padx=1,
                  pady=1)
        label = tk.Label(cell, text=name, font=self.f["label"],
                         bg=self.t["bg"], fg=self.t["muted"], anchor="w",
                         padx=6, cursor="hand2")
        label.pack(side="left")
        number = tk.Label(cell, text=str(value), font=self.f["label"],
                          bg=self.t["bg"], fg=self.t["fg"], anchor="e",
                          padx=6, cursor="hand2")
        number.pack(side="right")
        parts = (cell, label, number)
        for widget in parts:
            widget.bind("<Button-1>",
                        lambda _e, n=name: self._edit_stat(token, n))
            widget.bind("<Button-3>",
                        lambda e, n=name: self._stat_menu(token, n, e))
            widget.bind("<Enter>", lambda _e: [p.configure(bg=self.t["panel"])
                                               for p in parts])
            widget.bind("<Leave>", lambda _e: [p.configure(bg=self.t["bg"])
                                               for p in parts])

    def _stat_menu(self, token, name, event):
        """Right-clicking a stat: change it, or take it off."""
        menu = self._menu()
        menu.add_command(label=name, state="disabled")
        menu.add_separator()
        menu.add_command(label="Change...",
                         command=lambda: self._edit_stat(token, name))
        if name in STAT_ORDER:
            menu.add_command(label="Remove", state="disabled")
        else:
            menu.add_command(label="Remove",
                             command=lambda: self._drop_stat(token, name))
        menu.add_separator()
        menu.add_command(label="Add New...",
                         command=lambda: self._add_stat_here(token))
        menu.tk_popup(event.x_root, event.y_root)

    def _blank_stat_menu(self, token, event):
        """Right-clicking the empty part of the strip: add one."""
        menu = self._menu()
        menu.add_command(label="Add New...",
                         command=lambda: self._add_stat_here(token))
        menu.tk_popup(event.x_root, event.y_root)

    def _add_stat_here(self, token):
        self._add_stat(token)
        self._fill_stats()

    def _drop_stat(self, token, name):
        self._remove_stat(token, name)
        self._fill_stats()
        self.status.config(text="%s: %s removed" % (token["name"], name))

    def _fill_inventory(self):
        if not hasattr(self, "inventory_grid"):
            return
        if not self.inventory_grid.winfo_exists():
            return
        for child in self.inventory_grid.winfo_children():
            child.destroy()
        token = self._carrier()
        if token is None:
            self.inventory_heading.config(text="CARRYING")
            tk.Label(self.inventory_grid, text="pick one of your figures",
                     font=self.f["label"], bg=self.t["panel"],
                     fg=self.t["muted"], anchor="w").pack(fill="x", pady=4)
            return
        items = token.get("items") or []
        self.inventory_heading.config(text="%s IS CARRYING" % token["name"].upper())
        if not items:
            tk.Label(self.inventory_grid, text="nothing yet",
                     font=self.f["label"], bg=self.t["panel"],
                     fg=self.t["muted"], anchor="w").pack(fill="x", pady=4)
            return
        grid = tk.Frame(self.inventory_grid, bg=self.t["panel"])
        grid.pack(anchor="w")
        for index, item in enumerate(items):
            self._inventory_cell(grid, token, index, item)

    def _inventory_cell(self, grid, token, index, item):
        cell = tk.Frame(grid, bg=self.t["bg"], cursor="hand2")
        cell.grid(row=index // INVENTORY_COLUMNS,
                  column=index % INVENTORY_COLUMNS, padx=2, pady=2)
        face = tk.Canvas(cell, width=INVENTORY_CELL, height=INVENTORY_CELL - 14,
                         bg=self.t["bg"], highlightthickness=0, bd=0,
                         cursor="hand2")
        face.pack()
        # The same silhouette the map draws, shrunk to fit the cell.
        self._paint_shape(face, item, INVENTORY_CELL // 2,
                          (INVENTORY_CELL - 14) // 2,
                          (INVENTORY_CELL - 16) / float(TILE), tags="icon")
        gold = item.get("type") == GOLD
        count = item.get("count", 1)
        if not gold and count > 1:
            # A count in the corner, rather than a cell per identical item.
            face.create_oval(INVENTORY_CELL - 18, 1, INVENTORY_CELL - 2, 17,
                             fill=self.t["accent"], outline=self.t["bg"],
                             width=1, tags="icon")
            face.create_text(INVENTORY_CELL - 10, 9, text=str(count),
                             fill=self.t["bg"], font=self.f["label"],
                             tags="icon")
        worth = item.get("value") or 0
        # An item made anywhere but the usual places may carry only its type.
        label = item.get("text") or item.get("type") or "?"
        shown = "%d gold" % worth if (gold and worth) else label[:9]
        name = tk.Label(cell, text=shown, font=self.f["label"],
                        bg=self.t["bg"],
                        fg=self.t["accent"] if gold else self.t["muted"],
                        cursor="hand2")
        name.pack()
        tip = "%s - right-click to put it down" % self._carried_label(item)
        for widget in (cell, face, name):
            widget.bind("<Button-1>",
                        lambda _e, t=tip: self.status.config(text=t))
            widget.bind("<Button-3>",
                        lambda e, i=index: self._item_menu(token, i).tk_popup(
                            e.x_root, e.y_root))

    def _item_menu(self, token, index):
        menu = self._menu()
        items = token.get("items") or []
        label = (self._carried_label(items[index]) if index < len(items)
                 else "item")
        menu.add_command(label=label, state="disabled")
        menu.add_separator()
        menu.add_command(label="Put Down",
                         command=lambda: self._put_down(token, index))
        if index < len(items) and items[index].get("type") == GOLD:
            menu.add_command(label="Split...",
                             command=lambda: self._split_purse(token, index))
        return menu

    # -- colouring a figure -------------------------------------------------
    def _colour_menu(self, token):
        """Four to hand, the rest a click away - picking a colour should not
        mean reading a list of sixteen names every time."""
        menu = self._menu()
        current = token.get("color")
        for name, code in TOKEN_COLOURS[:QUICK_COLOURS]:
            menu.add_command(label=("* " if code == current else "   ") + name,
                             background=code, foreground=self.t["bg"],
                             activebackground=code,
                             activeforeground=self.t["bg"],
                             command=lambda c=code: self._set_token_colour(token, c))
        menu.add_separator()
        menu.add_command(label="More Colours...",
                         command=lambda: self._more_colours(token))
        if current:
            menu.add_command(label="Default",
                             command=lambda: self._set_token_colour(token, None))
        return menu

    def _set_token_colour(self, token, code):
        self._push_undo()
        if code is None:
            token.pop("color", None)
        else:
            token["color"] = code
        self._render()
        self.save()
        name = dict((c, n) for n, c in TOKEN_COLOURS).get(code, "default")
        self.status.config(text="%s is %s" % (token["name"], name.lower()))

    def _more_colours(self, token):
        """All sixteen as swatches - easier to choose from than a list."""
        win = tk.Toplevel(self.win)
        win.title("Colour - %s" % token["name"])
        win.configure(bg=self.t["bg"])
        win.transient(self.win)
        win.resizable(False, False)
        pad = tk.Frame(win, bg=self.t["bg"])
        pad.pack(padx=14, pady=12)
        tk.Label(pad, text="pick a colour for %s" % token["name"],
                 font=self.f["label"], bg=self.t["bg"],
                 fg=self.t["muted"]).pack(anchor="w", pady=(0, 8))
        grid = tk.Frame(pad, bg=self.t["bg"])
        grid.pack()
        current = token.get("color")

        def choose(code):
            self._set_token_colour(token, code)
            win.destroy()

        for index, (name, code) in enumerate(TOKEN_COLOURS):
            cell = tk.Frame(grid, bg=code, width=44, height=44,
                            cursor="hand2", highlightthickness=3,
                            highlightbackground=self.t["fg"] if code == current
                            else self.t["bg"],
                            highlightcolor=self.t["fg"] if code == current
                            else self.t["bg"])
            cell.grid(row=index // 4, column=index % 4, padx=3, pady=3)
            cell.grid_propagate(False)
            cell.bind("<Button-1>", lambda _e, c=code: choose(c))
            label = tk.Label(cell, text=name, font=self.f["label"], bg=code,
                             fg=self.t["bg"], cursor="hand2")
            label.place(relx=0.5, rely=0.5, anchor="center")
            label.bind("<Button-1>", lambda _e, c=code: choose(c))

        row = tk.Frame(pad, bg=self.t["bg"])
        row.pack(fill="x", pady=(12, 0))
        tk.Button(row, text="Default", font=self.f["label"], bg=self.t["bg"],
                  fg=self.t["muted"], activebackground=self.t["panel"],
                  activeforeground=self.t["fg"], relief="flat", bd=0,
                  cursor="hand2",
                  command=lambda: choose(None)).pack(side="left")
        tk.Button(row, text="Cancel", font=self.f["label"], bg=self.t["bg"],
                  fg=self.t["muted"], activebackground=self.t["panel"],
                  activeforeground=self.t["fg"], relief="flat", bd=0,
                  cursor="hand2", command=win.destroy).pack(side="right")
        win.bind("<Escape>", lambda _e: win.destroy())
        return win

    def _add_portrait_items(self, menu, token):
        menu.add_separator()
        menu.add_command(
            label="Change Portrait..." if token.get("portrait")
            else "Add Portrait...",
            command=lambda: self._choose_portrait(token))
        if token.get("portrait"):
            menu.add_command(label="Remove Portrait",
                             command=lambda: self._clear_portrait(token))

    def _object_menu(self, obj, tx, ty):
        menu = self._menu()
        if obj.get("kind") == "door":
            menu.add_command(label="Close Door" if obj.get("open")
                             else "Open Door",
                             command=lambda: self._toggle_door(obj))
            menu.add_command(label="Turn Door",
                             command=lambda: self._turn_object(obj))
        else:
            swap = self._menu()
            self._fill_choices(swap, self._object_choices(),
                               lambda n: self._retype_object(obj, n))
            menu.add_cascade(label="Change To", menu=swap)
        menu.add_command(label="Duplicate",
                         command=lambda: self._duplicate_object(obj))
        if obj.get("type") == GOLD:
            menu.add_command(label="Change Value...",
                             command=lambda: self._set_coin_value(obj))
        if obj.get("kind") != "door":
            self._add_open(menu, obj)
            self._add_take(menu, obj)
        menu.add_command(label="Unhide" if obj.get("hidden") else "Hide",
                         command=lambda: self._toggle_flag(obj, "hidden"))
        menu.add_separator()
        menu.add_command(label="Remove",
                         command=lambda: self._remove_object(obj))
        self._add_room_cascade(menu, tx, ty)
        return menu

    def _note_menu(self, note, tx, ty):
        menu = self._menu()
        menu.add_command(label="Edit Note",
                         command=lambda: self._edit_note(note))
        menu.add_command(label="Remove Note",
                         command=lambda: self._remove_object(note))
        self._add_room_cascade(menu, tx, ty)
        return menu

    def _add_room_cascade(self, menu, tx, ty):
        """Keep the room's own actions reachable from something sitting on it."""
        room = self._room_at(tx, ty)
        if room is None:
            return
        menu.add_separator()
        menu.add_cascade(label="Room %s" % room["code"],
                         menu=self._room_menu(room))

    def _room_menu(self, room):
        menu = self._menu()
        # One roll per sort, each of them repeatable: keep going until
        # the room feels right rather than being told it is full.
        rolls = self._menu()
        rolls.add_command(label="Loot",
                          command=lambda: self._roll_loot(room))
        rolls.add_command(label="Traps",
                          command=lambda: self._roll_traps(room))
        rolls.add_command(label="Ground",
                          command=lambda: self._roll_ground(room))
        rolls.add_separator()
        rolls.add_command(label="Creatures",
                          command=lambda: self._generate_creatures(room))
        menu.add_cascade(label="Generate", menu=rolls)
        menu.add_separator()
        menu.add_command(label="Hide Room" if room.get("revealed") else "Reveal Room",
                         command=lambda: self._toggle_flag(room, "revealed"))
        menu.add_command(label="Edit Room", command=lambda: self._edit_room(room))
        add = self._menu()
        self._fill_choices(
            add, self._object_choices(),
            lambda n: self._place_object(room["x"], room["y"], "object", n))
        menu.add_cascade(label="Add Object", menu=add)
        menu.add_command(label="Add Note",
                         command=lambda: self._add_note(room["x"], room["y"]))
        if room.get("locked"):
            menu.add_command(label="Unlock Room",
                             command=lambda: self._set_lock(room, False))
        else:
            locks = self._menu()
            locks.add_command(label="Plain key",
                              command=lambda: self._set_lock(room, True))
            locks.add_separator()
            for colour in LOCK_COLOURS:
                locks.add_command(
                    label="%s key" % colour,
                    command=lambda c=colour: self._set_lock(room, True, c))
            menu.add_cascade(label="Lock Room", menu=locks)
        menu.add_separator()
        menu.add_command(label="Remove Room",
                         command=lambda: self._remove_room(room))
        return menu

    # -- what the menus do -------------------------------------------------
    def _set_revealed(self, room, shown):
        """Put a room on the party's map, or take it back off.

        Taking it off has to stick. The party may still be standing in it,
        or next door to it, and the sweep that lights up wherever they are
        would put it straight back - so it is sealed until they have gone
        away and come back.
        """
        room["revealed"] = bool(shown)
        if shown:
            room.pop("resealed", None)
        else:
            room["resealed"] = True

    def _toggle_flag(self, item, flag):
        self._push_undo()
        if flag == "revealed":
            self._set_revealed(item, not item.get("revealed"))
        else:
            item[flag] = not item.get(flag)
        self._render()
        self.save()

    def _begin_move(self, token):
        """Pick the figure up. Until it is put down a line runs from it to the
        cursor with the number of squares the move would cost."""
        self._cancel()
        self.moving = token
        self._select_only("token", token)
        self.canvas.config(cursor="fleur")
        self._clear_ghost()
        self._draw_move_preview(*self.hover)

    def _duplicate(self, token):
        """Drop a copy on the first free tile next to the original."""
        taken = {(t["x"], t["y"]) for t in self.tokens}
        for dx, dy in ((1, 0), (0, 1), (-1, 0), (0, -1),
                       (1, 1), (-1, 1), (1, -1), (-1, -1)):
            x, y = token["x"] + dx, token["y"] + dy
            if 0 <= x < MAP_W and 0 <= y < MAP_H and (x, y) not in taken:
                self._push_undo()
                copy = dict(token)
                copy["id"] = self.new_id()
                copy["x"], copy["y"] = x, y
                self.tokens.append(copy)
                self._select_only("token", copy)
                self._render()
                self.save()
                return
        self.status.config(text="no free tile beside that creature")

    def _pool_for(self, item):
        for pool in (self.objects, self.notes, self.walls):
            if item in pool:
                return pool
        return None

    def _remove_object(self, item):
        pool = self._pool_for(item)
        if pool is None:
            return
        self._push_undo()
        pool.remove(item)
        self._drop_from_selection(item)
        self._render()
        self.save()

    def _remove_wall(self, wall):
        self._remove_object(wall)
        self.status.config(text="wall removed")

    def _doors_touching(self, tx, ty):
        """Every door on this square, from either side of it.

        One edge has two names - the east side of a tile is the west side of
        its neighbour - so a door is reachable by right-clicking the square
        on either side of it, which is how anybody would expect to open one.
        """
        found = []
        for obj in self.objects:
            if obj.get("kind") != "door":
                continue
            side = obj.get("side", "n")
            if (obj["x"], obj["y"]) == (tx, ty):
                found.append(obj)
                continue
            dx, dy = STEP[side]
            if (obj["x"] + dx, obj["y"] + dy) == (tx, ty):
                found.append(obj)
        return found

    def _toggle_door(self, door):
        """Swing it open, or push it shut again."""
        self._push_undo()
        door["open"] = not door.get("open")
        self._sight_cache = None
        self._render()
        self.save()
        self.status.config(text="%s %s" % (door.get("text", "Door"),
                                           "opened" if door["open"]
                                           else "closed"))

    def _add_door_actions(self, menu, doors):
        """Open or Close, one entry per door on the square."""
        if not doors:
            return
        menu.add_separator()
        for door in doors:
            name = door.get("text", "Door")
            label = "Close %s" % name if door.get("open") else "Open %s" % name
            menu.add_command(label=label,
                             command=lambda d=door: self._toggle_door(d))

    def _turn_object(self, obj):
        self._push_undo()
        side = obj.get("side", "n")
        obj["side"] = SIDES[(SIDES.index(side) + 1) % 4]
        self._render()
        self.save()
        self.status.config(text="door now on the %s side"
                                % SIDE_NAMES[obj["side"]])

    def _retype_object(self, obj, name):
        if name == CUSTOM_OBJECT:
            name = simpledialog.askstring("Object", "What is it?",
                                          initialvalue=obj.get("text", ""),
                                          parent=self.win)
            if not name:
                return
        self._push_undo()
        obj["text"] = name
        if name in OBJECTS:
            obj["type"] = name
        else:
            obj.pop("type", None)
        self._render()
        self.save()

    def _duplicate_object(self, obj):
        taken = {(o["x"], o["y"]) for o in self.objects}
        for dx, dy in ((1, 0), (0, 1), (-1, 0), (0, -1),
                       (1, 1), (-1, 1), (1, -1), (-1, -1)):
            x, y = obj["x"] + dx, obj["y"] + dy
            if 0 <= x < MAP_W and 0 <= y < MAP_H and (x, y) not in taken:
                self._push_undo()
                copy = dict(obj)
                copy["id"] = self.new_id()
                copy["x"], copy["y"] = x, y
                self.objects.append(copy)
                self._select_only("object", copy)
                self._render()
                self.save()
                return
        self.status.config(text="no free tile beside that")

    def _edit_note(self, note):
        text = simpledialog.askstring("Note", "Note:",
                                      initialvalue=note.get("text", ""),
                                      parent=self.win)
        if text is None:
            return
        self._push_undo()
        note["text"] = text
        self._render()
        self.save()

    def _remove(self, token):
        self._push_undo()
        self.tokens.remove(token)
        self._clear_selection()
        self._render()
        self.save()

    def _set_lock(self, room, locked, colour=None):
        """Lock or unlock a room, and say which key it wants."""
        self._push_undo()
        room["locked"] = bool(locked)
        if locked and colour:
            room["lock_colour"] = colour
        else:
            room.pop("lock_colour", None)
        self._render()
        self.save()
        if not locked:
            self.status.config(text="%s unlocked" % room["code"])
        elif colour:
            self.status.config(text="%s locked - needs the %s key"
                                    % (room["code"], colour.lower()))
        else:
            self.status.config(text="%s locked - needs a plain key"
                                    % room["code"])

    def _remove_room(self, room):
        if not messagebox.askyesno(
                "Remove room", "Take %s off the map?" % room["code"],
                parent=self.win, icon="warning"):
            return
        self._push_undo()
        self.rooms.remove(room)
        self._clear_selection()
        self._render()
        self.save()

    def _stat_block(self, token):
        room = self._room_of(token)
        lines = [
            token["name"],
            "",
            "Tile      %d, %d" % (token["x"], token["y"]),
            "Room      %s" % (room["code"] if room else "-"),
            "State     %s" % ("defeated" if token.get("defeated") else "active"),
            "Visible   %s" % ("no" if token.get("hidden") else "yes"),
        ]
        owner = self._owner_of(token)
        if owner is not None:
            lines.append("Player    %s" % owner["name"])
        if token.get("notes"):
            lines += ["", token["notes"]]
        messagebox.showinfo("Stat Block", "\n".join(lines), parent=self.win)

    def _edit_room(self, room):
        spec = blueprint(room["code"]) or {}
        current = room.get("label", "")
        label = simpledialog.askstring(
            "Edit room", "Name for %s (%s):" % (room["code"],
                                                spec.get("name", "?")),
            initialvalue=current, parent=self.win)
        if label is None:
            return
        self._push_undo()
        room["label"] = label
        self._render()
        self.save()

    def _generate_creatures(self, room):
        """Roll a count inside the room's capacity and scatter them about.

        The room's size is the whole budget - a small room will never hold
        more than two, however many times this is run.
        """
        spec = blueprint(room["code"])
        if spec is None:
            return
        low, high = CAPACITY.get(spec["size"], (0, 0))
        already = len(self._tokens_in(room))
        room_for = high - already
        if room_for <= 0:
            self.status.config(text="%s is already at capacity (%d)"
                                    % (room["code"], high))
            return
        wanted = rng.randint(low, high) - already
        wanted = max(0, min(wanted, room_for))
        free = self._free_tiles(room)
        rng.shuffle(free)
        if wanted == 0 or not free:
            self.status.config(text="%s: nothing stirs" % room["code"])
            return
        self._push_undo()
        names = BESTIARY.get(room.get("category", "Sewer"), ["Creature"])
        for tile in free[:wanted]:
            self.tokens.append({"id": self.new_id(), "name": rng.choice(names),
                                "x": tile[0], "y": tile[1], "hidden": False,
                                "defeated": False, "notes": ""})
        self._render()
        self.save()
        self.status.config(text="%s: %d creature%s"
                                % (room["code"], wanted,
                                   "" if wanted == 1 else "s"))

    def _roll_loot(self, room):
        """One handful of loot. Roll again for another."""
        spec = blueprint(room["code"])
        if spec is None:
            return
        low, high = OBJECT_CAPACITY.get(spec.get("size", "small"), (0, 1))
        groups = loot_groups()
        chances = [(name, weight) for name, weight in LOOT_ODDS.items()
                   if groups.get(name)]

        def roll():
            group = weighted_pick(chances)
            return rng.choice(groups[group])

        self._scatter(room, "loot", rng.randint(low, high), roll,
                      "nothing worth taking here")

    def _roll_traps(self, room):
        """A trap or two, laid where somebody might step."""
        spec = blueprint(room["code"])
        if spec is None:
            return
        low, high = TRAP_SPREAD.get(spec.get("size", "small"), (0, 1))
        self._scatter(room, "trap", rng.randint(low, high),
                      lambda: rng.choice(TRAP_TYPES), "nothing rigged here")

    def _roll_ground(self, room):
        """Water, growth and holes, in whatever suits the region."""
        where = room.get("category", "Sewer")
        chances = ENVIRONMENT.get(where) or list(ENVIRONMENT.values())[0]
        chances = [(name, weight) for name, weight in chances
                   if name in OBJECTS]
        floor = len(self.room_tiles(room))
        most = max(1, int(floor * GROUND_SHARE))
        self._scatter(room, "ground", rng.randint(0, most),
                      lambda: weighted_pick(chances),
                      "the floor is bare here")

    def _scatter(self, room, sort, wanted, choose, nothing):
        """Put `wanted` newly rolled things about the room.

        Shared by all three rolls so they agree on what a free square is and
        on how the result is reported.
        """
        free = self._spawn_tiles(room, sort)
        rng.shuffle(free)
        if wanted <= 0 or not free:
            self.status.config(text="%s: %s" % (room["code"], nothing))
            return
        self._push_undo()
        placed = []
        for tile in free[:wanted]:
            name = choose()
            if name is None:
                continue
            record = {"id": self.new_id(), "kind": "object", "type": name,
                      "text": name, "side": "n", "x": tile[0], "y": tile[1]}
            if name == GOLD:
                record["value"] = self._coin_value(*tile)
            self.objects.append(record)
            placed.append(name)
        if not placed:
            self.status.config(text="%s: %s" % (room["code"], nothing))
            return
        self._render()
        self.save()
        self.status.config(text="%s: %s" % (room["code"],
                                            ", ".join(sorted(placed))))
        self.status.config(text="%s: %s" % (room["code"], ", ".join(placed)))


class AmountDialog:
    """Ask for a number, by nudging it or by typing it.

    Kept apart from the map so it can be driven straight in a test, and so
    the same window serves both "how much is this pile worth" and "how much
    of it are you putting down".
    """

    def __init__(self, game_map, title, prompt, start, low, high,
                 allow_blank=False, note=None):
        self.t = game_map.t
        self.f = game_map.f
        self.low, self.high = low, high
        self.allow_blank = allow_blank    # empty field means "you decide"
        self.note_text = note
        self.value = None                 # the number, or None for "you decide"
        self.accepted = False             # False means they backed out

        self.win = tk.Toplevel(game_map.win)
        self.win.title(title)
        self.win.configure(bg=self.t["bg"])
        self.win.transient(game_map.win)
        self.win.resizable(False, False)

        pad = tk.Frame(self.win, bg=self.t["bg"])
        pad.pack(padx=16, pady=14)
        tk.Label(pad, text=prompt, font=self.f["label"], bg=self.t["bg"],
                 fg=self.t["muted"]).pack(anchor="w", pady=(0, 8))

        row = tk.Frame(pad, bg=self.t["bg"])
        row.pack()
        self._step(row, "-10", -10).pack(side="left")
        self._step(row, "-1", -1).pack(side="left", padx=(4, 8))
        self.var = tk.StringVar(
            value="" if start is None else str(self._clamp(start)))
        self.entry = tk.Entry(row, textvariable=self.var, width=8,
                              font=self.f["total"], justify="center",
                              bg=self.t["panel"], fg=self.t["fg"],
                              insertbackground=self.t["fg"], relief="flat",
                              bd=0, highlightthickness=1,
                              highlightbackground=self.t["panel"],
                              highlightcolor=self.t["accent"])
        self.entry.pack(side="left", ipady=4)
        self._step(row, "+1", 1).pack(side="left", padx=(8, 4))
        self._step(row, "+10", 10).pack(side="left")

        self.note = tk.Label(pad, text=self._range_text(), font=self.f["label"],
                             bg=self.t["bg"], fg=self.t["muted"])
        self.note.pack(anchor="w", pady=(8, 0))

        buttons = tk.Frame(pad, bg=self.t["bg"])
        buttons.pack(fill="x", pady=(12, 0))
        tk.Button(buttons, text="OK", font=self.f["title"],
                  bg=self.t["accent"], fg=self.t["bg"],
                  activebackground=self.t["accent_hot"],
                  activeforeground=self.t["bg"], relief="flat", bd=0,
                  cursor="hand2", command=self._accept).pack(side="right",
                                                             ipadx=14, ipady=5)
        tk.Button(buttons, text="Cancel", font=self.f["label"],
                  bg=self.t["bg"], fg=self.t["muted"],
                  activebackground=self.t["panel"],
                  activeforeground=self.t["fg"], relief="flat", bd=0,
                  cursor="hand2",
                  command=self.win.destroy).pack(side="right", padx=(0, 10))

        self.win.bind("<Return>", lambda _e: self._accept())
        self.win.bind("<Escape>", lambda _e: self.win.destroy())
        self.win.after(10, self.entry.focus_set)
        self.win.after(10, self.entry.select_range, 0, "end")

    def _range_text(self):
        if self.note_text:
            return self.note_text
        return "anything from %d to %d" % (self.low, self.high)

    def _step(self, parent, text, delta):
        return tk.Button(parent, text=text, font=self.f["label"], width=4,
                         bg=self.t["panel"], fg=self.t["fg"],
                         activebackground=self.t["accent"],
                         activeforeground=self.t["bg"], relief="flat", bd=0,
                         cursor="hand2",
                         command=lambda: self._nudge(delta))

    def _clamp(self, number):
        return max(self.low, min(self.high, int(number)))

    def _current(self):
        """Whatever is typed, made sense of.

        With an empty field allowed, blank - and anything unreadable - means
        "no number given"; otherwise it falls back to the bottom of the range.
        """
        typed = str(self.var.get()).strip()
        if not typed:
            return None if self.allow_blank else self.low
        try:
            return self._clamp(int(typed))
        except ValueError:
            return None if self.allow_blank else self.low

    def _nudge(self, delta):
        """From an empty box, count from nothing - pressing +10 should read
        10, not the minimum plus ten."""
        start = self._current()
        self.var.set(str(self._clamp((0 if start is None else start) + delta)))

    def _accept(self):
        self.value = self._current()
        self.accepted = True
        self.win.destroy()


class PortraitDialog(crop.CropDialog):
    """Frame an image before it becomes a token.

    The window itself is the shared one - the same as the profile picture
    uses. All this adds is which token the result belongs to.
    """

    def __init__(self, game_map, token, path):
        self.map = game_map
        self.token = token
        super().__init__(game_map.win, path,
                         title="Portrait - %s" % token["name"],
                         theme=game_map.t, fonts=game_map.f,
                         on_accept=lambda picture:
                             game_map._apply_portrait(token, picture),
                         preview=PORTRAIT_PREVIEW, store=PORTRAIT_STORE)


class AttackDialog:
    """Roll an attack of one creature against another.

    Deliberately the same shape as the main roller: pick dice, set a modifier,
    roll, read the individual dice and the total. The result is pushed through
    api.present() as well, so it lands in Roll History with everything else.
    """

    def __init__(self, game_map, attacker, target):
        self.map = game_map
        self.api = game_map.api
        self.t = game_map.t
        self.f = game_map.f
        self.attacker = attacker
        self.target = target
        self.log = []

        self.win = tk.Toplevel(game_map.win)
        self.win.title("Attack")
        self.win.configure(bg=self.t["bg"])
        self.win.transient(game_map.win)
        self.win.resizable(False, False)
        self._build()
        self.win.bind("<Return>", lambda _e: self.roll())
        self.win.bind("<Escape>", lambda _e: self.win.destroy())
        self.win.after(10, self.roll_button.focus_set)

    # -- layout ------------------------------------------------------------
    def _dice_keys(self):
        """Every die the app knows about, mod-added ones included."""
        dice = dict(self.api.dice)
        return [key for key, _die in sorted(dice.items(),
                                            key=lambda kv: (kv[1].sides, kv[0]))]

    def _build(self):
        pad = tk.Frame(self.win, bg=self.t["bg"])
        pad.pack(padx=16, pady=14)

        tk.Label(pad, text="%s  →  %s" % (self.attacker["name"],
                                               self.target["name"]),
                 font=self.f["title"], bg=self.t["bg"],
                 fg=self.t["fg"]).pack(anchor="w")
        reach = steps_between(self.attacker["x"], self.attacker["y"],
                              self.target["x"], self.target["y"])
        tk.Label(pad, text="%d square%s away" % (reach, "" if reach == 1 else "s"),
                 font=self.f["label"], bg=self.t["bg"],
                 fg=self.t["muted"]).pack(anchor="w", pady=(0, 12))

        # -- dice
        tk.Label(pad, text="DICE", font=self.f["label"], bg=self.t["bg"],
                 fg=self.t["muted"], anchor="w").pack(fill="x")
        dice_row = tk.Frame(pad, bg=self.t["bg"])
        dice_row.pack(fill="x", pady=(2, 12))

        self.count_var = tk.IntVar(value=self.map.attack_count)
        count = tk.Spinbox(dice_row, from_=1, to=20, width=3,
                           textvariable=self.count_var, font=self.f["die"],
                           bg=self.t["panel"], fg=self.t["fg"],
                           buttonbackground=self.t["panel"],
                           insertbackground=self.t["fg"], relief="flat", bd=0,
                           highlightthickness=1,
                           highlightbackground=self.t["panel"],
                           justify="center")
        count.pack(side="left", ipady=3)

        keys = self._dice_keys() or ["d20"]
        start = self.map.attack_die if self.map.attack_die in keys else keys[0]
        self.die_var = tk.StringVar(value=start)
        picker = tk.OptionMenu(dice_row, self.die_var, *keys)
        picker.config(font=self.f["die"], bg=self.t["panel"], fg=self.t["fg"],
                      activebackground=self.t["accent"],
                      activeforeground=self.t["bg"], relief="flat", bd=0,
                      highlightthickness=0, width=6, cursor="hand2")
        picker["menu"].config(bg=self.t["panel"], fg=self.t["fg"],
                              activebackground=self.t["accent"],
                              activeforeground=self.t["bg"],
                              font=self.f["label"], bd=0)
        picker.pack(side="left", padx=(6, 0))

        # -- modifier
        tk.Label(pad, text="MODIFIER", font=self.f["label"], bg=self.t["bg"],
                 fg=self.t["muted"], anchor="w").pack(fill="x")
        mod_row = tk.Frame(pad, bg=self.t["bg"])
        mod_row.pack(fill="x", pady=(2, 14))
        self.mod_var = tk.IntVar(value=self.map.attack_mod)
        self._step_button(mod_row, "−", -1).pack(side="left")
        self.mod_label = tk.Label(mod_row, text="", font=self.f["die"],
                                  bg=self.t["panel"], fg=self.t["accent"],
                                  width=6)
        self.mod_label.pack(side="left", padx=6, ipady=4)
        self._step_button(mod_row, "+", 1).pack(side="left")
        self._sync_mod()

        self.roll_button = tk.Button(
            pad, text="Roll Attack", font=self.f["title"],
            bg=self.t["accent"], fg=self.t["bg"],
            activebackground=self.t["accent_hot"],
            activeforeground=self.t["bg"], relief="flat", bd=0,
            cursor="hand2", command=self.roll)
        self.roll_button.pack(fill="x", ipady=8)

        # -- result
        self.total_label = tk.Label(pad, text="—", font=self.f["total"],
                                    bg=self.t["bg"], fg=self.t["fg"])
        self.total_label.pack(pady=(14, 0))
        self.detail_label = tk.Label(pad, text="pick your dice and roll",
                                     font=self.f["label"], bg=self.t["bg"],
                                     fg=self.t["muted"])
        self.detail_label.pack()

        tk.Frame(pad, bg=self.t["panel"], height=1).pack(fill="x", pady=12)
        self.log_label = tk.Label(pad, text="", font=self.f["label"],
                                  bg=self.t["bg"], fg=self.t["muted"],
                                  justify="left", anchor="nw", height=4)
        self.log_label.pack(fill="x")
        tk.Button(pad, text="Close", font=self.f["label"], bg=self.t["bg"],
                  fg=self.t["muted"], activebackground=self.t["panel"],
                  activeforeground=self.t["fg"], relief="flat", bd=0,
                  cursor="hand2", command=self.win.destroy).pack(anchor="e")

    def _step_button(self, parent, text, delta):
        return tk.Button(parent, text=text, font=self.f["die"], width=3,
                         bg=self.t["panel"], fg=self.t["fg"],
                         activebackground=self.t["accent"],
                         activeforeground=self.t["bg"], relief="flat", bd=0,
                         cursor="hand2",
                         command=lambda: self._bump(delta))

    def _bump(self, delta):
        self.mod_var.set(max(-30, min(30, self._modifier() + delta)))
        self._sync_mod()

    def _modifier(self):
        try:
            return int(self.mod_var.get())
        except (tk.TclError, ValueError):
            return 0

    def _sync_mod(self):
        self.mod_label.config(text="%+d" % self._modifier())

    # -- rolling -----------------------------------------------------------
    def roll(self):
        key = self.die_var.get()
        try:
            count = max(1, min(20, int(self.count_var.get())))
        except (tk.TclError, ValueError):
            count = 1
        modifier = self._modifier()
        try:
            values = [self.api.roll_die(key) for _ in range(count)]
        except KeyError:
            self.detail_label.config(text="no %s registered" % key,
                                     fg=self.t["fumble"])
            return

        total = sum(values) + modifier
        # Remember the setup so the next attack opens the way this one ended.
        self.map.attack_die, self.map.attack_count = key, count
        self.map.attack_mod = modifier

        label = "%s attacks %s" % (self.attacker["name"], self.target["name"])
        detail = "%d%s: %s" % (count, key, ", ".join(str(v) for v in values))
        if modifier:
            detail += "   %+d" % modifier

        self.total_label.config(text=str(total), fg=self._colour(key, values))
        self.detail_label.config(text=detail, fg=self.t["muted"])
        self.log.insert(0, "%s = %d" % (detail, total))
        del self.log[4:]
        self.log_label.config(text="\n".join(self.log))
        self.map.status.config(text="%s: %s = %d" % (label, detail, total))

        # hooks=False: this roll carries its own modifier, so the Modifier
        # panel must not quietly add a second one on top.
        group = self.api.make_group(key, values)
        self.api.present([group], label=label, bonus=modifier,
                         notes=["tile %d, %d" % (self.target["x"],
                                                 self.target["y"])],
                         hooks=False)

    def _colour(self, key, values):
        """Colour a single die that came up at either end of its range."""
        die = dict(self.api.dice).get(key)
        if die is None or len(values) != 1:
            return self.t["fg"]
        if values[0] == die.maximum:
            return self.t["crit"]
        if values[0] == die.minimum:
            return self.t["fumble"]
        return self.t["fg"]


class StatsDialog:
    """A character sheet: every stat, and a click to change any of them.

    Deliberately plain - a column of names and numbers, because that is what
    somebody glances at mid-fight. Clicking a row asks for a new number.
    """

    def __init__(self, game_map, token):
        self.map = game_map
        self.t = game_map.t
        self.f = game_map.f
        self.token = token

        self.win = tk.Toplevel(game_map.win)
        self.win.title("%s - character stats" % token["name"])
        self.win.configure(bg=self.t["bg"])
        self.win.transient(game_map.win)
        self.win.resizable(False, False)
        self.rows = tk.Frame(self.win, bg=self.t["bg"])
        self.rows.pack(padx=16, pady=14, fill="both", expand=True)
        self._build()
        self.win.bind("<Escape>", lambda _e: self.win.destroy())

    def _build(self):
        for child in self.rows.winfo_children():
            child.destroy()
        tk.Label(self.rows, text=self.token["name"], font=self.f["title"],
                 bg=self.t["bg"], fg=self.t["fg"],
                 anchor="w").pack(fill="x", pady=(0, 2))
        tk.Label(self.rows, text="click a stat to change it",
                 font=self.f["label"], bg=self.t["bg"], fg=self.t["muted"],
                 anchor="w").pack(fill="x", pady=(0, 10))

        for name, value in stats_of(self.token):
            self._row(name, value)

        tk.Frame(self.rows, bg=self.t["panel"], height=1).pack(fill="x",
                                                               pady=(10, 8))
        self.map._button(self.rows, "+  Add New...", self._add,
                         fg=self.t["accent"]).pack(fill="x")

    def _row(self, name, value):
        line = tk.Frame(self.rows, bg=self.t["panel"], cursor="hand2")
        line.pack(fill="x", pady=1)
        label = tk.Label(line, text=name, font=self.f["label"],
                         bg=self.t["panel"], fg=self.t["fg"], anchor="w",
                         padx=10, pady=5, cursor="hand2")
        label.pack(side="left")
        number = tk.Label(line, text=str(value), font=self.f["die"],
                          bg=self.t["panel"], fg=self.t["accent"], anchor="e",
                          padx=12, cursor="hand2")
        number.pack(side="right")

        for widget in (line, label, number):
            widget.bind("<Button-1>", lambda _e, n=name: self._edit(n))
            widget.bind("<Enter>", lambda _e, w=(line, label, number):
                        [part.configure(bg="#2c303a") for part in w])
            widget.bind("<Leave>", lambda _e, w=(line, label, number):
                        [part.configure(bg=self.t["panel"]) for part in w])
            if name not in STAT_ORDER:
                # Only the GM's own additions can be taken off again.
                widget.bind("<Button-3>", lambda e, n=name: self._drop(n))

    def _edit(self, name):
        self.map._edit_stat(self.token, name)
        self._refresh()

    def _add(self):
        self.map._add_stat(self.token)
        self._refresh()

    def _drop(self, name):
        self.map._remove_stat(self.token, name)
        self._refresh()

    def _refresh(self):
        if self.win.winfo_exists():
            self._build()
