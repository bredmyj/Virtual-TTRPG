# Bredmyj's VTT — v1.4.1

A desktop virtual tabletop for solo and small-group RPGs. Dice, a dungeon
map you can build and run live, a journal, and LAN or server multiplayer —
in one window, on your own machine, with no account and no subscription.

Windows, or a Mac running the source. Python 3 and Tkinter, plus Pillow for
pictures. The packaged Windows build needs none of that.

---

## Getting it running

**The easy way** — download the packaged build, unzip it anywhere, and
double-click **Bredmyj's VTT.exe**. No Python, no install, no administrator
rights.

**From source** — download the source zip and double-click **launcher.bat**.
It looks for Python, tells you exactly where to get it if it's missing, and
offers to install Pillow for you. Run **Create Shortcut.bat** once and you
get a proper desktop shortcut with an icon.

**On a Mac** — install Python from python.org, then double-click
**launcher.command**. macOS will block it the first time for being
downloaded rather than bought; Control-click the file and choose **Open**,
and it stops asking. Full steps, including what to do when there is no
*Open* on that menu, are in the README.

**Not on an iPhone or iPad.** This is a desktop program that draws its own
windows, and iOS does not run that kind of app at all.

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

### Encounters

Build a fight and run it, in its own window. A roster on the left, the
selected creature's stat block on the right, a few lines on what is going on
and what comes of it underneath, and — once it is running — a turn bar showing
the round and whose turn it is.

- **A library per campaign**, sixteen creatures deep to begin with — bat up to
  ogre, each with its ability scores, its attacks and a line on what it is.
  *+ Add creature* turns the roster into the library: click one to look it
  over, set **How many** with the arrows, and *Add 3 x Goblin* puts three in
  and comes straight back. A creature in an encounter is a copy, so wounding
  the goblin here leaves the library entry untouched, and a second Goblin is
  named Goblin 2 so the turn order is never ambiguous. *Save to library* keeps
  one of your own — scores, attacks, description and all.
- **Players come off the game map**, each with whoever they belong to and
  their stats brought across, along with anyone at the table who has no
  character yet. Or add one by hand with a name and an initiative bonus.
- **Ability scores that do the arithmetic.** Each score shows the modifier it
  is worth as you type it — 10 is +0, 19 is +4. Tie an attack to STR and a
  belt of giant strength moves its to-hit and its damage on its own.
- **Attacks and saves you can click.** An attack rolls the d20 to hit and the
  damage together. A save is the players' number to beat, so it shows the DC,
  which save it is, and what happens either way — and rolls only the damage.
- **A roll log beside the stats**, newest on top, keeping the last forty —
  what was rolled, what was added and the total, with a natural 20 in green
  and a 1 in red.
- **Whatever stats your game needs.** Right-click the stat block to add,
  rename or remove one — there is no fixed list. Anything that reads as a roll
  gets a **roll** beside it, and you can pin a die and an ability score to
  anything that does not.
- **A DMG box beside the hit points.** Type the damage, press Enter, and it
  comes off. A minus heals, and every hit is logged with its arithmetic.
- **A description** on every creature, and **system presets** — which ability
  scores exist and what a score is worth — with Dungeons & Dragons set up and
  room to make your own.
- **What's going on** and **Treasure and rewards** along the bottom: the two
  ends of a fight, one written before it starts and one once it is won.
- **Initiative, singly or in gangs.** Every creature gets its own d20, or
  Ctrl-click a group and roll one d20 for the lot of them, each still adding
  its own modifier.
- **Encounters saved under a name**, from a **File** menu of its own: build a
  fight once, name it, and load it back when the party gets there. Rename,
  duplicate and delete them from one place, and mark the ones worth reusing
  as available to every campaign rather than just the one they were built
  for.

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
table needs 1.4.1** — anyone on an older build will be turned away with a
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
and per-campaign storage of its own. The five that ship — the map, the
journal, the encounter builder, the fate chart and the meaning tables — are
written against exactly the same API, so nothing they do is off-limits to
yours.

---

## New in this release

**Encounters.** A new mod, at **Tools → Encounters...**, for building a fight
and running it round by round — the piece that sat between the dice roller's
Initiative panel and the figures on the map, with nothing joining them up.

Assemble the room from a per-campaign creature library, pull the players
straight off the game map with their stats, then roll initiative — a d20
each, or one d20 for a gang that acts together with everyone still adding
their own modifier. *Run Encounter* opens a turn bar under the summary:
the round, whose turn it is, who is next. **Next** hands the turn on and
lifts that creature to the top of the roster; a full cycle ticks the round.

Every count sits in its own box and can be typed over, so a rolled number is
only ever a suggestion — overrule one, set a whole room by hand without
rolling, or empty a box to put that creature back to no count at all. The
list settles when you leave the box rather than under your fingers, and a
correction made mid-fight leaves the turn with whoever is up.

Creatures in an encounter are copies, so the library entry is never wounded
and the same goblin can be pulled in again next week at full health. Stats
are whatever the creature carries — right-click to add, rename or remove
one — so it does not assume your system's stat line.

**Creatures worth adding, and a way to add them.** *+ Add creature* now turns
the roster into the library rather than dropping a menu over it: click an
entry and it opens on the right — scores, attacks, description — so you can
look it over before it goes anywhere. Along the bottom sit **How many**, with
up and down arrows, and **Add** right beside them, so three goblins is two
clicks and the list comes straight back.

The library ships with sixteen creatures instead of six, from a bat to an
ogre, each with its ability scores, its attacks and a line on what it is. An
existing campaign gains the new ones without losing anything it had; the six
originals fill themselves out unless you had already changed them.

**Numbers that do their own arithmetic.** Every creature now carries ability
scores, each showing the modifier it is worth as you type — 10 is +0, 19 is
+4, 7 is -2. Tie an attack to STR and a belt of giant strength is one number
in one box: its to-hit and its damage both follow.

**Things it can do.** Under the stats is a list of attacks and saves. Clicking
an attack rolls the d20 to hit *and* rolls the damage, in one go. A save is
the players' number to beat, so nothing is rolled for it — the DC, which save
it is, and what happens on a fail or a success are shown, and only its damage
rolls.

**A roll log beside the stats.** Every roll made in the window goes into it,
newest on top — what was rolled, what was added, the total, a natural 20 in
green and a 1 in red. It keeps the last forty and stays put when you click a
different creature, so the round can be read back without leaving the fight.
Roll History in the main window still gets everything as well.

**Roll beside the numbers.** A stat whose value is dice rolls those dice; a
stat whose value is a modifier, on something named like a check, rolls a d20
and adds it. For anything else, right-click it and say which die and which
ability score to use.

**Systems.** Which ability scores exist, what a score is worth, and what a new
creature starts with are a preset now, named after the game. Dungeons &
Dragons is set up, Plain Numbers is there for games without scores, and you
can build your own — add and remove abilities, and choose whether a score is
a score or already the modifier. Switching never touches a creature that
already exists.

**A description** on every creature, under everything else.

**Damage, taken rather than worked out.** Beside the hit points is a small box
marked **DMG**. Type what the creature just took, press Enter, and it comes
off — 59, take 17, and the box reads 42. Nobody at a table does the
subtraction in their head and types the answer, so this does not ask them to.
A minus heals. Each hit goes into the roll log with the arithmetic behind it,
red coming off and green going back on, so a creature's whole afternoon reads
back at a glance.

**Treasure and rewards.** A second box along the bottom, under what is going
on — what the party walks away with. Coin, what was on the bodies, the thing
in the locked chest, the favour owed by whoever you rescued.

**Encounters you can keep.** The window has a **File** menu now. Build a
fight, name it — *Treeline Ambush*, *Spiders in the Mill Loft* — and load it
back when the party finally gets there, creatures, notes and treasure
together. The name sits over the roster and in the title bar so you can see
which one is open.

*Saved encounters...* is the rest of it: rename one whose name stopped making
sense, duplicate one to change a little rather than build it again, delete
one. A saved encounter is a prepared fight rather than one halfway through, so
initiative is not kept with it and a loaded one always starts with nobody
having rolled.

Nothing has to be saved twice. Starting a new encounter or loading another one
writes the open one back to its name first; only one that has never been named
stops to ask.

**And shared across campaigns.** Tick *Save it for every campaign* and an
encounter moves out of the campaign onto a shelf every campaign can see — the
bar fight, the road patrol, whatever turns up when the party takes too long.
Those live in `shared_encounters.json` beside the program, with the profile
and the server list, and travel with the folder like everything else.

---

## Also new: it runs on a Mac

Less a port than the end of an assumption. Three things took Windows for
granted, and all three failed quietly rather than loudly:

- **Right-click.** Tk on macOS calls the right mouse button Button-2 and the
  middle one Button-3 — the opposite way round from everywhere else. Every
  context menu in this app is bound to Button-3, so on a Mac not one of them
  would have opened. A right-click anywhere is now turned into the Button-3
  the widget under the pointer is already listening for, which covers the
  map, the journal and anything a mod adds later without their knowing.
- **Scrolling.** Windows sends 120 per notch of the wheel, a Mac sends 1 —
  so the panels that divided by 120 scrolled by exactly nothing.
- **Fonts.** Segoe UI and Consolas are Windows fonts. The app now asks for
  what is installed and takes the first one it finds.

**launcher.command** is the Mac counterpart to launcher.bat: it finds Python,
checks Tkinter came with it, offers Pillow, and starts the app. **Run
Server.command** does the same for hosting. Where these notes say Ctrl-click
to pick several of something, a Mac uses Command-click.

macOS blocks the launcher the first time for having been downloaded rather
than bought. Control-click it, choose **Open**, and it stops asking; the
README has the longer way round for when that menu has no *Open* on it.

None of this changes anything on Windows — every one of them is a branch that
runs only on macOS.

---

## New in 1.3.0

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

- **The packaged build is Windows only.** A Mac runs the source through
  **launcher.command**; there is no `.app` to double-click yet, and macOS
  blocks the launcher once, the first time.
- **Mac support is new** and has had far less use than the Windows side.
  Right-click, scrolling and the fonts are handled; anything that looks
  wrong is worth reporting.
- **No iOS.** An iPhone or iPad cannot run it and cannot join a game either
  — every seat at the table needs this same program.
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

## Bug fixes in 1.3.0

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
