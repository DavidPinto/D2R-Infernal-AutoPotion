"""Unit tests for the pure logic that does not need a running game.

Run from the project root:

    python -m unittest discover -s tests -v

Config tests patch the module-level config path so the real
``config/config.json`` is never touched.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import d2r.config as cfg
from d2r import models as m


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="d2rap-test-")
        self._old_dir, self._old_path = cfg.CONFIG_DIR, cfg.CONFIG_PATH
        cfg.CONFIG_DIR = self._tmp
        cfg.CONFIG_PATH = os.path.join(self._tmp, "config.json")

    def tearDown(self):
        cfg.CONFIG_DIR, cfg.CONFIG_PATH = self._old_dir, self._old_path

    def test_defaults_and_accessors(self):
        c = cfg.AppConfig.load()
        self.assertFalse(c.enabled)
        self.assertEqual(c.threshold("healing_potion_at"), 80)
        self.assertEqual(c.cooldown("heal"), 4.0)
        self.assertEqual(c.key("heal"), "Q")
        # Unknown names fall back safely (never trigger / no spam), never raise.
        self.assertEqual(c.threshold("nope"), 0)
        self.assertEqual(c.cooldown("nope"), 2.0)
        self.assertEqual(c.key("nope"), "")
        self.assertEqual(c.keys_for("nope"), [])

    def test_keys_for_supports_multiple_columns(self):
        c = cfg.AppConfig.load()
        self.assertEqual(c.keys_for("heal"), ["Q"])          # plain string binding
        c.keys["heal"] = ["Q", "R"]                          # 4th-column binding
        self.assertEqual(c.keys_for("heal"), ["Q", "R"])
        self.assertEqual(c.key("heal"), "Q")                 # primary key unchanged
        c.keys["rejuv"] = "R"                                # bind rejuv to 4th column
        self.assertEqual(c.keys_for("rejuv"), ["R"])
        c.keys["mana"] = []
        self.assertEqual(c.keys_for("mana"), [])

    def test_persist_round_trip(self):
        c = cfg.AppConfig.load()
        c.thresholds["healing_potion_at"] = 55
        c.behavior["toggle_hotkey"] = "Ctrl+Shift+F9"
        c.save()
        d = cfg.AppConfig.load()
        self.assertEqual(d.threshold("healing_potion_at"), 55)
        self.assertEqual(d.behavior["toggle_hotkey"], "Ctrl+Shift+F9")

    def test_presets(self):
        c = cfg.AppConfig.load()
        self.assertEqual(sorted(cfg.PRESETS), ["Boss farming", "Conservative", "Leveling", "Mana-heavy"])
        self.assertTrue(c.apply_preset("Boss farming"))
        self.assertEqual(c.threshold("healing_potion_at"), 85)
        self.assertEqual(c.cooldown("rejuv"), 1.5)
        # Keys are left untouched by a preset.
        self.assertEqual(c.key("heal"), "Q")
        self.assertFalse(c.apply_preset("No such preset"))

    def test_profiles_round_trip(self):
        c = cfg.AppConfig.load()
        c.thresholds["healing_potion_at"] = 42
        c.keys["heal"] = "F1"
        c.save_profile("Zerker")
        self.assertIn("Zerker", c.profile_names())
        c.apply_preset("Leveling")
        self.assertNotEqual(c.threshold("healing_potion_at"), 42)
        self.assertTrue(c.load_profile("Zerker"))
        self.assertEqual(c.threshold("healing_potion_at"), 42)
        self.assertEqual(c.key("heal"), "F1")
        c.delete_profile("Zerker")
        self.assertNotIn("Zerker", c.profile_names())
        self.assertFalse(c.load_profile("Zerker"))

    def test_reset_to_defaults(self):
        c = cfg.AppConfig.load()
        c.apply_preset("Conservative")
        c.reset_to_defaults()
        self.assertEqual(c.threshold("healing_potion_at"), 80)
        self.assertEqual(c.cooldown("heal"), 4.0)

    def test_combos_round_trip(self):
        c = cfg.AppConfig.load()
        self.assertEqual(c.combo_names(), [])
        c.save_combo("MyMod", [[587, "heal", 0], [588, "heal", 1]], [999], "notes")
        self.assertIn("MyMod", c.combo_names())
        self.assertEqual(c.combo, "MyMod")
        self.assertEqual(c.potion_codes().kind(587), "heal")
        self.assertEqual(c.potion_codes().kind(602), None)   # combo replaces, not merges
        self.assertEqual(c.merc_txtfiles_set(), frozenset({999}))
        c.save()
        d = cfg.AppConfig.load()
        self.assertEqual(d.combo, "MyMod")
        self.assertEqual(d.potion_codes().kind(588), "heal")
        self.assertEqual(d.merc_txtfiles_set(), frozenset({999}))
        # Back to built-in defaults.
        self.assertTrue(d.set_active_combo(""))
        self.assertEqual(d.potion_codes().kind(602), "heal")
        self.assertEqual(d.merc_txtfiles_set(), frozenset({338, 271}))
        d.delete_combo("MyMod")
        self.assertEqual(d.combo_names(), [])
        self.assertFalse(d.set_active_combo("Nope"))

    def test_potion_margin_and_class_accessors(self):
        c = cfg.AppConfig.load()
        self.assertEqual(c.potion_margin(), 1.2)   # 20% default -> x1.2
        self.assertEqual(c.potion_class(), "")     # auto-detect by default
        c.behavior["potion_margin_percent"] = 50
        self.assertEqual(c.potion_margin(), 1.5)
        c.behavior["potion_margin_percent"] = -5
        self.assertEqual(c.potion_margin(), 1.0)   # never below 1.0
        c.behavior["potion_margin_percent"] = "bogus"
        self.assertEqual(c.potion_margin(), 1.2)   # bad data falls back safely
        c.behavior["potion_class_override"] = "Barbarian"
        self.assertEqual(c.potion_class(), "Barbarian")
        c.behavior["potion_class_override"] = "Nope"
        self.assertEqual(c.potion_class(), "")

    def test_managed_columns_and_refill_accessors(self):
        c = cfg.AppConfig.load()
        self.assertEqual(c.managed_columns(), ["Q", "W", "E", "R"])
        c.set_managed_columns(["Q", "R"])
        self.assertEqual(c.managed_columns(), ["Q", "R"])
        self.assertEqual(c.managed_indices(), {0, 3})
        c.set_managed_columns(["Q", "Bogus"])   # invalid keys dropped
        self.assertEqual(c.managed_columns(), ["Q"])
        c.set_managed_columns([])               # never empty -> falls back to all
        self.assertEqual(c.managed_columns(), ["Q", "W", "E", "R"])

        self.assertFalse(c.refill_enabled())
        self.assertEqual(c.refill_interval(), 0.4)
        self.assertFalse(c.refill_mapping()["calibrated"])
        c.set_refill_enabled(True)
        c.set_refill_mapping(29.5, 123, 456)
        self.assertTrue(c.refill_enabled())
        self.assertTrue(c.refill_mapping()["calibrated"])
        self.assertEqual(c.refill_mapping()["cell"], 29.5)
        c.clear_refill_mapping()
        self.assertFalse(c.refill_mapping()["calibrated"])

    def test_refill_and_managed_persist(self):
        c = cfg.AppConfig.load()
        c.set_managed_columns(["Q", "E"])
        c.set_refill_enabled(True)
        c.set_refill_mapping(30, 100, 200)
        c.save()
        d = cfg.AppConfig.load()
        self.assertEqual(d.managed_columns(), ["Q", "E"])
        self.assertTrue(d.refill_enabled())
        self.assertTrue(d.refill_mapping()["calibrated"])
        self.assertEqual(d.refill_mapping()["cell"], 30)

    def test_reset_refill_defaults(self):
        c = cfg.AppConfig.load()
        c.set_refill_enabled(True)
        c.set_refill_mapping(30, 1, 2)
        c.set_managed_columns(["Q"])
        c.reset_to_defaults()
        self.assertFalse(c.refill_enabled())
        self.assertFalse(c.refill_mapping()["calibrated"])
        self.assertEqual(c.managed_columns(), ["Q", "W", "E", "R"])

    def test_smart_plan_accessors_and_persist(self):
        c = cfg.AppConfig.load()
        self.assertTrue(c.smart_enabled())
        c.set_smart_enabled(False)
        self.assertFalse(c.smart_enabled())

        self.assertEqual(c.belt_layout(), {})
        c.set_belt_layout({0: "heal", 4: "mana", 99: "rejuv", "x": "mana"})
        self.assertEqual(c.belt_layout(), {0: "heal", 4: "mana"})   # invalid slot dropped
        c.set_belt_layout({0: "bogus"})
        self.assertEqual(c.belt_layout(), {})

        self.assertEqual(c.belt_ratio(), {"heal": 8, "mana": 6, "rejuv": 2})
        c.set_belt_ratio({"heal": 4, "mana": 4, "rejuv": 1, "bogus": 9})
        self.assertEqual(c.belt_ratio(), {"heal": 4, "mana": 4, "rejuv": 1})

        c.set_belt_layout({0: "heal", 4: "mana"})   # back to a real plan before saving
        c.save()
        d = cfg.AppConfig.load()
        self.assertFalse(d.smart_enabled())
        self.assertEqual(d.belt_layout(), {0: "heal", 4: "mana"})
        self.assertEqual(d.belt_ratio(), {"heal": 4, "mana": 4, "rejuv": 1})

        d.reset_to_defaults()
        self.assertTrue(d.smart_enabled())
        self.assertEqual(d.belt_layout(), {})
        self.assertEqual(d.belt_ratio(), {"heal": 8, "mana": 6, "rejuv": 2})


class ModelsTests(unittest.TestCase):
    def test_potion_kinds(self):
        # Infernal Edition (Warlock) codes: classic D2R + 15.
        self.assertEqual(m.potion_kind(602), "heal")
        self.assertEqual(m.potion_kind(606), "heal")
        self.assertEqual(m.potion_kind(607), "mana")
        self.assertEqual(m.potion_kind(611), "mana")
        self.assertEqual(m.potion_kind(530), "rejuv")
        self.assertEqual(m.potion_kind(531), "rejuv")
        self.assertEqual(m.potion_kind(528), "other")   # Stamina
        self.assertEqual(m.potion_kind(529), "other")   # Antidote
        self.assertEqual(m.potion_kind(532), "other")   # Thawing
        self.assertIsNone(m.potion_kind(1))
        self.assertIsNone(m.potion_kind(601))
        self.assertIsNone(m.potion_kind(515))           # old (classic) codes are gone

    def test_potion_grades_and_restore(self):
        self.assertEqual(m.potion_grade(602), 0)
        self.assertEqual(m.potion_grade(606), 4)
        self.assertEqual(m.potion_grade(607), 0)
        self.assertEqual(m.potion_grade(611), 4)
        self.assertEqual(m.potion_grade(530), 0)
        self.assertEqual(m.potion_grade(531), 1)
        self.assertEqual(m.potion_grade(1), -1)
        # Module helper defaults to the middle class group (group 1).
        self.assertEqual(m.potion_restore(602, 200), 45)   # Minor heal
        self.assertEqual(m.potion_restore(605, 200), 270)  # Greater heal
        self.assertEqual(m.potion_restore(606, 200), 480)  # Super heal (fixed, not 100%)
        self.assertEqual(m.potion_restore(608, 200), 60)   # Light mana
        self.assertEqual(m.potion_restore(530, 200), 70)   # rejuv 35% of max
        self.assertEqual(m.potion_restore(531, 200), 200)  # full rejuv 100%
        self.assertEqual(m.potion_restore(1, 200), 0)

    def test_potion_restore_is_class_dependent(self):
        codes = m.default_potion_codes()
        # Heal groups: 0 = Druid/Necro/Sorc/Warlock, 1 = mid, 2 = Barbarian.
        self.assertEqual(codes.restore(602, 200, "Sorceress"), 30)
        self.assertEqual(codes.restore(602, 200, "Amazon"), 45)
        self.assertEqual(codes.restore(602, 200, "Barbarian"), 60)
        self.assertEqual(codes.restore(606, 200, "Druid"), 320)
        self.assertEqual(codes.restore(606, 200, "Barbarian"), 640)
        # Mana groups: 0 = Barbarian, 1 = mid, 2 = Druid/Necro/Sorc/Warlock.
        self.assertEqual(codes.restore(608, 200, "Barbarian"), 40)
        self.assertEqual(codes.restore(608, 200, "Sorceress"), 80)
        self.assertEqual(codes.restore(611, 200, "Warlock"), 500)
        # Rejuv is class-independent and instant.
        self.assertEqual(codes.restore(530, 200, "Barbarian"), 70)
        self.assertEqual(codes.restore(531, 200, "Amazon"), 200)
        self.assertEqual(codes.duration(530), 0.0)
        self.assertEqual(codes.duration(531), 0.0)

    def test_potion_durations(self):
        codes = m.default_potion_codes()
        self.assertAlmostEqual(codes.duration(602), 7.68)    # Minor heal
        self.assertAlmostEqual(codes.duration(606), 10.24)   # Super heal
        self.assertAlmostEqual(codes.duration(607), 5.12)    # Minor mana
        self.assertAlmostEqual(codes.duration(611), 5.12)    # Super mana

    def test_potion_codes_player_class_default(self):
        codes = m.default_potion_codes()
        codes.player_class = "Barbarian"
        self.assertEqual(codes.restore(602, 200), 60)   # heal group 2
        self.assertEqual(codes.restore(607, 200), 20)   # mana group 0
        codes.player_class = "Sorceress"
        self.assertEqual(codes.restore(602, 200), 30)   # heal group 0
        self.assertEqual(codes.restore(607, 200), 40)   # mana group 2
        codes.player_class = ""
        self.assertEqual(codes.restore(602, 200), 45)   # unknown -> middle group

    def _col(self, key, txt, count=1):
        return m.BeltColumn(key=key, index=m.BELT_COLUMN_KEYS.index(key),
                            txt=txt, kind=m.potion_kind(txt),
                            grade=m.potion_grade(txt), count=count)

    def _pc(self, columns):
        pc = m.PotionCounts()
        pc.ok = True
        pc.columns = columns
        return pc

    def test_choose_belt_column_smallest_covering(self):
        # Minor (45, mid group) vs Super (270); deficit 50 -> Super covers, Minor not.
        pc = self._pc([self._col("Q", 602), self._col("R", 605)])
        self.assertEqual(pc.choose_belt_column("heal", 50, 200), 3)
        # Deficit 20 -> both cover, pick the smallest grade (Q).
        self.assertEqual(pc.choose_belt_column("heal", 20, 200), 0)

    def test_choose_belt_column_strongest_when_none_covers(self):
        pc = self._pc([self._col("Q", 602), self._col("R", 603)])
        self.assertEqual(pc.choose_belt_column("heal", 100, 200), 3)

    def test_choose_belt_column_respects_binding_and_kind(self):
        pc = self._pc([self._col("Q", 602), self._col("E", 605)])
        self.assertEqual(pc.choose_belt_column("heal", 40, 200, allowed_keys=("Q",)), 0)
        self.assertIsNone(pc.choose_belt_column("mana", 10, 200))
        self.assertIsNone(pc.choose_belt_column("heal", 10, 200, allowed_keys=("R",)))

    def test_choose_belt_column_uses_next_to_drink_potion(self):
        # Column R: next-to-drink is the Thawing (other) at slot 3; the Light Mana
        # behind it (slot 7) is not drinkable yet, so R is not a mana candidate.
        pc = self._pc([self._col("Q", 608), self._col("R", 532)])
        self.assertEqual(pc.choose_belt_column("mana", 10, 200), 0)
        self.assertIsNone(pc.choose_belt_column("mana", 10, 200, allowed_keys=("R",)))

    def test_choose_belt_column_rejuv(self):
        pc = self._pc([self._col("Q", 530), self._col("R", 531)])
        # 35% (70/200) does not cover a 100-deficit; Full Rejuv does.
        self.assertEqual(pc.choose_belt_column("rejuv", 100, 200), 3)
        self.assertEqual(pc.choose_belt_column("rejuv", 50, 200), 0)

    def test_potion_codes_custom_table(self):
        codes = m.PotionCodes([
            m.PotionEntry(587, "heal", 0), m.PotionEntry(591, "heal", 4),
            m.PotionEntry(515, "rejuv", 0), m.PotionEntry(516, "rejuv", 1),
            m.PotionEntry(512, "other", -1),
        ])
        self.assertEqual(codes.kind(587), "heal")
        self.assertEqual(codes.grade(587), 0)
        self.assertEqual(codes.kind(516), "rejuv")
        self.assertIsNone(codes.kind(602))     # not part of this table
        self.assertEqual(codes.grade(602), -1)
        # Custom tables use the same class-dependent restore model.
        self.assertEqual(codes.restore(587, 200), 45)   # heal grade 0 -> 45 (mid group)
        self.assertEqual(codes.restore(591, 200), 480)  # heal grade 4 -> Super 480
        self.assertEqual(codes.restore(515, 200), 70)   # rejuv 35% of max
        self.assertEqual(codes.restore(516, 200), 200)  # full rejuv
        self.assertEqual(codes.restore(512, 200), 0)    # utility
        self.assertEqual(codes.grade_names("heal"), ["minor", "light", "healing", "greater", "super"])
        self.assertEqual(codes.grade_names("mana"), ["minor", "light", "mana", "greater", "super"])
        self.assertEqual(codes.grade_names("rejuv"), ["rejuv", "full rejuv"])
        self.assertEqual(codes.grade_names("other"), ["utility"])

    def test_default_potion_codes_match_constants(self):
        codes = m.default_potion_codes()
        self.assertEqual(codes.kind(602), "heal")
        self.assertEqual(codes.kind(611), "mana")
        self.assertEqual(codes.kind(530), "rejuv")
        self.assertEqual(codes.kind(532), "other")
        self.assertEqual(codes.restore(605, 200), 270)   # Greater heal, mid group
        self.assertEqual(codes.restore(608, 200), 60)
        self.assertEqual(codes.grade(606), 4)

    def test_potion_entries_from_lists_filters_bad_rows(self):
        entries = m.potion_entries_from_lists(
            [[602, "heal", 0], ["oops"], [531, "rejuv", 1], [528, "other", -1], [1, "bogus", 0]])
        self.assertEqual([(e.txt, e.kind, e.grade) for e in entries],
                         [(602, "heal", 0), (531, "rejuv", 1), (528, "other", -1)])

    def test_corner_potion_code(self):
        # 8-slot belt corners are x=0,3,4,7.
        self.assertEqual(m.corner_potion_code({0: 608, 3: 608, 4: 608, 7: 608}), 608)
        self.assertIsNone(m.corner_potion_code({0: 608, 3: 608, 4: 608, 7: 609}))
        self.assertIsNone(m.corner_potion_code({0: 608, 4: 608}))        # too few corners
        self.assertIsNone(m.corner_potion_code({}))                       # empty belt
        # 12-slot belt corners: 0,3,4,7,8,11.
        slots = {x: 608 for x in (0, 3, 4, 7, 8, 11)}
        self.assertEqual(m.corner_potion_code(slots), 608)
        self.assertEqual(m.belt_corner_codes({0: 1, 2: 5, 3: 2}), {1, 2})

    def test_infer_potion_family(self):
        fam = m.infer_potion_family("mana", 608, 1)   # Light Mana anchored
        self.assertEqual({(e.txt, e.grade) for e in fam},
                         {(607, 0), (608, 1), (609, 2), (610, 3), (611, 4)})
        fam2 = m.infer_potion_family("heal", 602, 0)
        self.assertEqual([e.txt for e in fam2], [602, 603, 604, 605, 606])
        fam3 = m.infer_potion_family("rejuv", 531, 1)
        self.assertEqual({(e.txt, e.grade) for e in fam3}, {(530, 0), (531, 1)})
        # Already-learned codes are never re-claimed.
        fam4 = m.infer_potion_family("mana", 608, 1, existing=[611])
        self.assertNotIn(611, [e.txt for e in fam4])
        # Utility potions are single entries.
        fam5 = m.infer_potion_family("other", 512, -1)
        self.assertEqual([(e.txt, e.kind, e.grade) for e in fam5], [(512, "other", -1)])

    def test_belt_rows_for(self):
        self.assertEqual(m.belt_rows_for(345), 2)     # Light Belt (this build)
        self.assertEqual(m.belt_rows_for(348), 4)     # Plated Belt
        self.assertEqual(m.belt_rows_for(360), 2)     # Infernal +15 Light Belt
        self.assertIsNone(m.belt_rows_for(602))       # a potion, not a belt

    def test_belt_empty_slots(self):
        self.assertEqual(m.belt_empty_slots(1, []), [0, 1, 2, 3])
        self.assertEqual(m.belt_empty_slots(2, [0, 4]), [1, 2, 3, 5, 6, 7])
        self.assertEqual(m.belt_empty_slots(4, [0, 1, 2, 3]), [4, 5, 6, 7, 8, 9, 10, 11,
                                                               12, 13, 14, 15])
        self.assertEqual(m.belt_empty_slots(2, [0, 1, 2, 3, 4, 5, 6, 7]), [])
        # Slots that don't exist on a smaller belt are ignored.
        self.assertEqual(m.belt_empty_slots(1, []), [0, 1, 2, 3])

    def test_solve_grid_mapping(self):
        # Two samples on different cells solve cell + origin (least squares).
        solved = m.solve_grid_mapping([(0, 0, 100, 200), (2, 1, 100 + 58, 200 + 29)])
        self.assertIsNotNone(solved)
        cell, ox, oy = solved
        self.assertAlmostEqual(cell, 29.0, places=6)
        self.assertAlmostEqual(ox, 100.0, places=6)
        self.assertAlmostEqual(oy, 200.0, places=6)
        # Three noisy samples still converge to the true grid.
        solved = m.solve_grid_mapping([
            (0, 0, 100, 200), (1, 0, 129.2, 200.1), (0, 2, 100.1, 258),
        ])
        cell, ox, oy = solved
        self.assertAlmostEqual(cell, 29.0, places=1)
        self.assertAlmostEqual(ox, 100.0, places=0)
        self.assertAlmostEqual(oy, 200.0, places=0)
        # With a known cell a single sample is enough to find the origin.
        solved = m.solve_grid_mapping([(5, 3, 100 + 5 * 29, 200 + 3 * 29)], cell=29.0)
        cell, ox, oy = solved
        self.assertAlmostEqual(cell, 29.0, places=6)
        self.assertAlmostEqual(ox, 100.0, places=6)
        self.assertAlmostEqual(oy, 200.0, places=6)
        # Degenerate inputs -> None.
        self.assertIsNone(m.solve_grid_mapping([]))
        self.assertIsNone(m.solve_grid_mapping([(0, 0, 100, 200)]))
        self.assertIsNone(m.solve_grid_mapping([(0, 0, 100, 200), (1, 1, 100, 200)], cell=0))

    def test_potion_counts_belt_slots(self):
        pc = m.PotionCounts()
        pc.belt_rows = 2
        pc.belt_filled = [0, 4]
        pc.belt_empty = m.belt_empty_slots(2, pc.belt_filled)
        self.assertEqual(pc.belt_empty, [1, 2, 3, 5, 6, 7])

    def test_choose_belt_column_uses_custom_codes(self):
        codes = m.PotionCodes([m.PotionEntry(587, "heal", 0),
                               m.PotionEntry(588, "heal", 1)])
        q = m.BeltColumn(key="Q", index=0, txt=587, kind="heal", grade=0, count=1)
        r = m.BeltColumn(key="R", index=3, txt=588, kind="heal", grade=1, count=1)
        pc = self._pc([q, r])
        pc.codes = codes
        # 587 (45) vs 588 (90): a 50-deficit needs Light (R), 20 is covered by Q.
        self.assertEqual(pc.choose_belt_column("heal", 50, 200), 3)
        self.assertEqual(pc.choose_belt_column("heal", 20, 200), 0)
        # 602 is not in this custom table -> no candidate.
        self.assertIsNone(pc.choose_belt_column("mana", 10, 200))

    def test_potion_counts_formatting(self):
        pc = m.PotionCounts()
        self.assertFalse(pc.ok)
        self.assertEqual(pc.fmt_belt(), "unknown")
        pc.ok = True
        pc.belt["heal"] = 4
        pc.belt["mana"] = 2
        pc.inventory["rejuv"] = 6
        self.assertEqual(pc.belt_total(), 6)
        self.assertEqual(pc.inventory_total(), 6)
        self.assertIn("4 heal", pc.fmt_belt())
        self.assertIn("6 rejuv", pc.fmt_inventory())

    def test_snapshot_alive_helpers(self):
        s = m.PlayerSnapshot()
        self.assertFalse(s.alive)
        s.in_game = True
        s.hp = 100
        self.assertTrue(s.alive)
        self.assertFalse(s.merc_alive)
        s.merc_max_hp = 50
        self.assertFalse(s.merc_alive)   # hired but dead -> no potion waste
        s.merc_hp = 30
        self.assertTrue(s.merc_alive)
        s.merc_hp = 0
        self.assertFalse(s.merc_alive)

    def test_merc_values(self):
        from d2r.reader import GameReader
        STAT = m.STAT
        # Full merc: Life is the fraction boundary exactly (0x8000 == 1.0), so it
        # must read as full (the old "< 0x8000" check misread this as 128/189).
        raw = {STAT["Life"]: 128 << 8, STAT["MaxLife"]: 189 << 8}
        self.assertEqual(GameReader._merc_values(raw), (189, 189))
        # Life at/below the 32768 boundary is a 0..1 fraction of max.
        raw2 = {STAT["Life"]: 16384, STAT["MaxLife"]: 100 << 8}
        self.assertEqual(GameReader._merc_values(raw2), (50, 100))
        # Above the boundary it is a plain shifted value.
        raw4 = {STAT["Life"]: 150 << 8, STAT["MaxLife"]: 189 << 8}
        self.assertEqual(GameReader._merc_values(raw4), (150, 189))
        # Dead merc (zero life) keeps its max.
        raw3 = {STAT["Life"]: 0, STAT["MaxLife"]: 189 << 8}
        self.assertEqual(GameReader._merc_values(raw3), (0, 189))
        # No max -> no merc.
        self.assertEqual(GameReader._merc_values({STAT["Life"]: 10}), (0, 0))


class RefillTests(unittest.TestCase):
    def _potion(self, txt, kind, grade, x=0, y=0, unit_id=1):
        return {"unit_id": unit_id, "txt": txt, "kind": kind,
                "grade": grade, "x": x, "y": y}

    def test_refillable_potions_filters_and_sorts(self):
        from d2r.refill import refillable_potions
        pool = [
            self._potion(532, "other", -1),       # stamina - never auto-moved
            self._potion(608, "mana", 1),
            self._potion(602, "heal", 0),
            self._potion(530, "rejuv", 0),
        ]
        got = refillable_potions(pool)
        self.assertEqual([p["txt"] for p in got], [602, 530, 608])
        self.assertNotIn(532, [p["txt"] for p in got])

    def test_plan_refills_prefers_last_consumed_kind(self):
        from d2r.refill import plan_refills
        potions = [
            self._potion(602, "heal", 0, x=1, y=0),
            self._potion(608, "mana", 1, x=2, y=0),
        ]
        plan = plan_refills([2, 5], potions, last_kind="heal")
        self.assertEqual(len(plan), 2)
        self.assertEqual(plan[0]["slot"], 2)          # fill order: bottom row first
        self.assertEqual(plan[0]["potion"]["kind"], "heal")   # restock what was drunk
        self.assertEqual(plan[1]["slot"], 5)
        self.assertEqual(plan[1]["potion"]["kind"], "mana")

    def test_plan_refills_no_last_kind_uses_any(self):
        from d2r.refill import plan_refills
        potions = [self._potion(608, "mana", 1)]
        plan = plan_refills([0, 1], potions, last_kind=None)
        self.assertEqual(len(plan), 1)                # one potion, one click
        self.assertEqual(plan[0]["potion"]["kind"], "mana")

    def test_plan_refills_empty_inputs(self):
        from d2r.refill import plan_refills
        self.assertEqual(plan_refills([], [self._potion(602, "heal", 0)]), [])
        self.assertEqual(plan_refills([3], []), [])
        self.assertEqual(plan_refills([], []), [])
        # Utility-only inventory -> nothing to move.
        self.assertEqual(plan_refills([3], [self._potion(532, "other", -1)]), [])

    def test_belt_fill_order_bottom_row_first(self):
        from d2r.refill import belt_fill_order
        self.assertEqual(belt_fill_order([6, 1, 4, 2]), [1, 2, 4, 6])

    def test_plan_refills_no_duplicate_use(self):
        from d2r.refill import plan_refills
        potions = [self._potion(602, "heal", 0, unit_id=10)]
        plan = plan_refills([1, 2, 3], potions, last_kind="heal")
        # One potion can only fill one slot per plan (the rest refills on later
        # ticks after the game moves the first potion into the belt).
        self.assertEqual(len(plan), 1)
        self.assertEqual(plan[0]["potion"]["unit_id"], 10)

    # ------------------------------------------------------- smart consume
    def _col(self, key, txt, count=1):
        return m.BeltColumn(key=key, index=m.BELT_COLUMN_KEYS.index(key),
                            txt=txt, kind=m.potion_kind(txt),
                            grade=m.potion_grade(txt), count=count)

    def _pc(self, columns):
        pc = m.PotionCounts()
        pc.ok = True
        pc.columns = columns
        return pc

    _MANAGED_ALL = ("Q", "W", "E", "R")

    def _consume(self, hp, mana, max_hp, max_mana, pc, **kw):
        from d2r.refill import plan_consume
        default = dict(heal_at=80, mana_at=60, rejuv_life=40, rejuv_mana=40)
        default.update(kw)
        return plan_consume(
            hp_percent=int(hp / max_hp * 100), mana_percent=int(mana / max_mana * 100),
            hp_def=max(0, max_hp - hp), mp_def=max(0, max_mana - mana),
            max_hp=max_hp, max_mana=max_mana, pc=pc,
            managed=self._MANAGED_ALL,
            heal_at=default["heal_at"], mana_at=default["mana_at"],
            rejuv_life=default["rejuv_life"], rejuv_mana=default["rejuv_mana"])

    def test_plan_consume_prefers_heal_over_rejuv_when_only_hp_low(self):
        # HP 25% (critical), MP full; a covering Super heal is on the belt.
        pc = self._pc([self._col("Q", 605), self._col("R", 531)])
        acts, missing = self._consume(50, 200, 200, 200, pc)
        self.assertEqual(len(acts), 1)
        self.assertEqual(acts[0]["action"], "heal")
        self.assertEqual(acts[0]["deficit"], 150)
        self.assertEqual(acts[0]["reason"], "HP 25%")
        self.assertEqual(missing, [])

    def test_plan_consume_rejuv_when_only_hp_low_and_no_covering_heal(self):
        # Only a Minor heal (45) - does not cover the 150 deficit.
        pc = self._pc([self._col("Q", 602), self._col("R", 531)])
        acts, _ = self._consume(50, 200, 200, 200, pc)
        self.assertEqual(acts[0]["action"], "rejuv")
        self.assertEqual(acts[0]["kind"], "rejuv")
        self.assertEqual(acts[0]["deficit"], 150)

    def test_plan_consume_rejuv_when_both_stats_critical(self):
        pc = self._pc([self._col("Q", 602), self._col("R", 608)])
        acts, _ = self._consume(40, 40, 200, 200, pc)
        self.assertEqual(acts[0]["action"], "rejuv")

    def test_plan_consume_prefers_mana_when_only_mp_low(self):
        pc = self._pc([self._col("W", 610), self._col("E", 530)])
        acts, _ = self._consume(200, 50, 200, 200, pc)
        self.assertEqual(acts[0]["action"], "mana")
        self.assertEqual(acts[0]["deficit"], 150)

    def test_plan_consume_noncritical_heal_and_mana_independent(self):
        pc = self._pc([self._col("Q", 602), self._col("W", 608)])
        acts, missing = self._consume(140, 100, 200, 200, pc)
        self.assertEqual([a["action"] for a in acts], ["heal", "mana"])
        self.assertEqual(missing, [])
        # Nothing wrong -> no acts.
        acts, _ = self._consume(190, 190, 200, 200, pc)
        self.assertEqual(acts, [])

    def test_plan_consume_missing_reported(self):
        # Rejuv wanted but no rejuv column on the belt.
        pc = self._pc([self._col("Q", 602)])
        acts, missing = self._consume(50, 200, 200, 200, pc)
        self.assertEqual(acts[0]["action"], "rejuv")
        self.assertEqual(missing, ["rejuv"])

    def test_plan_consume_respects_managed_columns(self):
        # Covering heal sits on R, but R is not managed -> rejuv instead.
        pc = self._pc([self._col("Q", 531), self._col("R", 605)])
        from d2r.refill import plan_consume
        acts, _ = plan_consume(25, 100, 150, 0, 200, 200, pc,
                               ("Q", "W", "E"), 80, 60, 40, 40)
        self.assertEqual(acts[0]["action"], "rejuv")
        acts, _ = plan_consume(25, 100, 150, 0, 200, 200, pc,
                               ("Q", "W", "E", "R"), 80, 60, 40, 40)
        self.assertEqual(acts[0]["action"], "heal")

    def test_plan_consume_bound_keys_restrict_covering(self):
        # heal is bound only to R (which is managed) -> covering heal found there.
        pc = self._pc([self._col("R", 605), self._col("Q", 531)])
        from d2r.refill import plan_consume
        acts, _ = plan_consume(
            25, 100, 150, 0, 200, 200, pc, ("Q", "W", "E", "R"),
            80, 60, 40, 40, bound={"heal": ["R"], "mana": ["W"], "rejuv": ["E"]})
        self.assertEqual(acts[0]["action"], "heal")
        # Bound heal to Q, which only holds a rejuv -> no covering heal.
        acts, _ = plan_consume(
            25, 100, 150, 0, 200, 200, pc, ("Q", "W", "E", "R"),
            80, 60, 40, 40, bound={"heal": ["Q"], "mana": ["W"], "rejuv": ["E"]})
        self.assertEqual(acts[0]["action"], "rejuv")

    # ------------------------------------------------------- smart layout
    def test_desired_kind_layout_wins(self):
        from d2r.refill import desired_kind_for_slot
        self.assertEqual(desired_kind_for_slot(0, {0: "mana"}, {1: "heal"},
                                               {"heal": 8, "mana": 6, "rejuv": 2}), "mana")

    def test_desired_kind_column_family(self):
        from d2r.refill import desired_kind_for_slot
        # Column 0 (slots 0,4,8,12) already holds heal -> restock heal there.
        belt = {4: "heal", 8: "heal"}
        self.assertEqual(desired_kind_for_slot(0, {}, belt,
                                               {"heal": 8, "mana": 6, "rejuv": 2}), "heal")

    def test_desired_kind_ratio_shortfall(self):
        from d2r.refill import desired_kind_for_slot
        # Column 0 empty; rejuv already at/above its target, heal is short.
        belt = {1: "rejuv", 2: "rejuv", 5: "rejuv"}
        self.assertEqual(desired_kind_for_slot(0, {}, belt,
                                               {"heal": 8, "mana": 6, "rejuv": 2}), "heal")

    def test_desired_kind_none_when_mix_satisfied(self):
        from d2r.refill import desired_kind_for_slot
        belt = {0: "heal", 1: "mana", 4: "rejuv"}
        # Slot 15 (column 3, empty column) and every ratio target is met.
        self.assertIsNone(desired_kind_for_slot(15, {}, belt,
                                                {"heal": 1, "mana": 1, "rejuv": 1}))

    def test_plan_layout_refill_follows_layout_and_fill_order(self):
        from d2r.refill import plan_layout_refill
        plan = plan_layout_refill(
            [3, 7], {}, [
                self._potion(602, "heal", 0, x=1, y=0, unit_id=1),
                self._potion(608, "mana", 1, x=2, y=0, unit_id=2),
                self._potion(530, "rejuv", 0, x=3, y=0, unit_id=3),
            ], {3: "mana", 7: "rejuv"}, {"heal": 8, "mana": 6, "rejuv": 2})
        self.assertEqual([(p["slot"], p["potion"]["kind"]) for p in plan],
                         [(3, "mana"), (7, "rejuv")])

    def test_plan_layout_refill_ratio_fallback(self):
        from d2r.refill import plan_layout_refill
        belt_content = {1: "heal", 2: "mana", 5: "heal", 6: "mana"}   # col 0 empty
        plan = plan_layout_refill(
            [0], belt_content, [
                self._potion(602, "heal", 0, unit_id=1),
                self._potion(530, "rejuv", 0, unit_id=2),
            ], {}, {"heal": 2, "mana": 2, "rejuv": 1})
        self.assertEqual(plan[0]["potion"]["kind"], "rejuv")

    def test_plan_layout_refill_last_kind_fallback(self):
        from d2r.refill import plan_layout_refill
        plan = plan_layout_refill(
            [0], {}, [self._potion(602, "heal", 0, unit_id=1)],
            {0: "mana"}, {"heal": 8, "mana": 6, "rejuv": 2}, last_kind="heal")
        self.assertEqual(plan[0]["potion"]["kind"], "heal")

    def test_plan_layout_refill_no_duplicate_use(self):
        from d2r.refill import plan_layout_refill
        plan = plan_layout_refill(
            [0, 1], {}, [self._potion(602, "heal", 0, unit_id=10)],
            {}, {"heal": 8, "mana": 6, "rejuv": 2})
        self.assertEqual(len(plan), 1)
        self.assertEqual(plan[0]["potion"]["unit_id"], 10)

    def test_plan_layout_refill_empty_inputs(self):
        from d2r.refill import plan_layout_refill
        self.assertEqual(plan_layout_refill([], {}, [], {}, {}), [])
        self.assertEqual(plan_layout_refill([3], {}, [], {}, {}), [])
        self.assertEqual(plan_layout_refill(
            [3], {}, [self._potion(532, "other", -1)], {}, {}), [])


class FakeSender:
    """Stands in for KeySender so tests never inject keystrokes."""

    def __init__(self, *args, **kwargs):
        self.pressed: list[str] = []
        self.pressed_keys: list[tuple] = []

    def press(self, action: str, key: str | None = None) -> bool:
        self.pressed.append(action)
        self.pressed_keys.append((action, key))
        return True


class FakeReader:
    max_override = {"player_hp": 0, "player_mp": 0, "merc_hp": 0}
    codes = m.default_potion_codes()

    def snapshot(self):
        return m.PlayerSnapshot()


class WatcherTests(unittest.TestCase):
    def _watcher(self, enabled=True):
        c = cfg.AppConfig.load()
        c.reset_to_defaults()   # deterministic regardless of any real config.json
        c.enabled = enabled
        from d2r.watcher import PotionWatcher
        w = PotionWatcher(FakeReader(), c)
        w.sender = FakeSender()  # never touch the real SendInput
        return w

    def _snap(self, hp=90, mana=90, merc=0):
        s = m.PlayerSnapshot()
        s.in_game = True
        s.hp, s.mana = hp, mana
        s.hp_percent, s.mana_percent = hp, mana
        if merc:
            s.merc_max_hp = 100
            s.merc_hp = merc
            s.merc_hp_percent = merc
        return s

    def test_should_act_gates(self):
        w = self._watcher()
        s = self._snap()
        self.assertTrue(w._should_act(s))
        w.config.enabled = False
        self.assertFalse(w._should_act(s))
        w.config.enabled = True
        s.in_game = False
        self.assertFalse(w._should_act(s))
        s.in_game = True
        s.hp = 0
        self.assertFalse(w._should_act(s))
        s.hp = 90
        s.menus_open = True
        self.assertFalse(w._should_act(s))

    def test_tick_heal(self):
        w = self._watcher()
        w._tick(self._snap(hp=70, mana=90))
        self.assertEqual(w.sender.pressed, ["heal"])

    def test_tick_mana(self):
        w = self._watcher()
        w._tick(self._snap(hp=90, mana=50))
        self.assertEqual(w.sender.pressed, ["mana"])

    def test_tick_rejuv_on_critical_hp(self):
        w = self._watcher()
        w._tick(self._snap(hp=20, mana=90))
        self.assertEqual(w.sender.pressed, ["rejuv"])

    def test_tick_rejuv_on_critical_mana(self):
        w = self._watcher()
        w._tick(self._snap(hp=90, mana=10))
        self.assertEqual(w.sender.pressed, ["rejuv"])

    def test_tick_merc_rejuv_preferred(self):
        w = self._watcher()
        w._tick(self._snap(hp=90, mana=90, merc=10))
        self.assertEqual(w.sender.pressed, ["merc_rejuv"])

    def test_tick_merc_heal(self):
        w = self._watcher()
        w._tick(self._snap(hp=90, mana=90, merc=40))
        self.assertEqual(w.sender.pressed, ["merc_heal"])

    def test_tick_noop_when_fine(self):
        w = self._watcher()
        w._tick(self._snap(hp=90, mana=90))
        self.assertEqual(w.sender.pressed, [])

    def test_cooldown_gates_repeat(self):
        w = self._watcher()
        w._tick(self._snap(hp=70, mana=90))
        w._tick(self._snap(hp=70, mana=90))
        self.assertEqual(w.sender.pressed, ["heal"])  # second press within cooldown

    def test_metrics(self):
        w = self._watcher()
        w._tick(self._snap(hp=70, mana=90))
        st = w.stats()
        self.assertEqual(st["counts"]["heal"], 1)
        self.assertEqual(st["total"], 1)
        self.assertEqual(st["errors"], 0)
        self.assertIsNotNone(st["last_action"])
        self.assertEqual(w.counts()["heal"], 1)

    def test_derived_cooldown_from_potion_duration(self):
        w = self._watcher()
        w.config.keys["heal"] = ["Q", "R"]
        # Super heal (606) restores over 10.24 s -> effective cooldown ~12.3 s.
        snap = self._belt_snap(hp=140, columns=[self._col("Q", 602), self._col("R", 606)])
        w._tick(snap)
        self.assertAlmostEqual(w._last_potion_dur.get("heal", 0.0), 10.24)
        self.assertGreaterEqual(w._effective_cooldown("heal"), 12.2)
        # A second tick inside that window is gated: no weak-on-strong stacking.
        w._tick(snap)
        self.assertEqual(w.sender.pressed_keys, [("heal", "R")])

    def test_cooldown_fallbacks(self):
        w = self._watcher()
        # Rejuv is instant -> short fixed gate; unreadable belt -> config cooldown.
        self.assertEqual(w._effective_cooldown("rejuv"), 1.0)
        self.assertEqual(w._effective_cooldown("merc_rejuv"), 1.0)
        self.assertEqual(w._effective_cooldown("heal"), w.config.cooldown("heal"))
        self.assertEqual(w._effective_cooldown("merc_heal"), w.config.cooldown("merc_heal"))

    # ------------------------------------------------------- grade-aware
    def _col(self, key, txt, count=1):
        return m.BeltColumn(key=key, index=m.BELT_COLUMN_KEYS.index(key),
                            txt=txt, kind=m.potion_kind(txt),
                            grade=m.potion_grade(txt), count=count)

    def _belt_snap(self, hp=90, mana=90, max_hp=200, max_mana=200, columns=None, merc=0):
        s = m.PlayerSnapshot()
        s.in_game = True
        s.hp, s.mana = hp, mana
        s.max_hp, s.max_mana = max_hp, max_mana
        s.hp_percent = int(hp / max_hp * 100) if max_hp else 0
        s.mana_percent = int(mana / max_mana * 100) if max_mana else 0
        if merc:
            s.merc_max_hp = max_hp
            s.merc_hp = merc
            s.merc_hp_percent = int(merc / max_hp * 100)
        s.potion_counts = m.PotionCounts()
        s.potion_counts.ok = True
        s.potion_counts.columns = list(columns or [])
        return s

    def test_grade_picks_best_column(self):
        w = self._watcher()
        w.config.keys["heal"] = ["Q", "R"]   # 4th column now bound to heal
        # Q = Minor (45), R = Greater (270); deficit 60 -> R is the only cover.
        snap = self._belt_snap(hp=140, columns=[self._col("Q", 602), self._col("R", 605)])
        w._tick(snap)
        self.assertEqual(w.sender.pressed, ["heal"])
        self.assertEqual(w.sender.pressed_keys, [("heal", "R")])

    def test_grade_prefers_smallest_covering(self):
        w = self._watcher()
        w.config.keys["heal"] = ["Q", "R"]
        # max 150, hp 120 -> 80% (triggers); deficit 30, both grades cover -> Q.
        snap = self._belt_snap(hp=120, mana=150, max_hp=150, max_mana=150,
                               columns=[self._col("Q", 602), self._col("R", 603)])
        w._tick(snap)
        self.assertEqual(w.sender.pressed_keys, [("heal", "Q")])

    def test_grade_uses_strongest_when_none_covers(self):
        w = self._watcher()
        w.config.keys["heal"] = ["Q", "R"]
        snap = self._belt_snap(hp=100, mana=190, columns=[self._col("Q", 602), self._col("R", 603)])
        w._tick(snap)   # deficit 100, neither covers -> Light (R)
        self.assertEqual(w.sender.pressed_keys, [("heal", "R")])

    def test_grade_skips_when_belt_lacks_kind(self):
        w = self._watcher()
        w.config.keys["heal"] = "Q"
        # Q holds Thawing ("other"); pressing it would waste a wrong potion.
        snap = self._belt_snap(hp=70, columns=[self._col("Q", 532)])
        w._tick(snap)
        self.assertEqual(w.sender.pressed, [])
        # Reported once (no per-tick spam).
        w._tick(snap)
        self.assertEqual(w.sender.pressed, [])

    def test_grade_4th_column_rejuv(self):
        w = self._watcher()
        w.config.keys["rejuv"] = "R"   # rejuv bound to the 4th column
        snap = self._belt_snap(hp=20, columns=[self._col("R", 531)])
        w._tick(snap)
        self.assertEqual(w.sender.pressed_keys, [("rejuv", "R")])

    def test_grade_merc_uses_bound_column_with_shift(self):
        w = self._watcher()
        w.config.keys["merc_heal"] = ["Q", "R"]
        # Player healthy so only the merc's heal fires; R covers the merc deficit.
        snap = self._belt_snap(hp=190, mana=190, merc=80,
                               columns=[self._col("Q", 602), self._col("R", 605)])
        w._tick(snap)
        self.assertEqual(w.sender.pressed_keys, [("merc_heal", "R")])

    def test_grade_falls_back_to_binding_when_belt_unreadable(self):
        w = self._watcher()
        w.config.keys["heal"] = "Q"
        s = self._snap(hp=70, mana=90)   # potion_counts.ok stays False
        w._tick(s)
        self.assertEqual(w.sender.pressed_keys, [("heal", None)])

    def test_pick_respects_managed_columns(self):
        w = self._watcher()
        w.config.keys["heal"] = ["Q", "R"]
        # HP 45% (above the rejuv line) so only the heal branch runs.
        w.config.set_managed_columns(["Q", "W", "E"])
        snap = self._belt_snap(hp=90, mana=90, max_hp=200, max_mana=200,
                               columns=[self._col("Q", 532), self._col("R", 602)])
        w._tick(snap)
        self.assertEqual(w.sender.pressed, [])   # R is off-limits -> skip
        # Managing R again lets the app use it.
        w.config.set_managed_columns(["Q", "W", "E", "R"])
        w.sender.pressed = []
        w._tick(snap)
        self.assertEqual(w.sender.pressed_keys, [("heal", "R")])

    def test_last_kind_tracked_for_refill(self):
        w = self._watcher()
        w.config.keys["heal"] = ["Q", "R"]
        snap = self._belt_snap(hp=120, mana=150, max_hp=200, max_mana=200,
                               columns=[self._col("Q", 602), self._col("R", 605)])
        w._tick(snap)
        self.assertEqual(w._last_kind, "heal")
        w._tick(self._snap(hp=90, mana=50))
        self.assertEqual(w._last_kind, "mana")

    # ------------------------------------------------------- smart tier
    def test_smart_prefers_heal_over_rejuv(self):
        w = self._watcher()
        w.config.set_managed_columns(["Q", "W", "E", "R"])
        # HP 25% (critical), MP fine; a covering Super heal on Q beats the rejuv.
        snap = self._belt_snap(hp=50, mana=190, max_hp=200, max_mana=200,
                               columns=[self._col("Q", 605), self._col("R", 531)])
        w._tick(snap)
        self.assertEqual(w.sender.pressed_keys, [("heal", "Q")])

    def test_smart_uses_rejuv_when_heal_does_not_cover(self):
        w = self._watcher()
        w.config.keys["rejuv"] = ["R"]
        # Minor heal (30) does not cover a 150 deficit -> rejuv on R.
        snap = self._belt_snap(hp=50, mana=190, max_hp=200, max_mana=200,
                               columns=[self._col("Q", 602), self._col("R", 531)])
        w._tick(snap)
        self.assertEqual(w.sender.pressed_keys, [("rejuv", "R")])

    def test_smart_noncritical_heal_and_mana_fire(self):
        w = self._watcher()
        w.config.set_managed_columns(["Q", "W", "E", "R"])
        snap = self._belt_snap(hp=140, mana=100, max_hp=200, max_mana=200,
                               columns=[self._col("Q", 602), self._col("W", 608)])
        w._tick(snap)
        self.assertEqual(w.sender.pressed_keys, [("heal", "Q"), ("mana", "W")])

    def test_smart_disabled_uses_plain_tier(self):
        w = self._watcher()
        w.config.keys["rejuv"] = ["R"]
        snap = self._belt_snap(hp=50, mana=190, max_hp=200, max_mana=200,
                               columns=[self._col("Q", 605), self._col("R", 531)])
        w._tick(snap)                                  # smart: covering heal wins
        self.assertEqual(w.sender.pressed_keys, [("heal", "Q")])
        w.config.set_smart_enabled(False)
        w.sender.pressed, w.sender.pressed_keys = [], []
        w._tick(snap)                                  # plain: rejuv wins on critical
        self.assertEqual(w.sender.pressed_keys, [("rejuv", "R")])


class HotkeyTests(unittest.TestCase):
    def test_parse_hotkey(self):
        from d2r.hotkey import parse_hotkey
        self.assertEqual(parse_hotkey("Ctrl+Alt+F12"), (3, 0x7B))
        self.assertEqual(parse_hotkey("Ctrl+Shift+E"), (6, 0x45))
        self.assertEqual(parse_hotkey("WIN+1"), (8, 0x31))
        self.assertEqual(parse_hotkey(""), None)
        self.assertEqual(parse_hotkey("F12"), None)          # needs a modifier
        self.assertEqual(parse_hotkey("Ctrl+Bogus+X"), None)  # unknown modifier
        self.assertEqual(parse_hotkey("Ctrl+NOTAKEY"), None)  # unknown key

    def test_mod_from_keysym(self):
        from d2r.hotkey import mod_from_keysym
        self.assertEqual(mod_from_keysym("Control_L"), "Ctrl")
        self.assertEqual(mod_from_keysym("Alt_R"), "Alt")
        self.assertEqual(mod_from_keysym("shift"), "Shift")
        self.assertEqual(mod_from_keysym("Super_L"), "Win")
        self.assertEqual(mod_from_keysym("f"), None)
        self.assertEqual(mod_from_keysym(""), None)

    def test_keysym_to_key_name(self):
        from d2r.hotkey import keysym_to_key_name
        self.assertEqual(keysym_to_key_name("F12"), "F12")
        self.assertEqual(keysym_to_key_name("a"), "A")
        self.assertEqual(keysym_to_key_name("5"), "5")
        self.assertEqual(keysym_to_key_name("space"), "SPACE")
        self.assertEqual(keysym_to_key_name("Prior"), "PAGEUP")
        self.assertEqual(keysym_to_key_name("KP_1"), "NUMPAD1")
        self.assertEqual(keysym_to_key_name("Control_L"), None)

    def test_spec_for(self):
        from d2r.hotkey import spec_for
        self.assertEqual(spec_for("F12", frozenset({"Ctrl", "Alt"})), "Ctrl+Alt+F12")
        self.assertEqual(spec_for("f9", frozenset({"Ctrl"})), "Ctrl+F9")
        self.assertEqual(spec_for("E", frozenset()), "E")
        self.assertEqual(spec_for("Control_L", frozenset({"Ctrl"})), None)  # modifier alone
        self.assertEqual(spec_for("unknown_keysym", frozenset()), None)


class LogTests(unittest.TestCase):
    def _tmp_path(self):
        return os.path.join(tempfile.mkdtemp(prefix="d2rap-log-"), "test.log")

    def test_append_and_read_back(self):
        from d2r.log import EventLog
        path = self._tmp_path()
        log = EventLog(path=path, max_bytes=1_000_000)
        log.append("info", "hello world")
        log.append("heal", "HP 50%")
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("hello world", text)
        self.assertIn("HP 50%", text)

    def test_rotation_keeps_latest(self):
        from d2r.log import EventLog
        path = self._tmp_path()
        log = EventLog(path=path, max_bytes=200)
        for i in range(100):
            log.append("info", f"line-{i:03d}-" + "x" * 30)
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        self.assertLessEqual(len(text.encode("utf-8")), 400)  # slack for the header
        self.assertNotIn("line-000-", text)
        self.assertIn("line-099-", text)

    def test_clear(self):
        from d2r.log import EventLog
        path = self._tmp_path()
        log = EventLog(path=path)
        log.append("info", "one")
        log.clear()
        self.assertFalse(os.path.exists(path))


if __name__ == "__main__":
    unittest.main()
