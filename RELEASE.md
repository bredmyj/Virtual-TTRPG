# Bredmyj's VTT — v1.2.1

A desktop virtual tabletop for solo and small-group RPGs. Dice, a dungeon
map you can build and run live, a journal, and LAN or internet multiplayer —
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

Three ways to host, chosen from the main menu:

| | |
|---|---|
| **People on this network** | LAN. Nothing to set up. |
| **People anywhere, straight from this computer** | Self-hosted, like a Minecraft server. Needs a forwarded port; the app checks whether you're reachable and says so. |
| **People anywhere, through a relay** | Everyone dials out to a meeting point, so nobody needs to forward anything. One person runs **Run a Relay** from the main menu — see below. |

Joining takes an invite code. Once you're in:

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
table needs 1.2.1** — anyone on an older build will be turned away with a
message saying which version to get.

### Getting connected

Playing with someone in another house is the part that usually goes wrong,
because home connections let you dial out and refuse calls coming in. Three
things in this release deal with that.

**Can people reach me?** — in the host window. It runs the checks that tell
the failures apart, about ten seconds, and says which one it is:

- whether anything can get out at all
- what the internet sees you as
- whether there's a router here you control, asked the way games ask when
  they open their own ports
- whether Windows will accept connections **on the network you're on now**
- whether Tailscale is already running

Then one verdict and, where something can be done, a button that does it:
open the port on the router, allow it through Windows, or set up Tailscale.
The join window has the same checks behind **Why can I not join?**

**Run a Relay** — on the main menu. One person runs it and leaves the window
open; everybody else, the host included, dials out to it, so only that one
machine has to be reachable. It's the same idea as running a game server for
friends, except it only carries messages — it never sees a campaign and keeps
nothing. It sets itself up: asks the router to open its port, checks the
firewall, finds the address, and shows the one line to read out, with a live
count of who's connected. Stopping it closes the port again.

The person running the relay doesn't have to be the one running the game,
and they join with an invite code like anybody else. Only the host types the
relay address, once — it's baked into the invite code, so nobody else ever
sees it.

**Firewall help.** Windows only ever asks once, and a rule allowing the app
on a Private network does nothing on a Public one — so it blocks in complete
silence, which looks exactly like nothing being wrong. The check compares
the rule against the network you're actually on and says so. There's a
button to fix it, and step-by-step instructions naming the exact file to
browse to for anyone without an administrator password.

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
- **Self-hosting over the internet needs a forwarded port.** If you can't
  forward one, use the relay instead.
- **Automatic port opening has never met a real router.** It is covered by
  tests against a stand-in, but the machine it was written on has no router
  that offers the feature, so its first real trial will be on yours.
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
- The host window opened without showing the boxes the remembered choice
  needed — the rows only appeared when a radio button was *clicked*, and
  clicking the one already selected does nothing. Anyone who always hosted
  through a relay never saw the box to type the relay address into.
- Two relays could bind the same port on Windows and silently split
  arrivals between them, half a table meeting in each.
- The firewall fix built a command through four layers of quoting; the
  app's name contains an apostrophe, so the rule name arrived mangled and
  the fix failed without saying so.
- The firewall check compared a profile name against a numeric bitmask, so
  every machine reported as blocked.
