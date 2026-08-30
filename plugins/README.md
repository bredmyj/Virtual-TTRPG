# Writing a mod

Drop a `.py` file in this folder. It gets loaded automatically at startup.
Toggle mods on/off with the **⚙ Mods** button in the app (restart to apply).

```python
PLUGIN = {
    "name": "My Mod",
    "version": "1.0",
    "description": "What it does",
    "author": "you",
}

def setup(api):
    ...
```

If `setup()` raises, the app still starts and the mod is flagged red in the
Mods window with the error.

## api reference

### Register things

| call | what it does |
| --- | --- |
| `api.add_die(label, sides, key=None, roller=None, minimum=1, maximum=None, fmt=None, order=200)` | Adds a die button. `roller` is an optional `() -> int` for non-standard dice. |
| `api.add_action(label, callback, color=None)` | Adds a button to the mod bar under the total. Returns the widget. |
| `api.add_panel(title, builder)` | Adds a titled panel at the bottom. `builder(parent)` returns a widget. The title bar is free UI: click it to minimise, drag it to reorder. Both the minimised state and the order are remembered between sessions. |
| `api.on(event, callback)` | Subscribes to a hook (below). |

### Hooks

| event | payload | you can |
| --- | --- | --- |
| `before_roll` | `RollRequest` | edit `.counts` (die key → how many), or `.cancel()` |
| `after_roll` | `RollResult` | edit values, `.bonus`, `.notes`, or drop dice |
| `rolled` | `RollResult` | read only — fires once the result is on screen |
| `app_ready` | the app | everything is loaded |

### Roll things yourself

- `api.roll(counts=None)` — full roll pipeline; defaults to the current pool
- `api.roll_die("d20")` — one value
- `api.make_group("d20", [12, 5])` — build a result group
- `api.present(groups, notes=(), label="", bonus=0, hooks=True)` — display your
  own result. `hooks=False` skips `after_roll`, so no other mod can alter the
  numbers — use it for rolls read off a chart.

### Pool

`api.pool` (read), `api.set_pool({"d6": 3})`, `api.add_to_pool("d6", 2)`, `api.clear_pool()`

### Saved settings

`api.storage` is a plain dict, loaded from `../data/<modfile>.json`.
Call `api.save()` to write it.

### Looks

`api.theme` — `bg`, `panel`, `fg`, `muted`, `accent`, `crit`, `fumble`
`api.fonts` — `title`, `label`, `die`, `roll`, `result`, `total`
`api.app` — the Tk window, for anything not covered above.

## Data model

- `Group` — `.die`, `.values`, `.dropped` (indices left out of the total),
  `.note`, `.kept`, `.subtotal`
- `RollResult` — `.groups`, `.notes`, `.bonus`, `.total`, `.describe()`,
  `.group("d20")`

## Example: advantage

```python
PLUGIN = {"name": "Advantage", "version": "1.0", "description": "Roll 2d20, keep the best."}

def setup(api):
    api.add_action("Advantage", lambda: _roll(api, high=True))
    api.add_action("Disadvantage", lambda: _roll(api, high=False))

def _roll(api, high):
    values = [api.roll_die("d20"), api.roll_die("d20")]
    loser = min(values) if high else max(values)
    group = api.make_group("d20", values)
    group.dropped = {values.index(loser)}
    group.note = "advantage" if high else "disadvantage"
    api.present([group])
```

## Example: a custom die

```python
import random

PLUGIN = {"name": "Fate Dice", "version": "1.0", "description": "Adds dF (-1/0/+1)."}

rng = random.SystemRandom()

def setup(api):
    api.add_die("dF", sides=3, roller=lambda: rng.choice([-1, 0, 1]),
                minimum=-1, maximum=1, fmt=lambda v: f"{v:+d}" if v else "0")
```

`modifier.py` is a short, working example of a panel plus the `after_roll`
hook. The bigger bundled mods — `fate_chart.py`, `meaning_tables.py` and
`journal.py` — show the same api used in anger.

The Roll History and Initiative panels are built in rather than mods (they
live in `core_panels.py`), so they always load and don't appear in the Mods
window. They are still written against this same api, so it is worth reading
them as examples too.
