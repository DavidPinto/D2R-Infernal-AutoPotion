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
        self.assertEqual(m.potion_kind(587), "heal")
        self.assertEqual(m.potion_kind(591), "heal")
        self.assertEqual(m.potion_kind(592), "mana")
        self.assertEqual(m.potion_kind(596), "mana")
        self.assertEqual(m.potion_kind(515), "rejuv")
        self.assertEqual(m.potion_kind(516), "rejuv")
        self.assertEqual(m.potion_kind(514), "other")
        self.assertIsNone(m.potion_kind(1))
        self.assertIsNone(m.potion_kind(530))

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
        self.assertTrue(s.merc_alive)


class FakeSender:
    """Stands in for KeySender so tests never inject keystrokes."""

    def __init__(self, *args, **kwargs):
        self.pressed: list[str] = []

    def press(self, action: str) -> bool:
        self.pressed.append(action)
        return True


class FakeReader:
    max_override = {"player_hp": 0, "player_mp": 0, "merc_hp": 0}

    def snapshot(self):
        return m.PlayerSnapshot()


class WatcherTests(unittest.TestCase):
    def _watcher(self, enabled=True):
        c = cfg.AppConfig.load()
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
