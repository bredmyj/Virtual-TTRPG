"""The rules, checked without opening a window.

Run it with `python tests/test_rules.py`, or `python -m unittest discover
tests`. Nothing in here needs a display, a save file or a network - it pokes
at the parts of the mods that are plain Python, which is exactly the reason
those parts were kept plain Python.

Two things are covered:

  * `card_dungeon`'s `Duel`, and the tables it deals from. The fuzz below
    plays several hundred fights at random and asserts the things that must
    be true at the end of every one of them - nobody on negative hit points,
    no card conjured or lost, and the fight actually over. Random play is a
    poor player and loses more than it wins; that is not what is being
    measured. What is being measured is that no sequence of legal moves puts
    the game somewhere it cannot get out of.
  * `encounters`' naming, which is fiddlier than it looks: it has to letter
    a set of copies, migrate a save that used numbers, and leave alone both
    the players and anyone whose name merely happens to end in a letter.
"""

import os
import random
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, "plugins")]

import card_dungeon as cd          # noqa: E402
import encounters                  # noqa: E402


# --------------------------------------------------------------------------
# The tables the game deals from
# --------------------------------------------------------------------------
class TestTables(unittest.TestCase):
    """Every id the data points at should be a card that exists. A typo in
    here is the kind of thing that only shows up when the shop happens to
    roll that slot, which could be weeks."""

    def setUp(self):
        self.known = set(cd.CARDS)

    def test_enemy_decks_are_real_cards(self):
        for eid, enemy in cd.ENEMIES.items():
            for cid in enemy["deck"]:
                self.assertIn(cid, self.known, f"{eid} deals {cid!r}")

    def test_pools_are_real_cards(self):
        for cid in list(cd.PLAYER_CARDS) + list(cd.STARTER):
            self.assertIn(cid, self.known)

    def test_starter_can_field_a_deck(self):
        """The collection you begin with has to be a legal deck, or a new
        campaign opens on a screen it cannot leave."""
        self.assertGreaterEqual(sum(cd.STARTER.values()), cd.MIN_DECK)

    def test_floors_can_be_finished(self):
        """A room waits on the rooms leading to it. Work forward from the
        entrance and every room should come free - one that never does is a
        floor that cannot be cleared, and the delve would simply stop."""
        for dungeon in cd.DUNGEONS:
            rooms = dungeon["rooms"]
            ids = [room["id"] for room in rooms]
            self.assertEqual(len(ids), len(set(ids)), f"{dungeon['id']} ids")
            for room in rooms:
                for needed in room.get("needs", ()):
                    self.assertIn(needed, ids,
                                  f"{dungeon['id']}/{room['id']} waits on "
                                  f"{needed!r}, which is not on the floor")
            cleared, moved = set(), True
            while moved:
                moved = False
                for room in rooms:
                    if room["id"] in cleared:
                        continue
                    if all(n in cleared for n in room.get("needs", ())):
                        cleared.add(room["id"])
                        moved = True
            self.assertEqual(set(ids), cleared,
                             f"{dungeon['id']} strands "
                             f"{sorted(set(ids) - cleared)}")

    def test_plans_and_shop_roll_clean(self):
        for seed in range(120):
            rand = random.Random(seed)
            for dungeon in cd.DUNGEONS:
                plan = cd.roll_plan(dungeon, rand)
                cd.plan_briefing(dungeon, plan)
            for cleared in (0, 1, 4, 40):
                for entry in cd.roll_shop(cleared, rand):
                    self.assertIn(entry["card"], self.known)
                    self.assertGreaterEqual(entry["price"], 1)


# --------------------------------------------------------------------------
# A fight, played badly, several hundred times
# --------------------------------------------------------------------------
class TestDuel(unittest.TestCase):

    def _play(self, rand, enemy, cap=5000):
        """One fight, both sides playing at random, driven exactly the way
        the window drives it. Returns the finished duel."""
        deck = [rand.choice(list(cd.PLAYER_CARDS))
                for _ in range(rand.randint(cd.MIN_DECK, cd.MAX_DECK))]
        you = cd.Side("You", 30, deck, mod=rand.randint(0, 3))
        foe = cd.Side(enemy["name"], enemy["hp"], cd.deck_list(enemy["deck"]),
                      mod=enemy["init"], glyph=enemy["glyph"])
        duel = cd.Duel(you, foe, roll=lambda: rand.randint(1, 20))
        duel.begin()
        for _ in range(cap):
            if duel.state == "over":
                return duel
            if duel.state == "upkeep":
                if rand.random() < 0.3:
                    duel.mark_all(False)
                duel.upkeep_draw()
            elif duel.state == "you":
                playable = [i for i in range(len(you.hand)) if you.can_play(i)]
                settable = [i for i in range(len(you.hand)) if you.can_face(i)]
                if playable and rand.random() < 0.75:
                    duel.play("you", rand.choice(playable))
                elif settable and rand.random() < 0.5:
                    duel.play_face("you", rand.choice(settable))
                else:
                    duel.end_turn("you")
            elif duel.state == "foe":
                if duel.enemy_step() is None:
                    duel.end_turn("foe")
            elif duel.state == "react":
                quick = [i for i in range(len(you.hand))
                         if you.can_play(i, quick_only=True)]
                if quick and rand.random() < 0.5:
                    duel.play("you", rand.choice(quick))
                else:
                    duel.brace()
            else:
                self.fail(f"unknown state {duel.state!r}")
        self.fail(f"fight against {enemy['name']} never ended "
                  f"(round {duel.round})")

    def test_fights_end_and_stay_honest(self):
        rand = random.Random(20240918)
        enemies = list(cd.ENEMIES.values())
        for trial in range(400):
            enemy = rand.choice(enemies)
            duel = self._play(rand, enemy)
            with self.subTest(trial=trial, enemy=enemy["id"]):
                self.assertIn(duel.winner, ("you", "foe"))
                for side in (duel.you, duel.foe):
                    self.assertGreaterEqual(side.hp, 0)
                    self.assertGreaterEqual(side.ap, 0)
                    self.assertGreaterEqual(side.block, 0)
                    # Cards move between four piles and nowhere else. If the
                    # total drifts, something is being played twice or
                    # quietly dropped on the floor.
                    held = (len(side.hand) + len(side.draw_pile)
                            + len(side.discard) + len(side.field))
                    self.assertEqual(held, len(side.deck), f"{side.name} piles")

    def test_the_air_goes_bad(self):
        """Two sides that cannot hurt each other still have to finish. The
        grind is what guarantees it, so check it actually bites."""
        stalemate = ["guard"] * cd.MIN_DECK
        you = cd.Side("You", 30, list(stalemate))
        foe = cd.Side("Wall", 30, list(stalemate))
        # A real d20, because `begin` settles a tie between two equal
        # modifiers by rolling again - hand it a constant and it spins.
        rand = random.Random(4)
        duel = cd.Duel(you, foe, roll=lambda: rand.randint(1, 20))
        duel.begin()
        for _ in range(5000):
            if duel.state == "over":
                break
            if duel.state == "upkeep":
                duel.upkeep_draw()
            elif duel.state == "you":
                duel.end_turn("you")
            elif duel.state == "foe":
                if duel.enemy_step() is None:
                    duel.end_turn("foe")
            elif duel.state == "react":
                duel.brace()
        self.assertEqual(duel.state, "over", "a stalled fight never ended")
        self.assertGreater(duel.round, cd.GRIND_ROUND)


# --------------------------------------------------------------------------
# What the collection will and will not let you do
# --------------------------------------------------------------------------
class FakeAPI:
    """Stands in for the per-campaign storage a mod is handed."""

    def __init__(self, storage=None):
        self.storage = {} if storage is None else storage

    def save(self):
        pass

    def log(self, *args):
        pass


class TestProgress(unittest.TestCase):

    def test_a_new_campaign_gets_the_starter(self):
        progress = cd.Progress(FakeAPI())
        self.assertEqual(progress.collection, dict(cd.STARTER))

    def test_an_empty_collection_is_not_a_new_campaign(self):
        """Sell down to nothing and the starter must not come back. It used
        to: an empty collection read as a fresh campaign, so closing and
        reopening the window handed the cards back and left the gold - which
        is a purse that goes up for ever."""
        api = FakeAPI()
        first = cd.Progress(api)
        for _ in range(200):
            if not any(first.sell(cid) for cid in list(first.collection)):
                break
        purse = first.gold
        again = cd.Progress(api)
        self.assertEqual(again.collection, first.collection)
        self.assertEqual(again.gold, purse)

    def test_he_will_not_buy_you_out_of_a_deck(self):
        """Gold only comes back up the stairs, so a collection too small to
        delve with is a dead campaign."""
        api = FakeAPI()
        progress = cd.Progress(api)
        progress.gain("strike")
        progress.gain("strike")
        for _ in range(200):
            if not any(progress.sell(cid) for cid in list(progress.collection)):
                break
        self.assertGreaterEqual(progress.total_cards(), cd.MIN_DECK)
        self.assertFalse(progress.can_sell())

    def test_a_save_from_a_stranger_build_still_loads(self):
        """A card this build has never heard of comes off, and everything
        else should survive the trip."""
        api = FakeAPI({"collection": {"strike": 3, "moon_lance": 9},
                       "gold": 40, "cleared": ["nowhere"], "decks": "nonsense"})
        progress = cd.Progress(api)
        self.assertEqual(progress.collection, {"strike": 3})
        self.assertEqual(progress.gold, 40)
        self.assertEqual(progress.cleared, [])
        self.assertEqual(progress.decks, {})


# --------------------------------------------------------------------------
# Naming a room full of goblins
# --------------------------------------------------------------------------
class TestNaming(unittest.TestCase):
    """`_reletter` and `_unique` only ever touch `self.creatures`, so a bare
    instance with that one attribute set is enough to exercise them."""

    def roster(self, creatures):
        board = object.__new__(encounters.Encounters)
        board.creatures = creatures
        return board

    def creature(self, name, player=False, base=None):
        made = {"name": name, "player": player}
        if base is not None:
            made["base"] = base
        return made

    def names(self, board):
        return [creature["name"] for creature in board.creatures]

    def test_copies_get_letters(self):
        board = self.roster([self.creature("Goblin", base="Goblin")])
        added = board._unique("Goblin")
        self.assertEqual(self.names(board), ["Goblin A"])
        self.assertEqual(added, "Goblin B")

    def test_an_old_save_migrates_off_numbers(self):
        board = self.roster([self.creature("Goblin"),
                             self.creature("Goblin 2"),
                             self.creature("Goblin 3")])
        board._reletter()
        self.assertEqual(self.names(board), ["Goblin A", "Goblin B", "Goblin C"])
        # and the family is written down, so it is guessed at only the once
        self.assertEqual([c["base"] for c in board.creatures], ["Goblin"] * 3)

    def test_relettering_twice_changes_nothing(self):
        board = self.roster([self.creature("Goblin"), self.creature("Goblin 2")])
        board._reletter()
        settled = self.names(board)
        board._reletter()
        self.assertEqual(self.names(board), settled)

    def test_a_lone_creature_keeps_its_name(self):
        """The half of this that bites: a name ending in a letter or a
        numeral is not a label, and shortening it loses what it was called.
        A player's name is worse still - it came off the game map, and the
        map is still using it."""
        board = self.roster([self.creature("Golem Mark II"),
                             self.creature("Sir Gareth IV"),
                             self.creature("Unit 7"),
                             self.creature("Kara V", player=True)])
        board._reletter()
        self.assertEqual(self.names(board),
                         ["Golem Mark II", "Sir Gareth IV", "Unit 7", "Kara V"])

    def test_a_player_is_never_relettered(self):
        board = self.roster([self.creature("Shade", player=True),
                             self.creature("Shade"),
                             self.creature("Shade")])
        board._reletter()
        self.assertEqual(self.names(board), ["Shade", "Shade A", "Shade B"])

    def test_adding_a_player_letters_nothing(self):
        board = self.roster([self.creature("Shade", base="Shade")])
        added = board._unique("Shade", player=True)
        self.assertEqual(self.names(board), ["Shade"])
        self.assertEqual(added, "Shade")

    def test_an_odd_name_is_its_own_family(self):
        board = self.roster([self.creature("Golem Mark II",
                                           base="Golem Mark II")])
        added = board._unique("Golem Mark II")
        self.assertEqual(self.names(board), ["Golem Mark II A"])
        self.assertEqual(added, "Golem Mark II B")

    def test_the_letters_carry_past_z(self):
        board = self.roster([self.creature("Rat", base="Rat")
                             for _ in range(27)])
        board._reletter()
        self.assertEqual(self.names(board)[25], "Rat Z")
        self.assertEqual(self.names(board)[26], "Rat AA")


if __name__ == "__main__":
    unittest.main(verbosity=2)
