"""Persisted settings (thresholds, key bindings, behaviour).

Stored as JSON next to the executable so defaults survive restarts.  A factory
default is always available if the file is missing or corrupt.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field, asdict

if getattr(sys, "frozen", False):
    # Packaged exe: store config next to the executable so it persists.
    _base = os.path.dirname(os.path.abspath(sys.executable))
else:
    _base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.path.join(_base, "config")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")

# Defaults follow the original Go tool's config.yaml.
DEFAULTS = {
    "thresholds": {
        "healing_potion_at": 80,     # use a health potion at/under this HP%
        "mana_potion_at": 60,        # use a mana potion at/under this MP%
        "rejuv_potion_at_life": 40,  # prefer rejuv when HP% <= this ...
        "rejuv_potion_at_mana": 40,  # ... or MP% < this
        "merc_healing_potion_at": 60,
        "merc_rejuv_potion_at": 20,
    },
    "cooldowns": {
        # minimum seconds between repeats of the same action
        "heal": 4.0,
        "mana": 5.0,
        "rejuv": 2.0,
        "merc_heal": 6.0,
        "merc_rejuv": 2.0,
    },
    "keys": {
        "heal": "Q",
        "mana": "W",
        "rejuv": "E",
        "merc_heal": "Q",
        "merc_rejuv": "E",
    },
    "behavior": {
        "enabled": False,
        "auto_focus_game": True,
        "sound": True,
        "pause_when_menus_open": True,
        "poll_interval_ms": 150,
    },
    # Manual max-HP/MP overrides (0 = auto / observed).  Set these to your real
    # geared maximums so the % is correct before the observed max has latched.
    "max_override": {
        "player_hp": 0,
        "player_mp": 0,
        "merc_hp": 0,
    },
}


@dataclass
class AppConfig:
    thresholds: dict = field(default_factory=lambda: dict(DEFAULTS["thresholds"]))
    cooldowns: dict = field(default_factory=lambda: dict(DEFAULTS["cooldowns"]))
    keys: dict = field(default_factory=lambda: dict(DEFAULTS["keys"]))
    behavior: dict = field(default_factory=lambda: dict(DEFAULTS["behavior"]))
    max_override: dict = field(default_factory=lambda: dict(DEFAULTS["max_override"]))

    # ----------------------------------------------------------- accessors
    # All accessors fall back to the factory default if a key is missing from
    # the on-disk config, so an old/corrupt file can never break a lookup.
    def threshold(self, name: str) -> int:
        return int(self.thresholds.get(name, DEFAULTS["thresholds"][name]))

    def cooldown(self, name: str) -> float:
        return float(self.cooldowns.get(name, DEFAULTS["cooldowns"][name]))

    def key(self, name: str) -> str:
        return str(self.keys.get(name, DEFAULTS["keys"][name]))

    @property
    def enabled(self) -> bool:
        return bool(self.behavior.get("enabled", False))

    @enabled.setter
    def enabled(self, value: bool) -> None:
        self.behavior["enabled"] = bool(value)

    # ------------------------------------------------------------- persist
    def save(self) -> None:
        """Write the current settings to CONFIG_PATH (best-effort, never raises)."""
        try:
            os.makedirs(CONFIG_DIR, exist_ok=True)
            with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
                json.dump(asdict(self), fh, indent=2)
        except Exception:
            pass

    @classmethod
    def load(cls) -> "AppConfig":
        """Load persisted settings; a missing or corrupt file yields defaults."""
        if not os.path.exists(CONFIG_PATH):
            return cls()
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            cfg = cls()
            cfg.thresholds.update(data.get("thresholds", {}))
            cfg.cooldowns.update(data.get("cooldowns", {}))
            cfg.keys.update(data.get("keys", {}))
            cfg.behavior.update(data.get("behavior", {}))
            cfg.max_override.update(data.get("max_override", {}))
            return cfg
        except Exception:
            return cls()

    def reset_to_defaults(self) -> None:
        """Restore every section to the built-in factory defaults."""
        self.thresholds = dict(DEFAULTS["thresholds"])
        self.cooldowns = dict(DEFAULTS["cooldowns"])
        self.keys = dict(DEFAULTS["keys"])
        self.behavior = dict(DEFAULTS["behavior"])
