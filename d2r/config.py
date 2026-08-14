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

# One-click threshold/cooldown presets ("Leveling", "Boss farming", ...).
# These are code constants (never written to disk); the user can save any preset
# as a named profile to keep a customized copy.
PRESETS = {
    "Leveling": {
        "thresholds": {
            "healing_potion_at": 70, "mana_potion_at": 50,
            "rejuv_potion_at_life": 30, "rejuv_potion_at_mana": 30,
            "merc_healing_potion_at": 50, "merc_rejuv_potion_at": 15,
        },
        "cooldowns": {"heal": 5.0, "mana": 6.0, "rejuv": 3.0,
                      "merc_heal": 8.0, "merc_rejuv": 3.0},
    },
    "Boss farming": {
        "thresholds": {
            "healing_potion_at": 85, "mana_potion_at": 60,
            "rejuv_potion_at_life": 50, "rejuv_potion_at_mana": 50,
            "merc_healing_potion_at": 70, "merc_rejuv_potion_at": 25,
        },
        "cooldowns": {"heal": 2.5, "mana": 3.5, "rejuv": 1.5,
                      "merc_heal": 4.0, "merc_rejuv": 1.5},
    },
    "Conservative": {
        "thresholds": {
            "healing_potion_at": 90, "mana_potion_at": 75,
            "rejuv_potion_at_life": 60, "rejuv_potion_at_mana": 60,
            "merc_healing_potion_at": 80, "merc_rejuv_potion_at": 30,
        },
        "cooldowns": {"heal": 3.0, "mana": 4.0, "rejuv": 2.0,
                      "merc_heal": 5.0, "merc_rejuv": 2.0},
    },
    "Mana-heavy": {
        "thresholds": {
            "healing_potion_at": 60, "mana_potion_at": 85,
            "rejuv_potion_at_life": 30, "rejuv_potion_at_mana": 45,
            "merc_healing_potion_at": 50, "merc_rejuv_potion_at": 20,
        },
        "cooldowns": {"heal": 6.0, "mana": 3.0, "rejuv": 3.0,
                      "merc_heal": 8.0, "merc_rejuv": 3.0},
    },
}

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
        # Global hotkey that toggles arm/disarm while you are in-game.
        # Format "Ctrl+Alt+F12" / "Ctrl+Shift+F9"; "" = disabled (default).
        "toggle_hotkey": "",
    },
    # Manual max-HP/MP overrides (0 = auto / observed).  Set these to your real
    # geared maximums so the % is correct before the observed max has latched.
    "max_override": {
        "player_hp": 0,
        "player_mp": 0,
        "merc_hp": 0,
    },
    # Named "game version / mods" combos (Calibrate tab).  Each combo teaches the
    # app which potion txtFileNo codes (and optional merc hireling txtFileNo) the
    # user's build uses.  "combo" = the active combo name; "" = built-in Infernal
    # defaults.  A combo body is:
    #   {"potions": [[txt, kind, grade], ...], "merc": [int, ...], "notes": str}
    "combos": {},
    "combo": "",
}


@dataclass
class AppConfig:
    thresholds: dict = field(default_factory=lambda: dict(DEFAULTS["thresholds"]))
    cooldowns: dict = field(default_factory=lambda: dict(DEFAULTS["cooldowns"]))
    keys: dict = field(default_factory=lambda: dict(DEFAULTS["keys"]))
    behavior: dict = field(default_factory=lambda: dict(DEFAULTS["behavior"]))
    max_override: dict = field(default_factory=lambda: dict(DEFAULTS["max_override"]))
    # Active profile name ("" = none / ad-hoc settings) and saved named profiles.
    profile: str = ""
    profiles: dict = field(default_factory=dict)
    # Named game version/mods combos + the active combo name ("" = built-in).
    combos: dict = field(default_factory=dict)
    combo: str = ""

    # ----------------------------------------------------------- accessors
    # All accessors fall back to the factory default if a key is missing from
    # the on-disk config, so an old/corrupt file can never break a lookup.
    def threshold(self, name: str) -> int:
        # Unknown names default to 0 (never trigger) rather than raising.
        return int(self.thresholds.get(name, DEFAULTS["thresholds"].get(name, 0)))

    def cooldown(self, name: str) -> float:
        # Unknown names default to a conservative 2.0 s (no key spam).
        return float(self.cooldowns.get(name, DEFAULTS["cooldowns"].get(name, 2.0)))

    def keys_for(self, name: str) -> list[str]:
        """All keys bound to an action, in order (a binding may be a plain string
        for one key or a list for several belt columns, e.g. heal -> [Q, R])."""
        raw = self.keys.get(name, DEFAULTS["keys"].get(name, ""))
        if isinstance(raw, (list, tuple)):
            return [str(k).strip() for k in raw if str(k).strip()]
        s = str(raw).strip()
        return [s] if s else []

    def key(self, name: str) -> str:
        # Primary (first) key for an action; "" when unbound (press -> no-op).
        keys = self.keys_for(name)
        return keys[0] if keys else ""

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
            cfg.profile = str(data.get("profile", ""))
            cfg.profiles = {
                k: v for k, v in data.get("profiles", {}).items()
                if isinstance(v, dict) and k
            }
            cfg.combos = {
                k: v for k, v in data.get("combos", {}).items()
                if isinstance(v, dict) and k
            }
            cfg.combo = str(data.get("combo", ""))
            return cfg
        except Exception:
            return cls()

    def reset_to_defaults(self) -> None:
        """Restore every section to the built-in factory defaults."""
        self.thresholds = dict(DEFAULTS["thresholds"])
        self.cooldowns = dict(DEFAULTS["cooldowns"])
        self.keys = dict(DEFAULTS["keys"])
        self.behavior = dict(DEFAULTS["behavior"])
        self.combos = dict(DEFAULTS["combos"])
        self.combo = ""

    # ------------------------------------------------------------- profiles
    PROFILE_SECTIONS = ("thresholds", "cooldowns", "keys", "max_override")

    def _profile_snapshot(self) -> dict:
        """Current tunable sections, as a saveable profile body."""
        return {s: dict(getattr(self, s)) for s in self.PROFILE_SECTIONS}

    def _profile_apply(self, body: dict) -> None:
        """Overwrite the tunable sections from a profile body (defensive).

        Each section is merged over the factory defaults so a hand-edited or
        older profile that omits a key still resolves every setting."""
        for s in self.PROFILE_SECTIONS:
            data = body.get(s)
            if isinstance(data, dict):
                merged = dict(DEFAULTS[s])
                merged.update({k: v for k, v in data.items()})
                setattr(self, s, merged)

    def profile_names(self) -> list[str]:
        """Saved profile names, sorted for a stable dropdown."""
        return sorted(self.profiles.keys())

    def save_profile(self, name: str) -> None:
        """Persist the current settings as a named profile."""
        name = name.strip()
        if not name:
            return
        self.profiles[name] = self._profile_snapshot()
        self.profile = name
        self.save()

    def load_profile(self, name: str) -> bool:
        """Apply a saved profile.  Returns False if it does not exist."""
        body = self.profiles.get(name)
        if not isinstance(body, dict):
            return False
        self._profile_apply(body)
        self.profile = name
        self.save()
        return True

    def delete_profile(self, name: str) -> None:
        """Remove a saved profile (no-op if missing)."""
        self.profiles.pop(name, None)
        if self.profile == name:
            self.profile = ""
        self.save()

    def apply_preset(self, name: str) -> bool:
        """Apply a built-in preset's thresholds/cooldowns.  Keys and max overrides
        are left untouched (they are character-specific, not style-specific)."""
        preset = PRESETS.get(name)
        if not preset:
            return False
        self.thresholds.update(dict(preset["thresholds"]))
        self.cooldowns.update(dict(preset["cooldowns"]))
        self.save()
        return True

    # ------------------------------------------------------------- combos
    def combo_names(self) -> list[str]:
        """Saved combo names, sorted for a stable dropdown."""
        return sorted(self.combos.keys())

    def active_combo(self) -> dict | None:
        """The active combo's body, or None when using built-in defaults."""
        body = self.combos.get(self.combo)
        return body if isinstance(body, dict) else None

    def potion_codes(self) -> "m.PotionCodes":
        """Potion table for the active combo, or the built-in Infernal defaults."""
        from . import models as m
        body = self.active_combo()
        if body:
            entries = m.potion_entries_from_lists(body.get("potions"))
            if entries:
                return m.PotionCodes(entries)
        return m.default_potion_codes()

    def merc_txtfiles_set(self) -> frozenset:
        """Hireling txtFileNos for the active combo, or the built-in default."""
        from . import models as m
        body = self.active_combo()
        ids = body.get("merc") if body else None
        if ids:
            out = set()
            for v in ids:
                try:
                    out.add(int(v))
                except (TypeError, ValueError):
                    pass
            if out:
                return frozenset(out)
        return m.MERC_TXTFILES_DEFAULT

    def save_combo(self, name: str, potions: list | None = None,
                   merc: list | None = None, notes: str = "") -> bool:
        """Persist a named combo (potions as [[txt, kind, grade], ...]) and make
        it active.  Returns False when the name is empty."""
        name = str(name).strip()
        if not name:
            return False
        rows = []
        for r in (potions or []):
            try:
                rows.append([int(r[0]), str(r[1]).strip(), int(r[2])])
            except (TypeError, ValueError, IndexError):
                continue
        merc_ids = []
        for v in (merc or []):
            try:
                merc_ids.append(int(v))
            except (TypeError, ValueError):
                continue
        self.combos[name] = {
            "potions": rows,
            "merc": merc_ids,
            "notes": str(notes),
        }
        self.combo = name
        self.save()
        return True

    def set_active_combo(self, name: str) -> bool:
        """Switch the active combo ("" resets to built-in defaults)."""
        name = str(name).strip()
        if name and name not in self.combos:
            return False
        self.combo = name
        self.save()
        return True

    def delete_combo(self, name: str) -> None:
        """Remove a combo; resetting the active name when it was the one deleted."""
        self.combos.pop(name, None)
        if self.combo == name:
            self.combo = ""
        self.save()
