# Bredmyj's VTT

A desktop virtual tabletop for solo and small-group RPGs. Dice, a dungeon map
you can build and run live, a journal, solo oracles, and multiplayer over a
network or the internet — in one window, on your own machine, with no account
and no subscription.

Windows. Nothing to sign up for, nothing phones home, and your campaigns are
plain files in a folder you can copy anywhere.

**[Download the latest release →](../../releases/latest)**

---

## Getting it running

### The easy way

1. Download `Bredmyj-VTT-1.2.1-windows.zip` from the
   [releases page](../../releases/latest).
2. Unzip it anywhere — Desktop, Documents, a memory stick.
3. Double-click **Bredmyj's VTT.exe**.

No Python, no install, no administrator rights.

> Windows may show a blue "Windows protected your PC" box the first time.
> That is SmartScreen noticing the program is not code-signed, which costs
> money to do. Click **More info** → **Run anyway**.

### From source

If you would rather run the Python:

1. Download the source zip, or `git clone` this repository.
2. Double-click **launcher.bat**. It looks for Python, tells you where to get
   it if it is missing, and offers to install Pillow for you.
3. Run **Create Shortcut.bat** once for a desktop shortcut with the icon.

Needs Python 3 (with Tkinter, which the standard installer includes). Pillow
is optional — without it you lose profile pictures and portraits, and
everything else works.

The whole folder can be moved or copied wherever you like. Campaigns,
profiles and pictures travel with it.

---

## First run

Set up your profile before playing with anyone. On the main menu, press
**Profile** on the card at the bottom.

- **Name** — what everyone else sees.
- **Colour** — your cursor and your figures on the shared map.
- **Picture** — optional. You get a crop window to move and zoom before
  confirming.

That is enough. There is no account and nothing is sent anywhere; the profile
is a file beside the program.

---

## The main window

The dice roller is the home screen. Click a die to roll it, click again to add
another of the same. Three panels sit around it:

| | |
|---|---|
| **Modifier** | A standing bonus added to every roll. Reach for it constantly, so it sits under the dice. |
| **Roll History** | The last twenty rolls, so you can check what you actually got. |
| **Initiative** | Turn order for a fight. Add combatants, and it tracks whose turn it is. |

Everything else lives under **Tools**:

- **Game Map...** — the dungeon (see below)
- **Adventuring Journal...** — notes, cast and quest threads
- **Mods...** — turn extras on and off

**Fate Chart** and **Meaning Tables** appear as panels in the main window. The
Fate Chart is the full Mythic GM Emulator 2nd Edition oracle — pick a Chaos
Factor and the odds, and it answers yes or no. Meaning Tables roll a d100 for
a word to interpret; the tables are plain text files in
`plugins/meaning_tables/`, so you can add your own.

Campaigns are managed under **File** — save, open, create, or delete. The
title bar shows which one you are in.

---

## The Game Map

**Tools → Game Map...** opens it in its own window.

### Two ways to look at it

The button at the top left says **GM Mode** or **Player Mode**. Click it to
switch.

- **GM Mode** — everything, revealed or not. Unrevealed rooms are dimmed and
  hatched, hidden creatures are ghosted, your notes show. This is where you
  build.
- **Player Mode** — only what the party has actually found. Nothing still
  secret is drawn at all, so you can turn the window round to face the table
  without giving anything away.

In a multiplayer session, only whoever holds the GM chair can use GM Mode.

### Building

Five tabs along the top:

| Tab | What it does |
|---|---|
| **Select** | Click things, drag them, right-click for what you can do to them |
| **Draw** | Walls, doors, objects, terrain |
| **Room** | Place prefab rooms from a region |
| **Creature** | Place creature and player figures |
| **Tags** | Labels and notes on the map |

Pick a room shape and click to place it. **R** rotates before you place;
scroll the wheel over a placed thing to turn it. **Ctrl+Z** undoes, **Ctrl+Y**
redoes, **Delete** removes what is selected, **Escape** cancels.

Rooms come in five regions — Sewer, Prison, Mines, Dwarven Ruins and Deep
Dark. Room shapes are drawn for the **Sewer** so far; the other four exist as
regions and their terrain generation works, but they have no room blueprints
yet.

### Filling a room

Right-click a room → **Generate**, then pick one:

- **Loot** — potions, treasure, scrolls, weapons, wands and the rest
- **Traps**
- **Ground** — water, moss, tall grass and pits, chosen to suit the region
- **Creatures**

Each is a separate roll and you can run it as often as you like — there is no
cap. Roll until the room feels right. Ground never lands on ground, and
nothing ever lands on top of a pit.

The rest of the room's right-click menu: **Reveal Room**, **Edit Room**, **Add
Object**, **Add Note**, **Lock Room** and **Remove Room**.

### Doors and locks

Doors open and close — right-click one. An open door lets sight through as if
it were not there.

There are four coloured doors (red, blue, green, violet) with four matching
keys, plus the plain sort. A **plain key is a skeleton key** for plain locked
rooms; a **coloured key opens only its own colour**. When a figure carrying
the right key walks into a locked room, the key is used up and the room is
revealed. Without the right key, the party cannot get in at all.

### Figures

Right-click a creature or character for **Move**, **Attack**, **Duplicate**,
**Hide**, **Mark Defeated**, **View Stat Block**, **Character Stats...**,
**Size**, **Turn**, **Colour**, **Belongs To**, **Add Portrait...** and
**Remove**.

- **Size** sets the footprint — 1×1 up to 4×4 squares.
- **Turn**, or the scroll wheel, rotates it.
- **Character Stats...** opens HP, Temp HP, PD, AD, AC, Move, Sight, plus any
  stat you add yourself.

Select a figure and its stats appear in the panel on the right, under its
name. In the stats strip you can **right-click a stat** to change or remove
it, or **right-click empty space** to add one. The seven standard stats cannot
be deleted.

### Sight and movement

Each figure sees out to its own **Sight** stat, blocked by walls, closed
doors, tall grass, and the gap between rooms that are not connected. Moss does
not block. What the party has already seen stays on the map but dimmed.

A figure moves up to its **Move** stat, on room floor only — never through a
wall, never across empty space, and never into a locked room without the key.

---

## Playing together

Three ways to play with other people. Pick by where they are.

| Where they are | Use |
|---|---|
| Same house, same wifi | **People on this network** |
| Elsewhere, and your router lets connections in | **People anywhere, straight from this computer** |
| Elsewhere, and it does not | **People anywhere, through a relay** |

Everyone needs the **same version** — the check is exact, and anyone on an
older build is turned away with a message saying which version to get.

### Hosting a session

1. Main menu → **Host a Session**.
2. Pick the campaign.
3. Under **Who is playing**, choose one of the three above.
4. Press **Start Hosting**.
5. Read out the **invite code** it gives you.

If you chose *through a relay*, two boxes appear for the relay's address and
port — see [Running a relay](#running-a-relay). You only type that once; it is
remembered, and it gets baked into the invite code so nobody else ever needs
it.

Whoever hosts starts as the **GM**. Right-click a face on the roster along the
bottom to give somebody a seat — GM, or Player 1 through 8. Handing the GM
chair over really hands it over: the tools go with it, and you drop to player
mode. The chair is never left empty; if you demote whoever holds it, it comes
back to you.

### Joining a session

1. Main menu → **Join a Session**.
2. Type the invite code. Dashes and capitals do not matter.
3. Press **Join**.

That is all — even for a relay game. The code carries everything.

Once you are in, you will see a roster of faces along the bottom with names
and pictures, and everyone's coloured cursor moving on the shared map. If a
player figure has not been claimed, right-click it and choose **"This is my
character"** to make it yours; its inventory and stats then fill your panel on
the right.

If the join fails, a **Why can I not join?** button appears. A timeout almost
always means the host cannot be reached from outside rather than anything
wrong at your end.

### Running a relay

Home internet connections let you dial *out* freely but usually refuse calls
coming *in*. If nobody's connection will accept a call, one person runs a
relay — a middleman everybody dials out to, the same idea as running a game
server for friends.

**Whoever has the most ordinary home connection should run it. It does not
have to be the person running the game.**

1. Main menu → **Run a Relay**.
2. Press **Start the relay**.
3. It sets itself up — asks the router to open its port, checks the firewall,
   finds the address — then shows a line like:

   ```
   TELL EVERYONE TO USE
   203.0.113.9     port 7788
   ```

4. Read that out, or press **Copy this**.
5. **Leave the window open while you play.**

Whoever is hosting puts that address and port into **Host a Session → People
anywhere, through a relay**. Everyone else just uses the invite code as usual.

The relay carries messages and nothing else — it never sees a campaign and
keeps nothing. Stopping it, or closing the window, shuts it down properly and
closes the port on the router again. Every session on it ends when you stop
it.

The person running the relay joins the game with an invite code like anybody
else. Running it gives them nothing special.

You can also run it without the app at all — double-click **Run Relay.bat**,
or `python relay.py`.

### When people cannot reach you

In the host window, press **Can people reach me?**. It takes about ten seconds
and tells the failures apart:

- whether anything can get out at all
- what the internet sees you as
- whether there is a router here you control, and whether it will open a port
- whether Windows will accept connections **on the network you are on now**
- whether Tailscale is running

Then it gives one verdict and, where something can be done, a button that does
it: open the port on the router, allow it through Windows, or set up
Tailscale.

**The firewall one catches people out.** Windows only ever asks once, and a
rule allowing the app on a *Private* network does nothing on a *Public* one —
so it blocks in silence, which looks exactly like nothing being wrong. The
check compares the rule against the network you are actually on. There is a
button to fix it, and written steps naming the exact file to browse to if you
do not have the administrator password.

If you are on a shared connection — a flat, a campus, or an internet provider
that puts many homes behind one address — no port forwarding is possible for
you at all, by anyone. Use a relay on somebody else's machine, or Tailscale.

---

## Mods

Anything in `plugins/` with a `PLUGIN` dictionary and a `setup(api)` function
loads on startup and gets its own panel or window, hooks around every roll,
and storage of its own per campaign. See `plugins/README.md`.

The four that ship — the map, the journal, the fate chart and the meaning
tables — are written against exactly the same API, so nothing they do is
off-limits to yours. Turn them on and off under **Tools → Mods...**.

---

## Your files

Everything of yours stays in the app folder and none of it is in this
repository:

| | |
|---|---|
| `saves/` | your campaigns, one folder each |
| `profile.json`, `profile.png` | your name, colour and picture |
| `faces/` | cached pictures of people who have joined |
| `mods.json` | your settings |

To back a campaign up, copy its folder out of `saves/`. To move the whole
thing to another computer, copy the folder.

---

## Troubleshooting

**"Windows protected your PC" on first run** — SmartScreen, because the
program is not code-signed. **More info** → **Run anyway**.

**A friend's join times out** — the host cannot be reached. Host presses **Can
people reach me?**; usually it is the router or the firewall, and usually the
answer is to run a relay.

**No firewall prompt appeared** — Windows only asks once ever. If a rule
already exists for the wrong network type it blocks silently. Use **Can people
reach me?** → **Allow it through Windows**.

**"The host is running version X and you have Y"** — everyone needs the same
build. Grab the same release.

**No profile pictures** — Pillow is not installed. `launcher.bat` offers to
install it, or run `pip install pillow`.

**The relay says NOT READY** — nothing could open a port to that machine. Run
the relay on someone else's computer instead; it does not have to be the host.

---

## Building it yourself

```
python build.py
```

Puts a ready-to-send folder in `dist/`. Zip it and hand it to anyone —
nothing needs installing at the other end.

---

Version 1.2.1. See [RELEASE.md](RELEASE.md) for what changed.
