# Bredmyj's VTT — v1.3.0

A desktop virtual tabletop for solo and small-group RPGs. Dice, a dungeon
map you can build and run live, a journal, and LAN or server multiplayer —
in one window, on your own machine, with no account and no subscription.

Windows. Python 3 and Tkinter, plus Pillow for pictures. A packaged build
needs none of that.

---

## Getting it running

**The easy way** — download the packaged build, unzip it anywhere, and
double-click **Bredmyj's VTT.exe**. No Python, no install, no administrator
rights.

**From source** — download the source zip and double-click **launcher.bat**.
It looks for Python, tells you exactly where to get it if it's missing, and
offers to install Pillow for you. Run **Create Shortcut.bat** once and you
get a proper desktop shortcut with an icon.

The whole folder can be moved or copied wherever you like — saves, profiles
and pictures all travel with it.

---

## What's in it

### Dice

A clickable roller for the usual dice, with a standing **Modifier** applied
to every roll, a **Roll History** of the last twenty, and an **Initiative**
tracker for running a fight.

### Game Map

The big one — a tile map for building and running a dungeon, in its own
window, with two ways to look at it:

- **GM mode** — everything, revealed or not. Unrevealed rooms are dimmed and
  hatched, hidden creatures are ghosted, notes show.
- **Player mode** — only what the party has actually found. Nothing still
  secret is drawn at all, so the window can be turned round to face the
  table.

What you can put on it:

- **Rooms** from a set of blueprints, rotatable, on as many levels as you
  like — and the level tabs can be dragged into whatever order you want.
- **Walls and doors**, including four coloured door variants with four
  matching keys. Doors open and close, and an open one lets sight through
  as if it weren't there.
- **Locks.** A plain key is a skeleton key for plain locked rooms; a
  coloured key opens only its own colour. Walking in consumes the key and
  reveals the room. A party without the right key cannot get in at all.
- **Terrain** — water, moss, tall grass and pits, each drawn to the tile.
- **41 kinds of object** — chests, potions, scrolls, runestones, weapons,
  wands, gold piles with a real coin count, and three sorts of trap.
- **Creature and player figures**, with footprints from 1×1 up to 4×4, a
  colour, an optional portrait, and rotation by scroll wheel or right-click.

Running a game on it:

- **Line of sight.** Each figure sees out to its own Sight stat, blocked by
  walls, closed doors, tall grass and the gap between unconnected rooms.
  What the party has seen stays remembered but dimmed. Moss doesn't block.
- **Movement.** A figure moves up to its Move stat, on room floor only,
  never through a wall or across empty space, and never into a locked room
  without the key.
- **Character stats** — HP, Temp HP, PD, AD, AC, Move, Sight, plus any you
  add yourself. Sight really does drive line of sight.
- **Room generation**, split three ways so you roll only what you want:
  **Loot**, **Traps** and **Ground**, each repeatable as often as you like
  with no per-room cap. Ground never lands on ground, and nothing ever lands
  on a pit.

### Adventuring Journal

Notes on a drawing surface with an optional grid, a **Cast** list of people
and places, and **Threads** for quests and vows with ten four-tick progress
bars each.

### Solo tools

- **Fate Chart** — the full Mythic GM Emulator 2nd Edition chart, all nine
  odds across Chaos Factors 1–9.
- **Meaning Tables** — roll a d100 for a word to interpret. Tables are plain
  text files in `meaning_tables/`, so you can add your own.

### Multiplayer

Two ways, chosen from the main menu by where the other people are:

| | |
|---|---|
| **Host on This Network** / **Join on This Network** | LAN. Nothing to set up: one person hosts and reads out an invite code. |
| **Connect to a Server** | One person runs a server; everyone else adds its address once and picks a session off a list. |

Once you're in:

- A **roster** of faces along the bottom, with names and profile pictures.
- **Live coloured cursors** — you can see where everyone is pointing, and
  they can see you.
- A **shared map** that stays in step. The host is authoritative, so nobody
  can clobber anybody else's work, and a latecomer gets the map as it stands
  rather than a stale copy.
- **Roles.** The host starts as GM and can hand the chair to anyone. One GM
  at a time, and the chair is never left empty.
- **Profiles** — name, colour, token and a profile picture you can crop and
  zoom before confirming.

Everyone in a session is version-checked, so you'll be told if someone's on
a different build rather than finding out the hard way. **Everyone at the
table needs 1.3.0** — anyone on an older build will be turned away with a
message saying which version to get.

### Servers

New in 1.3.0, and the way to play with anyone outside your own house.

**`server.py`** is a plain console program — double-click **Run Server.bat**
or run `python server.py`. One person leaves it running on a machine the
others can reach, and it prints the addresses to hand round. Its name, port,
password and identity live in `server.json` beside it, so a server somebody
saved last week is still the same server this week.

It is a switchboard with a memory. It carries messages between a host and
the people who joined that host, and it keeps the last map of each session
so somebody arriving late is caught up without waiting on the GM's machine.
It holds no campaign, no rules and no save files — the GM's app is still the
authority on what is true.

**In the app**, **Connect to a Server** opens a saved list: add an address,
give it any name you like, connect. That name is yours; nobody else sees it,
and the list sorts so the one you used last is at the top.

Being on a server is as good as being on the same network. The lobby shows
**everyone on it by name**, and **every session running on it** as
`[Marshell: Curse of Strahd]` with the seats taken. Anybody can host; joining
is picking one and pressing **Join**.

There is one manual step in the whole arrangement, done once by one person:
forwarding a port on the router to the machine running the server. The
README has the details, including the two things that quietly break it later
— a home address that changes, and a machine whose network address moves.

### Mods

Anything in `plugins/` with a `PLUGIN` dict and a `setup(api)` function
loads on startup and gets its own panel or window, hooks around every roll,
and per-campaign storage of its own. The four that ship — the map, the
journal, the fate chart and the meaning tables — are written against exactly
the same API, so nothing they do is off-limits to yours.

---

## New in this release

**Multiplayer roles that actually work.** Right-clicking a face on the
roster and assigning GM or a player seat now does what it says. Handing the
GM chair over really hands it over — no more two GMs at one table, and the
host can step down and sit in a player's seat. The badge on each face shows
the seat: `GM`, `P1`, `P2`. Whoever is handed the chair drops straight into
GM mode with the tools, and whoever loses it drops to player mode — a GM who
*chooses* player mode to see what the party sees is left where they asked to
be. And the chair is never left empty: demoting the GM hands it back to the
host rather than leaving the map unbuildable.

**Claim your own character.** A player right-clicking a figure nobody has
taken gets **"This is my character"**. Taking it seats them behind it, and
from then on that figure's inventory and stats fill their right-hand panel.
A figure someone already holds isn't offered.

**Stats from the panel.** Right-click a stat for **Change / Remove / Add
New**, or right-click empty space in the strip to add one. The seven
standard stats can't be deleted; anything you added yourself can.

**Stats on whatever you select.** Selecting any figure — creature or
character — now shows its numbers in the selection panel under the name,
square and state, wrapped to two or three short rows rather than one long
line. Creatures are included now, which they weren't, so a GM can read a
monster's HP and AC mid-fight without opening a window. Temp HP is hidden
when it's zero.

**Room contents counted, not listed.** Inspecting a room used to spell out
every single patch — twelve lines of `Moss`, `Moss`, `Moss`. Now it reads:

```
You find:
  - Chest
  - Moss ×4
  - Pit ×2
  - Tall Grass ×5
```

A count of one stays plain. Hidden objects still don't count toward what the
party sees.

**Connection troubleshooting that tells the truth.** The old check only
tested whether an outbound packet kept its port number and called that
"reachable" — which gave a green light on connections where nobody can be
reached at all, and the other person just timed out with no explanation. It
is replaced by the real checks described above.

**Room generation reworked.** The old single "Generate Contents" is gone,
along with its per-room cap. In its place: **Loot**, **Traps** and **Ground**
as three separate rolls, each repeatable until the room feels right. Ground
is picked to suit the region. Ground never covers ground, and traps and loot
never land on a pit.

**Also new since 1.1.1** — open/closed door states, four coloured doors
and matching keys, coloured locks that consume the key, line of sight with
dimmed memory, movement rules, character stats, creature footprints and
rotation, draggable level tabs, a scrollable stats-and-inventory panel, a
compact dice roller that fits beside the map, a solid-tile pit, and internet
multiplayer.

---

## Known limitations

- **Windows only** for the packaged build and the launcher scripts. The
  Python source has nothing Windows-specific in it beyond those.
- **Room blueprints exist for the Sewer only.** Prison, Mines, Dwarven Ruins
  and Deep Dark are set up as regions — terrain generation knows what each
  should be made of — but have no room shapes drawn yet.
- **Playing with people outside your house needs a server**, and that
  server needs a forwarded port. There is no way around it built into the
  app any more: the previous release tried to open the router itself, check
  the firewall and install Tailscale for you, and it was a great deal of
  code for something one person doing it once does better by hand.
- **A session ends when its host leaves.** The server keeps the last map,
  not the campaign, so it cannot carry a game on without the GM.
- **Pillow is optional but wanted.** Without it, profile pictures and
  portraits are unavailable; everything else works.

---

## Bug fixes

- Two hosts could bind the same port on Windows, so a second session
  silently stole the first one's connections.
- A joiner whose profile had a real photo was dropped with "the host closed
  the connection" — a partial message was being read as a hangup.
- A stale client could overwrite the host's newer map.
- The profile window opened with no confirm button and saved nothing.
- Character stats couldn't be edited at all.
- Generate Contents refused to place anything in a room with terrain in it.
- The stats and inventory panel was cut off in a small window.
- The host's cursor was invisible to everyone else.
- Two servers could bind the same port on Windows and silently split
  arrivals between them, half a table meeting in each.
