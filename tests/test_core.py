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
        self.assertEqual(m.potion_restore(602, 200), 30)
        self.assertEqual(m.potion_restore(605, 200), 200)
        self.assertEqual(m.potion_restore(606, 200), 200)   # full = 100% of max
        self.assertEqual(m.potion_restore(608, 200), 60)
        self.assertEqual(m.potion_restore(530, 200), 70)    # 35% of max
        self.assertEqual(m.potion_restore(531, 200), 200)
        self.assertEqual(m.potion_restore(1, 200), 0)

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
        # Minor (30) vs Super (200); deficit 40 -> Super covers, Minor does not.
        pc = self._pc([self._col("Q", 602), self._col("R", 605)])
        self.assertEqual(pc.choose_belt_column("heal", 40, 200), 3)
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
        # Normal shifted life.
        raw = {STAT["Life"]: 128 << 8, STAT["MaxLife"]: 189 << 8}
        self.assertEqual(GameReader._merc_values(raw), (128, 189))
        # Life below the 32768 shift boundary is a 0..1 fraction of max.
        raw2 = {STAT["Life"]: 16384, STAT["MaxLife"]: 100 << 8}
        self.assertEqual(GameReader._merc_values(raw2), (50, 100))
        # Dead merc (zero life) keeps its max.
        raw3 = {STAT["Life"]: 0, STAT["MaxLife"]: 189 << 8}
        self.assertEqual(GameReader._merc_values(raw3), (0, 189))
        # No max -> no merc.
        self.assertEqual(GameReader._merc_values({STAT["Life"]: 10}), (0, 0))


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
        # Q = Minor (30), R = Super (200); deficit 40 -> R covers.
        snap = self._belt_snap(hp=160, columns=[self._col("Q", 602), self._col("R", 605)])
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
