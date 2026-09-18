"""Card Dungeon - a deck of cards, a floor of rooms, and one life to spend.

Opens from Tools > Card Dungeon, next to the Game Map and Encounters. A whole
small game rather than a table aid: pick a dungeon, build a deck, then click
your way through the rooms until the floor is clear or you are not.

Four screens, and they run in a loop:

  * the hub      - the dungeons on offer, what each one will throw at you,
                   and how big the collection has grown.
  * the prep     - the deck builder. The briefing on the left says what the
                   floor is made of; the collection and the deck sit beside
                   it. Nothing stops you walking in with ten Strikes, but the
                   briefing did warn you about the pits.
  * the delve    - the floor itself, drawn as rooms joined by corridors. A
                   room lights up once the rooms it waits on are cleared;
                   click it to go in.
  * the duel     - the fight. Your hand at the bottom, the enemy at the top,
                   and the banked action points down the middle.

The rules in one breath: decks are ten cards or more, a turn begins by
throwing away whatever is still in your hand and drawing five, and playing a
card costs action points that you bank a turn at a time. Attacks land at the
end of the turn that played them, against whatever block the other side is
still standing behind - so the cards you did not spend are the cards that
keep you alive. Quick cards break that rule: they can be played while the
other side is swinging, which is how a fight gets finished without a scratch.

The one thing that is easy to miss is where the pressure comes from. A hand
is swept at the start of your turn, not the end of it, so holding a Guard
back is never free - it survives exactly one enemy turn and is then gone. Every
turn asks the same question: everything into the attack, or something into
staying upright?

Rooms are not all fights. A hazard is paid before anything else happens, in
cards of the right type off the top of your opening hand, and you carry that
thinner hand into the fight that follows - which is the whole reason the
briefing is worth reading.

What survives a run is the collection: cards found in the dungeon and handed
out for clearing it. Decks are built out of that collection each time, so the
next delve starts from what the last one paid for. Everything belongs to the
campaign that is open, so each save file keeps its own collection and its own
run in progress.

The rules live in `Duel`, which knows nothing about Tk and can be driven from
a prompt. The window on top of it only draws what `Duel` says is true.
"""

import copy
import random
import tkinter as tk
from tkinter import messagebox, simpledialog

import dice_api

PLUGIN = {
    "name": "Card Dungeon",
    "version": "1.0",
    "description": "A deck-building dungeon crawl: build a deck, take a floor.",
    "author": "bundled",
}

rng = random.SystemRandom()

# How many cards a hand is refilled to at the start of a turn, and the
# smallest deck anyone is allowed to walk in with. The floor is ten because
# below that a deck stops being a choice; most decks want to be bigger, since
# a deck you see all of every two turns has nothing left to surprise you with.
HAND_SIZE = 5
MIN_DECK = 10
MAX_DECK = 30

# The three things a card can be about. A hazard asks for a type by name -
# the pit wants acrobatics - so these are the vocabulary the dungeon and the
# collection both speak.
TYPES = ("might", "acrobatics", "magic")

TYPE_COLOR = {
    "might": "#c9705a",
    "acrobatics": "#5fa8d3",
    "magic": "#9b7fd4",
}

# One acrobatics card in three is worth a point of initiative. Going first is
# worth having, so a deck packed for the pits is quicker off the mark as well
# - the same cards paying twice, which is what makes the type worth building
# around rather than just insuring against.
INIT_PER_ACROBATICS = 3

# Every turn banks one point whatever you drew, so a hand with no Focus in it
# is a slow turn rather than a dead one. Everything above this comes off cards.
BASE_AP = 1

# Decks cycle forever - a swept hand goes back under the draw pile - so two
# sides that cannot finish each other would trade cards until the heat death
# of the universe. It is not hypothetical: anything that heals itself beats a
# deck that chips for less than the healing, and the fight simply never ends.
#
# So the barrow starts closing in. From this round on, both sides take
# damage at the top of their own turn, one more each round, and it goes
# straight past block - there is no card that answers it. It ends a stalled
# fight in a handful of rounds and it ends it for whoever is further behind,
# which is the right answer. In a fight that is going anywhere it never fires.
GRIND_ROUND = 15


# --------------------------------------------------------------------------
# The card pool
# --------------------------------------------------------------------------
# A card is a plain dict and does only what its numbers say: deal damage, add
# block, heal, draw, bank action points. Keeping the vocabulary this small is
# deliberate - every card in the game is something `Duel` can already
# resolve, and a new card is a line of data rather than a new rule.
#
#   cost    action points it takes to play
#   damage  added to the attack that lands at the end of this turn
#   block   added to the wall the other side has to get through
#   heal    hit points back, never above the maximum
#   draw    extra cards, off the top, straight away
#   ap      action points banked (what a Focus card is for)
#   quick   can be played while the other side is swinging
#   face    if set, the card can instead be played face down for this many
#           action points - see below
#   unlock  floors you must have cleared before a shop will stock it
#
# Commons carry `face`, and nothing else does. That one line is most of the
# economy: a common is never a dead draw, because the worst it can be is an
# action point, and it is also the thing you are trying to grow out of. Which
# sets the trap the whole shop is built on - sell your commons to afford the
# good cards and you will find you can no longer afford to play them.
def _card(cid, name, kind, ctype, rarity="common", cost=0, damage=0, block=0,
          heal=0, draw=0, ap=0, quick=False, face=0, unlock=0, text="",
          enemy_only=False):
    return {
        "id": cid, "name": name, "kind": kind, "type": ctype,
        "rarity": rarity, "cost": cost, "damage": damage, "block": block,
        "heal": heal, "draw": draw, "ap": ap, "quick": quick, "face": face,
        "unlock": unlock, "text": text, "enemy_only": enemy_only,
    }


def _common(cid, name, kind, ctype, **kw):
    """A common. Weak for its cost, and worth an action point face down."""
    kw.setdefault("face", 1)
    return _card(cid, name, kind, ctype, rarity="common", **kw)


def _uncommon(cid, name, kind, ctype, **kw):
    return _card(cid, name, kind, ctype, rarity="uncommon", **kw)


def _rare(cid, name, kind, ctype, **kw):
    return _card(cid, name, kind, ctype, rarity="rare", **kw)


def _foe(cid, name, kind, ctype, **kw):
    return _card(cid, name, kind, ctype, enemy_only=True, **kw)


# What the shop charges, and what it pays. Selling is worth well under half
# of buying, so churning the collection for gold is a losing trade and the
# only way to get rich is to go back down the stairs.
PRICE = {"common": 10, "uncommon": 32, "rare": 95}
SELL = {"common": 4, "uncommon": 13, "rare": 38}

RARITIES = ("common", "uncommon", "rare")

RARITY_COLOR = {
    "common": "#8b90a0",
    "uncommon": "#5fd38d",
    "rare": "#e0bb63",
}


CARDS = {c["id"]: c for c in [
    # -- commons -----------------------------------------------------------
    # The starting stock, and the resource base. Every one of these is a
    # point of action banked if you would rather have the point.
    _common("strike", "Strike", "attack", "might", cost=1, damage=2,
            text="Deal 2 damage."),
    _common("guard", "Guard", "defend", "might", cost=1, block=3,
            text="Gain 3 block."),
    _common("jab", "Jab", "attack", "might", cost=1, damage=1, quick=True,
            text="Quick. Deal 1 damage."),
    _common("parry", "Parry", "defend", "might", cost=1, block=2, quick=True,
            text="Quick. Gain 2 block."),
    _common("second_wind", "Second Wind", "utility", "might", cost=1, heal=3,
            text="Heal 3."),
    _common("brace", "Brace", "defend", "might", block=2,
            text="Free. Gain 2 block."),
    _common("tumble", "Tumble", "defend", "acrobatics", block=1, quick=True,
            text="Quick. Free. Gain 1 block."),
    _common("dagger_flick", "Dagger Flick", "attack", "acrobatics", cost=1,
            damage=1, quick=True, text="Quick. Deal 1 damage."),
    _common("vault", "Vault", "utility", "acrobatics", draw=1,
            text="Free. Draw a card."),
    _common("sidestep", "Sidestep", "defend", "acrobatics", cost=1, block=2,
            quick=True, text="Quick. Gain 2 block."),
    _common("spark", "Spark", "attack", "magic", damage=1,
            text="Free. Deal 1 damage."),
    _common("kindle", "Kindle", "attack", "magic", cost=1, damage=2,
            text="Deal 2 damage."),
    _common("mend", "Mend", "utility", "magic", cost=1, heal=3,
            text="Heal 3."),
    _common("ward", "Ward", "defend", "magic", cost=1, block=2, quick=True,
            text="Quick. Gain 2 block."),
    # Focus banks two where a common face down banks one, which is the only
    # reason to give a card slot to banking on purpose.
    _common("focus", "Focus", "power", "magic", ap=2,
            text="Free. Bank 2 action points."),

    # -- uncommons ---------------------------------------------------------
    # No face value: these are what you spend the points on, not what you
    # make them out of. Rarity buys efficiency, not new rules.
    _uncommon("power_strike", "Power Strike", "attack", "might", cost=2,
              damage=5, text="Deal 5 damage."),
    _uncommon("bulwark", "Bulwark", "defend", "might", cost=2, block=7,
              text="Gain 7 block."),
    _uncommon("riposte", "Riposte", "defend", "might", cost=2, block=3,
              damage=3, quick=True,
              text="Quick. Gain 3 block and deal 3 damage."),
    _uncommon("shield_bash", "Shield Bash", "attack", "might", cost=2,
              damage=3, block=3, text="Deal 3 damage and gain 3 block."),
    _uncommon("rally", "Rally", "utility", "might", cost=2, heal=5, block=2,
              unlock=1, text="Heal 5 and gain 2 block."),
    _uncommon("swift_cut", "Swift Cut", "attack", "acrobatics", cost=1,
              damage=3, quick=True, text="Quick. Deal 3 damage."),
    _uncommon("flurry", "Flurry", "attack", "acrobatics", cost=2, damage=4,
              draw=1, text="Deal 4 damage. Draw a card."),
    _uncommon("shadow_step", "Shadow Step", "defend", "acrobatics", cost=2,
              block=5, draw=1, quick=True,
              text="Quick. Gain 5 block. Draw a card."),
    _uncommon("roll_aside", "Roll Aside", "defend", "acrobatics", cost=1,
              block=3, quick=True, text="Quick. Gain 3 block."),
    _uncommon("firebolt", "Firebolt", "attack", "magic", cost=2, damage=5,
              text="Deal 5 damage."),
    _uncommon("mage_armor", "Mage Armor", "defend", "magic", cost=2, block=7,
              text="Gain 7 block."),
    _uncommon("siphon", "Siphon", "attack", "magic", cost=2, damage=4, heal=3,
              text="Deal 4 damage. Heal 3."),
    _uncommon("deep_focus", "Deep Focus", "power", "magic", cost=1, ap=4,
              unlock=1, text="Bank 4 action points."),

    # -- rares -------------------------------------------------------------
    # Gated behind floors cleared, priced accordingly, and stocked one at a
    # time. Anything that simply draws cards lives up here: drawing is the
    # strongest thing a card can do in a game where the hand is the clock.
    _rare("cleave", "Cleave", "attack", "might", cost=3, damage=9, unlock=1,
          text="Deal 9 damage."),
    _rare("shield_wall", "Shield Wall", "defend", "might", cost=3, block=12,
          unlock=1, text="Gain 12 block."),
    _rare("executioner", "Executioner", "attack", "might", cost=4, damage=13,
          unlock=2, text="Deal 13 damage."),
    _rare("pounce", "Pounce", "attack", "acrobatics", cost=3, damage=7,
          draw=1, unlock=1, text="Deal 7 damage. Draw a card."),
    _rare("grappling_hook", "Grappling Hook", "utility", "acrobatics", cost=1,
          draw=3, unlock=2, text="Draw 3 cards."),
    _rare("foresight", "Foresight", "utility", "acrobatics", draw=2, unlock=2,
          text="Free. Draw 2 cards."),
    _rare("chain_lightning", "Chain Lightning", "attack", "magic", cost=4,
          damage=13, unlock=2, text="Deal 13 damage."),
    _rare("sanctuary", "Sanctuary", "defend", "magic", cost=3, block=10,
          heal=5, unlock=2, text="Gain 10 block and heal 5."),
    _rare("wellspring", "Wellspring", "power", "magic", cost=1, ap=3, draw=2,
          unlock=3, text="Bank 3 action points. Draw 2 cards."),
    _rare("time_slip", "Time Slip", "utility", "magic", ap=2, draw=2,
          unlock=3, text="Free. Bank 2 action points. Draw 2 cards."),

    # -- what the dungeon fights with --------------------------------------
    # The same shape, kept out of the collection so a lucky find never hands
    # you a skeleton's bow. No face value either: an enemy deck is built to
    # be what it is, not to be taken apart for parts.
    _foe("e_claw", "Claw", "attack", "might", cost=1, damage=2,
         face=1, text="Deal 2 damage."),
    _foe("e_bite", "Bite", "attack", "might", cost=1, damage=1,
         face=1, text="Deal 1 damage."),
    _foe("e_scurry", "Scurry", "defend", "acrobatics", block=2,
         face=1, text="Free. Gain 2 block."),
    _foe("e_arrow", "Arrow", "attack", "acrobatics", cost=1, damage=2,
         face=1, text="Deal 2 damage."),
    _foe("e_aimed_shot", "Aimed Shot", "attack", "acrobatics", cost=2,
         damage=4, text="Deal 4 damage."),
    _foe("e_bone_shield", "Bone Shield", "defend", "might", cost=1, block=3,
         text="Gain 3 block."),
    _foe("e_rusty_blade", "Rusty Blade", "attack", "might", cost=1, damage=3,
         face=1, text="Deal 3 damage."),
    _foe("e_shove", "Shove", "attack", "might", cost=1, damage=2, quick=True,
         text="Quick. Deal 2 damage."),
    _foe("e_hide", "Thick Hide", "defend", "might", cost=1, block=5,
         text="Gain 5 block."),
    _foe("e_lunge", "Lunge", "attack", "might", cost=3, damage=7,
         text="Deal 7 damage."),
    _foe("e_command", "Command", "power", "might", cost=1, ap=2,
         text="Bank 2 action points."),
    _foe("e_grave_chill", "Grave Chill", "attack", "magic", cost=2, damage=4,
         heal=2, text="Deal 4 damage. Heal 2."),
    _foe("e_pike", "Pike Thrust", "attack", "might", cost=2, damage=5,
         text="Deal 5 damage."),
    _foe("e_ember", "Ember", "attack", "magic", cost=1, damage=3,
         face=1, text="Deal 3 damage."),
    _foe("e_furnace", "Furnace Blast", "attack", "magic", cost=3, damage=8,
         text="Deal 8 damage."),
    _foe("e_slag", "Slag Skin", "defend", "might", cost=2, block=7,
         text="Gain 7 block."),
    _foe("e_crown", "Crown Toll", "attack", "magic", cost=3, damage=7, heal=4,
         text="Deal 7 damage. Heal 4."),
    _foe("e_hollow", "Hollow Guard", "defend", "magic", cost=2, block=8,
         text="Gain 8 block."),
]}

PLAYER_CARDS = [cid for cid, c in CARDS.items() if not c["enemy_only"]]

# What a new campaign starts with: nine commons and one uncommon, which is
# exactly one legal deck and almost no choice about it. The choices start at
# the shop, which is the point - the first thing the game teaches is that the
# deck you have is not the deck you want.
STARTER = {
    "strike": 3, "guard": 2, "focus": 2, "tumble": 1, "spark": 1,
    "power_strike": 1,
}


# --------------------------------------------------------------------------
# What lives down there
# --------------------------------------------------------------------------
# An enemy is a pile of hit points and a deck, and it plays by exactly the
# rules you do - draws to five, banks a point a turn, lands its attack at the
# end of its turn. A skeleton archer is dangerous because its deck is mostly
# arrows, not because it is allowed to cheat.
#
# Ten cards each, the same floor a player builds to. A boss gets twelve,
# which is the only concession in here to being a boss.
def _enemy(eid, name, glyph, tier, hp, init, deck, text, boss=False):
    return {"id": eid, "name": name, "glyph": glyph, "tier": tier, "hp": hp,
            "init": init, "deck": deck, "text": text, "boss": boss}


ENEMIES = {e["id"]: e for e in [
    # -- tier one ----------------------------------------------------------
    _enemy("giant_rat", "Giant Rat", "r", 1, 6, 3,
           {"e_bite": 5, "e_scurry": 3, "focus": 2},
           "Fast and thin. It will out-roll you and then fail to hurt you."),
    _enemy("skeleton_archer", "Skeleton Archer", "s", 1, 8, 1,
           {"e_arrow": 4, "e_aimed_shot": 1, "e_bone_shield": 2, "focus": 3},
           "Arrows most turns, a shield when it draws one. Nothing quick in "
           "the deck at all - what it shows you is what it has."),
    _enemy("goblin_cutter", "Goblin Cutter", "g", 1, 9, 1,
           {"e_rusty_blade": 4, "e_shove": 2, "e_bone_shield": 1, "focus": 3},
           "Carries two Shoves, which are quick - block that looked like "
           "enough can turn out not to be."),

    # -- tier two ----------------------------------------------------------
    _enemy("cave_lurker", "Cave Lurker", "L", 2, 14, 0,
           {"e_claw": 4, "e_hide": 2, "e_lunge": 1, "focus": 3},
           "Slow, thick-skinned, and holding one Lunge that costs three to "
           "play. It will get there eventually."),
    _enemy("skeleton_pikeman", "Skeleton Pikeman", "p", 2, 13, 2,
           {"e_pike": 3, "e_rusty_blade": 2, "e_bone_shield": 2,
            "e_command": 3},
           "Banks hard and swings at five. The turns it spends banking are "
           "the turns you have to use."),
    _enemy("bog_shambler", "Bog Shambler", "b", 2, 16, -1,
           {"e_claw": 3, "e_hide": 3, "e_grave_chill": 2, "focus": 2},
           "Last to move every time, and heals off its own attacks. Slow "
           "damage loses to it."),

    # -- tier three --------------------------------------------------------
    _enemy("kiln_hound", "Kiln Hound", "h", 3, 15, 4,
           {"e_ember": 4, "e_bite": 2, "e_shove": 2, "focus": 2},
           "Goes first almost always, and opens hot. Survive the first two "
           "rounds and it has nothing left."),
    _enemy("slag_golem", "Slag Golem", "G", 3, 20, -1,
           {"e_slag": 3, "e_claw": 3, "e_lunge": 2, "e_command": 2},
           "Seven block a card and a Lunge behind it. Chip damage does "
           "nothing at all here."),
    _enemy("ember_wisp", "Ember Wisp", "w", 3, 13, 3,
           {"e_ember": 5, "e_scurry": 2, "focus": 3},
           "Nothing but Embers. Predictable, quick, and it adds up."),
    _enemy("drowned_thrall", "Drowned Thrall", "t", 3, 19, 0,
           {"e_grave_chill": 3, "e_claw": 3, "e_hollow": 2, "focus": 2},
           "Heals two every time it hits. Kill it in bursts or not at all."),

    # -- tier four ---------------------------------------------------------
    _enemy("crown_thrall", "Crown Thrall", "T", 4, 26, 1,
           {"e_crown": 2, "e_lunge": 3, "e_claw": 2, "e_command": 3},
           "Heals four every Toll it lands. Damage spread thin does "
           "nothing to it at all."),
    _enemy("gilded_sentinel", "Gilded Sentinel", "S", 4, 32, -1,
           {"e_hollow": 3, "e_slag": 2, "e_pike": 3, "e_command": 2},
           "Eight block a card and always last to move, so it is standing "
           "behind a wall by the time you swing."),
    _enemy("pale_herald", "Pale Herald", "H", 4, 24, 5,
           {"e_ember": 3, "e_shove": 3, "e_aimed_shot": 2, "focus": 2},
           "Moves first against almost anything, and three of its cards are "
           "quick. Block you have not put up yet is no block."),

    # -- bosses ------------------------------------------------------------
    _enemy("bone_captain", "Bone Captain", "C", 1, 24, 2,
           {"e_rusty_blade": 2, "e_lunge": 2, "e_grave_chill": 2,
            "e_bone_shield": 2, "e_command": 2, "e_shove": 2},
           "Banks two a card and spends them on Lunges. Grave Chill heals "
           "it, so a long fight is its fight, not yours.", boss=True),
    _enemy("drowned_warden", "Drowned Warden", "W", 2, 30, 1,
           {"e_grave_chill": 3, "e_lunge": 3, "e_hide": 2, "e_command": 2,
            "e_bone_shield": 2},
           "Three cards in twelve heal it and three hit for seven. Bring "
           "damage you can land in one turn.", boss=True),
    _enemy("kiln_tyrant", "Kiln Tyrant", "K", 3, 32, 2,
           {"e_furnace": 3, "e_ember": 3, "e_slag": 2, "e_command": 3,
            "e_shove": 1},
           "Furnace Blast costs three and hits for eight, and it banks two "
           "a card to pay for it. Every turn you leave it is a Blast.",
           boss=True),
    _enemy("hollow_king", "The Hollow King", "K", 4, 42, 3,
           {"e_crown": 3, "e_lunge": 3, "e_hollow": 2, "e_command": 3,
            "e_grave_chill": 1},
           "Heals four a Toll behind eight block, and moves first. There is "
           "no grinding this one down - it has to come off in slabs.",
           boss=True),
]}

FOES_BY_TIER = {}
for _e in ENEMIES.values():
    if not _e["boss"]:
        FOES_BY_TIER.setdefault(_e["tier"], []).append(_e["id"])


# A hazard is the toll on a door: spend this many cards of this type out of
# your opening hand, or take the damage. It is paid before anything else in
# the room happens, out of the hand you then have to fight with - which is
# what makes a deck with no acrobatics in it a decision rather than an
# oversight.
HAZARDS = {h["id"]: h for h in [
    {"id": "pitfall", "name": "Pitfall", "type": "acrobatics", "cards": 1,
     "damage": 2, "tier": 1,
     "text": "A hole where the floor was. Jump it or fall in."},
    {"id": "barred_gate", "name": "Barred Gate", "type": "might", "cards": 1,
     "damage": 3, "tier": 1,
     "text": "Rusted shut. Shoulder it and take the splinters."},
    {"id": "warding_glyph", "name": "Warding Glyph", "type": "magic",
     "cards": 1, "damage": 3, "tier": 1,
     "text": "Still lit after all this time. Answer it in kind or walk "
             "through it."},
    {"id": "collapsing_stair", "name": "Collapsing Stair",
     "type": "acrobatics", "cards": 1, "damage": 3, "tier": 2,
     "text": "The steps go as you cross them."},
    {"id": "yawning_pit", "name": "Yawning Pit", "type": "acrobatics",
     "cards": 2, "damage": 5, "tier": 2,
     "text": "Too wide to jump cleanly. Two acrobatics, or a long drop."},
    {"id": "seized_winch", "name": "Seized Winch", "type": "might",
     "cards": 2, "damage": 5, "tier": 2,
     "text": "The chain has not moved in a century. It will take both arms."},
    {"id": "old_binding", "name": "Old Binding", "type": "magic", "cards": 2,
     "damage": 5, "tier": 2,
     "text": "Someone sealed this, and meant it."},
    {"id": "ember_vent", "name": "Ember Vent", "type": "acrobatics",
     "cards": 2, "damage": 7, "tier": 3,
     "text": "It breathes out every few seconds. Time it."},
    {"id": "slag_door", "name": "Slag Door", "type": "might", "cards": 2,
     "damage": 7, "tier": 3,
     "text": "Cooled shut across the frame. It has to come off."},
    {"id": "kings_ward", "name": "The King's Ward", "type": "magic",
     "cards": 2, "damage": 7, "tier": 3,
     "text": "Older than the crown, and it still knows its business."},
]}

HAZARDS_BY_TIER = {}
for _h in HAZARDS.values():
    HAZARDS_BY_TIER.setdefault(_h["tier"], []).append(_h["id"])


# --------------------------------------------------------------------------
# The floors
# --------------------------------------------------------------------------
# A room carries its own position, because the map is drawn from this and
# nothing else - move the numbers and the corridors follow. `needs` is the
# rooms that must be cleared first; a room with an empty `needs` is where you
# come in. Corridors are drawn from `needs`, so the shape of the floor and
# the order it opens in can never disagree.
#
# What a room *holds* is not written here. The shape is authored and the
# contents are rolled when you sit down to prepare for the floor, so the same
# stair is a different walk every time. `slot` says what kind of room it is:
#
#   start   the way in, always empty
#   fight   something from this floor's pool is waiting
#   vault   no fight, but a good place to put the loot
#   rest    hit points back
#   boss    the one at the bottom
#
# `toll` marks a room that may be given a hazard; `loot` marks one that may
# be given a card or a purse. Both are budgets spent by `roll_plan`.
def _room(rid, name, x, y, needs, slot="fight", toll=False, loot=False,
          text=""):
    return {"id": rid, "name": name, "x": x, "y": y, "needs": needs,
            "slot": slot, "toll": toll, "loot": loot, "text": text}


DUNGEONS = [
    {
        "id": "barrow_steps",
        "name": "The Barrow Steps",
        "level": 1, "tier": 1, "hp": 34, "rest": 10, "needs": None,
        "text": "A stair cut into a burial mound, and something at the "
                "bottom that used to give orders.",
        "flavour": "Shallow, and honest about it.",
        "foes": [1], "bosses": ["bone_captain"], "hazard_tiers": [1],
        "budget": {"tolls": 2, "cards": 2, "purses": 2},
        "loot": {"common": 84, "uncommon": 15, "rare": 1},
        "purse": (10, 18), "clear_gold": (30, 45),
        "rooms": [
            _room("mouth", "Barrow Mouth", 72, 214, [], "start",
                  text="Cold air coming up the steps."),
            _room("stair", "Cracked Stair", 210, 112, ["mouth"], toll=True,
                  text="Something is already living in the gap."),
            _room("alcove", "Bone Alcove", 210, 316, ["mouth"], loot=True,
                  text="It was waiting, and it does not need to breathe."),
            _room("niche", "Offering Niche", 352, 112, ["stair"], "vault",
                  loot=True, text="Grave goods, still where they were left."),
            _room("post", "Guard Post", 352, 316, ["alcove"], toll=True,
                  loot=True, text="The gate was barred from this side."),
            _room("water", "Still Water", 486, 214, ["niche", "post"], "rest",
                  text="Clean, somehow. Drink and sit a while."),
            _room("rest", "The Captain's Rest", 618, 214, ["water"], "boss",
                  text="It stands up as you come in."),
        ],
    },
    {
        "id": "sunken_vault",
        "name": "The Sunken Vault",
        "level": 2, "tier": 2, "hp": 42, "rest": 12, "needs": "barrow_steps",
        "text": "Below the barrow, past where the water starts. Whatever is "
                "down here was locked in on purpose.",
        "flavour": "Wetter, and it bites back.",
        "foes": [1, 2], "bosses": ["drowned_warden"], "hazard_tiers": [1, 2],
        "budget": {"tolls": 3, "cards": 2, "purses": 2},
        "loot": {"common": 62, "uncommon": 33, "rare": 5},
        "purse": (16, 28), "clear_gold": (50, 70),
        "rooms": [
            _room("entry", "Flooded Entry", 72, 214, [], "start",
                  text="Knee-deep and rising slowly."),
            _room("silt", "Silt Passage", 204, 112, ["entry"], toll=True,
                  text="The floor gives underfoot."),
            _room("cells", "Drowned Cells", 204, 316, ["entry"], loot=True,
                  text="The doors open outward. All of them."),
            _room("glyph", "Glyph Door", 340, 112, ["silt"], "vault",
                  toll=True, loot=True, text="Lit from inside the stone."),
            _room("sump", "The Sump", 340, 316, ["cells"], toll=True,
                  loot=True, text="Something moves under the water."),
            _room("pocket", "Air Pocket", 474, 214, ["glyph", "sump"], "rest",
                  text="Dry stone and a draught from somewhere."),
            _room("vault", "The Vault", 610, 214, ["pocket"], "boss",
                  text="It has been standing here the whole time."),
        ],
    },
    {
        "id": "ashen_kiln",
        "name": "The Ashen Kiln",
        "level": 3, "tier": 3, "hp": 74, "rest": 18, "needs": "sunken_vault",
        "text": "They fired something here for a long time, and never quite "
                "let it go out.",
        "flavour": "Hot, fast, and it opens hard.",
        "foes": [2, 3], "bosses": ["kiln_tyrant"], "hazard_tiers": [2, 3],
        "budget": {"tolls": 3, "cards": 3, "purses": 3},
        "loot": {"common": 40, "uncommon": 46, "rare": 14},
        "purse": (24, 40), "clear_gold": (75, 105),
        "rooms": [
            _room("gate", "Kiln Gate", 66, 214, [], "start",
                  text="The handle is warm."),
            _room("flue", "The Flue", 190, 104, ["gate"], toll=True,
                  text="Narrow, and it draws air past you the wrong way."),
            _room("yard", "Cinder Yard", 190, 324, ["gate"], loot=True,
                  text="Ankle-deep, and still warm underneath."),
            _room("racks", "Firing Racks", 318, 104, ["flue"], "vault",
                  loot=True, text="Whatever was stacked here fused."),
            _room("channel", "Slag Channel", 318, 324, ["yard"], toll=True,
                  loot=True, text="It ran molten once and set where it was."),
            _room("bellows", "The Bellows", 446, 214, ["racks", "channel"],
                  toll=True, loot=True,
                  text="Big enough to walk inside. Something did."),
            _room("draw", "Draw Pit", 566, 104, ["bellows"], "rest",
                  text="Cool air, at last, from somewhere below."),
            _room("throne", "The Kiln Floor", 566, 324, ["bellows"], "boss",
                  text="It was never not here."),
        ],
    },
    {
        "id": "hollow_crown",
        "name": "The Hollow Crown",
        "level": 4, "tier": 4, "hp": 78, "rest": 22, "needs": "ashen_kiln",
        "text": "The bottom of it. Whoever the barrow was built for is "
                "still sitting down here, and still collecting.",
        "flavour": "Everything at once, and then the King.",
        "foes": [3, 4], "bosses": ["hollow_king"], "hazard_tiers": [2, 3],
        "budget": {"tolls": 4, "cards": 3, "purses": 3},
        "loot": {"common": 26, "uncommon": 48, "rare": 26},
        "purse": (32, 52), "clear_gold": (110, 150),
        "rooms": [
            _room("descent", "The Descent", 66, 214, [], "start",
                  text="Steps worn in the middle by a great many feet."),
            _room("court", "Empty Court", 190, 104, ["descent"], toll=True,
                  text="Seats for a hundred, and all of them taken once."),
            _room("treasury", "The Treasury", 190, 324, ["descent"], "vault",
                  toll=True, loot=True, text="Counted, stacked, and left."),
            _room("gallery", "Long Gallery", 318, 104, ["court"], loot=True,
                  text="Portraits, and none of them finished."),
            _room("cistern", "The Cistern", 318, 324, ["treasury"], toll=True,
                  loot=True, text="Still full, and still moving."),
            _room("vestry", "The Vestry", 446, 214, ["gallery", "cistern"],
                  toll=True, loot=True,
                  text="Robes on hooks, shaped like the people in them."),
            _room("stillroom", "The Stillroom", 566, 104, ["vestry"], "rest",
                  text="Somebody kept this one clean."),
            _room("crown", "The Hollow Crown", 566, 324, ["vestry"], "boss",
                  text="It does not stand up. It does not need to."),
        ],
    },
]

DUNGEON_BY_ID = {d["id"]: d for d in DUNGEONS}


# --------------------------------------------------------------------------
# Reading cards
# --------------------------------------------------------------------------
def card(cid):
    """The card with this id. Unknown ids come back as a blank rather than
    an exception, so a save written by an older build still loads - the card
    is simply worthless until the build that knows it comes back."""
    got = CARDS.get(cid)
    if got is None:
        return _card(cid, cid.replace("_", " ").title(), "utility", "might",
                     text="An unfamiliar card.")
    return got


def buy_price(cid):
    return PRICE.get(card(cid)["rarity"], 10)


def sell_price(cid):
    return SELL.get(card(cid)["rarity"], 4)


def deck_list(counts):
    """A {card id: how many} bag flattened into the list a deck really is."""
    out = []
    for cid, count in counts.items():
        out.extend([cid] * max(0, int(count)))
    return out


def deck_types(counts):
    """How many cards of each type are in a deck. What the briefing reads,
    and what decides who moves first."""
    tally = {t: 0 for t in TYPES}
    for cid, count in counts.items():
        ctype = card(cid)["type"]
        tally[ctype] = tally.get(ctype, 0) + max(0, int(count))
    return tally


def deck_faces(counts):
    """How many cards in a deck can be played face down for a point. Below
    about a third, a deck stops being able to pay for itself."""
    return sum(max(0, int(n)) for cid, n in counts.items() if card(cid)["face"])


def init_mod(counts):
    """The bonus on the initiative roll. Acrobatics buys it, three cards to
    the point, so packing for the pits also buys the first swing."""
    return deck_types(counts).get("acrobatics", 0) // INIT_PER_ACROBATICS


# --------------------------------------------------------------------------
# Rolling a floor, and rolling a shop
# --------------------------------------------------------------------------
# The shape of a floor is authored; what is standing in it is not. Both of
# these are rolled once and then kept, so the floor you were briefed on is
# the floor you walk into, and closing the window does not reshuffle it.
def _weighted(table, rand):
    """Pick a key from a {key: weight} table."""
    total = sum(table.values())
    ticket = rand.randint(1, max(1, total))
    running = 0
    for key in sorted(table):
        running += table[key]
        if ticket <= running:
            return key
    return max(table, key=table.get)


def roll_loot_card(table, reach, rand):
    """One card off a floor's loot table. `reach` keeps a floor from handing
    out something four floors deeper than you have any business holding."""
    for _ in range(6):
        rarity = _weighted(table, rand)
        pool = [cid for cid in PLAYER_CARDS
                if CARDS[cid]["rarity"] == rarity
                and CARDS[cid]["unlock"] <= reach]
        if pool:
            return rand.choice(pool)
    return "strike"


def roll_plan(dungeon, rand=None):
    """Decide what is actually in each room of this floor.

    Rolled when you sit down to prepare, not when you walk in, because the
    briefing has to be able to tell you the truth about what is down there -
    a warning about pits is worth nothing if the pits are decided after you
    have finished building the deck.
    """
    rand = rand or rng
    reach = max(0, dungeon["level"] - 1)
    plan = {}
    foes = [e for tier in dungeon["foes"] for e in FOES_BY_TIER.get(tier, [])]
    hazards = [h for tier in dungeon["hazard_tiers"]
               for h in HAZARDS_BY_TIER.get(tier, [])]

    for room in dungeon["rooms"]:
        entry = {}
        if room["slot"] == "boss":
            entry["fight"] = rand.choice(dungeon["bosses"])
        elif room["slot"] == "fight":
            entry["fight"] = rand.choice(foes)
        elif room["slot"] == "rest":
            entry["rest"] = dungeon["rest"]
        plan[room["id"]] = entry

    takers = [r["id"] for r in dungeon["rooms"] if r["toll"]]
    rand.shuffle(takers)
    for rid in takers[:dungeon["budget"]["tolls"]]:
        plan[rid]["hazard"] = rand.choice(hazards)

    # The floor guarantees its haul and only rolls where it comes from, so
    # a delve never pays nothing at all for having gone the long way round.
    spots = [r["id"] for r in dungeon["rooms"] if r["loot"]]
    rand.shuffle(spots)
    for rid in spots[:dungeon["budget"]["cards"]]:
        plan[rid]["find"] = roll_loot_card(dungeon["loot"], reach, rand)

    purses = [r["id"] for r in dungeon["rooms"]
              if r["slot"] in ("fight", "vault", "boss")]
    rand.shuffle(purses)
    low, high = dungeon["purse"]
    for rid in purses[:dungeon["budget"]["purses"]]:
        plan[rid]["gold"] = rand.randint(low, high)

    return plan


def plan_briefing(dungeon, plan):
    """What the prep screen can honestly say about a rolled floor: the tolls
    it will ask for, who is down there, and what it is carrying."""
    tolls = {}
    foes = {}
    cards = 0
    gold = 0
    for room in dungeon["rooms"]:
        entry = plan.get(room["id"], {})
        if entry.get("hazard"):
            hazard = HAZARDS[entry["hazard"]]
            tolls[hazard["type"]] = (tolls.get(hazard["type"], 0)
                                     + hazard["cards"])
        if entry.get("fight"):
            name = ENEMIES[entry["fight"]]["name"]
            foes[name] = foes.get(name, 0) + 1
        if entry.get("find"):
            cards += 1
        gold += entry.get("gold", 0)
    return {"tolls": tolls, "foes": foes, "cards": cards, "gold": gold}


# How many of each rarity the shop puts out, and how deep the stack goes.
# One rare at a time and never two, so the expensive thing stays something
# you save for rather than something you clear out.
SHOP_PLAN = (("common", 3, 2, 4), ("uncommon", 2, 1, 2), ("rare", 1, 1, 1))


def roll_shop(cleared, rand=None):
    """What the shop has in today. Restocked once a delve, and gated on how
    far down you have been - the good cards are not for sale until you have
    earned the right to be told they exist."""
    rand = rand or rng
    stock = []
    for rarity, slots, low, high in SHOP_PLAN:
        pool = [cid for cid in PLAYER_CARDS
                if CARDS[cid]["rarity"] == rarity
                and CARDS[cid]["unlock"] <= cleared]
        rand.shuffle(pool)
        for cid in pool[:slots]:
            stock.append({"card": cid, "stock": rand.randint(low, high),
                          "price": PRICE[rarity]})
    return stock


# --------------------------------------------------------------------------
# The duel
# --------------------------------------------------------------------------
class Side:
    """One combatant: hit points, a deck, and the three piles it moves
    between. Both sides of a fight are this same object - the enemy has no
    private rules, only a different deck."""

    def __init__(self, name, hp, deck, mod=0, glyph="@"):
        self.name = name
        self.glyph = glyph
        self.max_hp = int(hp)
        self.hp = int(hp)
        self.deck = list(deck)
        self.draw_pile = list(deck)
        rng.shuffle(self.draw_pile)
        self.hand = []
        self.discard = []
        self.field = []         # cards played this turn, left face up
        self.ap = 0
        self.block = 0
        self.pending = 0        # the attack building up, landing at turn's end
        self.mod = int(mod)

    # -- the piles ---------------------------------------------------------
    def draw(self, count=1):
        """Take cards off the top, shuffling the discard back under when the
        pile runs out. A deck that cannot fill a hand simply gives what it
        has - running dry is a bad position, not an error."""
        taken = []
        for _ in range(count):
            if not self.draw_pile:
                if not self.discard:
                    break
                self.draw_pile = list(self.discard)
                self.discard = []
                rng.shuffle(self.draw_pile)
            taken.append(self.draw_pile.pop())
        self.hand.extend(taken)
        return taken

    def clear_field(self):
        """Everything played last turn goes to the discard. Cards on the
        table are a record of the turn that is now over, not a board."""
        self.discard.extend(self.field)
        self.field = []

    def throw(self, indices):
        """Discard these hand positions. The top of a turn, and a choice:
        what you keep, you keep instead of drawing, because the hand is
        always filled back to the same size. Holding a Parry through the
        enemy's turn is never free - it costs you the card you would have
        drawn over it."""
        keep, gone = [], []
        for index, cid in enumerate(self.hand):
            (gone if index in indices else keep).append(cid)
        self.hand = keep
        self.discard.extend(gone)
        return len(gone)

    def refill(self):
        """Back up to a full hand, however many that takes."""
        return self.draw(max(0, HAND_SIZE - len(self.hand)))

    def sweep(self):
        """Throw the whole hand, the old way. Still what the enemy does."""
        self.clear_field()
        return self.throw(set(range(len(self.hand))))

    def spend_hand(self, ctype, count):
        """Pay a hazard: drop `count` cards of `ctype` out of hand. Returns
        the names paid, or None if the hand could not cover it - nothing is
        discarded in that case, so an unpayable toll costs cards and health
        both only when it is actually paid."""
        matching = [i for i, cid in enumerate(self.hand)
                    if card(cid)["type"] == ctype]
        if len(matching) < count:
            return None
        paid = []
        for index in sorted(matching[:count], reverse=True):
            cid = self.hand.pop(index)
            self.discard.append(cid)
            paid.append(card(cid)["name"])
        return list(reversed(paid))

    # -- state -------------------------------------------------------------
    def alive(self):
        return self.hp > 0

    def can_play(self, index, quick_only=False):
        """Whether the card at this hand position can be played right now."""
        if not 0 <= index < len(self.hand):
            return False
        info = card(self.hand[index])
        if quick_only and not info["quick"]:
            return False
        return info["cost"] <= self.ap

    def can_face(self, index):
        """Whether it can go down face up-side-down for its point instead.
        Commons only, and never in answer to someone else's turn - banking
        is something you do on your own time."""
        if not 0 <= index < len(self.hand):
            return False
        return bool(card(self.hand[index])["face"])

    def faces(self):
        """How many cards in hand could be banked. What the enemy checks
        before deciding it cannot afford anything."""
        return sum(1 for cid in self.hand if card(cid)["face"])

    def hurt(self, amount):
        """Damage through the wall. Block soaks what it can and is worn down
        by what it soaked, so a wall that stops one blow is thinner for the
        next - which is what makes a quick attack after the main one land."""
        amount = max(0, int(amount))
        soaked = min(self.block, amount)
        self.block -= soaked
        through = amount - soaked
        self.hp = max(0, self.hp - through)
        return soaked, through

    def heal(self, amount):
        before = self.hp
        self.hp = min(self.max_hp, self.hp + max(0, int(amount)))
        return self.hp - before


class Duel:
    """One fight, as a state machine the window steps through.

    The states are `ready` before initiative is rolled, `you` and `foe` while
    that side is playing cards, `react` while the enemy's attack is in the
    air and you may still answer it, and `over`. Nothing in here draws
    anything; the window reads the state and the piles and puts them on
    screen, which is what keeps the rules honest enough to run from a prompt.

    The shape of a turn:

        sweep the hand -> draw five -> bank a point -> play cards ->
        the other side may answer with quick cards -> the attack lands

    Attacks wait until the end of the turn that played them, so block that
    is already standing gets its chance. Quick cards played in answer land
    the moment they are played, which is the whole reason to hold one: an
    enemy killed mid-swing does not get to finish the swing.
    """

    def __init__(self, you, foe, roll=None, dealt=False):
        self.you = you
        self.foe = foe
        # Injected so the window can roll through the app's own d20 and have
        # it show up in the roll history like every other roll in the app.
        self.roll = roll or (lambda: rng.randint(1, 20))
        self.dealt = dealt      # the opening hand is already in front of you
        self.log = []
        self.marked = set()     # hand positions to throw at the next upkeep
        self.state = "ready"
        self.round = 0
        self.first = None
        self.winner = None

    # -- talking -----------------------------------------------------------
    def say(self, text, tone="plain"):
        self.log.append((text, tone))

    def side(self, who):
        return self.you if who == "you" else self.foe

    def other(self, who):
        return "foe" if who == "you" else "you"

    # -- the opening -------------------------------------------------------
    def begin(self):
        """Roll initiative and hand the first turn out. A tie goes to the
        higher modifier, and a tie there is rerolled - somebody has to move
        first and it should not be whoever the code happened to list first."""
        while True:
            yours = self.roll() + self.you.mod
            theirs = self.roll() + self.foe.mod
            if yours != theirs:
                break
            if self.you.mod != self.foe.mod:
                yours += self.you.mod > self.foe.mod
                break
        self.say(f"Initiative: you {yours}, {self.foe.name} {theirs}.", "note")
        self.first = "you" if yours > theirs else "foe"
        if self.first == "you":
            self.say("You move first.", "good")
            self.open_turn("you")
        else:
            self.say(f"{self.foe.name} moves first.", "bad")
            self.open_turn("foe")

    # -- turns -------------------------------------------------------------
    def open_turn(self, who):
        """Start a turn.

        Block is built to survive one enemy turn and no longer, so it goes
        here, at the top of your own next turn, alongside the hand that built
        it. Then the hand is thrown and refilled - for you that is a choice
        and pauses in `upkeep`; the enemy simply throws the lot.

        The one exception is your very first turn when a hazard has already
        dealt you a hand. Refilling there would hand back the cards the toll
        just took, and the toll would have cost nothing at all.
        """
        side = self.side(who)
        if who == self.first:
            self.round += 1
            self.say(f"-- Round {self.round} --", "note")
        side.block = 0
        side.pending = 0

        if self.round >= GRIND_ROUND:
            # Straight to hit points, past block, growing every round. A
            # fight neither side can win is ended by the dungeon itself.
            bite = self.round - GRIND_ROUND + 1
            side.hp = max(0, side.hp - bite)
            self.say(f"The air goes bad. {side.name} takes {bite}.", "bad")
            if not side.alive():
                self.finish(self.other(who))
                return

        if who == "you":
            if self.dealt:
                self.dealt = False
                side.ap += BASE_AP
                self.say(f"You go in with {len(side.hand)} cards.", "note")
                self.state = "you"
                return
            # Everything is marked to go by default, because most turns that
            # is what you want. Clicking a card rescues it.
            side.clear_field()
            self.marked = set(range(len(side.hand)))
            self.state = "upkeep"
            return

        side.sweep()
        drawn = side.refill()
        if len(side.hand) < HAND_SIZE and not drawn:
            self.say(f"{side.name} is out of cards to draw.", "bad")
        side.ap += BASE_AP
        self.state = "foe"

    # -- your upkeep -------------------------------------------------------
    def mark(self, index):
        """Toggle whether this card is thrown when the turn opens."""
        if self.state != "upkeep":
            return
        if index in self.marked:
            self.marked.discard(index)
        else:
            self.marked.add(index)

    def mark_all(self, on=True):
        if self.state != "upkeep":
            return
        self.marked = set(range(len(self.you.hand))) if on else set()

    def upkeep_draw(self):
        """Throw what is marked, fill the hand back up, bank the turn's
        point, and start playing."""
        if self.state != "upkeep":
            return
        side = self.you
        thrown = side.throw(self.marked)
        self.marked = set()
        drawn = side.refill()
        side.ap += BASE_AP
        kept = len(side.hand) - len(drawn)
        bits = []
        if thrown:
            bits.append(f"throw {thrown}")
        if kept:
            bits.append(f"keep {kept}")
        bits.append(f"draw {len(drawn)}")
        self.say("You " + ", ".join(bits) + ".", "note")
        if len(side.hand) < HAND_SIZE:
            self.say("You are out of cards to draw.", "bad")
        self.state = "you"

    def play(self, who, index):
        """Play the card at this hand position. Returns the card, or None if
        it could not be played - too expensive, or not quick enough to be
        played while the other side is swinging."""
        side = self.side(who)
        reaction = self.state == "react" and who == "you"
        if not reaction and self.state != who:
            return None
        if not side.can_play(index, quick_only=reaction):
            return None
        return self._resolve(who, index, reaction)

    def play_face(self, who, index):
        """Put a card down face down for the point on it instead of for what
        it says. The whole reason a common is never a dead draw - and the
        reason selling every common you own is a worse idea than it looks."""
        side = self.side(who)
        if self.state != who or not side.can_face(index):
            return None
        info = card(side.hand.pop(index))
        side.field.append(info["id"])
        side.ap += info["face"]
        self.say(f"{side.name} sets {info['name']} down for "
                 f"{info['face']} - banked.",
                 "good" if who == "you" else "bad")
        return info

    def _resolve(self, who, index, reaction):
        """A card leaving a hand, whoever played it and whenever.

        The one thing `reaction` changes is when damage arrives. On your own
        turn it is added to the blow you are winding up and lands at the end
        of it; played in answer to someone else's turn it lands immediately,
        which is the entire reason a quick card is worth a slot.
        """
        side = self.side(who)
        foe = self.side(self.other(who))
        info = card(side.hand.pop(index))
        side.ap -= info["cost"]
        side.field.append(info["id"])
        bits = []

        if info["ap"]:
            side.ap += info["ap"]
            bits.append(f"banks {info['ap']}")
        if info["block"]:
            side.block += info["block"]
            bits.append(f"blocks {info['block']}")
        if info["heal"]:
            bits.append(f"heals {side.heal(info['heal'])}")
        if info["draw"]:
            bits.append(f"draws {len(side.draw(info['draw']))}")
        if info["damage"]:
            if reaction:
                soaked, through = foe.hurt(info["damage"])
                bits.append(f"hits for {through}"
                            + (f" ({soaked} blocked)" if soaked else ""))
            else:
                side.pending += info["damage"]
                bits.append(f"winds up {info['damage']}")

        verb = "answers with" if reaction else "plays"
        self.say(f"{side.name} {verb} {info['name']} - "
                 f"{', '.join(bits) or 'nothing much'}.",
                 "good" if who == "you" else "bad")
        if not foe.alive():
            self.finish(who)
        return info

    def end_turn(self, who):
        """Called when a side stops playing cards.

        Your turn runs straight through: the enemy answers, your attack
        lands, and the turn passes. The enemy's turn stops short of landing
        and waits in `react`, because that pause is your reaction window -
        you get to see the number coming before deciding what to spend.
        """
        if self.state != who:
            return
        if who == "you":
            self._foe_reacts()
            if self.state == "over":
                return
            self._land("you")
            if self.state == "over":
                return
            self.open_turn("foe")
        else:
            if self.foe.pending:
                self.say(f"{self.foe.name} swings for {self.foe.pending}.",
                         "bad")
            else:
                self.say(f"{self.foe.name} holds back.", "note")
            self.state = "react"

    def brace(self):
        """Take the blow. The end of your reaction window, and the only way
        out of it - a fight cannot be stalled by simply not answering."""
        if self.state != "react":
            return
        self._land("foe")
        if self.state == "over":
            return
        self.open_turn("you")

    def _land(self, who):
        """Put the attack that has been building through the other side's
        block, and see who is left standing."""
        side = self.side(who)
        foe = self.side(self.other(who))
        amount = side.pending
        side.pending = 0
        if amount <= 0:
            return
        soaked, through = foe.hurt(amount)
        tone = "good" if who == "you" else "bad"
        if soaked and through:
            self.say(f"{foe.name} blocks {soaked} and takes {through}.", tone)
        elif soaked:
            self.say(f"{foe.name} blocks all {soaked} of it.",
                     "bad" if who == "you" else "good")
        else:
            self.say(f"{foe.name} takes {through}.", tone)
        if not foe.alive():
            self.finish(who)

    def finish(self, winner):
        self.winner = winner
        self.state = "over"
        if winner == "you":
            self.say(f"{self.foe.name} goes down.", "good")
        else:
            self.say("You go down.", "bad")

    # -- how the dungeon plays its hand -------------------------------------
    # The enemy is not clever and is not meant to be. It banks whatever it
    # can, spends big when it can afford to, blocks when it is hurt, and
    # holds back just enough to answer with a quick card once it is in real
    # trouble. Every one of those is a move a player can read off the table
    # and plan around, which matters more here than being hard to beat.
    def _affordable(self, side, keep=0):
        return [(i, card(cid)) for i, cid in enumerate(side.hand)
                if card(cid)["cost"] <= side.ap - keep]

    def _reserve(self, side):
        """Action points the enemy keeps back for an answer. Only once it is
        hurt - a healthy enemy spends everything, which is why the early
        turns of a fight are the safe ones."""
        if side.hp > side.max_hp // 2:
            return 0
        quick = [card(cid)["cost"] for cid in side.hand if card(cid)["quick"]]
        return min(quick) if quick else 0

    def enemy_step(self):
        """One card of the enemy's turn, or None when it is done. The window
        calls this on a timer so the turn can be watched rather than just
        appearing, finished, in the log."""
        if self.state != "foe":
            return None
        side = self.foe
        keep = self._reserve(side)
        options = self._affordable(side, keep)
        if not options:
            # Nothing it can pay for. It banks instead of standing there,
            # which is exactly the option you have in the same spot.
            return self.enemy_banks()

        def best(test):
            picks = [(i, c) for i, c in options if test(c)]
            return max(picks, key=lambda p: p[1]["cost"]) if picks else None

        hurt = side.hp <= side.max_hp * 2 // 5
        choice = (best(lambda c: c["ap"] > 0)
                  or best(lambda c: c["cost"] == 0 and c["draw"] > 0)
                  or (best(lambda c: c["block"] > 0) if hurt else None)
                  or best(lambda c: c["damage"] > 0)
                  or best(lambda c: c["block"] > 0))
        if choice is None:
            return None
        return self.play("foe", choice[0])

    def enemy_banks(self):
        """The enemy setting a card down for its point, when it has nothing
        it can pay for. Only ever the least useful card in hand, so it does
        not bank the Lunge it was saving up to play."""
        side = self.foe
        if self.state != "foe":
            return None
        faces = [(i, card(cid)) for i, cid in enumerate(side.hand)
                 if card(cid)["face"]]
        if not faces:
            return None
        index = min(faces, key=lambda p: (p[1]["damage"] + p[1]["block"],
                                          p[1]["cost"]))[0]
        return self.play_face("foe", index)

    def _foe_reacts(self):
        """The enemy's answer to your turn. It will finish you if a quick
        card gets there, and otherwise puts up what block it can afford."""
        incoming = self.you.pending
        while True:
            quick = [(i, card(cid)) for i, cid in enumerate(self.foe.hand)
                     if card(cid)["quick"] and card(cid)["cost"] <= self.foe.ap]
            if not quick:
                return
            kill = [(i, c) for i, c in quick
                    if c["damage"] - self.you.block >= self.you.hp]
            if kill:
                index = max(kill, key=lambda p: p[1]["damage"])[0]
            elif incoming > self.foe.block:
                blocks = [(i, c) for i, c in quick if c["block"] > 0]
                if not blocks:
                    return
                index = max(blocks, key=lambda p: p[1]["block"])[0]
            else:
                return
            self._resolve("foe", index, reaction=True)
            if self.state == "over":
                return


# --------------------------------------------------------------------------
# What a campaign keeps
# --------------------------------------------------------------------------
def _listing(value):
    """A list out of a save file, or nothing at all."""
    return value if isinstance(value, list) else []


def _whole(value, fallback=0):
    """A number out of a save file, whatever was actually in the slot."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


class Progress:
    """The collection, the purse, the decks, the floors already beaten, and
    the delve in progress.

    All of it lives in `api.storage`, which is per-campaign, so two save
    files have two separate collections without this having to know that.
    Loading is forgiving on purpose: a save written by a build that knew a
    card this one does not should come back with everything else intact.
    """

    def __init__(self, api):
        self.api = api
        store = api.storage

        self.collection = {}
        hoard = store.get("collection")
        for cid, count in (hoard.items() if isinstance(hoard, dict) else ()):
            if cid in CARDS and not CARDS[cid]["enemy_only"]:
                if _whole(count) > 0:
                    self.collection[cid] = _whole(count)
        # Whether the key is there, not whether it has anything in it. The
        # shop will happily buy the last card you own, and an empty
        # collection that read as a new campaign would hand the starter back
        # every time the window was opened - sell, reopen, sell again, and
        # the purse goes up for ever.
        if "collection" not in store:
            self.collection = dict(STARTER)

        self.gold = max(0, _whole(store.get("gold")))
        self.cleared = [d for d in _listing(store.get("cleared"))
                        if d in DUNGEON_BY_ID]
        self.delves = max(0, _whole(store.get("delves")))

        self.decks = {}
        shelf = store.get("decks")
        for name, counts in (shelf.items()
                             if isinstance(shelf, dict) else ()):
            cleaned = self._clean_deck(counts)
            if cleaned:
                self.decks[str(name)[:28]] = cleaned
        self.deck_name = str(store.get("deck_name") or "")
        if self.deck_name not in self.decks:
            self.deck_name = next(iter(self.decks), "")

        self.offer = self._clean_offer(store.get("offer"))
        self.run = self._clean_run(store.get("run"))

    # -- reading -----------------------------------------------------------
    def _clean_deck(self, raw):
        """A deck trimmed to what is actually in the collection. Selling the
        cards out from under a saved deck shrinks the deck rather than
        breaking it."""
        out = {}
        for cid, count in (raw.items() if isinstance(raw, dict) else ()):
            if cid in CARDS and not CARDS[cid]["enemy_only"]:
                held = self.collection.get(cid, 0)
                want = _whole(count)
                if want > 0 and held:
                    out[cid] = min(want, held)
        return out

    def _clean_offer(self, raw):
        if not isinstance(raw, dict):
            return None
        stock = []
        shelf = raw.get("shop")
        for entry in shelf if isinstance(shelf, list) else []:
            if not isinstance(entry, dict):
                continue
            cid = entry.get("card")
            if cid in CARDS and not CARDS[cid]["enemy_only"]:
                stock.append({
                    "card": cid,
                    "stock": max(0, _whole(entry.get("stock"))),
                    "price": max(1, _whole(entry.get("price"),
                                           buy_price(cid))),
                })
        plans = {}
        shelved = raw.get("plans")
        for did, plan in (shelved.items()
                          if isinstance(shelved, dict) else ()):
            if did in DUNGEON_BY_ID and isinstance(plan, dict):
                kept = self._clean_plan(DUNGEON_BY_ID[did], plan)
                if kept:
                    plans[did] = kept
        return {"stamp": _whole(raw.get("stamp"), -1), "shop": stock,
                "plans": plans}

    def _clean_plan(self, dungeon, raw):
        """A rolled floor read back off disk, with anything unrecognised
        dropped. A plan missing a room is no plan at all - better to roll a
        new floor than to walk into a half-remembered one."""
        plan = {}
        for room in dungeon["rooms"]:
            entry = raw.get(room["id"])
            if not isinstance(entry, dict):
                return None
            kept = {}
            if entry.get("fight") in ENEMIES:
                kept["fight"] = entry["fight"]
            if entry.get("hazard") in HAZARDS:
                kept["hazard"] = entry["hazard"]
            if entry.get("find") in CARDS:
                kept["find"] = entry["find"]
            if entry.get("gold"):
                kept["gold"] = max(0, _whole(entry["gold"]))
            if entry.get("rest"):
                kept["rest"] = max(0, _whole(entry["rest"]))
            plan[room["id"]] = kept
        return plan

    def _clean_run(self, raw):
        """A delve read back off disk, or None. Anything that does not add
        up - a floor that no longer exists, no hit points left, a plan that
        will not load - is dropped rather than resumed into a broken
        state."""
        if not isinstance(raw, dict):
            return None
        dungeon = DUNGEON_BY_ID.get(raw.get("dungeon"))
        if dungeon is None:
            return None
        plan = self._clean_plan(dungeon, raw.get("plan") or {})
        if plan is None:
            return None
        rooms = {r["id"] for r in dungeon["rooms"]}
        hp = _whole(raw.get("hp"))
        if hp <= 0:
            return None
        deck = self._clean_deck(raw.get("deck") or {})
        if sum(deck.values()) < MIN_DECK:
            return None
        return {
            "dungeon": dungeon["id"],
            "hp": min(hp, _whole(raw.get("max_hp"), dungeon["hp"])),
            "max_hp": _whole(raw.get("max_hp"), dungeon["hp"]),
            "deck": deck,
            "plan": plan,
            "cleared": [r for r in _listing(raw.get("cleared"))
                        if r in rooms],
            "found": [c for c in _listing(raw.get("found")) if c in CARDS],
            "purse": max(0, _whole(raw.get("purse"))),
        }

    def unlocked(self, dungeon):
        need = dungeon.get("needs")
        return need is None or need in self.cleared

    def owned(self, cid):
        return self.collection.get(cid, 0)

    def total_cards(self):
        return sum(self.collection.values())

    def can_sell(self):
        """Whether there is anything to spare. A deck is MIN_DECK cards and
        selling below that strands the campaign, so the floor is the floor."""
        return self.total_cards() > MIN_DECK

    # -- what is on offer this time ----------------------------------------
    # The shop and the floors are rolled together and stamped with the number
    # of delves gone by, so both hold still until you actually go down the
    # stairs. Backing out of the prep screen to fish for a kinder floor or a
    # better shop is the one thing this is built to prevent.
    def _ensure_offer(self):
        if self.offer is None or self.offer.get("stamp") != self.delves:
            self.offer = {"stamp": self.delves,
                          "shop": roll_shop(len(self.cleared)),
                          "plans": {}}
        return self.offer

    def shop(self):
        return self._ensure_offer()["shop"]

    def plan_for(self, dungeon):
        offer = self._ensure_offer()
        plan = offer["plans"].get(dungeon["id"])
        if plan is None:
            plan = roll_plan(dungeon)
            offer["plans"][dungeon["id"]] = plan
        return plan

    # -- the shop ----------------------------------------------------------
    def buy(self, index):
        """Take one off the shelf. Returns the card id, or None if the gold
        or the stock was not there."""
        stock = self.shop()
        if not 0 <= index < len(stock):
            return None
        entry = stock[index]
        if entry["stock"] <= 0 or self.gold < entry["price"]:
            return None
        self.gold -= entry["price"]
        entry["stock"] -= 1
        self.gain(entry["card"])
        self.flush()
        return entry["card"]

    def sell(self, cid):
        """Sell one. Anything in a saved deck shrinks the deck with it, and
        the last copy of a card can go the same as any other - there is no
        sentimentality in here and no undo, so the window asks first.

        The one thing he will not do is buy you out of a deck. Gold only
        comes back up the stairs, so a collection too small to field one has
        no way left of growing - it is a dead campaign rather than a hard
        one. He stops at MIN_DECK cards for that reason."""
        if self.owned(cid) <= 0:
            return 0
        if not self.can_sell():
            return 0
        paid = sell_price(cid)
        self.collection[cid] -= 1
        if self.collection[cid] <= 0:
            del self.collection[cid]
        for name, counts in list(self.decks.items()):
            if counts.get(cid, 0) > self.owned(cid):
                counts[cid] = self.owned(cid)
                if counts[cid] <= 0:
                    counts.pop(cid, None)
        self.gold += paid
        self.flush()
        return paid

    # -- decks -------------------------------------------------------------
    def save_deck(self, name, counts):
        name = (str(name).strip() or "Untitled")[:28]
        self.decks[name] = dict(counts)
        self.deck_name = name
        self.flush()
        return name

    def drop_deck(self, name):
        self.decks.pop(name, None)
        if self.deck_name == name:
            self.deck_name = next(iter(self.decks), "")
        self.flush()

    # -- writing -----------------------------------------------------------
    def gain(self, cid, count=1):
        if cid in CARDS and not CARDS[cid]["enemy_only"]:
            self.collection[cid] = self.collection.get(cid, 0) + count

    def flush(self):
        store = self.api.storage
        store["collection"] = dict(self.collection)
        store["gold"] = self.gold
        store["cleared"] = list(self.cleared)
        store["delves"] = self.delves
        store["decks"] = {n: dict(c) for n, c in self.decks.items()}
        store["deck_name"] = self.deck_name
        store["offer"] = copy.deepcopy(self.offer) if self.offer else None
        store["run"] = copy.deepcopy(self.run) if self.run else None
        self.api.save()

    # -- the delve ---------------------------------------------------------
    def start_run(self, dungeon, deck):
        plan = self.plan_for(dungeon)
        self.run = {
            "dungeon": dungeon["id"], "hp": dungeon["hp"],
            "max_hp": dungeon["hp"], "deck": dict(deck),
            "plan": copy.deepcopy(plan),
            "cleared": [], "found": [], "purse": 0,
        }
        # The stamp moves the moment you go in, so the shop and the floors
        # are already different by the time you come back up.
        self.delves += 1
        self.offer = None
        self.flush()

    def end_run(self, won):
        """Close the delve out. Gold and cards picked up on the way are kept
        whichever way it went - dying with a card in your pocket still means
        you found it. The clearing bonus is paid once, the first time."""
        reward, bonus = [], 0
        if self.run:
            self.gold += self.run.get("purse", 0)
            for cid in self.run.get("found", []):
                self.gain(cid)
            if won:
                dungeon = DUNGEON_BY_ID[self.run["dungeon"]]
                if dungeon["id"] not in self.cleared:
                    self.cleared.append(dungeon["id"])
                low, high = dungeon["clear_gold"]
                bonus = rng.randint(low, high)
                self.gold += bonus
        self.run = None
        self.flush()
        return reward, bonus


# --------------------------------------------------------------------------
# The window
# --------------------------------------------------------------------------
class CardDungeon:
    """One window with four screens in it - hub, prep, delve, duel - swapped
    in and out of the same body frame. Nothing here decides anything about
    the rules; it reads `Duel` and `Progress` and draws what they say."""

    def __init__(self, api):
        self.api = api
        self.t = api.theme
        self.f = api.fonts
        self.progress = Progress(api)

        self.screen = "hub"
        self.build = {}         # the deck being put together on the prep screen
        self.dungeon = None     # the floor being prepped or delved
        self.duel = None
        self.room = None        # the room the duel is being fought in
        self.step_job = None    # the enemy's turn, playing itself out
        self.log_box = None

        self._build_window()
        self.show_hub() if not self.progress.run else self.resume()

    # -- window ------------------------------------------------------------
    def alive(self):
        try:
            return bool(self.win.winfo_exists())
        except tk.TclError:
            return False

    def _build_window(self):
        self.win = tk.Toplevel(self.api.app)
        self.win.title(f"Card Dungeon - {self.api.save_name}")
        self.win.configure(bg=self.t["bg"])
        self.win.geometry("1020x760")
        self.win.minsize(880, 660)
        self.win.protocol("WM_DELETE_WINDOW", self._close)

        self.win.rowconfigure(1, weight=1)
        self.win.columnconfigure(0, weight=1)

        self.bar = tk.Frame(self.win, bg=self.t["panel"])
        self.bar.grid(row=0, column=0, sticky="ew")
        self.title = tk.Label(self.bar, text="", font=self.f["title"],
                              bg=self.t["panel"], fg=self.t["accent"],
                              anchor="w", padx=12, pady=7)
        self.title.pack(side="left")
        self.status = tk.Label(self.bar, text="", font=self.f["label"],
                               bg=self.t["panel"], fg=self.t["muted"],
                               anchor="e", padx=12)
        self.status.pack(side="right")

        self.body = tk.Frame(self.win, bg=self.t["bg"])
        self.body.grid(row=1, column=0, sticky="nsew")

    def _close(self):
        self._cancel_step()
        self.save()
        self.win.destroy()

    def save(self):
        try:
            self.progress.flush()
        except Exception as exc:              # never lose the window over it
            self.api.log(f"could not save: {exc}")

    def _cancel_step(self):
        if self.step_job is not None:
            try:
                self.win.after_cancel(self.step_job)
            except tk.TclError:
                pass
            self.step_job = None

    def _clear(self):
        self._cancel_step()
        for child in self.body.winfo_children():
            child.destroy()

    # -- small widgets -----------------------------------------------------
    def _button(self, parent, text, command, fg=None, bg=None, font=None,
                width=None, state="normal"):
        return tk.Button(parent, text=text, font=font or self.f["label"],
                         bg=bg or self.t["panel"], fg=fg or self.t["fg"],
                         activebackground=self.t["accent"],
                         activeforeground=self.t["bg"], relief="flat", bd=0,
                         padx=10, pady=4, cursor="hand2", command=command,
                         state=state, **({"width": width} if width else {}))

    def _label(self, parent, text, fg=None, bg=None, font=None, **kw):
        return tk.Label(parent, text=text, font=font or self.f["label"],
                        bg=bg or self.t["bg"], fg=fg or self.t["fg"],
                        anchor="w", justify="left", **kw)

    def _wrapped(self, parent, text, width, fg=None, bg=None):
        return tk.Label(parent, text=text, font=self.f["label"],
                        bg=bg or self.t["bg"], fg=fg or self.t["muted"],
                        anchor="w", justify="left", wraplength=width)

    def _scroller(self, parent):
        """A scrolling column. Returns the frame to put things in.

        Tk has no scrollable frame, so this is the usual canvas-with-a-window
        trick, plus the wheel binding the rest of the app uses so a Mac
        scrolls at the same speed as everything else.
        """
        holder = tk.Frame(parent, bg=self.t["bg"])
        canvas = tk.Canvas(holder, bg=self.t["bg"], highlightthickness=0, bd=0)
        bar = tk.Scrollbar(holder, orient="vertical", command=canvas.yview)
        inner = tk.Frame(canvas, bg=self.t["bg"])
        window = canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=bar.set)
        canvas.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")

        def resized(_event=None):
            canvas.configure(scrollregion=canvas.bbox("all"))
            canvas.itemconfigure(window, width=canvas.winfo_width())

        inner.bind("<Configure>", resized)
        canvas.bind("<Configure>", resized)

        def wheel(event):
            steps = dice_api.wheel_steps(event)
            if steps:
                canvas.yview_scroll(steps, "units")

        for widget, seq in ((canvas, "<MouseWheel>"), (canvas, "<Button-4>"),
                            (canvas, "<Button-5>")):
            widget.bind(seq, wheel)
        holder.inner = inner
        holder.canvas = canvas
        return holder

    def _hp_bar(self, parent, hp, maximum, width=180, color=None):
        """A hit point bar. Drawn rather than a widget so it can sit tight
        against a name without a theme fighting it."""
        bar = tk.Canvas(parent, width=width, height=13, bg=self.t["panel"],
                        highlightthickness=0, bd=0)
        share = max(0.0, min(1.0, hp / float(maximum or 1)))
        tone = color or (self.t["crit"] if share > 0.5
                         else self.t["accent"] if share > 0.25
                         else self.t["fumble"])
        if share > 0:
            bar.create_rectangle(0, 0, max(2, width * share), 13,
                                 fill=tone, outline="")
        bar.create_text(width // 2, 7, text=f"{hp} / {maximum}",
                        font=self.f["label"], fill=self.t["bg"] if share > 0.45
                        else self.t["fg"])
        return bar

    # -- cards on screen ---------------------------------------------------
    def _cost_text(self, info):
        return "free" if not info["cost"] else "*" * info["cost"]

    def _card_row(self, parent, cid, command=None, badge="", label="Add",
                  enabled=True, price=None, second=None, second_label=""):
        """One line of a list: the colour of its type, name, cost and text,
        with its rarity down the side. Used everywhere a lot of cards have to
        be shown at once - the collection, the deck, the shop."""
        info = card(cid)
        row = tk.Frame(parent, bg=self.t["panel"], highlightthickness=0)
        stripe = tk.Frame(row, bg=TYPE_COLOR.get(info["type"], self.t["muted"]),
                          width=4)
        stripe.pack(side="left", fill="y")
        stripe.pack_propagate(False)

        text = tk.Frame(row, bg=self.t["panel"])
        text.pack(side="left", fill="both", expand=True, padx=8, pady=4)
        head = tk.Frame(text, bg=self.t["panel"])
        head.pack(fill="x")
        self._label(head, info["name"], bg=self.t["panel"],
                    font=self.f["die"]).pack(side="left")
        self._label(head, info["rarity"], bg=self.t["panel"],
                    fg=RARITY_COLOR[info["rarity"]]).pack(side="left", padx=8)
        if badge:
            self._label(head, badge, bg=self.t["panel"],
                        fg=self.t["accent"]).pack(side="right")
        self._label(head, self._cost_text(info), bg=self.t["panel"],
                    fg=self.t["accent"]).pack(side="right", padx=8)

        body = info["text"]
        if info["face"]:
            body += f"   (or set down for {info['face']})"
        self._label(text, body, bg=self.t["panel"],
                    fg=self.t["muted"]).pack(fill="x")

        if price is not None:
            self._label(text, f"{price} gold", bg=self.t["panel"],
                        fg=self.t["accent"]).pack(side="left")

        if second is not None:
            self._button(row, second_label, second, bg=self.t["bg"],
                         fg=self.t["muted"]).pack(side="right", padx=(0, 6))
        if command is not None:
            self._button(row, label, command, bg=self.t["bg"],
                         state="normal" if enabled else "disabled").pack(
                             side="right", padx=6)
        return row

    def _card_face(self, parent, cid, on_play=None, on_bank=None,
                   playable=True, note="", dimmed=False):
        """A card as a card: upright, bordered in its type's colour, big
        enough to read across the table. This is what a hand is made of.

        A common carries a second, smaller button along the bottom - the
        same card, set down for its point instead of played for its words.
        """
        info = card(cid)
        tone = TYPE_COLOR.get(info["type"], self.t["muted"])
        live = playable and not dimmed
        edge = tone if live else self.t["muted"]
        ink = self.t["fg"] if live else self.t["muted"]
        face = tk.Frame(parent, bg=self.t["panel"], highlightbackground=edge,
                        highlightthickness=2, width=136,
                        height=192 if info["face"] else 176)
        face.pack_propagate(False)

        top = tk.Frame(face, bg=self.t["panel"])
        top.pack(fill="x", padx=6, pady=(6, 0))
        self._label(top, self._cost_text(info), bg=self.t["panel"],
                    fg=self.t["accent"] if live else self.t["muted"],
                    font=self.f["die"]).pack(side="left")
        if info["quick"]:
            self._label(top, "quick", bg=self.t["panel"],
                        fg=self.t["crit"] if live
                        else self.t["muted"]).pack(side="right")

        tk.Label(face, text=info["name"], font=self.f["die"],
                 bg=self.t["panel"], fg=ink, wraplength=118,
                 justify="left", anchor="w").pack(fill="x", padx=6, pady=(4, 2))
        tk.Frame(face, bg=edge, height=1).pack(fill="x", padx=6)
        tk.Label(face, text=info["text"], font=self.f["label"],
                 bg=self.t["panel"], fg=self.t["muted"], wraplength=118,
                 justify="left", anchor="nw").pack(
                     fill="both", expand=True, padx=6, pady=4)
        tk.Label(face, text=note or info["type"], font=self.f["label"],
                 bg=self.t["panel"], fg=edge, anchor="w").pack(
                     fill="x", padx=6, pady=(0, 2))

        if on_play is not None and live:
            # The whole card is the button - clicking the text should play it
            # as readily as clicking the border.
            def bind(widget):
                widget.bind("<Button-1>", lambda _e: on_play())
                widget.configure(cursor="hand2")
                for inner in widget.winfo_children():
                    bind(inner)
            bind(face)

        if on_bank is not None and info["face"]:
            # Packed last and bound after the card-wide binding above, so a
            # click down here banks rather than plays.
            bank = self._button(face, f"set down  +{info['face']}", on_bank,
                                bg=self.t["bg"], fg=self.t["accent"])
            bank.pack(fill="x", padx=6, pady=(0, 6))
            bank.bind("<Button-1>", lambda _e: (on_bank(), "break")[1])
        return face

    def _deck_summary(self, counts):
        """The line under a deck: how big it is, what it is made of, what
        that buys on the initiative roll, and how much of it can pay for
        itself."""
        total = sum(counts.values())
        tally = deck_types(counts)
        bits = [f"{tally[t]} {t}" for t in TYPES if tally[t]]
        mod = init_mod(counts)
        faces = deck_faces(counts)
        return (f"{total} cards" + ("  -  " + ", ".join(bits) if bits else "")
                + f"  -  {faces} can be set down"
                + (f"  -  initiative +{mod}" if mod else ""))

    def _purse(self):
        return f"{self.progress.gold} gold"

    # -- the hub -----------------------------------------------------------
    def show_hub(self):
        self._clear()
        self.screen = "hub"
        self.dungeon = None
        self.title.configure(text="Card Dungeon")
        self.status.configure(
            text=f"{self.progress.total_cards()} cards   -   {self._purse()}")

        wrap = self._scroller(self.body)
        wrap.pack(fill="both", expand=True, padx=14, pady=12)
        page = wrap.inner

        self._wrapped(page, "Pick a floor. You build the deck you take in "
                            "before the door closes behind you, and it is "
                            "the only deck you get. What is waiting down "
                            "there is rolled fresh every time.", 860).pack(
                                fill="x", pady=(0, 12))

        for dungeon in DUNGEONS:
            self._dungeon_panel(page, dungeon)

        foot = tk.Frame(page, bg=self.t["bg"])
        foot.pack(fill="x", pady=14)
        self._button(foot, "The collection",
                     self.show_collection).pack(side="left")
        self._button(foot, "How this works",
                     self.show_rules).pack(side="left", padx=8)

    def _dungeon_panel(self, parent, dungeon):
        open_now = self.progress.unlocked(dungeon)
        done = dungeon["id"] in self.progress.cleared

        panel = tk.Frame(parent, bg=self.t["panel"])
        panel.pack(fill="x", pady=6)
        inner = tk.Frame(panel, bg=self.t["panel"])
        inner.pack(fill="x", padx=12, pady=10)

        head = tk.Frame(inner, bg=self.t["panel"])
        head.pack(fill="x")
        self._label(head, dungeon["name"], bg=self.t["panel"],
                    font=self.f["title"],
                    fg=self.t["accent"] if open_now
                    else self.t["muted"]).pack(side="left")
        if done:
            mark = "cleared"
        elif open_now:
            mark = ""
        else:
            gate = DUNGEON_BY_ID[dungeon["needs"]]["name"]
            mark = f"locked - clear {gate} first"
        self._label(head, mark, bg=self.t["panel"],
                    fg=self.t["crit"] if done
                    else self.t["muted"]).pack(side="right")
        self._label(head,
                    f"level {dungeon['level']}  -  {dungeon['hp']} hit points",
                    bg=self.t["panel"],
                    fg=self.t["muted"]).pack(side="right", padx=12)

        self._wrapped(inner, dungeon["text"], 820, bg=self.t["panel"]).pack(
            fill="x", pady=(4, 2))
        if open_now:
            self._wrapped(inner, dungeon["flavour"], 820, bg=self.t["panel"],
                          fg=self.t["accent"]).pack(fill="x")
            row = tk.Frame(inner, bg=self.t["panel"])
            row.pack(fill="x", pady=(8, 0))
            self._button(row, "Delve" if not done else "Delve again",
                         lambda d=dungeon: self.show_prep(d),
                         bg=self.t["bg"], fg=self.t["accent"]).pack(side="left")
            low, high = dungeon["clear_gold"]
            self._label(row, f"clearing it pays {low}-{high} gold",
                        bg=self.t["panel"],
                        fg=self.t["muted"]).pack(side="left", padx=12)

    def show_rules(self):
        self._clear()
        self.screen = "rules"
        self.title.configure(text="How this works")
        self.status.configure(text="")
        wrap = self._scroller(self.body)
        wrap.pack(fill="both", expand=True, padx=14, pady=12)
        page = wrap.inner
        for head, text in RULES:
            self._label(page, head, font=self.f["die"],
                        fg=self.t["accent"]).pack(fill="x", pady=(10, 2))
            self._wrapped(page, text, 840).pack(fill="x")
        self._button(page, "Back", self.show_hub).pack(anchor="w", pady=16)

    def show_collection(self):
        self._clear()
        self.screen = "collection"
        self.title.configure(text="The collection")
        self.status.configure(
            text=f"{self.progress.total_cards()} cards   -   {self._purse()}")

        wrap = self._scroller(self.body)
        wrap.pack(fill="both", expand=True, padx=14, pady=12)
        page = wrap.inner
        for rarity in RARITIES:
            owned = sorted((c for c in self.progress.collection
                            if card(c)["rarity"] == rarity),
                           key=lambda c: (card(c)["type"], card(c)["cost"],
                                          card(c)["name"]))
            if not owned:
                continue
            self._label(page, rarity, font=self.f["die"],
                        fg=RARITY_COLOR[rarity]).pack(fill="x", pady=(10, 4))
            for cid in owned:
                self._card_row(page, cid,
                               badge=f"x{self.progress.collection[cid]}").pack(
                                   fill="x", pady=1)
        self._button(page, "Back", self.show_hub).pack(anchor="w", pady=16)

    # -- the prep ----------------------------------------------------------
    # Three things happen on this screen and they are all the same decision:
    # what to walk in with. The briefing down the left says what the floor
    # rolled up this time, and it is the same rolled floor you will walk
    # into - it is decided here, not at the door, or a warning about pits
    # would be worth nothing.
    def show_prep(self, dungeon, mode=None):
        self._clear()
        self.screen = "prep"
        self.dungeon = dungeon
        self.plan = self.progress.plan_for(dungeon)
        self.prep_mode = mode or getattr(self, "prep_mode", "build")
        if not hasattr(self, "build") or mode is None:
            saved = self.progress.decks.get(self.progress.deck_name, {})
            self.build = self.progress._clean_deck(saved)
        self.title.configure(text=f"Prepare - {dungeon['name']}")

        self.body.columnconfigure(0, weight=0, minsize=258)
        self.body.columnconfigure(1, weight=1)
        self.body.columnconfigure(2, weight=0)
        self.body.rowconfigure(0, weight=1)

        brief = tk.Frame(self.body, bg=self.t["panel"])
        brief.grid(row=0, column=0, sticky="nsew", padx=(12, 6), pady=12)
        self._build_briefing(brief, dungeon)

        main = tk.Frame(self.body, bg=self.t["bg"])
        main.grid(row=0, column=1, columnspan=2, sticky="nsew",
                  padx=(6, 12), pady=12)
        main.rowconfigure(1, weight=1)
        main.columnconfigure(0, weight=1)

        tabs = tk.Frame(main, bg=self.t["bg"])
        tabs.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        for key, label in (("build", "Build the deck"), ("shop", "Shop"),
                           ("sell", "Sell")):
            on = self.prep_mode == key
            self._button(tabs, label,
                         lambda k=key: self.show_prep(self.dungeon, k),
                         bg=self.t["accent"] if on else self.t["panel"],
                         fg=self.t["bg"] if on else self.t["fg"]).pack(
                             side="left", padx=(0, 4))
        self._label(tabs, self._purse(), fg=self.t["accent"],
                    font=self.f["die"]).pack(side="right", padx=8)
        self._button(tabs, "Back", self.show_hub).pack(side="right")

        holder = tk.Frame(main, bg=self.t["bg"])
        holder.grid(row=1, column=0, sticky="nsew")
        if self.prep_mode == "shop":
            self._build_shop(holder)
        elif self.prep_mode == "sell":
            self._build_sell(holder)
        else:
            self._build_deck(holder)

    def _build_briefing(self, parent, dungeon):
        inner = tk.Frame(parent, bg=self.t["panel"])
        inner.pack(fill="both", expand=True, padx=10, pady=10)
        self._label(inner, dungeon["name"], font=self.f["title"],
                    bg=self.t["panel"], fg=self.t["accent"]).pack(fill="x")
        self._label(inner, f"{dungeon['hp']} hit points, and no healing but "
                           f"what you bring", bg=self.t["panel"],
                    fg=self.t["muted"]).pack(fill="x", pady=(0, 8))

        # Read off the rolled floor rather than written out again, so the
        # briefing cannot be wrong about the floor it is briefing you on.
        brief = plan_briefing(dungeon, self.plan)

        self._label(inner, "The tolls", font=self.f["die"],
                    bg=self.t["panel"]).pack(fill="x", pady=(4, 2))
        if brief["tolls"]:
            for ctype, count in sorted(brief["tolls"].items()):
                word = "card" if count == 1 else "cards"
                self._label(inner, f"{count} {ctype} {word}",
                            bg=self.t["panel"],
                            fg=TYPE_COLOR.get(ctype,
                                              self.t["fg"])).pack(fill="x")
            self._wrapped(inner, "Paid out of the hand you walk in with. "
                                 "Short of the right type and you take the "
                                 "damage instead.", 220,
                          bg=self.t["panel"]).pack(fill="x", pady=(2, 0))
        else:
            self._label(inner, "none this time", bg=self.t["panel"],
                        fg=self.t["muted"]).pack(fill="x")

        self._label(inner, "What is down there", font=self.f["die"],
                    bg=self.t["panel"]).pack(fill="x", pady=(10, 2))
        for name, count in sorted(brief["foes"].items()):
            self._label(inner, name + (f" x{count}" if count > 1 else ""),
                        bg=self.t["panel"],
                        fg=self.t["muted"]).pack(fill="x")

        self._label(inner, "Worth going for", font=self.f["die"],
                    bg=self.t["panel"]).pack(fill="x", pady=(10, 2))
        haul = f"{brief['cards']} cards lying about"
        if brief["gold"]:
            haul += f", and about {brief['gold']} gold"
        self._wrapped(inner, haul, 220, bg=self.t["panel"]).pack(fill="x")
        low, high = dungeon["clear_gold"]
        self._wrapped(inner, f"Clearing it pays {low}-{high} more.", 220,
                      bg=self.t["panel"]).pack(fill="x")

    # -- building ----------------------------------------------------------
    def _build_deck(self, parent):
        parent.rowconfigure(0, weight=1)
        parent.columnconfigure(0, weight=1, uniform="halves")
        parent.columnconfigure(1, weight=1, uniform="halves")

        left = tk.Frame(parent, bg=self.t["bg"])
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        self._label(left, "Collection", font=self.f["die"]).pack(fill="x")
        self.pool_wrap = self._scroller(left)
        self.pool_wrap.pack(fill="both", expand=True, pady=(4, 0))

        right = tk.Frame(parent, bg=self.t["bg"])
        right.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        self._label(right, "Your deck", font=self.f["die"]).pack(fill="x")
        self.deck_wrap = self._scroller(right)
        self.deck_wrap.pack(fill="both", expand=True, pady=(4, 4))
        self.deck_note = self._label(right, "", fg=self.t["muted"])
        self.deck_note.pack(fill="x")

        presets = tk.Frame(right, bg=self.t["bg"])
        presets.pack(fill="x", pady=(6, 0))
        self._label(presets, "Saved decks", fg=self.t["muted"]).pack(
            side="left", padx=(0, 6))
        names = list(self.progress.decks) or ["(none saved)"]
        self.deck_pick = tk.StringVar(
            value=self.progress.deck_name or names[0])
        picker = tk.OptionMenu(presets, self.deck_pick, *names,
                               command=self._load_deck)
        picker.configure(bg=self.t["panel"], fg=self.t["fg"],
                         activebackground=self.t["accent"],
                         highlightthickness=0, relief="flat", bd=0,
                         font=self.f["label"])
        picker["menu"].configure(bg=self.t["panel"], fg=self.t["fg"],
                                 font=self.f["label"])
        picker.pack(side="left")
        self._button(presets, "Save as", self._save_deck).pack(side="left",
                                                               padx=4)
        self._button(presets, "Delete", self._drop_deck).pack(side="left")

        buttons = tk.Frame(right, bg=self.t["bg"])
        buttons.pack(fill="x", pady=(8, 0))
        self.go_button = self._button(buttons, "Go in", self._begin_run,
                                      fg=self.t["accent"], font=self.f["die"])
        self.go_button.pack(side="left")
        self._button(buttons, "Clear",
                     self._clear_build).pack(side="left", padx=6)

        self._render_prep()

    def _render_prep(self):
        for wrap in (self.pool_wrap, self.deck_wrap):
            for child in wrap.inner.winfo_children():
                child.destroy()

        pool = sorted(self.progress.collection,
                      key=lambda c: (RARITIES.index(card(c)["rarity"]),
                                     card(c)["type"], card(c)["cost"],
                                     card(c)["name"]))
        full = sum(self.build.values()) >= MAX_DECK
        for cid in pool:
            spare = self.progress.owned(cid) - self.build.get(cid, 0)
            self._card_row(
                self.pool_wrap.inner, cid,
                command=(lambda c=cid: self._add(c)),
                badge=f"{spare} spare", label="Add",
                enabled=spare > 0 and not full,
            ).pack(fill="x", pady=1)
        if not pool:
            self._label(self.pool_wrap.inner, "Nothing left. Go and buy "
                        "something.", fg=self.t["muted"]).pack(fill="x",
                                                               pady=6)

        in_deck = sorted(self.build, key=lambda c: (card(c)["cost"],
                                                    card(c)["name"]))
        if not in_deck:
            self._label(self.deck_wrap.inner, "Nothing in it yet.",
                        fg=self.t["muted"]).pack(fill="x", pady=6)
        for cid in in_deck:
            self._card_row(self.deck_wrap.inner, cid,
                           command=(lambda c=cid: self._drop(c)),
                           badge=f"x{self.build[cid]}", label="Remove").pack(
                               fill="x", pady=1)

        total = sum(self.build.values())
        faces = deck_faces(self.build)
        note = self._deck_summary(self.build)
        self.deck_note.configure(text=note)
        short = total < MIN_DECK
        self.go_button.configure(state="disabled" if short else "normal")
        if short:
            tail = f"{MIN_DECK - total} more needed"
        elif faces < 3:
            # Not blocked, only pointed at. A deck with nothing to set down
            # is a deck that will sit there holding cards it cannot pay for.
            tail = "ready - but almost nothing to set down for points"
        else:
            tail = "ready"
        self.status.configure(text=f"{total} cards - {tail}   -   "
                                   f"{self._purse()}")

    def _add(self, cid):
        if sum(self.build.values()) >= MAX_DECK:
            return
        if self.build.get(cid, 0) < self.progress.owned(cid):
            self.build[cid] = self.build.get(cid, 0) + 1
            self._render_prep()

    def _drop(self, cid):
        if self.build.get(cid, 0) > 1:
            self.build[cid] -= 1
        else:
            self.build.pop(cid, None)
        self._render_prep()

    def _clear_build(self):
        self.build = {}
        self._render_prep()

    def _load_deck(self, name):
        deck = self.progress.decks.get(name)
        if deck is None:
            return
        self.progress.deck_name = name
        self.build = self.progress._clean_deck(deck)
        self._render_prep()

    def _save_deck(self):
        name = simpledialog.askstring(
            "Save deck", "Call it what?", parent=self.win,
            initialvalue=self.progress.deck_name or "Deck")
        if not name:
            return
        self.progress.save_deck(name, self.build)
        self.show_prep(self.dungeon, "build")

    def _drop_deck(self):
        name = self.deck_pick.get()
        if name not in self.progress.decks:
            return
        if not messagebox.askyesno("Delete deck", f"Forget {name}?",
                                   parent=self.win):
            return
        self.progress.drop_deck(name)
        self.show_prep(self.dungeon, "build")

    def _begin_run(self):
        if sum(self.build.values()) < MIN_DECK:
            return
        if self.progress.deck_name:
            self.progress.decks[self.progress.deck_name] = dict(self.build)
        self.progress.start_run(self.dungeon, self.build)
        self.show_delve()

    # -- the shop ----------------------------------------------------------
    def _build_shop(self, parent):
        wrap = self._scroller(parent)
        wrap.pack(fill="both", expand=True)
        page = wrap.inner

        self._wrapped(page, "New stock every time you come back up the "
                            "stairs, and nothing worth having until you have "
                            "been down a few times. One rare at a time, so "
                            "the expensive thing stays something you save "
                            "for.", 700).pack(fill="x", pady=(0, 10))

        stock = self.progress.shop()
        for index, entry in enumerate(stock):
            cid = entry["card"]
            left = entry["stock"]
            can = left > 0 and self.progress.gold >= entry["price"]
            badge = f"{left} in stock" if left else "sold out"
            self._card_row(page, cid,
                           command=(lambda i=index: self._buy(i)),
                           badge=badge, label="Buy", enabled=can,
                           price=entry["price"]).pack(fill="x", pady=2)
        if not stock:
            self._label(page, "Nothing in today.",
                        fg=self.t["muted"]).pack(fill="x", pady=8)

        locked = sorted({c["unlock"] for c in CARDS.values()
                         if not c["enemy_only"]
                         and c["unlock"] > len(self.progress.cleared)})
        if locked:
            self._wrapped(page, f"The shopkeeper has better things behind "
                                f"the counter. Clear {locked[0]} floor"
                                f"{'s' if locked[0] != 1 else ''} and he "
                                f"might mention them.", 700,
                          fg=self.t["muted"]).pack(fill="x", pady=(12, 0))

    def _buy(self, index):
        if self.progress.buy(index) is None:
            return
        self.show_prep(self.dungeon, "shop")

    # -- selling -----------------------------------------------------------
    def _build_sell(self, parent):
        wrap = self._scroller(parent)
        wrap.pack(fill="both", expand=True)
        page = wrap.inner
        self._wrapped(page, "He pays well under what he charges, so selling "
                            "to get rich does not work. Selling to get rid "
                            "of the chaff does - but remember the chaff is "
                            "what you set down for points.", 700).pack(
                                fill="x", pady=(0, 10))

        owned = sorted(self.progress.collection,
                       key=lambda c: (RARITIES.index(card(c)["rarity"]),
                                      card(c)["type"], card(c)["name"]))
        for cid in owned:
            held = self.progress.owned(cid)
            self._card_row(page, cid,
                           command=(lambda c=cid: self._sell(c)),
                           badge=f"x{held}", label="Sell",
                           price=sell_price(cid)).pack(fill="x", pady=2)
        if not owned:
            self._label(page, "Nothing to sell.",
                        fg=self.t["muted"]).pack(fill="x", pady=8)

    def _sell(self, cid):
        held = self.progress.owned(cid)
        if not self.progress.can_sell():
            messagebox.showinfo(
                "Sell it",
                f"He stops buying at {MIN_DECK} cards - that is a deck, and "
                f"selling it out from under you would leave nothing to delve "
                f"with and no way to earn the gold to fix it.",
                parent=self.win)
            return
        if held <= 1 and not messagebox.askyesno(
                "Sell it", f"That is your last {card(cid)['name']}. "
                           f"Sell it anyway?", parent=self.win):
            return
        if self.progress.sell(cid):
            self.build = self.progress._clean_deck(self.build)
            self.show_prep(self.dungeon, "sell")

    # -- the delve ---------------------------------------------------------
    def resume(self):
        self.dungeon = DUNGEON_BY_ID[self.progress.run["dungeon"]]
        self.plan = self.progress.run["plan"]
        self.show_delve()

    def _holds(self, room):
        """What this room turned out to hold. Rolled once when the floor was
        prepared and carried in the delve ever since, so it reads the same
        after the window has been closed and opened again."""
        return (self.progress.run or {}).get("plan", {}).get(room["id"], {})

    def _run_room(self, rid):
        for room in self.dungeon["rooms"]:
            if room["id"] == rid:
                return room
        return None

    def _room_state(self, room):
        run = self.progress.run
        if room["id"] in run["cleared"]:
            return "cleared"
        if all(need in run["cleared"] for need in room["needs"]):
            return "open"
        return "locked"

    def show_delve(self, note=""):
        self._clear()
        self.screen = "delve"
        run = self.progress.run
        self.title.configure(text=self.dungeon["name"])
        left = len([r for r in self.dungeon["rooms"]
                    if r["id"] not in run["cleared"]])
        self.status.configure(text=f"{left} rooms to go" if left != 1
                              else "one room to go")

        self.body.columnconfigure(0, weight=1)
        self.body.columnconfigure(1, weight=0, minsize=260)
        self.body.rowconfigure(0, weight=1)

        holder = tk.Frame(self.body, bg=self.t["bg"])
        holder.grid(row=0, column=0, sticky="nsew", padx=(12, 6), pady=12)
        self.map = tk.Canvas(holder, bg=self.t["panel"], highlightthickness=0,
                             bd=0)
        self.map.pack(fill="both", expand=True)
        self.map.bind("<Configure>", lambda _e: self._draw_map())
        self.map.bind("<Button-1>", self._map_click)
        self.map.bind("<Motion>", self._map_hover)

        side = tk.Frame(self.body, bg=self.t["panel"])
        side.grid(row=0, column=1, sticky="nsew", padx=(6, 12), pady=12)
        pad = tk.Frame(side, bg=self.t["panel"])
        pad.pack(fill="both", expand=True, padx=10, pady=10)

        self._label(pad, "Condition", font=self.f["die"],
                    bg=self.t["panel"]).pack(fill="x")
        self._hp_bar(pad, run["hp"], run["max_hp"], width=230).pack(
            fill="x", pady=(4, 10))
        self._label(pad, "Deck", font=self.f["die"],
                    bg=self.t["panel"]).pack(fill="x")
        self._wrapped(pad, self._deck_summary(run["deck"]), 230,
                      bg=self.t["panel"]).pack(fill="x", pady=(2, 10))

        if run["purse"]:
            self._label(pad, f"{run['purse']} gold in your pocket",
                        bg=self.t["panel"],
                        fg=self.t["accent"]).pack(fill="x", pady=(0, 6))
        if run["found"]:
            self._label(pad, "Found so far", font=self.f["die"],
                        bg=self.t["panel"]).pack(fill="x")
            for cid in run["found"]:
                self._label(pad, card(cid)["name"], bg=self.t["panel"],
                            fg=TYPE_COLOR.get(card(cid)["type"],
                                              self.t["muted"])).pack(fill="x")

        opening = ("Click a room you can reach. A room opens once the rooms "
                   "leading to it are clear.")
        self.room_note = self._wrapped(pad, note or opening, 230,
                                       bg=self.t["panel"],
                                       fg=self.t["fg"] if note
                                       else self.t["muted"])
        self.room_note.pack(fill="x", pady=(12, 0))

        foot = tk.Frame(pad, bg=self.t["panel"])
        foot.pack(side="bottom", fill="x")
        self._button(foot, "Give up the delve", self._abandon,
                     bg=self.t["bg"], fg=self.t["fumble"]).pack(fill="x")
        self.win.after(30, self._draw_map)

    def _map_geometry(self):
        """Where the floor sits on the canvas. The rooms carry raw
        coordinates; this centres and scales them into whatever size the
        window happens to be, so the map is never cropped and never has to
        be redrawn by hand when a room moves."""
        width = max(1, self.map.winfo_width())
        height = max(1, self.map.winfo_height())
        xs = [r["x"] for r in self.dungeon["rooms"]]
        ys = [r["y"] for r in self.dungeon["rooms"]]
        span_x = (max(xs) - min(xs)) or 1
        span_y = (max(ys) - min(ys)) or 1
        pad = 78
        scale = min((width - pad * 2) / span_x, (height - pad * 2) / span_y,
                    1.6)
        scale = max(scale, 0.35)
        off_x = (width - span_x * scale) / 2 - min(xs) * scale
        off_y = (height - span_y * scale) / 2 - min(ys) * scale
        return scale, off_x, off_y

    def _room_at(self, room, geometry=None):
        scale, off_x, off_y = geometry or self._map_geometry()
        return room["x"] * scale + off_x, room["y"] * scale + off_y

    def _radius(self, room):
        return 34 if room["slot"] == "boss" else 27

    def _draw_map(self):
        if self.screen != "delve":
            return
        try:
            if not self.map.winfo_exists():
                return
        except tk.TclError:
            return
        self.map.delete("all")
        geometry = self._map_geometry()
        run = self.progress.run

        # Corridors first so the rooms sit on top of them. They are drawn
        # from `needs`, which is also what decides when a room opens - the
        # picture and the rule cannot drift apart.
        for room in self.dungeon["rooms"]:
            x2, y2 = self._room_at(room, geometry)
            for need in room["needs"]:
                other = self._run_room(need)
                if other is None:
                    continue
                x1, y1 = self._room_at(other, geometry)
                walked = need in run["cleared"]
                self.map.create_line(x1, y1, x2, y2, width=3 if walked else 2,
                                     fill=self.t["accent"] if walked
                                     else self.t["bg"])

        for room in self.dungeon["rooms"]:
            self._draw_room(room, geometry)

    def _draw_room(self, room, geometry):
        state = self._room_state(room)
        holds = self._holds(room)
        x, y = self._room_at(room, geometry)
        radius = self._radius(room)
        fill = self.t["accent"] if state == "open" else self.t["bg"]
        edge = {"cleared": self.t["crit"], "open": self.t["accent_hot"],
                "locked": self.t["muted"]}[state]

        self.map.create_oval(x - radius, y - radius, x + radius, y + radius,
                             fill=fill, outline=edge,
                             width=3 if state == "open" else 2)
        if state == "cleared":
            glyph = "x"
        elif holds.get("fight"):
            glyph = ENEMIES[holds["fight"]]["glyph"]
        elif holds.get("rest"):
            glyph = "+"
        elif holds.get("find") or holds.get("gold"):
            glyph = "?"
        else:
            glyph = "-"
        self.map.create_text(x, y, text=glyph, font=self.f["roll"],
                             fill=self.t["bg"] if state == "open" else edge)
        self.map.create_text(x, y + radius + 13, text=room["name"],
                             font=self.f["label"],
                             fill=self.t["fg"] if state != "locked"
                             else self.t["muted"])
        if holds.get("hazard") and state != "cleared":
            hazard = HAZARDS[holds["hazard"]]
            self.map.create_text(
                x, y - radius - 11, text=hazard["name"].lower(),
                font=self.f["label"],
                fill=TYPE_COLOR.get(hazard["type"], self.t["muted"]))

    def _room_under(self, event):
        geometry = self._map_geometry()
        for room in self.dungeon["rooms"]:
            x, y = self._room_at(room, geometry)
            radius = self._radius(room)
            if (event.x - x) ** 2 + (event.y - y) ** 2 <= radius ** 2:
                return room
        return None

    def _map_hover(self, event):
        room = self._room_under(event)
        clickable = room is not None and self._room_state(room) == "open"
        self.map.configure(cursor="hand2" if clickable else "")

    def _map_click(self, event):
        room = self._room_under(event)
        if room is None:
            return
        state = self._room_state(room)
        if state == "cleared":
            self._note(f"{room['name']} is behind you.")
            return
        if state == "locked":
            waiting = [self._run_room(n)["name"] for n in room["needs"]
                       if n not in self.progress.run["cleared"]]
            self._note(f"{room['name']} is shut. Clear "
                       f"{' and '.join(waiting)} first.")
            return
        self._enter(room)

    def _note(self, text):
        self.room_note.configure(text=text, fg=self.t["muted"])

    def _abandon(self):
        if not messagebox.askyesno(
                "Give up the delve",
                "Walk out now and the floor is gone - a new one is rolled "
                "next time. The gold and the cards you picked up down there "
                "are yours to keep.", parent=self.win):
            return
        self.progress.end_run(False)
        self.show_hub()

    # -- walking into a room -----------------------------------------------
    def _enter(self, room):
        """Arriving somewhere. The hazard is paid first, out of the hand you
        will then have to fight with - which is the only reason a toll costs
        anything at all. Pay it out of a hand you were about to throw away
        and it is free."""
        run = self.progress.run
        holds = self._holds(room)

        if holds.get("rest"):
            healed = min(run["max_hp"] - run["hp"], holds["rest"])
            run["hp"] += healed
            self._clear_room(room)
            self.show_delve(note=f"{room['name']}. {room['text']} "
                                 + (f"You get {healed} back."
                                    if healed else "Nothing left to mend."))
            return

        side = Side("You", run["max_hp"], deck_list(run["deck"]),
                    init_mod(run["deck"]))
        side.hp = run["hp"]
        side.draw(HAND_SIZE)

        notes = [(f"{room['name']}. {room['text']}", "note")]
        hazard = HAZARDS.get(holds.get("hazard"))
        if hazard:
            paid = side.spend_hand(hazard["type"], hazard["cards"])
            if paid is not None:
                notes.append((f"{hazard['name']}: you spend "
                              f"{', '.join(paid)} and come through clean.",
                              "good"))
            else:
                side.hp = max(0, side.hp - hazard["damage"])
                notes.append((f"{hazard['name']}: no {hazard['type']} card in "
                              f"hand. You take {hazard['damage']}.", "bad"))
                run["hp"] = side.hp
                if not side.alive():
                    self._lost(f"The {hazard['name'].lower()} finishes you in "
                               f"{room['name']}.")
                    return

        run["hp"] = side.hp
        if holds.get("fight"):
            self._start_duel(room, side, notes)
        else:
            self._clear_room(room)
            self.show_delve(note=notes[-1][0] + self._spoils(holds))

    def _spoils(self, holds):
        bits = []
        if holds.get("find"):
            bits.append(card(holds["find"])["name"])
        if holds.get("gold"):
            bits.append(f"{holds['gold']} gold")
        return f" You come away with {' and '.join(bits)}." if bits else ""

    def _clear_room(self, room):
        run = self.progress.run
        holds = self._holds(room)
        if room["id"] not in run["cleared"]:
            run["cleared"].append(room["id"])
            run["purse"] += holds.get("gold", 0)
            if holds.get("find"):
                run["found"].append(holds["find"])
        self.progress.flush()

    def _start_duel(self, room, you, notes):
        holds = self._holds(room)
        enemy = ENEMIES[holds["fight"]]
        foe = Side(enemy["name"], enemy["hp"], deck_list(enemy["deck"]),
                   enemy["init"], enemy["glyph"])
        # Rolled through the app's own d20, so the house weighting on it
        # applies here the same as it does everywhere else.
        self.duel = Duel(you, foe, roll=lambda: self.api.roll_die("d20"),
                         dealt=True)
        self.duel.log.extend(notes)
        self.room = room
        self.duel.begin()
        self.show_duel()
        if self.duel.state == "foe":
            self._schedule_step()

    # -- the duel ----------------------------------------------------------
    def show_duel(self):
        self._clear()
        self.screen = "duel"
        enemy = ENEMIES[self._holds(self.room)["fight"]]
        self.title.configure(text=f"{self.room['name']} - {enemy['name']}")

        self.body.rowconfigure(0, weight=0)
        self.body.rowconfigure(1, weight=1)
        self.body.rowconfigure(2, weight=0)
        self.body.rowconfigure(3, weight=0)
        self.body.columnconfigure(0, weight=1)

        self.foe_panel = tk.Frame(self.body, bg=self.t["panel"])
        self.foe_panel.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 6))

        middle = tk.Frame(self.body, bg=self.t["bg"])
        middle.grid(row=1, column=0, sticky="nsew", padx=12)
        self.log_box = tk.Text(middle, bg=self.t["panel"], fg=self.t["fg"],
                               font=self.f["result"], relief="flat", bd=0,
                               wrap="word", height=8, padx=10, pady=8,
                               state="disabled", cursor="arrow")
        scroll = tk.Scrollbar(middle, orient="vertical",
                              command=self.log_box.yview)
        self.log_box.configure(yscrollcommand=scroll.set)
        self.log_box.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        tones = (("plain", self.t["fg"]), ("note", self.t["muted"]),
                 ("good", self.t["crit"]), ("bad", self.t["fumble"]))
        for tone, colour in tones:
            self.log_box.tag_configure(tone, foreground=colour)

        self.you_panel = tk.Frame(self.body, bg=self.t["panel"])
        self.you_panel.grid(row=2, column=0, sticky="ew", padx=12, pady=6)

        self.hand_panel = tk.Frame(self.body, bg=self.t["bg"])
        self.hand_panel.grid(row=3, column=0, sticky="ew", padx=12,
                             pady=(0, 12))

        self._render_duel()

    def _pips(self, count):
        return ("*" * count) if count else "-"

    def _render_duel(self):
        duel = self.duel
        for panel in (self.foe_panel, self.you_panel, self.hand_panel):
            for child in panel.winfo_children():
                child.destroy()

        self._render_fighter(self.foe_panel, duel.foe, mine=False)
        self._render_fighter(self.you_panel, duel.you, mine=True)
        self._render_log()
        self._render_hand()

        self.status.configure(
            text={"upkeep": "throw what you do not want",
                  "you": "your turn", "foe": f"{duel.foe.name}'s turn",
                  "react": "answer it, or take it",
                  "over": "done"}.get(duel.state, "")
            + f"   -   round {duel.round}")

    def _render_fighter(self, panel, side, mine):
        inner = tk.Frame(panel, bg=self.t["panel"])
        inner.pack(fill="x", padx=10, pady=8)

        head = tk.Frame(inner, bg=self.t["panel"])
        head.pack(fill="x")
        self._label(head, "You" if mine else side.name, font=self.f["die"],
                    bg=self.t["panel"],
                    fg=self.t["fg"] if mine
                    else self.t["fumble"]).pack(side="left")
        self._hp_bar(head, side.hp, side.max_hp, width=150).pack(side="left",
                                                                 padx=10)
        stats = (f"block {side.block}    points {self._pips(side.ap)}"
                 f"    hand {len(side.hand)}    deck {len(side.draw_pile)}"
                 f"    discard {len(side.discard)}")
        self._label(head, stats, bg=self.t["panel"],
                    fg=self.t["muted"]).pack(side="left", padx=10)
        if side.pending:
            self._label(head, f"winding up {side.pending}",
                        bg=self.t["panel"], fg=self.t["accent"],
                        font=self.f["die"]).pack(side="right")

        if side.field:
            played = tk.Frame(inner, bg=self.t["panel"])
            played.pack(fill="x", pady=(4, 0))
            self._label(played, "on the table:", bg=self.t["panel"],
                        fg=self.t["muted"]).pack(side="left")
            for cid in side.field[-8:]:
                info = card(cid)
                self._label(played, info["name"], bg=self.t["panel"],
                            fg=TYPE_COLOR.get(
                                info["type"],
                                self.t["muted"])).pack(side="left", padx=5)

    def _render_log(self):
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        for text, tone in self.duel.log:
            self.log_box.insert("end", text + "\n", tone)
        self.log_box.configure(state="disabled")
        self.log_box.see("end")

    # A hand is normally five, but a Grappling Hook or two can push it well
    # past that, and eight cards side by side is wider than the window. They
    # wrap instead of running off the edge.
    HAND_ROW = 7

    def _render_hand(self):
        duel = self.duel
        state = duel.state

        # The buttons go down first so they keep their place on the right;
        # the cards take whatever is left.
        side_bar = tk.Frame(self.hand_panel, bg=self.t["bg"])
        side_bar.pack(side="right", fill="y", padx=(10, 0))
        row = tk.Frame(self.hand_panel, bg=self.t["bg"])
        row.pack(side="left", fill="both", expand=True)

        reacting = state == "react"
        for index, cid in enumerate(list(duel.you.hand)):
            info = card(cid)
            if state == "upkeep":
                going = index in duel.marked
                self._card_face(
                    row, cid, on_play=(lambda i=index: self._mark(i)),
                    playable=True, dimmed=going,
                    note="throwing it" if going else "keeping it",
                ).grid(row=index // self.HAND_ROW,
                       column=index % self.HAND_ROW, padx=4, pady=3)
                continue
            playable = ((state == "you" or reacting)
                        and duel.you.can_play(index, quick_only=reacting))
            note = ""
            if reacting and not info["quick"]:
                note = "not quick"
            elif info["cost"] > duel.you.ap:
                note = "too dear"
            bank = None
            if state == "you" and info["face"]:
                bank = (lambda i=index: self._bank(i))
            self._card_face(row, cid,
                            on_play=(lambda i=index: self._play(i)),
                            on_bank=bank, playable=playable,
                            note=note or info["type"]).grid(
                                row=index // self.HAND_ROW,
                                column=index % self.HAND_ROW, padx=4, pady=3)

        if not duel.you.hand:
            self._label(row, "Nothing in hand.", fg=self.t["muted"]).grid(
                row=0, column=0, pady=20)

        if state == "upkeep":
            going = len(duel.marked)
            keeping = len(duel.you.hand) - going
            drawing = max(0, HAND_SIZE - keeping)
            self._label(side_bar, "Click a card to keep it.",
                        fg=self.t["muted"]).pack()
            self._label(side_bar, f"keep {keeping}, draw {drawing}",
                        fg=self.t["accent"], font=self.f["die"]).pack(pady=2)
            self._button(side_bar, "Throw and draw", self._upkeep,
                         fg=self.t["accent"], font=self.f["die"]).pack(pady=4)
            self._button(side_bar, "Keep everything",
                         lambda: self._mark_all(False)).pack()
            self._button(side_bar, "Throw everything",
                         lambda: self._mark_all(True)).pack(pady=2)
        elif state == "you":
            self._button(side_bar, "End turn", self._end_turn,
                         fg=self.t["accent"], font=self.f["die"]).pack(pady=4)
            self._label(side_bar, "what you keep\nrides out their turn",
                        fg=self.t["muted"]).pack()
        elif state == "react":
            incoming = duel.foe.pending
            through = max(0, incoming - duel.you.block)
            self._label(side_bar, f"{incoming} coming in",
                        fg=self.t["fumble"], font=self.f["die"]).pack()
            self._label(side_bar, f"{through} would land",
                        fg=self.t["fumble"] if through
                        else self.t["crit"]).pack()
            self._button(side_bar, "Take it", self._brace,
                         fg=self.t["accent"], font=self.f["die"]).pack(pady=4)
        elif state == "foe":
            self._label(side_bar, f"{duel.foe.name} is playing...",
                        fg=self.t["muted"]).pack(pady=10)

    # -- driving it --------------------------------------------------------
    def _mark(self, index):
        self.duel.mark(index)
        self._render_duel()

    def _mark_all(self, on):
        self.duel.mark_all(on)
        self._render_duel()

    def _upkeep(self):
        self.duel.upkeep_draw()
        self._after_move()

    def _play(self, index):
        if self.duel.play("you", index) is None:
            return
        self._after_move()

    def _bank(self, index):
        if self.duel.play_face("you", index) is None:
            return
        self._after_move()

    def _end_turn(self):
        self.duel.end_turn("you")
        self._after_move()
        if self.duel.state == "foe":
            self._schedule_step()

    def _brace(self):
        self.duel.brace()
        self._after_move()

    def _schedule_step(self):
        """The enemy plays one card at a time on a timer. It could all be
        resolved in a single call, but then the log would simply appear with
        the turn already over and there would be nothing to read."""
        self._cancel_step()
        self.step_job = self.win.after(620, self._step)

    def _step(self):
        self.step_job = None
        if self.screen != "duel" or self.duel.state != "foe":
            return
        if self.duel.enemy_step() is None:
            self.duel.end_turn("foe")
            self._after_move()
            return
        self._after_move()
        if self.duel.state == "foe":
            self._schedule_step()

    def _after_move(self):
        self._render_duel()
        if self.duel.state == "over":
            # A beat to read the last line of the log before the screen
            # changes under you. Tracked like the enemy's turn is, so closing
            # the window in that beat does not fire it at a closed window.
            self._cancel_step()
            self.step_job = self.win.after(700, self._duel_over)

    def _duel_over(self):
        self.step_job = None
        # Reachable twice - the timer above, and anything that settles the
        # fight while it is still pending - and by then the delve it wants to
        # write into may already be closed out.
        if self.screen != "duel" or self.progress.run is None:
            return
        run = self.progress.run
        run["hp"] = self.duel.you.hp
        holds = self._holds(self.room)
        if self.duel.winner != "you":
            self._lost(f"{ENEMIES[holds['fight']]['name']} puts you down in "
                       f"{self.room['name']}.")
            return
        room = self.room
        self._clear_room(room)
        note = f"{ENEMIES[holds['fight']]['name']} is down."
        note += self._spoils(holds)
        if all(r["id"] in run["cleared"] for r in self.dungeon["rooms"]):
            self._won()
            return
        self.show_delve(note=note)

    # -- how it ended ------------------------------------------------------
    def _won(self):
        run = self.progress.run
        found = list(run["found"])
        purse = run["purse"]
        first = self.dungeon["id"] not in self.progress.cleared
        _reward, bonus = self.progress.end_run(True)
        self.show_result(
            True,
            f"{self.dungeon['name']} is clear." if first
            else f"{self.dungeon['name']} is clear again.",
            found, purse, bonus)

    def _lost(self, reason):
        run = self.progress.run
        found = list(run["found"])
        purse = run["purse"]
        self.progress.end_run(False)
        self.show_result(False, reason, found, purse, 0)

    def show_result(self, won, reason, found, purse, bonus):
        self._clear()
        self.screen = "result"
        self.title.configure(text="Clear" if won else "Down")
        self.status.configure(text=self._purse())

        wrap = self._scroller(self.body)
        wrap.pack(fill="both", expand=True, padx=24, pady=20)
        page = wrap.inner

        self._label(page, "The floor is yours." if won
                    else "That is as far as you got.", font=self.f["total"],
                    fg=self.t["crit"] if won else self.t["fumble"]).pack(
                        fill="x")
        self._wrapped(page, reason, 780).pack(fill="x", pady=(6, 16))

        if purse or bonus:
            self._label(page, "Gold", font=self.f["die"],
                        fg=self.t["accent"]).pack(fill="x", pady=(6, 2))
            if purse:
                self._label(page, f"{purse} picked up on the way",
                            fg=self.t["muted"]).pack(fill="x")
            if bonus:
                self._label(page, f"{bonus} for clearing it",
                            fg=self.t["muted"]).pack(fill="x")
            self._label(page, f"{self.progress.gold} gold in hand now",
                        fg=self.t["accent"]).pack(fill="x", pady=(2, 0))

        if found:
            self._label(page, "Cards picked up", font=self.f["die"],
                        fg=self.t["accent"]).pack(fill="x", pady=(12, 4))
            for cid in found:
                self._card_row(page, cid).pack(fill="x", pady=1)

        if not found and not purse and not bonus:
            self._wrapped(page, "Nothing to show for it. The cards you built "
                                "the deck from are all still in the "
                                "collection - a bad delve costs the delve, "
                                "not the collection.", 780).pack(fill="x")

        if not won:
            self._wrapped(page, "The floor is gone; a fresh one is rolled "
                                "next time, and the shop has new stock. "
                                "Build again and go back in.", 780,
                          fg=self.t["muted"]).pack(fill="x", pady=(16, 0))

        self._button(page, "Back to the hub", self.show_hub,
                     fg=self.t["accent"], font=self.f["die"]).pack(
                         anchor="w", pady=20)


# What the How this works screen says. Kept out here because it is prose
# about the rules rather than part of them.
RULES = [
    ("The deck",
     f"At least {MIN_DECK} cards, at most {MAX_DECK}, built out of your "
     f"collection before you go in. The deck is rebuilt for every delve and "
     f"nothing in it is used up, so a deck is a choice rather than a cost. "
     f"Save as many as you like and pick one on the way down."),
    ("A turn",
     f"Throw whatever you do not want out of your hand, draw back up to "
     f"{HAND_SIZE}, bank a point, then play what you can afford. The hand is "
     f"always filled to the same size, so a card you keep is a card you do "
     f"not draw - holding a Parry back is never free."),
    ("Action points",
     "Cards cost points to play and you bank one a turn whatever you drew. "
     "Focus banks two. And every common can be set face down for a point "
     "instead of played, so a common is never a dead draw - it is either a "
     "small effect or the money to pay for a big one."),
    ("Rarity",
     "Commons are weak for their cost and can be set down for a point. "
     "Uncommons and rares are better per point and cannot. That is the whole "
     "trap: sell all your commons to afford the good cards and you will find "
     "you can no longer pay for them."),
    ("Attacking",
     "Damage from the cards you play lands at the end of your turn, all at "
     "once, against whatever block the other side is standing behind. Block "
     "soaks what it can and is worn down by what it soaked."),
    ("Block",
     "Worth about half as much again as damage, point for point, because it "
     "only pays if the blow actually comes. Built on your turn, survives "
     "their turn, gone when your next turn starts."),
    ("Quick cards",
     "Playable while the other side is swinging, and their damage lands the "
     "moment it is played rather than at the end of a turn. That is how a "
     "fight gets finished before the blow arrives."),
    ("Card types",
     "Every card is might, acrobatics or magic. Hazards ask for a type by "
     "name, and three acrobatics cards in a deck buy a point of initiative."),
    ("Tolls",
     "Paid on arrival, out of the hand you are about to fight with. Spend "
     "the cards it asks for or take the damage - and either way you go into "
     "the fight with what is left."),
    ("Gold and the shop",
     "Gold comes out of the rooms and out of clearing the floor. The shop "
     "restocks every time you come back up, sells one rare at a time, and "
     "keeps the best cards behind the counter until you have been deep "
     "enough to be shown them. It buys back at well under what it charges."),
    ("Every floor is rolled",
     "The shape of a floor is fixed but what is standing in it is not. It is "
     "rolled when you sit down to prepare, so the briefing is telling you "
     "the truth about the floor you are about to walk into - and backing out "
     "will not reroll it."),
    ("Hit points",
     "One pool for the whole floor. Nothing gives it back but a rest room "
     "and the cards you brought."),
    ("Going long",
     f"From round {GRIND_ROUND} the air goes bad and both sides start taking "
     f"damage that block cannot stop, a little more each round. Two sides "
     f"that cannot finish each other would otherwise trade cards forever."),
]


def setup(api):
    holder = {"window": None}

    def open_game():
        window = holder["window"]
        if window is not None and window.alive():
            window.win.deiconify()
            window.win.lift()
            window.win.focus_force()
            return
        holder["window"] = CardDungeon(api)

    def flush(_name=None):
        window = holder["window"]
        if window is not None and window.alive():
            window.save()

    api.add_menu_command("Tools", "Card Dungeon...", open_game)
    api.on("save", flush)
