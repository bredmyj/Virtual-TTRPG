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

1. Download `Bredmyj-VTT-1.3.0-windows.zip` from the
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

Two ways, and which one you want depends only on where the other people are.

| Where they are | Use |
|---|---|
| Same house, same wifi | **Host on This Network** / **Join on This Network** |
| Anywhere else | **Connect to a Server** |

Everyone needs the **same version** — the check is exact, and anyone on an
older build is turned away with a message saying which version to get.

Whoever hosts starts as the **GM**. Right-click a face on the roster along the
bottom to give somebody a seat — GM, or Player 1 through 8. Handing the GM
chair over really hands it over: the tools go with it, and you drop to player
mode. The chair is never left empty; if you demote whoever holds it, it comes
back to you.

Once you are in a game you will see a roster of faces along the bottom with
names and pictures, and everyone's coloured cursor moving on the shared map.
If a player figure has not been claimed, right-click it and choose **"This is
my character"** to make it yours; its inventory and stats then fill your panel
on the right.

### On the same network

Nothing to set up. One person hosts, everyone else types a code.

**Hosting:**

1. Main menu → **Host on This Network**.
2. Pick the campaign.
3. Press **Start Hosting**.
4. Read out the **invite code**.

**Joining:**

1. Main menu → **Join on This Network**.
2. Type the invite code. Dashes and capitals do not matter.
3. Press **Join**.

The code carries the address, the port and a secret, so nothing else has to
be said out loud. If a join times out, you are almost certainly not on the
same network — check the wifi, not the app.

### Through a server

One person runs a server; everyone else adds its address once and forgets
about it. Being on the same server is as good as being on the same network:
anybody there can host, everybody sees what is being played, and joining is
picking a session off a list.

**Getting on one:**

1. Main menu → **Connect to a Server**.
2. **Add**, and put in the address the server's owner read out — something
   like `203.0.113.9:7777`, or a name like `dave.duckdns.org`. Give it
   whatever name you like; that name is yours and nobody else sees it.
3. Pick it and press **Connect**.

You are now in the **lobby**. Along the top is everyone else on the server by
name. Below is every session running on it, shown as
`[Marshell: Curse of Strahd]` with how many seats are taken.

**Hosting there:** press **Host a Session**, pick the campaign, and it appears
on everyone's list straight away. Your machine is still the one running the
game — the server only carries the messages.

**Joining there:** pick a session and press **Join**.

While you are playing, anyone arriving on or leaving the server gets a single
line in the log by name — enough to notice somebody has turned up, and not
enough to get in the way.

Leaving a game puts you back at the menu. The saved server stays in your list
for next time, sorted so the one you used last is at the top.

### Running a server

The server is a plain console program. It needs Python, and it needs to be
somewhere the others can reach — which for people outside your house means
forwarding one port on the router.

1. Double-click **Run Server.bat**, or `python server.py`.
2. It prints the addresses to hand round:

   ```
   On this network, people use:
       192.168.1.50:7777

   From anywhere else, people use:
       203.0.113.9:7777
   ```

3. Read out whichever applies and leave it running.

Ctrl-C stops it, and every session on it ends.

**For people outside the house, forward TCP port 7777 to that machine.** That
is the one manual step in all of this, and it is done once:

- Give the machine a fixed address on your network — a **DHCP reservation** in
  the router is better than setting a static IP on the machine itself.
- Forward **TCP 7777** to that address.
- Allow it through the machine's firewall.
- Your home address usually changes every so often. A free dynamic-DNS name
  (DuckDNS, No-IP) saves re-reading the number out; people then save the name
  instead and it keeps working.

If your provider has you behind a shared address — common on mobile, satellite
and some fibre — no forwarding is possible at all, by anyone. The way round it
is to run the server on a machine that does have a real address, or to put
everyone on a virtual network like Tailscale and use its addresses.

**Settings** live in `server.json` beside the program, written on first run:

| | |
|---|---|
| `name` | what the server calls itself in the lobby |
| `motd` | a line shown to everyone who connects |
| `port` | which port to listen on |
| `password` | leave empty for none |
| `max_people` | how many can be on it at once |

Anything given on the command line sticks — `python server.py --name "Tuesday
Game" --password hello` writes those in and they apply from then on.

The server holds no campaign and no save files. It keeps the roster, and the
last map of each session so somebody arriving late is caught up without
waiting on the GM's machine. That is all it keeps, and it keeps none of it
after it stops.

The person running the server joins games on it like anybody else. Running it
gives them nothing special.

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
| `servers.json` | the servers you have added |
| `server.json` | your own server's settings, if you run one |

To back a campaign up, copy its folder out of `saves/`. To move the whole
thing to another computer, copy the folder.

---

## Troubleshooting

**"Windows protected your PC" on first run** — SmartScreen, because the
program is not code-signed. **More info** → **Run anyway**.

**A join on this network times out** — you are not on the same network.
Check that both machines are on the same wifi or the same router, not a guest
network.

**Nobody can reach the server** — from outside the house that is nearly always
the router: the port is not forwarded, it points at the wrong machine, or the
machine's address moved. From inside the house it is nearly always the
firewall on the machine running it. Test from a phone on mobile data; if that
works and a friend still cannot get in, the problem is at their end.

**"The host is running version X and you have Y"** — everyone needs the same
build. Grab the same release.

**No profile pictures** — Pillow is not installed. `launcher.bat` offers to
install it, or run `pip install pillow`.

**"Could not listen on port 7777"** — something else on that machine already
has it. Run the server with `--port` and another number, and tell people the
new one.

---

## Building it yourself

```
python build.py
```

Puts a ready-to-send folder in `dist/`. Zip it and hand it to anyone —
nothing needs installing at the other end.

---

Version 1.3.0. See [RELEASE.md](RELEASE.md) for what changed.
