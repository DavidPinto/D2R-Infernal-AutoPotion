"""Persisted settings (thresholds, key bindings, behaviour).

Stored as JSON next to the executable so defaults survive restarts.  A factory
default is always available if the file is missing or corrupt.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field, asdict

from .models import BELT_COLUMN_KEYS

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
        "rejuv_potion_at_life": 25,  # rejuv is for critical HP (instant save) ...
        "rejuv_potion_at_mana": 25,  # ... or critical MP (instant save)
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
    # Deprecated since 1.8.0: potions are no longer bound to a key by type.
    # The app drinks via the belt's own hotkeys (Q/W/E/R) and reads each slot
    # to see which potion it holds.  Kept as an empty dict so old persisted
    # configs and profiles still load (the section is simply unused).
    "keys": {},
    "behavior": {
        "enabled": False,
        "auto_focus_game": True,
        "sound": True,
        "pause_when_menus_open": True,
        "poll_interval_ms": 150,
        # Smart potion use: pick the best potion across the whole managed belt
        # (prefer a specific potion over a rejuv when only one stat is low) and
        # refill the belt per the layout/ratio plan below.
        "smart": True,
        # Desperation mode: when HP is at/below rejuv threshold, bypass normal
        # restrictions to reach an instant-heal rejuv.  THIS IS WASTEFUL - it
        # may drink multiple potions (mana/heal) to clear a path to a rejuv
        # deeper in the belt.  Respects empty slots (potions don't drop through
        # empty space).  Only enable if you accept wasting potions to survive.
        "desperation_mode": False,
        # Gamepad support: use gamepad D-pad instead of keyboard for belt keys.
        # When enabled, the app sends XInput gamepad button presses instead of
        # keyboard keystrokes.  Requires a connected XInput-compatible controller.
        "use_gamepad": False,
        # XInput controller index (0-3).  Default 0 = first connected controller.
        "gamepad_id": 0,
        # Potions restore over a duration (rejuv is instant).  A same-or-higher
        # grade potion may be drunk once the in-effect potion is half consumed;
        # a weaker/unknown one waits the full duration * (1 + margin) so it never
        # drags the fill rate down.  Config cooldowns are only a fallback while
        # the potion on the belt is unknown.
        "potion_margin_percent": 20,
        # Character class used for potion restore amounts ("" = auto-detect the
        # class from the game each tick; otherwise a fixed class from the list).
        "potion_class_override": "",
        # Global hotkey that toggles enable/disable while you are in-game.
        # Format "Ctrl+Alt+F12" / "Ctrl+Shift+F9"; "" = disabled (default).
        "toggle_hotkey": "",
        # Modifier held together with a belt hotkey (Q/W/E/R) to give that
        # potion to the mercenary - D2R's feed-merc binding (default Shift).
        "merc_modifier": "Shift",
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
    # Belt columns (Q/W/E/R) the app may drink from and refill into.  Unchecked
    # columns are left alone entirely (the user manages those manually).
    "managed": ["Q", "W", "E", "R"],
    # The actual hotkey bound to each belt column (keyed by the column's DEFAULT
    # letter Q/W/E/R).  D2R defaults are Q/W/E/R but the game lets you rebind
    # them; the app must press the rebound key so it reads/writes the right slot.
    "belt_keys": {"Q": "Q", "W": "W", "E": "E", "R": "R"},
    # Belt refill: while the inventory panel is open the app moves a matching
    # potion from the inventory into an empty managed belt slot (and relocates a
    # potion sitting in the wrong column).  "calibrated" means the *inventory*
    # click grid was measured against the live window; the belt panel has its own
    # origin ("belt_origin_*") because the belt grid sits at a different spot.
    "refill": {
        "enabled": False,
        "calibrated": False,
        "cell": 29.0,
        "origin_x": 0.0,
        "origin_y": 0.0,
        "belt_calibrated": False,
        "belt_cell": 29.0,
        "belt_origin_x": 0.0,
        "belt_origin_y": 0.0,
        "interval_ms": 400,
    },
    # Smart-tier belt plan.  "layout" pins a potion kind per belt slot X
    # (JSON keys are strings; "" / missing = "Any").  "ratio" is the target
    # belt mix (counts per kind) the refill tries to keep.
    "layout": {},
    "ratio": {"heal": 8, "mana": 6, "rejuv": 2},
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
    managed: list = field(default_factory=lambda: list(DEFAULTS["managed"]))
    belt_keys: dict = field(default_factory=lambda: dict(DEFAULTS["belt_keys"]))
    refill: dict = field(default_factory=lambda: dict(DEFAULTS["refill"]))
    layout: dict = field(default_factory=lambda: dict(DEFAULTS["layout"]))
    ratio: dict = field(default_factory=lambda: dict(DEFAULTS["ratio"]))
    # Override tables (calibration/per-build customization)
    overrides: dict = field(default_factory=dict)

    # ----------------------------------------------------------- accessors
    # All accessors fall back to the factory default if a key is missing from
    # the on-disk config, so an old/corrupt file can never break a lookup.
    def threshold(self, name: str) -> int:
        # Unknown names default to 0 (never trigger) rather than raising.
        return int(self.thresholds.get(name, DEFAULTS["thresholds"].get(name, 0)))

    def cooldown(self, name: str) -> float:
        # Unknown names default to a conservative 2.0 s (no key spam).
        return float(self.cooldowns.get(name, DEFAULTS["cooldowns"].get(name, 2.0)))

    def merc_modifier(self) -> str:
        """Modifier key held with a belt hotkey to feed the merc a potion."""
        name = str(self.behavior.get("merc_modifier", "Shift")).strip().upper()
        return name if name in ("SHIFT", "CTRL", "ALT") else "SHIFT"

    def set_merc_modifier(self, name: str) -> None:
        norm = str(name or "").strip().upper()
        self.behavior["merc_modifier"] = norm if norm in ("SHIFT", "CTRL", "ALT") else "SHIFT"

    @property
    def enabled(self) -> bool:
        return bool(self.behavior.get("enabled", False))

    @enabled.setter
    def enabled(self, value: bool) -> None:
        self.behavior["enabled"] = bool(value)

    @property
    def desperation_mode(self) -> bool:
        return bool(self.behavior.get("desperation_mode", False))

    @desperation_mode.setter
    def desperation_mode(self, value: bool) -> None:
        self.behavior["desperation_mode"] = bool(value)

    @property
    def use_gamepad(self) -> bool:
        return bool(self.behavior.get("use_gamepad", False))

    @use_gamepad.setter
    def use_gamepad(self, value: bool) -> None:
        self.behavior["use_gamepad"] = bool(value)

    @property
    def gamepad_id(self) -> int:
        return int(self.behavior.get("gamepad_id", 0))

    @gamepad_id.setter
    def gamepad_id(self, value: int) -> None:
        self.behavior["gamepad_id"] = int(value)

    # ------------------------------------------------- belt columns + refill
    def managed_columns(self) -> list[str]:
        """Belt column keys the app may manage (never empty; always valid keys)."""
        valid = {k: i for i, k in enumerate(BELT_COLUMN_KEYS)}
        kept = [k for k in self.managed if k in valid]
        return kept or list(BELT_COLUMN_KEYS)

    def managed_indices(self) -> set[int]:
        valid = {k: i for i, k in enumerate(BELT_COLUMN_KEYS)}
        return {valid[k] for k in self.managed_columns()}

    def set_managed_columns(self, keys) -> None:
        valid = set(BELT_COLUMN_KEYS)
        self.managed = [k for k in keys if k in valid] or list(BELT_COLUMN_KEYS)

    # ------------------------------------------------------ belt column keys
    def _column_index(self, column) -> int | None:
        """Belt column index (0..3) from an index or a Q/W/E/R letter."""
        if isinstance(column, bool):
            return None
        if isinstance(column, int):
            return column if 0 <= column < len(BELT_COLUMN_KEYS) else None
        valid = {k: i for i, k in enumerate(BELT_COLUMN_KEYS)}
        return valid.get(str(column).strip().upper())

    def belt_key(self, column) -> str:
        """The hotkey bound to a belt column (index 0..3 or a Q/W/E/R letter).

        Falls back to the column's default letter when the stored value is
        missing or invalid, so an old/corrupt config can never produce a None
        key to press."""
        idx = self._column_index(column)
        if idx is None:
            return ""
        default = BELT_COLUMN_KEYS[idx]
        name = str(self.belt_keys.get(default, default) or default).strip().upper()
        return name if name else default

    def set_belt_key(self, column, name) -> None:
        """Bind a hotkey to a belt column.  An empty/unresolvable name resets
        the column to its default letter (D2R's own binding)."""
        idx = self._column_index(column)
        if idx is None:
            return
        default = BELT_COLUMN_KEYS[idx]
        name = str(name or "").strip().upper()
        if name in ("ESC", "DELETE"):
            name = ""
        elif name:
            from .keys import resolve_key  # lazy: keys imports config
            if resolve_key(name) is None:
                name = ""
        self.belt_keys[default] = name if name else default

    def belt_keys_map(self) -> dict:
        """{column index: bound hotkey} for all four belt columns."""
        return {i: self.belt_key(i) for i in range(len(BELT_COLUMN_KEYS))}

    def refill_enabled(self) -> bool:
        return bool(self.refill.get("enabled", False))

    def set_refill_enabled(self, value: bool) -> None:
        self.refill["enabled"] = bool(value)

    def refill_interval(self) -> float:
        return float(self.refill.get("interval_ms", 400)) / 1000.0

    def refill_mapping(self) -> dict:
        """Click-position mapping (client-relative origin + cell size)."""
        return dict(self.refill)

    def set_refill_mapping(self, cell: float, origin_x: float, origin_y: float) -> None:
        self.refill["cell"] = float(cell)
        self.refill["origin_x"] = float(origin_x)
        self.refill["origin_y"] = float(origin_y)
        self.refill["calibrated"] = True

    def clear_refill_mapping(self) -> None:
        self.refill["calibrated"] = False
        self.refill["cell"] = float(DEFAULTS["refill"]["cell"])
        self.refill["origin_x"] = 0.0
        self.refill["origin_y"] = 0.0

    def belt_refill_mapping(self) -> dict:
        """Belt-panel click mapping (client-relative origin + cell size)."""
        return {
            "calibrated": bool(self.refill.get("belt_calibrated", False)),
            "cell": float(self.refill.get("belt_cell", DEFAULTS["refill"]["belt_cell"])),
            "origin_x": float(self.refill.get("belt_origin_x", 0.0)),
            "origin_y": float(self.refill.get("belt_origin_y", 0.0)),
        }

    def set_belt_refill_mapping(self, cell: float, origin_x: float, origin_y: float) -> None:
        self.refill["belt_cell"] = float(cell)
        self.refill["belt_origin_x"] = float(origin_x)
        self.refill["belt_origin_y"] = float(origin_y)
        self.refill["belt_calibrated"] = True

    def clear_belt_refill_mapping(self) -> None:
        self.refill["belt_calibrated"] = False
        self.refill["belt_cell"] = float(DEFAULTS["refill"]["belt_cell"])
        self.refill["belt_origin_x"] = 0.0
        self.refill["belt_origin_y"] = 0.0

    # ------------------------------------------------------- potion behaviour
    def potion_margin(self) -> float:
        """Multiplier (>= 1.0) applied to a potion's restore duration to derive
        the effective cooldown; 20% default -> 1.2.  Falls back safely."""
        pct = self.behavior.get("potion_margin_percent", 20)
        try:
            return max(1.0, 1.0 + float(pct) / 100.0)
        except (TypeError, ValueError):
            return 1.2

    def potion_class(self) -> str:
        """Fixed class override for potion amounts ("" = auto-detect in-game)."""
        from . import models as mm
        name = str(self.behavior.get("potion_class_override", "")).strip()
        return name if name in mm.CLASS else ""

    # ------------------------------------------------------- smart belt plan
    def smart_enabled(self) -> bool:
        return bool(self.behavior.get("smart", True))

    def set_smart_enabled(self, value: bool) -> None:
        self.behavior["smart"] = bool(value)

    def belt_layout(self) -> dict:
        """Per-slot belt layout: {slot_x: kind} for valid slot/kind pairs."""
        out: dict = {}
        for k, v in (self.layout or {}).items():
            try:
                x = int(k)
            except (TypeError, ValueError):
                continue
            if 0 <= x <= 15 and v in ("heal", "mana", "rejuv"):
                out[x] = v
        return out

    def set_belt_layout(self, layout: dict) -> None:
        clean: dict = {}
        for k, v in (layout or {}).items():
            try:
                x = int(k)
            except (TypeError, ValueError):
                continue
            if 0 <= x <= 15 and v in ("heal", "mana", "rejuv"):
                clean[str(x)] = v
        self.layout = clean

    def belt_ratio(self) -> dict:
        """Target belt mix: {kind: count} (missing kinds default to 0)."""
        return {k: max(0, int(self.ratio.get(k, 0))) for k in ("heal", "mana", "rejuv")}

    def set_belt_ratio(self, ratio: dict) -> None:
        clean = {k: max(0, int(v)) for k, v in (ratio or {}).items()
                 if k in ("heal", "mana", "rejuv")}
        self.ratio = clean

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
            cfg.managed = [k for k in data.get("managed", []) if isinstance(k, str)]
            belt_keys = data.get("belt_keys")
            if isinstance(belt_keys, dict):
                cfg.belt_keys.update({str(k): v for k, v in belt_keys.items()})
            refill = data.get("refill")
            if isinstance(refill, dict):
                cfg.refill.update({k: v for k, v in refill.items()})
            layout = data.get("layout")
            if isinstance(layout, dict):
                cfg.layout.update({str(k): v for k, v in layout.items()})
            ratio = data.get("ratio")
            if isinstance(ratio, dict):
                cfg.ratio.update({str(k): v for k, v in ratio.items()})
            overrides = data.get("overrides")
            if isinstance(overrides, dict):
                cfg.overrides.update({str(k): v for k, v in overrides.items()})
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
        self.managed = list(DEFAULTS["managed"])
        self.belt_keys = dict(DEFAULTS["belt_keys"])
        self.refill = dict(DEFAULTS["refill"])
        self.layout = dict(DEFAULTS["layout"])
        self.ratio = dict(DEFAULTS["ratio"])

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
        """Potion table for the active combo, or the built-in Infernal defaults.

        Passes config overrides (class groups, rejuv %) when using built-in codes."""
        from . import models as m
        body = self.active_combo()
        if body:
            entries = m.potion_entries_from_lists(body.get("potions"))
            if entries:
                return m.PotionCodes(entries)
        return m.default_potion_codes(
            class_heal_group=self.class_heal_group() or None,
            class_mana_group=self.class_mana_group() or None,
            rejuv_restore_percent=self.rejuv_restore_percent(),
        )

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
        """Persist a named combo with optional restore/duration overrides.

        ``potions`` can be either:
        - Legacy format: [[txt, kind, grade], ...]
        - New format: [[txt, kind, grade, {group: restore}, duration], ...]
          where restore is {class_group: restore} and duration is float.
        """
        name = str(name).strip()
        if not name:
            return False
        rows = []
        for r in (potions or []):
            try:
                txt = int(r[0])
                kind = str(r[1]).strip().lower()
                grade = int(r[2])
                restore_override = None
                duration_override = None
                if len(r) > 3 and isinstance(r[3], dict):
                    restore_override = {int(k): int(v) for k, v in r[3].items()}
                if len(r) > 4 and r[4] is not None:
                    duration_override = float(r[4])
                rows.append([txt, kind, grade, restore_override, duration_override])
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

    def calibrated_ui_address(self) -> int:
        """Persisted live UI struct base address (0 if not calibrated)."""
        return int(self.overrides.get("calibrated_ui_address", 0))

    def set_calibrated_ui_address(self, addr: int) -> None:
        """Store the calibrated UI struct base address."""
        self.overrides["calibrated_ui_address"] = int(addr)
        self.save()

    def calibrated_ui_flags(self) -> dict[str, int] | None:
        """Persisted menu flag map {menu_name: encoded_flag}.
        
        Encoding: (byte_idx << 6) | (bit << 1) | open_value
        """
        fmap = self.overrides.get("calibrated_ui_flags")
        if isinstance(fmap, dict):
            return {str(k): int(v) for k, v in fmap.items()}
        return None

    def set_calibrated_ui_flags(self, fmap: dict[str, int]) -> None:
        """Store the calibrated menu flag map {menu_name: encoded_flag}.
        
        Encoding: (byte_idx << 6) | (bit << 1) | open_value
        """
        self.overrides["calibrated_ui_flags"] = {str(k): int(v) for k, v in fmap.items()}
        self.save()

    def calibrated_ui_closed_values(self) -> dict[str, int]:
        """Persisted baseline (closed) values for calibrated menu flags."""
        val = self.overrides.get("calibrated_ui_closed_values")
        if isinstance(val, dict):
            return {str(k): int(v) for k, v in val.items()}
        return {}

    def set_calibrated_ui_closed_values(self, vals: dict[str, int]) -> None:
        """Store the baseline (closed) values for calibrated menu flags."""
        self.overrides["calibrated_ui_closed_values"] = {str(k): int(v) for k, v in vals.items()}
        self.save()

    # ---------------------------------------------------- override tables
    def class_heal_group(self) -> dict[str, int]:
        """Class -> heal restore group (0/1/2).  Empty = built-in defaults."""
        return self.overrides.get("class_heal_group", {})

    def set_class_heal_group(self, mapping: dict[str, int]) -> None:
        self.overrides["class_heal_group"] = {str(k): int(v) for k, v in mapping.items()}
        self.save()

    def class_mana_group(self) -> dict[str, int]:
        """Class -> mana restore group (0/1/2).  Empty = built-in defaults."""
        return self.overrides.get("class_mana_group", {})

    def set_class_mana_group(self, mapping: dict[str, int]) -> None:
        self.overrides["class_mana_group"] = {str(k): int(v) for k, v in mapping.items()}
        self.save()

    def rejuv_restore_percent(self) -> tuple[int, int] | None:
        """Rejuv restore % for grades 0 and 1 (e.g. (35, 100)).  None = built-in."""
        val = self.overrides.get("rejuv_restore_percent")
        if isinstance(val, (list, tuple)) and len(val) == 2:
            return (int(val[0]), int(val[1]))
        return None

    def set_rejuv_restore_percent(self, pct: tuple[int, int] | list[int]) -> None:
        self.overrides["rejuv_restore_percent"] = [int(pct[0]), int(pct[1])]
        self.save()

    def belt_rows(self) -> dict[int, int]:
        """txtFileNo -> belt rows mapping.  Empty = built-in defaults."""
        return self.overrides.get("belt_rows", {})

    def set_belt_rows(self, mapping: dict[int, int]) -> None:
        self.overrides["belt_rows"] = {int(k): int(v) for k, v in mapping.items()}
        self.save()
