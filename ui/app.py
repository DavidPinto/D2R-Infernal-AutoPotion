"""CustomTkinter UI for the D2R Infernal Auto Potion tool.

Tabs:
  Dashboard   - live HP / Mana / Merc bars, character info, enable/disable toggle
  Triggers    - thresholds + real potion timing/values + safety margin
   Keys        - belt columns, feed-to-merc modifier, refill, belt plan + behaviour
  Calibrate   - teach the app your build's potion txtFileNo codes (per version/mods)
  Diagnostics - offset scan + read sanity (the tool we use to verify 3.0.91636)
  Log         - event history
"""

from __future__ import annotations

import os
import time
import threading
import customtkinter as ctk

from d2r import __version__, models as m
from d2r.config import AppConfig, PRESETS
from d2r.process import Process, ProcessNotFound, find_d2r_processes
from d2r.reader import GameReader
from d2r.watcher import PotionWatcher
from d2r.log import EventLog
from d2r.hotkey import HotkeyListener, parse_hotkey, spec_for
from d2r.hotkey import keysym_to_key_name, mod_from_keysym as hotkey_mod_from_keysym
from ui import widgets as w

ACCENT = "#2f80ed"
DANGER = "#eb5757"
GOOD = "#27ae60"
WARN = "#f2994a"
MERC = "#bb6bd9"

ACTION_NAMES = {
    "heal": "Health potion",
    "mana": "Mana potion",
    "rejuv": "Rejuvenation",
    "merc_heal": "Merc health (Shift)",
    "merc_rejuv": "Merc rejuv (Shift)",
}

# Compact per-action labels for the Dashboard stats row.
ACTION_SHORT = {
    "heal": "Hp", "mana": "Mp", "rejuv": "Rej",
    "merc_heal": "MercHp", "merc_rejuv": "MercRej",
}

HOTKEY_PRESETS = [
    "Disabled", "Ctrl+Alt+F9", "Ctrl+Alt+F10", "Ctrl+Alt+F11",
    "Ctrl+Alt+F12", "Ctrl+Shift+F12", "Ctrl+Shift+E",
]

# Feed-to-merc modifier choices (held with a belt hotkey to give the merc a
# potion).  Config stores the uppercase form; the UI shows the friendly name.
MERC_MODIFIERS = ["Shift", "Ctrl", "Alt"]
_MERC_LABEL_TO_CFG = {"Shift": "SHIFT", "Ctrl": "CTRL", "Alt": "ALT"}
_MERC_CFG_TO_LABEL = {v: k for k, v in _MERC_LABEL_TO_CFG.items()}

_potion_labels = {"heal": "heal", "mana": "mana", "rejuv": "rejuv", "other": "other"}

# Guided-calibration wizard: the potion choices a user can place in belt corners.
# The app reads the corner slots, finds the txtFileNo code that appears in all of
# them, and saves it as that potion — no code-typing required.
_WIZARD_POTIONS = [
    ("Minor Health potion", "heal", 0),
    ("Light Health potion", "heal", 1),
    ("Healing Potion", "heal", 2),
    ("Greater Health potion", "heal", 3),
    ("Super Health potion", "heal", 4),
    ("Minor Mana potion", "mana", 0),
    ("Light Mana potion", "mana", 1),
    ("Mana Potion", "mana", 2),
    ("Greater Mana potion", "mana", 3),
    ("Super Mana potion", "mana", 4),
    ("Rejuvenation potion", "rejuv", 0),
    ("Full Rejuvenation potion", "rejuv", 1),
]

# The wizard auto-saves into this combo name (no naming step for the user).
_CALIB_COMBO = "Calibrated build"

_CALIB_INSTRUCTIONS = (
    "Potions are identified by an internal code that changes between game "
    "versions and mods.  Calibrate once — the app finds the codes itself and "
    "remembers them forever.\n\n"
    "1. In-game, put ONE potion you can identify (Minor Health or Minor Mana — "
    "available from the start) in ALL 4 corners of your belt (the two edge "
    "slots of every row — needs at least a 2-row belt).\n"
    "2. Pick that same potion in the list and click 'Scan belt corners'.\n"
    "3. The app reads the belt slots in memory, finds the code automatically, "
    "saves it, and fills in the rest of its family (Minor→Super) when the codes "
    "are consecutive, as in D2R.\n"
    "4. Repeat for any other potion you use, then play.\n\n"
)


class MainApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("dark-blue")

        self.title(f"D2R Infernal Auto Potion v{__version__}")
        self.geometry("920x820")
        self.minsize(760, 640)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self.config = AppConfig.load()
        self.proc: Process | None = None
        self.reader: GameReader | None = None
        self.watcher: PotionWatcher | None = None
        self.connected = False
        self._connecting = False
        self._capturing: str | None = None
        self._capture_col: str | None = None
        self._held_mods: set[str] = set()
        self._last_connect_attempt = 0.0
        self._last_discover = 0.0
        self._shown_errors: set[str] = set()

        self.event_log = EventLog()
        self.hotkey: HotkeyListener | None = None

        self._build_topbar()
        self._build_tabs()

        from d2r.config import CONFIG_PATH
        self._emit_log(f"Auto Potion v{__version__} started. Config: {CONFIG_PATH}", "info")
        self._try_connect()
        self._refresh_hotkey()
        self.after(150, self._poll)

    # ------------------------------------------------------------ top bar
    def _build_topbar(self):
        bar = ctk.CTkFrame(self)
        bar.pack(fill="x", padx=10, pady=10)

        ctk.CTkLabel(bar, text="⚔  D2R Infernal Auto Potion",
                     font=ctk.CTkFont(size=18, weight="bold")).pack(side="left", padx=(6, 12))

        self.status_pill = ctk.CTkLabel(bar, text="Starting…", corner_radius=12,
                                        fg_color=WARN, text_color="white",
                                        font=ctk.CTkFont(size=12, weight="bold"),
                                        width=150, height=26)
        self.status_pill.pack(side="left", padx=(0, 12))

        self.reconnect_btn = ctk.CTkButton(bar, text="Connect", width=90,
                                           command=self._reconnect)
        self.reconnect_btn.pack(side="left", padx=(0, 12))
        w.attach_tooltip(self.reconnect_btn,
                         "Attach to D2R and resolve offsets. Use Reconnect to "
                         "drop and re-attach (e.g. after a game restart).")

        self.enable_btn = ctk.CTkButton(bar, text="DISABLED", width=140, height=34,
                                        fg_color=DANGER, hover_color="#c0392b",
                                        font=ctk.CTkFont(size=13, weight="bold"),
                                        command=self._toggle_enabled)
        self._sync_enable_button()
        self.enable_btn.pack(side="right", padx=(0, 6))
        w.attach_tooltip(self.enable_btn,
                         "Turn auto-potion drinking on/off (same as the global hotkey).")

        self._hotkey_state = ctk.CTkLabel(bar, text="", font=ctk.CTkFont(size=11),
                                          text_color="gray60")
        self._hotkey_state.pack(side="right", padx=(0, 8))
        self._hotkey_btn = ctk.CTkButton(bar, text="Hotkey: off", width=150, height=34,
                                         fg_color="#3a3a3a", hover_color="#4a4a4a",
                                         font=ctk.CTkFont(size=11),
                                         command=self._toggle_hotkey_capture)
        self._hotkey_btn.pack(side="right", padx=(0, 8))
        w.attach_tooltip(self._hotkey_btn,
                         "Set a global key combo that toggles auto-potion — works while "
                         "the game has focus. Hold Ctrl/Alt/Shift + a key; Esc clears.")

        self._build_quickbar()

    def _build_quickbar(self):
        """Persistent profile strip: profile save/load/delete on every tab."""
        qbar = ctk.CTkFrame(self, fg_color="#191919", corner_radius=8)
        qbar.pack(fill="x", padx=10, pady=(0, 8))
        ctk.CTkLabel(qbar, text="⚡", font=ctk.CTkFont(size=13, weight="bold")).pack(side="left", padx=(10, 6))
        ctk.CTkLabel(qbar, text="Profile:", font=ctk.CTkFont(size=11, weight="bold")).pack(side="left")
        self._profile_entry = ctk.CTkEntry(qbar, width=120, height=26,
                                           placeholder_text="new name")
        self._profile_entry.pack(side="left", padx=(4, 4))
        self._profile_menu = ctk.CTkOptionMenu(qbar, values=[""], width=150, height=26)
        self._profile_menu.set("")
        self._profile_menu.pack(side="left", padx=(4, 0))
        ctk.CTkButton(qbar, text="Save", width=52, height=26,
                      command=self._save_profile).pack(side="left", padx=(4, 0))
        ctk.CTkButton(qbar, text="Load", width=52, height=26,
                      command=self._load_profile).pack(side="left", padx=(4, 0))
        ctk.CTkButton(qbar, text="Delete", width=62, height=26,
                      fg_color="#7a4a4a", hover_color="#8c5555",
                      command=self._delete_profile).pack(side="left", padx=(4, 0))
        self._refresh_profile_menu()

    def _set_status(self, text: str, color: str):
        # Always marshal widget updates to the main thread (called from threads).
        try:
            self.after(0, lambda: self.status_pill.configure(text=text, fg_color=color))
        except Exception:
            pass

    def _sync_enable_button(self):
        if self.config.enabled:
            self.enable_btn.configure(text="● ENABLED", fg_color=GOOD, hover_color="#1e8449")
        else:
            self.enable_btn.configure(text="DISABLED", fg_color=DANGER, hover_color="#c0392b")

    def _toggle_enabled(self):
        # Do not allow enabling without a working connection.
        if not self.connected or (self.reader and not self.reader.offsets.ok):
            self.on_event(m.GameEvent(kind="error",
                          message="Cannot enable: not connected / offsets unresolved. See Diagnostics."))
            return
        self.config.enabled = not self.config.enabled
        self._sync_enable_button()
        self.config.save()
        state = "enabled" if self.config.enabled else "disabled"
        self.on_event(m.GameEvent(kind="info", message=f"Auto-potion {state}."))

    # -------------------------------------------------------------- tabs
    def _build_tabs(self):
        self.tabs = ctk.CTkTabview(self, corner_radius=10)
        self.tabs.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        for name in ("Dashboard", "Triggers", "Keys", "Calibrate", "Diagnostics", "Log"):
            self.tabs.add(name)
        self._build_dashboard(self.tabs.tab("Dashboard"))
        self._build_triggers(self.tabs.tab("Triggers"))
        self._build_keys(self.tabs.tab("Keys"))
        self._build_calibrate(self.tabs.tab("Calibrate"))
        self._build_diagnostics(self.tabs.tab("Diagnostics"))
        self._build_log(self.tabs.tab("Log"))

    # ---------------------------------------------------------- dashboard
    def _build_dashboard(self, parent):
        self.char_label = ctk.CTkLabel(parent, text="No character",
                                      font=ctk.CTkFont(size=14, weight="bold"))
        self.char_label.pack(anchor="w", padx=12, pady=(12, 2))

        self.state_label = ctk.CTkLabel(parent, text="Not in game", text_color="gray60",
                                        font=ctk.CTkFont(size=12))
        self.state_label.pack(anchor="w", padx=12, pady=(0, 10))

        self.hp_name, self.hp_bar, self.hp_read = w.stat_bar(parent, "Health", DANGER)
        self.mp_name, self.mp_bar, self.mp_read = w.stat_bar(parent, "Mana", ACCENT)
        self.merc_name, self.merc_bar, self.merc_read = w.stat_bar(parent, "Mercenary", MERC)
        self.merc_info_label = ctk.CTkLabel(parent, text="", text_color="gray60",
                                            font=ctk.CTkFont(size=11))
        self.merc_info_label.pack(anchor="w", padx=12, pady=(0, 8))

        # Potion supply (read from the client item table; read-only monitoring).
        pot = ctk.CTkFrame(parent, fg_color="transparent")
        pot.pack(anchor="w", padx=12, pady=(6, 0), fill="x")
        ctk.CTkLabel(pot, text="Potion supply", font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w")
        self.potions_label = ctk.CTkLabel(pot, text="Belt: unknown   ·   Inventory: unknown",
                                          text_color="gray70", justify="left",
                                          font=ctk.CTkFont(size=11))
        self.potions_label.pack(anchor="w", pady=(2, 0))

        stats = ctk.CTkFrame(parent, fg_color="transparent")
        stats.pack(anchor="w", padx=12, pady=(8, 0), fill="x")
        ctk.CTkLabel(stats, text="Session", font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w")
        self.stats_label = ctk.CTkLabel(stats, text="uptime 0:00:00 · 0 potions · 0 errors",
                                        text_color="gray70", font=ctk.CTkFont(size=11))
        self.stats_label.pack(anchor="w", pady=(2, 0))

        self.uses_label = ctk.CTkLabel(parent, text="Potions used: 0", font=ctk.CTkFont(size=12))
        self.uses_label.pack(anchor="w", padx=12, pady=(6, 0))

        # Manual max-HP/MP override (calibration).  0 = auto (observed max).
        cal = ctk.CTkFrame(parent, fg_color="transparent")
        cal.pack(anchor="w", padx=12, pady=(12, 0), fill="x")
        ctk.CTkLabel(cal, text="Manual max (0 = auto):", font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w")
        row = ctk.CTkFrame(cal, fg_color="transparent")
        row.pack(anchor="w", fill="x", pady=(4, 0))
        self._max_entries = {}
        for label, key in (("HP", "player_hp"), ("MP", "player_mp"), ("Merc", "merc_hp")):
            c = ctk.CTkFrame(row, fg_color="transparent")
            c.pack(side="left", padx=(0, 12))
            ctk.CTkLabel(c, text=label).pack(side="left")
            ent = ctk.CTkEntry(c, width=60, justify="center")
            ent.insert(0, str(self.config.max_override.get(key, 0)))
            ent.pack(side="left", padx=(4, 0))
            self._max_entries[key] = ent
        ctk.CTkButton(cal, text="Apply", width=70, command=self._apply_max_override).pack(anchor="e", pady=(4, 0))

        help_text = ("The tool watches your HP / Mana / Mercenary and presses the belt keys "
                     "you configured. Make sure your potions are placed in the matching belt "
                     "slots (Keys tab). Enable with the button top-right.")
        w.hint(parent, help_text).pack(anchor="w", padx=12, pady=(14, 0))

    def _update_dashboard(self, snap: m.PlayerSnapshot):
        """Refresh the character info, stat bars, and potion counter."""
        if not self.connected:
            return
        if snap.in_game:
            self.char_label.configure(
                text=f"{snap.name or 'Unknown'}  ·  {snap.class_name}  ·  Lvl {snap.level}")
            self.state_label.configure(text="In game" + ("  ·  menus open"
                                   if snap.menus_open else ""), text_color="gray80")
        else:
            self.char_label.configure(text="No character")
            self.state_label.configure(text="Not in game", text_color="gray60")

        hp = max(0, min(100, snap.hp_percent))
        mp = max(0, min(100, snap.mana_percent))
        self.hp_bar.set(hp / 100)
        self.hp_bar.configure(progress_color=w.color_for_percent(hp))
        self.hp_read.configure(text=f"{snap.hp}/{snap.max_hp}  ({hp}%)")
        self.mp_bar.set(mp / 100)
        self.mp_bar.configure(progress_color=w.color_for_percent(mp))
        self.mp_read.configure(text=f"{snap.mana}/{snap.max_mana}  ({mp}%)")

        if snap.merc_max_hp > 0:  # hired (alive, or dead but still hired)
            self.merc_bar.set(snap.merc_hp_percent / 100)
            self.merc_bar.configure(progress_color=w.color_for_percent(snap.merc_hp_percent))
            dead = "  (dead)" if snap.merc_hp == 0 else ""
            self.merc_read.configure(text=f"{snap.merc_hp}/{snap.merc_max_hp}  ({snap.merc_hp_percent}%){dead}")
            info = " · ".join(x for x in (snap.merc_type, snap.merc_name,
                                          f"Lvl {snap.merc_level}" if snap.merc_level else "")
                              if x)
            self.merc_info_label.configure(text=info if info else "Mercenary")
        else:
            self.merc_bar.set(0)
            self.merc_read.configure(text="no merc")
            self.merc_info_label.configure(text="")

        pc = snap.potion_counts
        if pc.ok:
            self.potions_label.configure(
                text=f"Belt: {pc.fmt_belt()}\nInventory: {pc.fmt_inventory()}")
        else:
            self.potions_label.configure(
                text="Belt: unknown   ·   Inventory: unknown (read in-game)")

        if self.watcher:
            self.uses_label.configure(text=f"Potions used: {self.watcher.potion_uses()}")
            st = self.watcher.stats()
            counts = "   ".join(
                f"{ACTION_SHORT[a]}={n}" for a, n in st["counts"].items() if n)
            up = st["uptime"]
            uptime = f"{int(up // 3600)}:{int(up % 3600 // 60):02d}:{int(up % 60):02d}"
            last = ""
            if st["last_action"]:
                a, ts = st["last_action"]
                last = f"   ·   last: {ACTION_NAMES[a]} {max(0, int(time.monotonic() - ts))}s ago"
            self.stats_label.configure(
                text=f"uptime {uptime} · {st['total']} potions · {st['errors']} errors"
                     + (f"   ({counts})" if counts else "") + last)

    # ----------------------------------------------------------- calibration
    def _emit_log(self, message: str, kind: str = "info"):
        """Queue a log line to the main thread (safe to call from anywhere)."""
        try:
            self.after(0, self._log_event, m.GameEvent(kind=kind, message=message))
        except Exception:
            pass

    def _apply_max_override(self):
        """Read the Manual max fields, persist them, and let the reader use them."""
        for key, ent in self._max_entries.items():
            try:
                val = int(ent.get().strip() or "0")
            except ValueError:
                val = 0
            ent.delete(0, "end")
            ent.insert(0, str(val))
            self.config.max_override[key] = val
        self.config.save()
        self._emit_log("Calibration saved (0 = auto).", "info")

    # ----------------------------------------------------------- triggers
    def _build_triggers(self, parent):
        scroll = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=4, pady=4)
        body = scroll

        # --- one-click presets (top of the tab) --------------------------------
        w.heading(body, "Presets").pack(anchor="w", padx=12, pady=(10, 4))
        p_row = ctk.CTkFrame(body, fg_color="transparent")
        p_row.pack(anchor="w", padx=12, fill="x", pady=(0, 4))
        preset_names = list(PRESETS.keys())
        self._preset_menu = ctk.CTkOptionMenu(p_row, values=preset_names,
                                              width=180, height=28)
        self._preset_menu.set(preset_names[0] if preset_names else "")
        self._preset_menu.pack(side="left")
        ctk.CTkButton(p_row, text="Apply preset", width=110, height=28,
                      command=self._apply_preset).pack(side="left", padx=(8, 0))
        w.hint(body, "Presets set trigger thresholds/cooldowns only - keys, potion "
                     "supply and manual maxes are untouched.").pack(anchor="w", padx=12, pady=(0, 8))

        w.heading(body, "Trigger thresholds (%)").pack(anchor="w", padx=12, pady=(4, 4))
        w.hint(body, "The app drinks when a bar drops to its threshold.  Rejuv lines "
                     "are the emergency reserve: at/below them the app prefers a "
                     "rejuvenation potion (instant restore).").pack(anchor="w", padx=12, pady=(0, 2))
        self._trigger_sliders: dict[str, object] = {}
        for key, label in (("healing_potion_at", "Health potion at HP ≤"),
                           ("mana_potion_at", "Mana potion at MP ≤"),
                           ("rejuv_potion_at_life", "Rejuv at HP ≤"),
                           ("rejuv_potion_at_mana", "Rejuv at MP <"),
                           ("merc_healing_potion_at", "Merc health at HP ≤"),
                           ("merc_rejuv_potion_at", "Merc rejuv at HP ≤")):
            frame, _ = w.labeled_slider(
                body, label, 0, 100, self.config.threshold(key),
                lambda v, k=key: self._on_threshold(k, v))
            frame.pack(fill="x", padx=12, pady=2)
            self._trigger_sliders[key] = frame

        frame, _ = w.labeled_slider(
            body, "Safety margin (%)", 0, 100,
            self.config.behavior.get("potion_margin_percent", 20),
            self._on_margin, step=5, fmt="{:.0f}%")
        frame.pack(fill="x", padx=12, pady=2)
        self._margin_slider = frame
        w.hint(body, "Potions restore over time, not instantly.  A same-or-stronger "
                     "potion may be drunk again once the one in effect is half "
                     "consumed; a WEAKER potion waits this percentage of the "
                     "in-effect potion's restore duration first, so stacking down "
                     "never slows the fill rate.  Rejuvenation is instant.").pack(anchor="w", padx=12, pady=(0, 4))

        # --- smart behavior toggles -----------------------------------------
        w.heading(body, "Smart behavior").pack(anchor="w", padx=12, pady=(8, 2))
        predictive_frame = ctk.CTkFrame(body, fg_color="transparent")
        predictive_frame.pack(fill="x", padx=12, pady=(4, 2))
        self._predictive_var = ctk.BooleanVar(value=self.config.behavior.get("predictive_drinking", True))
        predictive_cb = ctk.CTkCheckBox(predictive_frame,
            text="Predictive drinking (drink slightly before a bar empties)",
            variable=self._predictive_var,
            command=self._on_predictive_toggle)
        predictive_cb.pack(side="left")
        w.hint(predictive_frame, "Tracks how fast you lose Life/Mana and starts the potion "
                      "just before the threshold is crossed, so its restore-over-time has "
                      "already begun when the bar runs dry (no more empty-mana casting). "
                      "Also drinks immediately when you are poisoned.  OFF = drink exactly "
                      "at the slider thresholds.").pack(anchor="w", padx=4)

        # Reach Buried Rejuv
        panic_frame = ctk.CTkFrame(body, fg_color="transparent")
        panic_frame.pack(fill="x", padx=12, pady=(4, 2))
        self._panic_var = ctk.BooleanVar(value=self.config.reach_buried_rejuv)
        panic_cb = ctk.CTkCheckBox(panic_frame,
            text="Reach buried rejuv (emergency; wastes potions)",
            variable=self._panic_var,
            command=self._on_panic_toggle)
        panic_cb.pack(side="left")
        w.hint(panic_frame, "When HP hits the rejuv line and no rejuv sits in row 0 of any "
                     "managed column: drink the potions stacked above a rejuv to bring it "
                     "into reach.  Potions cannot drop through empty slots, so only columns "
                     "with a full stack above the rejuv qualify.  WASTEFUL - enable only if "
                     "surviving is worth the potions.").pack(anchor="w", padx=24, pady=(0, 4))

        ctk.CTkButton(body, text="Reset to defaults", fg_color="#444",
                      hover_color="#555", command=self._reset_triggers).pack(anchor="w", padx=12, pady=14)
        self._sync_sliders()

    def _on_threshold(self, key, value):
        self.config.thresholds[key] = int(round(value))
        self.config.save()

    def _on_margin(self, value):
        self.config.behavior["potion_margin_percent"] = int(round(value))
        self.config.save()

    def _on_predictive_toggle(self):
        self.config.behavior["predictive_drinking"] = self._predictive_var.get()
        self.config.save()

    def _on_panic_toggle(self):
        self.config.reach_buried_rejuv = self._panic_var.get()
        self.config.save()

    def _on_gamepad_toggle(self):
        self.config.use_gamepad = self._gamepad_var.get()
        self.config.save()

    def _sync_sliders(self):
        """Push config values into every trigger slider + margin slider."""
        for k, frame in self._trigger_sliders.items():
            frame.set_value(self.config.threshold(k))  # type: ignore[attr-defined]
        self._margin_slider.set_value(  # type: ignore[attr-defined]
            self.config.behavior.get("potion_margin_percent", 20))
        self._panic_var.set(self.config.reach_buried_rejuv)
        self._predictive_var.set(self.config.behavior.get("predictive_drinking", True))
        if hasattr(self, "_gamepad_var"):
            self._gamepad_var.set(self.config.use_gamepad)

    def _reset_triggers(self):
        from d2r.config import DEFAULTS
        self.config.thresholds = dict(DEFAULTS["thresholds"])
        self.config.behavior["potion_margin_percent"] = DEFAULTS["behavior"]["potion_margin_percent"]
        self.config.behavior["potion_class_override"] = ""
        self.config.behavior["reach_buried_rejuv"] = DEFAULTS["behavior"]["reach_buried_rejuv"]
        self.config.behavior["predictive_drinking"] = DEFAULTS["behavior"]["predictive_drinking"]
        self.config.behavior["use_gamepad"] = DEFAULTS["behavior"]["use_gamepad"]
        self.config.behavior["gamepad_id"] = DEFAULTS["behavior"]["gamepad_id"]
        self._sync_sliders()
        self.config.save()

    # ------------------------------------------------------------ presets
    def _apply_preset(self):
        name = self._preset_menu.get()
        if self.config.apply_preset(name):
            self._sync_sliders()
            self._emit_log(f"Preset '{name}' applied.", "info")

    # ------------------------------------------------------------ profiles
    def _refresh_profile_menu(self):
        names = self.config.profile_names()
        self._profile_menu.configure(values=names or [""])
        self._profile_menu.set(self.config.profile if self.config.profile in names else "")

    def _save_profile(self):
        name = self._profile_entry.get().strip()
        if not name:
            self._emit_log("Enter a profile name first.", "error")
            return
        self.config.save_profile(name)
        self._profile_entry.delete(0, "end")
        self._refresh_profile_menu()
        self._emit_log(f"Profile '{name}' saved.", "info")

    def _load_profile(self):
        name = self._profile_menu.get()
        if not name:
            self._emit_log("No profile selected to load.", "error")
            return
        if self.config.load_profile(name):
            self._sync_sliders()
            for key, ent in self._max_entries.items():
                ent.delete(0, "end")
                ent.insert(0, str(self.config.max_override.get(key, 0)))
            self._refresh_profile_menu()
            self._emit_log(f"Profile '{name}' loaded.", "info")
        else:
            self._emit_log(f"Profile '{name}' not found.", "error")

    def _delete_profile(self):
        name = self._profile_menu.get()
        if not name:
            return
        self.config.delete_profile(name)
        self._refresh_profile_menu()
        self._emit_log(f"Profile '{name}' deleted.", "info")

    # --------------------------------------------------------------- keys
    def _build_keys(self, parent):
        scroll = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=4, pady=4)
        body = scroll

        w.heading(body, "Belt columns & hotkeys").pack(anchor="w", padx=12, pady=(10, 4))
        w.hint(body, "Tick a column to let the app drink from it; the input shows "
                     "the in-game key bound to that column.  Type a single key "
                     "(letter/number) and press Enter — Esc/Delete/blank restores "
                     "the default.  Match these to the game so the correct potion "
                     "is always drunk.").pack(anchor="w", padx=12, pady=(0, 6))
        man = ctk.CTkFrame(body, fg_color="transparent")
        man.pack(anchor="w", padx=12, pady=(0, 2), fill="x")
        self._managed_boxes: dict[str, ctk.CTkCheckBox] = {}
        self._belt_key_entries: dict[str, ctk.CTkEntry] = {}
        for col in m.BELT_COLUMN_KEYS:
            box = ctk.CTkCheckBox(man, text="", width=24, height=24,
                                  command=self._on_managed_toggle)
            box.pack(side="left", padx=(0, 2))
            self._managed_boxes[col] = box
            entry = ctk.CTkEntry(man, width=30, height=26, font=ctk.CTkFont(size=11),
                                 justify="center")
            entry.pack(side="left", padx=(0, 8))
            entry.bind("<Return>", lambda e, c=col: self._on_belt_key_entry(c))
            entry.bind("<FocusOut>", lambda e, c=col: self._on_belt_key_entry(c))
            self._belt_key_entries[col] = entry
        self._refresh_managed()
        self._refresh_belt_keys()
        self._belt_keys_hint = ctk.CTkLabel(body, text="", font=ctk.CTkFont(size=11),
                                            text_color=WARN, wraplength=760, justify="left")
        self._belt_keys_hint.pack(anchor="w", padx=12, pady=(0, 10))

        # Gamepad support
        w.heading(body, "Gamepad support").pack(anchor="w", padx=12, pady=(4, 4))
        self._gamepad_var = ctk.BooleanVar(value=self.config.use_gamepad)
        gp_cb = ctk.CTkCheckBox(body, text="Use gamepad D-pad for belt keys (real gamepad input)",
                                variable=self._gamepad_var,
                                command=self._on_gamepad_toggle)
        gp_cb.pack(anchor="w", padx=12, pady=2)
        w.hint(body, "When enabled, the app creates a real Xbox controller via "
                     "Microsoft's built-in synthetic gamepad API "
                     "(xboxgipsynthetic.dll — ships with Windows 10 22H2+ "
                     "updates; no drivers, nothing to install) and taps the "
                     "D-pad for belt actions: Q=Left, W=Up, E=Down, R=Right.  "
                     "Mercenary feeds hold LT while tapping (the controller "
                     "feed-merc binding).  Requires the app to run as "
                     "administrator (Windows asks once at launch).").pack(anchor="w", padx=12, pady=(0, 4))

        w.heading(body, "Mercenary potion modifier").pack(anchor="w", padx=12, pady=(4, 4))
        merc = ctk.CTkFrame(body, fg_color="transparent")
        merc.pack(anchor="w", padx=12, pady=(0, 4), fill="x")
        ctk.CTkLabel(merc, text="Feed-to-merc modifier",
                     font=ctk.CTkFont(size=12)).pack(side="left")
        self._merc_mod_menu = ctk.CTkOptionMenu(
            merc, values=MERC_MODIFIERS, width=120, height=28,
            command=self._on_merc_modifier)
        self._merc_mod_menu.pack(side="left", padx=(10, 0))
        self._merc_mod_menu.set(self._merc_mod_label())
        w.hint(body, "To give a potion to your mercenary the app holds this "
                     "modifier together with a belt hotkey (e.g. Shift + Q) — the "
                     "same feed-merc binding D2R uses.  Set it to whatever your "
                     "in-game feed-merc key is.").pack(anchor="w", padx=12, pady=(0, 10))

        w.heading(body, "General options").pack(anchor="w", padx=12, pady=(4, 4))
        self._focus_switch = ctk.CTkSwitch(body, text="Auto-focus game window before pressing keys",
                                          command=self._on_focus)
        self._focus_switch.pack(anchor="w", padx=12, pady=4)
        self._focus_switch.select() if self.config.behavior.get("auto_focus_game", True) else self._focus_switch.deselect()

        self._sound_switch = ctk.CTkSwitch(body, text="Play a chime on each potion",
                                          command=self._on_sound)
        self._sound_switch.pack(anchor="w", padx=12, pady=4)
        self._sound_switch.select() if self.config.behavior.get("sound", True) else self._sound_switch.deselect()

        self._pause_switch = ctk.CTkSwitch(body, text="Pause while inventory/stash/menus are open",
                                          command=self._on_pause)
        self._pause_switch.pack(anchor="w", padx=12, pady=4)
        self._pause_switch.select() if self.config.behavior.get("pause_when_menus_open", True) else self._pause_switch.deselect()

        # Poll interval (responsiveness vs CPU).
        self._poll_frame, _ = w.labeled_slider(
            body, "Watch refresh interval", 100, 500,
            float(self.config.behavior.get("poll_interval_ms", 150)),
            lambda v: self._on_poll_interval(v), step=50, fmt="{:.0f} ms")
        self._poll_frame.pack(fill="x", padx=12, pady=(8, 2))

        ctk.CTkButton(body, text="Reset to defaults", fg_color="#444",
                      hover_color="#555", command=self._reset_keys).pack(anchor="w", padx=12, pady=14)

    # ----------------------------------------------------- key capturing
    def _merc_mod_label(self) -> str:
        """Current feed-to-merc modifier, as a UI menu label ("Shift"/"Ctrl"/"Alt")."""
        return _MERC_CFG_TO_LABEL.get(self.config.merc_modifier(), "Shift")

    def _on_merc_modifier(self, value: str):
        """Persist the feed-to-merc modifier choice."""
        self.config.set_merc_modifier(value)
        self.config.save()

    def _on_focus(self):
        """Toggle auto-focusing the game window before each key press."""
        self.config.behavior["auto_focus_game"] = bool(self._focus_switch.get())
        self.config.save()

    def _on_sound(self):
        """Toggle the potion chime."""
        self.config.behavior["sound"] = bool(self._sound_switch.get())
        self.config.save()

    def _on_pause(self):
        """Toggle pausing while blocking panels (inventory/stash/menus) are open."""
        self.config.behavior["pause_when_menus_open"] = bool(self._pause_switch.get())
        self.config.save()

    def _on_poll_interval(self, value):
        """Set the watcher refresh interval (live - applied next tick)."""
        self.config.behavior["poll_interval_ms"] = int(round(value))
        self.config.save()

    # ------------------------------------------------------- belt columns
    def _refresh_managed(self):
        managed = set(self.config.managed_columns())
        for col, box in self._managed_boxes.items():
            box.select() if col in managed else box.deselect()

    def _on_managed_toggle(self):
        self.config.set_managed_columns(
            [k for k, box in self._managed_boxes.items() if box.get()])
        self.config.save()
        self._refresh_managed()   # normalise to "all columns" when none selected

    def _on_belt_key_entry(self, col: str):
        """Validate and save a belt-column key typed into the entry."""
        entry = self._belt_key_entries.get(col)
        if not entry:
            return
        text = entry.get().strip().upper()
        if text in ("ESC", "DELETE", ""):
            # Restore default
            self.config.set_belt_key(col, "")
        else:
            name = keysym_to_key_name(text)
            if not name:
                self._belt_keys_hint.configure(
                    text=f"Unsupported key for column {col} — try a letter, number, F-key or arrow.",
                    text_color=DANGER)
                return
            self.config.set_belt_key(col, name)
        self.config.save()
        self._refresh_belt_keys()
        self._belt_keys_hint.configure(text="")

    # ------------------------------------------------------- global hotkey
    def _toggle_hotkey_capture(self):
        """Grab a new global enable/disable combo (Esc or Delete clears it)."""
        if self._capturing:
            if self._capturing == "hotkey":
                self._end_capture()
            return
        self._capturing = "hotkey"
        self._capture_col = None
        self._held_mods: set[str] = set()
        self._hotkey_btn.configure(text="Press combo… (Esc clears)")
        self._hotkey_state.configure(text="", text_color="gray60")
        self.focus_force()
        self.bind("<KeyPress>", self._on_hotkey_capture_key)
        self.bind("<KeyRelease>", self._on_hotkey_capture_release)

    def _on_hotkey_capture_release(self, event):
        mod = hotkey_mod_from_keysym(getattr(event, "keysym", ""))
        if mod:
            self._held_mods.discard(mod)

    def _on_hotkey_capture_key(self, event):
        """Finish a global-hotkey capture (held modifiers + a key)."""
        if self._capturing is None:
            return
        keysym = getattr(event, "keysym", "")
        mod = hotkey_mod_from_keysym(keysym)
        if mod:
            self._held_mods.add(mod)
            return
        if keysym.lower() in ("escape", "delete"):
            self.config.behavior["toggle_hotkey"] = ""
            self.config.save()
            self._emit_log("Global hotkey cleared.", "info")
            self._end_capture()
            self._refresh_hotkey()
            return
        if not self._held_mods:
            self._hotkey_state.configure(text="hold Ctrl/Alt/Shift + a key", text_color=WARN)
            return
        spec = spec_for(keysym, frozenset(self._held_mods))
        if not spec:
            self._hotkey_state.configure(text="unsupported key", text_color=DANGER)
            return
        self.config.behavior["toggle_hotkey"] = spec
        self.config.save()
        self._emit_log(f"Global hotkey set to {spec}.", "info")
        self._end_capture()
        self._refresh_hotkey()

    def _end_capture(self):
        """Stop any active key capture and restore the widgets' labels."""
        self.unbind("<KeyPress>")
        self.unbind("<KeyRelease>")
        mode = self._capturing
        self._capturing = None
        self._capture_col = None
        if mode == "hotkey":
            self._sync_hotkey_ui()

    def _sync_hotkey_ui(self):
        """Push the stored combo onto the topbar hotkey button."""
        spec = self.config.behavior.get("toggle_hotkey", "")
        self._hotkey_btn.configure(text=f"Hotkey: {spec}" if spec else "Hotkey: off")

    def _refresh_hotkey(self):
        """(Re)register the global enable/disable hotkey from config."""
        if self.hotkey:
            self.hotkey.stop()
            self.hotkey = None
        self._sync_hotkey_ui()
        spec = self.config.behavior.get("toggle_hotkey", "")
        parsed = parse_hotkey(spec)
        if not parsed:
            self._hotkey_state.configure(text="" if not spec else "invalid combo",
                                         text_color="gray60" if not spec else DANGER)
            return
        mods, vk = parsed
        listener = HotkeyListener(mods, vk, self._hotkey_toggle)
        ok = listener.start()
        if ok:
            self.hotkey = listener
            self._hotkey_state.configure(text="active", text_color=GOOD)
            self._emit_log(f"Global hotkey {spec} registered.", "info")
        else:
            self._hotkey_state.configure(text="failed (in use?)", text_color=DANGER)
            self._emit_log(f"Could not register hotkey {spec} (already in use?).", "error")

    def _hotkey_toggle(self):
        """Global-hotkey callback: enable/disable, marshalled to the main thread."""
        self.after(0, self._toggle_enabled)

    def _refresh_belt_keys(self):
        """Push the bound in-game keys onto the per-column entries."""
        keys = self.config.belt_keys_map()
        for i, col in enumerate(m.BELT_COLUMN_KEYS):
            entry = self._belt_key_entries.get(col)
            if entry:
                entry.delete(0, "end")
                entry.insert(0, keys[i])

    def _reset_keys(self):
        """Restore default behaviour switches, merc modifier, and belt plan."""
        from d2r.config import DEFAULTS
        self.config.behavior = dict(DEFAULTS["behavior"])
        self.config.layout = dict(DEFAULTS["layout"])
        self.config.ratio = dict(DEFAULTS["ratio"])
        self.config.belt_keys = dict(DEFAULTS["belt_keys"])
        self._focus_switch.select() if self.config.behavior.get("auto_focus_game", True) else self._focus_switch.deselect()
        self._sound_switch.select() if self.config.behavior.get("sound", True) else self._sound_switch.deselect()
        self._pause_switch.select() if self.config.behavior.get("pause_when_menus_open", True) else self._pause_switch.deselect()
        self._poll_frame.set_value(float(self.config.behavior.get("poll_interval_ms", 150)))
        self._merc_mod_menu.set(self._merc_mod_label())
        self._refresh_managed()
        self._refresh_belt_keys()
        self.config.save()
        self._refresh_hotkey()

    # ---------------------------------------------------------- calibrate
    def _build_calibrate(self, parent):
        """Guided-calibration wizard: the user places a known potion in the belt
        corners, the app reads the corner slot codes itself, infers the family
        and saves it into the "_CALIB_COMBO" combo (persisted, auto-active)."""
        scroll = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=4, pady=4)

        w.heading(scroll, "Saved potion codes").pack(anchor="w", padx=12, pady=(10, 4))
        w.hint(scroll, "A 'potion code set' is the table mapping item ids to potion "
                       "families/grades.  These are separate from the whole-config "
                       "profiles on the top bar.").pack(anchor="w", padx=12, pady=(0, 2))
        combo_row = ctk.CTkFrame(scroll, fg_color="transparent")
        combo_row.pack(anchor="w", padx=12, fill="x", pady=(0, 4))
        ctk.CTkLabel(combo_row, text="Active profile:").pack(side="left")
        self._combo_menu = ctk.CTkOptionMenu(combo_row, values=[""], width=220, height=28)
        self._combo_menu.set("")
        self._combo_menu.pack(side="left", padx=(6, 0))
        ctk.CTkButton(combo_row, text="Use", width=60, height=28,
                      command=self._apply_combo).pack(side="left", padx=(6, 0))
        ctk.CTkButton(combo_row, text="Delete", width=70, height=28,
                      fg_color="#7a4a4a", hover_color="#8c5555",
                      command=self._delete_combo).pack(side="left", padx=(6, 0))
        self._combo_state = ctk.CTkLabel(scroll, text="", text_color="gray70",
                                         font=ctk.CTkFont(size=11))
        self._combo_state.pack(anchor="w", padx=12, pady=(2, 6))

        w.heading(scroll, "Teach the app your potions").pack(anchor="w", padx=12, pady=(4, 4))
        calib_row = ctk.CTkFrame(scroll, fg_color="transparent")
        calib_row.pack(anchor="w", padx=12, fill="x", pady=(0, 4))
        ctk.CTkLabel(calib_row, text="Potion in the belt corners:").pack(side="left")
        self._calib_potion_menu = ctk.CTkOptionMenu(
            calib_row, values=[label for label, _, _ in _WIZARD_POTIONS], width=220, height=28)
        self._calib_potion_menu.set(_WIZARD_POTIONS[0][0])
        self._calib_potion_menu.pack(side="left", padx=(6, 0))
        ctk.CTkButton(calib_row, text="Scan belt corners", width=140, height=28,
                      command=self._wizard_scan).pack(side="left", padx=(8, 0))
        self._calib_status = ctk.CTkLabel(scroll, text="", text_color="gray70",
                                           font=ctk.CTkFont(size=11))
        self._calib_status.pack(anchor="w", padx=12, pady=(2, 6))

        # Menu-detection calibration UI removed (2026-08): drinking while the
        # inventory/stash panels are open works perfectly well, so mapping the
        # UI-panel flags is not needed for the app itself.  FORKS: the whole
        # backend stays functional in d2r/reader.py (`calibrate_ui`,
        # `open_menus`, `_get_ui_base`) plus the config accessors
        # (`calibrated_ui_address`/`calibrated_ui_flags`/
        # `calibrated_ui_closed_values`) — a fork can re-add a button that
        # calls `MainApp._calibrate_ui`-style flow or drive the reader
        # directly.  See git history for the removed handlers.

        merc_row = ctk.CTkFrame(scroll, fg_color="transparent")
        merc_row.pack(anchor="w", padx=12, fill="x", pady=(4, 2))
        ctk.CTkLabel(merc_row, text="Merc hireling txtFileNo(s) (optional):").pack(side="left")
        self._calib_merc_entry = ctk.CTkEntry(merc_row, width=160, height=28)
        self._calib_merc_entry.pack(side="left", padx=(6, 0))
        w.hint(scroll, "Comma-separated (e.g. 271, 338). Only needed if the merc "
                       "reads as 'no merc'; find the id in Diagnostics.").pack(
                           anchor="w", padx=12, pady=(0, 8))

        w.heading(scroll, "Learned so far").pack(anchor="w", padx=12, pady=(6, 2))
        self._learned_label = ctk.CTkLabel(scroll, text="", justify="left", anchor="w",
                                           font=ctk.CTkFont(size=12), wraplength=560)
        self._learned_label.pack(anchor="w", padx=12, pady=(0, 4))
        ctk.CTkButton(scroll, text="Clear calibration", width=140, height=28,
                      fg_color="#7a4a4a", hover_color="#8c5555",
                      command=self._clear_calibration).pack(anchor="w", padx=12, pady=(2, 4))

        w.heading(scroll, "Instructions").pack(anchor="w", padx=12, pady=(8, 4))
        w.hint(scroll, _CALIB_INSTRUCTIONS).pack(anchor="w", padx=12, pady=(0, 14))

        self._refresh_combo_menu()
        self._refresh_combo_state()
        self._refresh_learned()

    def _active_combo_potion_txts(self) -> set:
        """txtFileNos already learned in the active combo (never the defaults)."""
        body = self.config.combos.get(self.config.combo)
        rows = body.get("potions", []) if body else []
        out = set()
        for row in rows:
            try:
                out.add(int(row[0]))
            except (TypeError, ValueError, IndexError):
                continue
        return out

    def _parse_merc_ids(self) -> list:
        """Parse the merc txtFileNo field into a list of ints (empty ok)."""
        out = []
        for part in self._calib_merc_entry.get().replace(",", " ").split():
            try:
                out.append(int(part))
            except ValueError:
                continue
        return out

    def _learn_potion(self, kind: str, anchor_txt: int, anchor_grade: int):
        """Infer the potion family from the anchor code and persist the result
        into the wizard's combo (auto-active, so the reader picks it up instantly)."""
        new_entries = m.infer_potion_family(kind, anchor_txt, anchor_grade,
                                            existing=self._active_combo_potion_txts())
        if not new_entries:
            self._emit_log(f"'{kind}' already learned — nothing new to save.", "info")
            return
        body = self.config.combos.get(self.config.combo) or {}
        rows = [[e.txt, e.kind, e.grade] for e in new_entries]
        rows.extend(body.get("potions", []))
        merc = self._parse_merc_ids() or body.get("merc", [])
        self.config.save_combo(_CALIB_COMBO, rows, merc, body.get("notes", ""))
        self._apply_codes_to_reader()
        self._refresh_combo_menu()
        self._refresh_combo_state()
        self._refresh_learned()
        names = ", ".join(str(e.txt) for e in new_entries)
        self._emit_log(f"Learned '{kind}' codes: {names} (saved to "
                       f"'{_CALIB_COMBO}', now active).", "info")

    def _clear_calibration(self):
        """Delete the wizard's combo and fall back to the built-in defaults."""
        self.config.delete_combo(_CALIB_COMBO)
        self._calib_merc_entry.delete(0, "end")
        self._apply_codes_to_reader()
        self._refresh_combo_menu()
        self._refresh_combo_state()
        self._refresh_learned()
        self._set_calib_status("")
        self._emit_log("Calibration cleared — back to built-in potion defaults.", "info")

    def _apply_combo(self):
        """Switch to the potion-code set selected in the dropdown."""
        name = self._combo_menu.get()
        if not name:
            self._emit_log("Select a saved potion-code set first.", "error")
            return
        if not self.config.set_active_combo(name):
            self._emit_log(f"Potion-code set '{name}' not found.", "error")
            return
        self._apply_codes_to_reader()
        self._refresh_combo_state()
        self._emit_log(f"Potion codes '{name}' are now active.", "info")

    def _delete_combo(self):
        """Remove the selected potion-code set."""
        name = self._combo_menu.get()
        if not name:
            return
        self.config.delete_combo(name)
        self._refresh_combo_menu()
        self._refresh_combo_state()
        self._emit_log(f"Potion-code set '{name}' deleted.", "info")

    def _apply_codes_to_reader(self):
        """Push the active combo's codes into the live reader (no reconnect)."""
        if self.reader is not None:
            self.reader.codes = self.config.potion_codes()
            self.reader.merc_txtfiles = self.config.merc_txtfiles_set()

    def _refresh_combo_menu(self):
        names = self.config.combo_names()
        self._combo_menu.configure(values=names or [""])
        self._combo_menu.set(self.config.combo if self.config.combo in names else "")

    def _refresh_combo_state(self):
        if self.config.combo:
            self._combo_state.configure(
                text=f"Using '{self.config.combo}' - "
                     f"{len(self.config.potion_codes().entries)} potion codes.")
        else:
            self._combo_state.configure(text="Using built-in Infernal potion defaults.")

    def _wizard_scan(self):
        """Read the belt corner slots in the background (never freezes UI)."""
        if not self.reader:
            self._emit_log("Connect to the game first, then scan.", "error")
            return
        self._set_calib_status("Scanning belt corners… (stay in a game)")
        threading.Thread(target=self._do_wizard_scan, daemon=True).start()

    def _do_wizard_scan(self):
        data = self.reader.scan_item_codes()
        slots = {e["x"]: e["txt"] for e in data.get("belt", []) if e.get("x", -1) >= 0}
        self.after(0, lambda: self._finish_wizard_scan(slots, data.get("error")))

    def _finish_wizard_scan(self, slots: dict, error: str | None):
        if error:
            self._set_calib_status(f"Scan failed: {error}")
            return
        code = m.corner_potion_code(slots)
        if code is None:
            detail = ", ".join(f"x{k}:{v}" for k, v in sorted(slots.items())) or "none"
            self._set_calib_status(
                "Could not find a single code in all 4 belt corners "
                f"(read: {detail}). Place one potion in every corner slot and retry.")
            return
        label, kind, grade = self._selected_wizard_potion()
        self._set_calib_status(
            f"Found txtFileNo {code} in all 4 corners — that matches "
            f"'{label}'. Saving…")
        self._learn_potion(kind, code, grade)

    def _selected_wizard_potion(self):
        label = self._calib_potion_menu.get()
        for item in _WIZARD_POTIONS:
            if item[0] == label:
                return item
        return _WIZARD_POTIONS[0]

    def _set_calib_status(self, text: str):
        self._calib_status.configure(text=text)

    # Menu-detection calibration handlers were removed with their UI section
    # (2026-08) — drinking with panels open is fine, so flag mapping is not
    # needed.  FORKS: `GameReader.calibrate_ui` in d2r/reader.py is the
    # self-verifying implementation (stable-baseline / stable-open /
    # baseline-return checks); persist its result via
    # `AppConfig.set_calibrated_ui_address/flags/closed_values` and
    # `open_menus()` picks it up.  See git history for the removed handlers.

    def _refresh_learned(self):
        """Show the active combo's potion table as plain text (or the defaults)."""
        codes = self.config.potion_codes()
        if not codes.entries:
            self._learned_label.configure(
                text="Nothing learned yet — follow the steps below to teach the app "
                     "your build's codes.")
            return
        lines = [f"{txt} = {e.kind}" + ("" if e.grade < 0 else f" ({codes.grade_names(e.kind)[e.grade]})")
                 for txt, e in sorted(codes.entries.items())]
        self._learned_label.configure(text="  " + "\n  ".join(lines))

    # --------------------------------------------------------- diagnostics
    def _build_diagnostics(self, parent):
        top = ctk.CTkFrame(parent, fg_color="transparent")
        top.pack(fill="x", padx=12, pady=(10, 4))
        ctk.CTkButton(top, text="Run offset scan & read test",
                      command=self._run_scan).pack(side="left")
        self.diag_hint = ctk.CTkLabel(top, text="", text_color="gray60")
        self.diag_hint.pack(side="left", padx=12)

        w.hint(parent, "Run this while in a game.  Every signature must read 'RESOLVED' and "
                       "the live reads 'plausible: YES'.  If not, the built-in byte patterns "
                       "no longer match your game build — copy the output below when asking "
                       "for support.").pack(anchor="w", padx=12, pady=(4, 6))

        self.diag_box = ctk.CTkTextbox(parent, wrap="none")
        self.diag_box.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self.diag_box.configure(state="disabled")

    def _run_scan(self):
        """Kick off the diagnostics scan on a background thread."""
        self.diag_hint.configure(text="Scanning… (stay in a game, up to ~45s)")
        self.update_idletasks()
        threading.Thread(target=self._do_scan, daemon=True).start()

    def _do_scan(self):
        """Run the offset/read diagnostics and marshal the result to the UI."""
        lines: list[str] = []
        try:
            if not self.connected:
                # Already on a background thread: connect synchronously so the
                # scan below sees a reader (the async path would race it).
                if not self._connecting:
                    self._connect_worker()
            if self.reader is not None:
                lines = self.reader.diagnose()
            elif self.proc is not None:
                temp = GameReader(self.proc)
                lines = temp.diagnose()
            elif not find_d2r_processes():
                lines = ["D2R.exe is not running. Start the game, then scan."]
            else:
                lines = ["Could not attach to D2R.exe."]
        except Exception as exc:
            lines = [f"Scan error: {exc}"]
        text = "\n".join(lines)
        self.after(0, lambda: self._show_scan(text, lines))

    def _show_scan(self, text: str, lines: list[str]):
        self.diag_box.configure(state="normal")
        self.diag_box.delete("1.0", "end")
        self.diag_box.insert("end", text)
        self.diag_box.configure(state="disabled")
        found = any("FOUND UnitTable" in l for l in lines)
        readable = any("bytes read :" in l and "OK" in l for l in lines)
        if found:
            self._set_status("Connected", GOOD)
            self.diag_hint.configure(text="Offsets found", text_color=GOOD)
        elif readable:
            self.diag_hint.configure(text="Check output", text_color=WARN)
        else:
            self.diag_hint.configure(text="Cannot read game", text_color=DANGER)
        for l in lines[:6]:
            self.on_event(m.GameEvent(kind="info", message="[diag] " + l))

    # --------------------------------------------------------------- log
    def _build_log(self, parent):
        bar = ctk.CTkFrame(parent, fg_color="transparent")
        bar.pack(fill="x", padx=12, pady=(10, 4))
        ctk.CTkButton(bar, text="Clear log", width=90, height=28,
                      command=self._clear_log).pack(side="left")
        ctk.CTkButton(bar, text="Export diagnostics", width=150, height=28,
                      command=self._export_diagnostics).pack(side="left", padx=(8, 0))
        self.log_hint = ctk.CTkLabel(
            bar, text="", text_color="gray60", font=ctk.CTkFont(size=11))
        self.log_hint.pack(side="left", padx=12)
        self.log_box = ctk.CTkTextbox(parent, wrap="word")
        self.log_box.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self.log_box.configure(state="disabled")

    def _clear_log(self):
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")
        self.event_log.clear()
        self.log_hint.configure(text="Log cleared.")

    def _export_diagnostics(self):
        """Dump the current diagnostics report to a file next to the log."""
        from d2r.config import CONFIG_DIR
        path = os.path.join(CONFIG_DIR, "diagnostics.txt")
        lines = ["D2R Infernal Auto Potion diagnostics export",
                 f"generated: {time.strftime('%Y-%m-%d %H:%M:%S')}", ""]
        try:
            if self.reader is not None:
                lines += self.reader.diagnose()
            else:
                lines.append("(not connected - no diagnostics available)")
        except Exception as exc:
            lines.append(f"(scan failed: {exc})")
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("\n".join(lines))
            self.log_hint.configure(text=f"Saved to {path}")
        except Exception:
            self.log_hint.configure(text="Could not write diagnostics file.")

    def on_event(self, e: m.GameEvent):
        """Queue a GameEvent to be rendered by the UI.

        Must marshal to the main thread: this is invoked from the watcher
        thread, and Tkinter/CustomTkinter must not be touched off it.  Guarded
        so a window that is being torn down can never kill the watcher."""
        try:
            self.after(0, self._log_event, e)
        except Exception:
            pass

    def _log_event(self, e: m.GameEvent):
        """Append one event line to the Log tab (main thread only)."""
        stamp = time.strftime("%H:%M:%S", time.localtime(e.timestamp or time.time()))
        prefix = {
            "heal": "❤", "mana": "🔷", "rejuv": "✨",
            "merc_heal": "🛡", "merc_rejuv": "✨",
            "info": "•", "error": "⚠", "status": "•",
        }.get(e.kind, "•")
        w.append_log(self.log_box, f"[{stamp}] {prefix} {e.message}")
        self.event_log.append(e.kind, e.message, e.timestamp)

    # -------------------------------------------------------- connection
    def _sync_connect_button(self):
        """Connect when detached, Reconnect once attached (marshalled)."""
        text = "Reconnect" if self.connected else "Connect"
        try:
            self.after(0, lambda: self.reconnect_btn.configure(text=text))
        except Exception:
            pass

    def _reconnect(self):
        """Force a fresh attach + offset resolution (disconnect first)."""
        self._disconnect()
        self._try_connect()

    def _try_connect(self):
        """Kick off attach + offset resolution on a background thread.

        The signature scan can take seconds; running it on the UI thread froze
        the window at every startup.  Idempotent: a connect already in flight
        is never doubled."""
        if self.connected or self._connecting:
            return
        self._connecting = True
        self._set_status("Looking for D2R…", WARN)
        threading.Thread(target=self._connect_worker, daemon=True).start()

    def _connect_worker(self):
        """Attach to D2R, resolve offsets, and start the watcher (background).

        Never opens the process when the game is not running — a cheap process
        snapshot answers that, and the status pill says so instead of silently
        retrying."""
        try:
            if not find_d2r_processes():
                self._set_status("Game not found", WARN)
                return
            proc = Process.attach()
            reader = GameReader(proc, codes=self.config.potion_codes(),
                                merc_txtfiles=self.config.merc_txtfiles_set(),
                                config=self.config)
            watcher = PotionWatcher(reader, self.config, on_event=self.on_event)
            watcher.start()
            self.proc, self.reader, self.watcher = proc, reader, watcher
            self.connected = True
            self._shown_errors.clear()
            if reader.offsets.ok:
                self._set_status("Connected", GOOD)
                self.on_event(m.GameEvent(kind="info",
                              message=f"Connected to D2R (pid {proc.pid}). {reader.offsets.version_hint}."))
            else:
                self._set_status("Searching offsets…", WARN)
                self.on_event(m.GameEvent(kind="info",
                              message="Connected, scanning for unit-table offset (be in a game)."))
                threading.Thread(target=self._background_discover, daemon=True).start()
        except ProcessNotFound:
            self._set_status("Game not found", WARN)
        except Exception as exc:
            self._set_status("Attach failed", DANGER)
            self.on_event(m.GameEvent(kind="error", message=f"Attach failed: {exc}"))
        finally:
            self._connecting = False
            self._sync_connect_button()

    def _background_discover(self):
        """Try the structural UnitTable scan in the background after connect."""
        if not self.reader:
            return
        off = self.reader.discover()
        if off:
            self._set_status("Connected", GOOD)
            self.on_event(m.GameEvent(kind="info",
                          message=f"Resolved UnitTable offset structurally at 0x{off:X}."))
        else:
            self._set_status("Offsets unresolved", WARN)
            self.on_event(m.GameEvent(kind="error",
                          message="Could not auto-find offsets. Open Diagnostics → Run scan while in a game."))

    def _disconnect(self):
        """Stop the watcher and drop all process/reader references."""
        if self.watcher:
            self.watcher.stop()
        self.proc = self.reader = self.watcher = None
        self.connected = False
        self._sync_connect_button()

    def _poll(self):
        """Periodic UI refresh: watch for game close, update the dashboard,
        retry connect/discover as needed."""
        try:
            if self.connected and self.proc is not None:
                if not self.proc.read_bytes(self.proc.module_base, 4):
                    self._disconnect()
                    self._set_status("Game closed", WARN)
                else:
                    snap = self.watcher.snapshot()
                    self._update_dashboard(snap)
                    if snap.error and snap.error not in self._shown_errors:
                        self._shown_errors.add(snap.error)
                        self.on_event(m.GameEvent(kind="error", message=snap.error))
                    # If offsets never resolved (e.g. we attached while in menus),
                    # keep trying the structural scan in the background, but only
                    # while the game is actually alive.
                    if not self.reader.offsets.ok:
                        now = time.time()
                        if now - self._last_discover > 5:
                            self._last_discover = now
                            threading.Thread(target=self._background_discover,
                                             daemon=True).start()
            elif not self._connecting:
                # Not attached: a cheap process-name snapshot decides whether a
                # (potentially seconds-long) connect attempt is even worth
                # starting — no offset searching without a running game.
                now = time.time()
                if now - self._last_connect_attempt > 2:
                    self._last_connect_attempt = now
                    if find_d2r_processes():
                        self._try_connect()
                    else:
                        self._set_status("Game not found", WARN)
        except Exception:
            pass
        self.after(150, self._poll)

    def _on_close(self):
        """Stop the watcher thread + hotkey before the window closes (clean exit)."""
        if self.watcher:
            self.watcher.stop()
        if self.hotkey:
            self.hotkey.stop()
        self.destroy()


def _is_elevated() -> bool:
    """True when the current process runs with administrator rights."""
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _relaunch_elevated() -> bool:
    """Restart the app with administrator rights (UAC).  False if declined."""
    import ctypes
    import sys
    exe = sys.executable
    script = os.path.abspath(sys.argv[0])
    rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, f'"{script}"', None, 1)
    return rc > 32


def run():
    # Gamepad mode needs an elevated process (Microsoft's synthetic gamepad API
    # refuses access otherwise); offer a UAC relaunch before the UI appears.
    if AppConfig.load().use_gamepad and not _is_elevated():
        if ctk.messagebox.askyesno(
                "Administrator required",
                "Gamepad mode needs administrator rights (it uses Microsoft's "
                "built-in synthetic gamepad API — no drivers are installed).\n\n"
                "Restart the app as administrator now?"):
            if _relaunch_elevated():
                return
    app = MainApp()
    app.mainloop()
