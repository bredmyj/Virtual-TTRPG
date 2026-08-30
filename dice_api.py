"""Plugin (mod) API for Dice Roller.

A mod is a single .py file dropped in the `plugins/` folder. It looks like this:

    PLUGIN = {
        "name": "My Mod",
        "version": "1.0",
        "description": "What it does",
        "author": "you",
    }

    def setup(api):
        api.add_die("d7", sides=7)
        api.on("after_roll", lambda res: res.notes.append("hello"))

Everything a mod can do lives on the `api` object passed to setup().
See plugins/README.md for the full reference.
"""

import importlib.util
import json
import os
import random
import shutil
import sys
import traceback
from dataclasses import dataclass, field

rng = random.SystemRandom()

# House rule: the d20 is not a flat die. Each face in 1-10 gives up one
# percentage point to the top half, so 1-10 come up 4% of the time each and
# 11-20 come up 6% each. The two halves still add to 100, and the die still
# reads 1-20 everywhere else in the app.
#
# To go back to a fair d20, drop the `roller=` argument where the core dice
# are registered in dice_roller.py. To retune it, edit the percentages here -
# they must be whole numbers and they must add up to 100.
D20_WEIGHTS = {face: (4 if face <= 10 else 6) for face in range(1, 21)}


def weighted_roll(weights):
    """Roll one face from a {face: percent} table.

    Draws a ticket in 1..sum and walks the faces in order, so a face with
    weight w gets exactly w tickets out of the total - no floating point and
    no rounding drift.
    """
    total = sum(weights.values())
    ticket = rng.randint(1, total)
    running = 0
    for face in sorted(weights):
        running += weights[face]
        if ticket <= running:
            return face
    return max(weights)     # unreachable while the weights are positive


def roll_d20():
    return weighted_roll(D20_WEIGHTS)


import paths

VERSION = paths.VERSION
APP_DIR = paths.APP_DIR
PLUGIN_DIR = os.path.join(APP_DIR, "plugins")
DATA_DIR = os.path.join(APP_DIR, "data")      # pre-campaign layout, migrated once
SAVES_DIR = os.path.join(APP_DIR, "saves")
CONFIG_PATH = os.path.join(APP_DIR, "mods.json")
DEFAULT_SAVE = "Default"

# Hook names a mod may subscribe to with api.on(...)
EVENTS = (
    "before_roll",  # (request)  -- change which dice get rolled, or cancel
    "after_roll",   # (result)   -- change values / add bonus / add notes
    "rolled",       # (result)   -- read-only; fires once the result is on screen
    "app_ready",    # (app)      -- every mod is loaded and the window is built
    "save",         # (name)     -- flush anything unsaved to api.storage now
)

THEME = {
    "bg": "#1b1d23",
    "panel": "#24272f",
    "fg": "#e6e8ee",
    "muted": "#8b90a0",
    "accent": "#c8a24a",
    "accent_hot": "#e0bb63",
    "crit": "#5fd38d",
    "fumble": "#e2585f",
}


# --------------------------------------------------------------------------
# Data model
# --------------------------------------------------------------------------
@dataclass
class Die:
    """One rollable die. Core dice and mod-added dice are the same thing."""

    key: str
    label: str
    sides: int
    roller: object = None       # optional callable () -> int
    minimum: int = 1
    maximum: int = None
    fmt: object = None          # optional callable (int) -> str for display
    order: int = 100            # lower sorts earlier in the button grid
    source: str = "core"

    def __post_init__(self):
        if self.maximum is None:
            self.maximum = self.sides
        if self.fmt is None:
            self.fmt = str

    def roll(self):
        return self.roller() if self.roller else rng.randint(1, self.sides)


@dataclass
class Group:
    """All the values rolled for one die type."""

    die: Die
    values: list = field(default_factory=list)
    dropped: set = field(default_factory=set)  # indices excluded from the total
    note: str = ""

    @property
    def kept(self):
        return [v for i, v in enumerate(self.values) if i not in self.dropped]

    @property
    def subtotal(self):
        return sum(self.kept)


@dataclass
class RollRequest:
    """Passed to `before_roll`. Edit `counts` (die key -> how many)."""

    counts: dict = field(default_factory=dict)
    cancelled: bool = False

    def cancel(self):
        self.cancelled = True


@dataclass
class RollResult:
    """Passed to `after_roll` and `rolled`."""

    groups: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    bonus: int = 0
    label: str = ""

    @property
    def total(self):
        return sum(g.subtotal for g in self.groups) + self.bonus

    def describe(self):
        parts = [f"{len(g.values)}{g.die.label}" for g in self.groups]
        text = " + ".join(parts) if parts else "—"
        if self.bonus:
            text += f" {self.bonus:+d}"
        return f"{self.label} {text}".strip()

    def group(self, key):
        for g in self.groups:
            if g.die.key == key:
                return g
        return None


@dataclass
class PluginInfo:
    filename: str
    path: str
    name: str = ""
    version: str = ""
    description: str = ""
    author: str = ""
    enabled: bool = True
    loaded: bool = False
    error: str = ""
    module: object = None


# --------------------------------------------------------------------------
# The object every mod is handed
# --------------------------------------------------------------------------
class PluginAPI:
    def __init__(self, app, info):
        self._app = app
        self._info = info
        self.name = info.name or info.filename
        self.theme = THEME
        self.storage = self._load_storage()

    # -- app access ------------------------------------------------------
    @property
    def app(self):
        """The Tk window itself. Escape hatch for anything not covered here."""
        return self._app

    @property
    def session(self):
        """Who else is playing. Always there - on your own it is a table of
        one, so a mod never has to check whether anyone is connected."""
        return getattr(self._app, "session", None)

    @property
    def fonts(self):
        return self._app.fonts

    @property
    def dice(self):
        return self._app.dice

    def log(self, message):
        print(f"[{self.name}] {message}")

    # -- registering things ----------------------------------------------
    def add_die(self, label, sides, key=None, roller=None, minimum=1,
                maximum=None, fmt=None, order=200):
        """Add a die button. `roller` is an optional callable returning a value."""
        die = Die(
            key=key or label,
            label=label,
            sides=sides,
            roller=roller,
            minimum=minimum,
            maximum=maximum,
            fmt=fmt,
            order=order,
            source=self.name,
        )
        self._app.register_die(die)
        return die

    def add_action(self, label, callback, color=None):
        """Add a button to the mod bar under the total. Returns the widget."""
        return self._app.register_action(label, self._guard(callback), color)

    def add_panel(self, title, builder, area="mods"):
        """Add a titled panel at the bottom. builder(parent) -> widget.

        area="core" pins it into the roller's own block instead, directly
        under the total - that's for built-ins, not mods.
        """
        return self._app.register_panel(title, builder, area)

    def add_menu_command(self, menu, label, command):
        """Add an entry to a menu in the window's menu bar, e.g. "Tools"."""
        return self._app.register_menu_command(menu, label, self._guard(command))

    def on(self, event, callback):
        """Subscribe to a hook. See dice_api.EVENTS."""
        if event not in EVENTS:
            raise ValueError(f"unknown event {event!r}; expected one of {EVENTS}")
        self._app.hooks.setdefault(event, []).append((self.name, callback))

    # -- doing things -----------------------------------------------------
    def roll(self, counts=None):
        """Run a full roll. Defaults to whatever is in the pool."""
        return self._app.roll(counts)

    def roll_die(self, key):
        """Roll one die by key ('d20', 'dF', ...) and return the value."""
        die = self._app.dice.get(key)
        if die is None:
            raise KeyError(f"no die registered with key {key!r}")
        return die.roll()

    def make_group(self, key, values):
        return Group(die=self._app.dice[key], values=list(values))

    def present(self, groups, notes=(), label="", bonus=0, hooks=True):
        """Display a result built by the mod itself.

        `hooks=False` skips the `after_roll` pass, so other mods can't alter
        the numbers. Use it for rolls read off a chart, where a stray +2 from
        another mod would change the answer.
        """
        result = RollResult(
            groups=list(groups), notes=list(notes), bonus=bonus, label=label
        )
        return self._app.present(result, hooks=hooks)

    # -- the pool ---------------------------------------------------------
    @property
    def pool(self):
        return dict(self._app.pool)

    def set_pool(self, counts):
        self._app.set_pool(counts)

    def add_to_pool(self, key, count=1):
        self._app.add_die(key, count)

    def clear_pool(self):
        self._app.clear_pool()

    # -- per-mod saved settings -------------------------------------------
    def _storage_path(self):
        """Inside the campaign folder, so each save has its own copy."""
        stem = os.path.splitext(self._info.filename)[0]
        return os.path.join(save_path(), f"{stem}.json")

    def _load_storage(self):
        try:
            with open(self._storage_path(), encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, ValueError):
            return {}

    @property
    def save_name(self):
        """Name of the campaign currently loaded."""
        return current_save()

    def save(self):
        """Persist api.storage (a plain dict) to the current campaign."""
        os.makedirs(os.path.dirname(self._storage_path()), exist_ok=True)
        try:
            with open(self._storage_path(), "w", encoding="utf-8") as fh:
                json.dump(self.storage, fh, indent=2)
        except OSError as exc:
            self.log(f"could not save settings: {exc}")

    # -- internal ---------------------------------------------------------
    def _guard(self, callback):
        """Keep a broken mod callback from taking down the app."""

        def wrapped(*a, **kw):
            try:
                return callback(*a, **kw)
            except Exception:
                self.log("action failed:\n" + traceback.format_exc())

        return wrapped


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
# Campaigns (save files). Each campaign is a folder under saves/ holding one
# JSON file per mod, so switching campaign switches every mod's data at once.
# --------------------------------------------------------------------------
def clean_save_name(name):
    """Turn whatever the user typed into something safe for a folder name."""
    cleaned = "".join(c for c in (name or "") if c.isalnum() or c in " -_'").strip()
    return cleaned[:60] or "Campaign"


def list_saves():
    migrate_legacy_data()
    os.makedirs(SAVES_DIR, exist_ok=True)
    names = sorted(d for d in os.listdir(SAVES_DIR)
                   if os.path.isdir(os.path.join(SAVES_DIR, d)))
    return names or [DEFAULT_SAVE]


def current_save():
    name = load_config().get("current_save") or DEFAULT_SAVE
    return name


def set_current_save(name):
    cfg = load_config()
    cfg["current_save"] = name
    save_config(cfg)


def save_path(name=None, create=True):
    path = os.path.join(SAVES_DIR, name or current_save())
    if create:
        os.makedirs(path, exist_ok=True)
    return path


def create_save(name, copy_from=None):
    """Make a new campaign, optionally duplicating an existing one."""
    name = clean_save_name(name)
    target = os.path.join(SAVES_DIR, name)
    if os.path.exists(target):
        return None  # caller decides what to tell the user
    if copy_from and os.path.isdir(os.path.join(SAVES_DIR, copy_from)):
        shutil.copytree(os.path.join(SAVES_DIR, copy_from), target)
    else:
        os.makedirs(target, exist_ok=True)
    return name


def delete_save(name):
    path = os.path.join(SAVES_DIR, name)
    if os.path.isdir(path):
        shutil.rmtree(path, ignore_errors=True)


def migrate_legacy_data():
    """The old flat data/ folder becomes the Default campaign, once."""
    if os.path.isdir(SAVES_DIR) or not os.path.isdir(DATA_DIR):
        return
    target = os.path.join(SAVES_DIR, DEFAULT_SAVE)
    os.makedirs(target, exist_ok=True)
    for filename in os.listdir(DATA_DIR):
        if filename.endswith(".json"):
            try:
                shutil.move(os.path.join(DATA_DIR, filename),
                            os.path.join(target, filename))
            except OSError as exc:
                print(f"[saves] could not migrate {filename}: {exc}")


def load_config():
    try:
        with open(CONFIG_PATH, encoding="utf-8") as fh:
            cfg = json.load(fh)
    except (OSError, ValueError):
        cfg = {}
    cfg.setdefault("disabled", [])
    return cfg


def save_config(cfg):
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, indent=2)
    except OSError as exc:
        print(f"[mods] could not save {CONFIG_PATH}: {exc}")


def discover():
    """Every .py file in plugins/ that isn't private."""
    os.makedirs(PLUGIN_DIR, exist_ok=True)
    names = [
        f
        for f in sorted(os.listdir(PLUGIN_DIR))
        if f.endswith(".py") and not f.startswith(("_", "."))
    ]
    return [(f, os.path.join(PLUGIN_DIR, f)) for f in names]


def load_all(app):
    """Import and set up every enabled mod. Never raises."""
    cfg = load_config()
    disabled = set(cfg.get("disabled", []))
    infos = []

    for filename, path in discover():
        info = PluginInfo(filename=filename, path=path, name=filename)
        info.enabled = filename not in disabled
        infos.append(info)
        if not info.enabled:
            continue
        try:
            module = _import_file(path)
            meta = getattr(module, "PLUGIN", {}) or {}
            info.module = module
            info.name = meta.get("name") or os.path.splitext(filename)[0]
            info.version = str(meta.get("version", ""))
            info.description = meta.get("description", "")
            info.author = meta.get("author", "")
            setup = getattr(module, "setup", None)
            if not callable(setup):
                raise AttributeError("mod has no setup(api) function")
            setup(PluginAPI(app, info))
            info.loaded = True
        except Exception:
            info.error = traceback.format_exc(limit=4)
            print(f"[mods] {filename} failed to load:\n{info.error}")

    return infos


def core_api(app, stem, name):
    """An api object for a built-in feature, not backed by a plugin file.

    It behaves exactly like the one a mod is handed - same theme, panels,
    hooks and per-campaign storage - so built-ins and mods are written the
    same way. Storage lands in saves/<campaign>/<stem>.json.
    """
    info = PluginInfo(filename=f"{stem}.py", path="", name=name, loaded=True)
    return PluginAPI(app, info)


def _import_file(path):
    stem = os.path.splitext(os.path.basename(path))[0]
    mod_name = f"dicemod_{stem}"
    spec = importlib.util.spec_from_file_location(mod_name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    spec.loader.exec_module(module)
    return module
