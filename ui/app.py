"""CustomTkinter UI for the D2R Infernal Auto Potion tool.

Tabs:
  Dashboard   - live HP / Mana / Merc bars, character info, arm/disarm toggle
  Triggers    - threshold + cooldown sliders
  Keys        - belt-key bindings + behaviour switches
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
from d2r.process import Process, ProcessNotFound
from d2r.reader import GameReader
from d2r.watcher import PotionWatcher
from d2r.keys import vk_name
from d2r.log import EventLog
from d2r.hotkey import HotkeyListener, parse_hotkey, spec_for
from d2r.hotkey import mod_from_keysym as hotkey_mod_from_keysym
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

_potion_labels = {"heal": "heal", "mana": "mana", "rejuv": "rejuv", "other": "other"}


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
        self._capturing: str | None = None
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

        self.status_pill = ctk.CTkLabel(bar, text="Connecting…", corner_radius=12,
                                        fg_color=WARN, text_color="white",
                                        font=ctk.CTkFont(size=12, weight="bold"),
                                        width=150, height=26)
        self.status_pill.pack(side="left", padx=(0, 12))

        self.reconnect_btn = ctk.CTkButton(bar, text="Reconnect", width=90,
                                           command=self._reconnect)
        self.reconnect_btn.pack(side="left", padx=(0, 12))

        self.enable_btn = ctk.CTkButton(bar, text="DISABLED", width=140, height=34,
                                        fg_color=DANGER, hover_color="#c0392b",
                                        font=ctk.CTkFont(size=13, weight="bold"),
                                        command=self._toggle_enabled)
        self._sync_enable_button()
        self.enable_btn.pack(side="right", padx=(0, 6))

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
            self.enable_btn.configure(text="● ARMED", fg_color=GOOD, hover_color="#1e8449")
        else:
            self.enable_btn.configure(text="DISABLED", fg_color=DANGER, hover_color="#c0392b")

    def _toggle_enabled(self):
        # Do not allow arming without a working connection.
        if not self.connected or (self.reader and not self.reader.offsets.ok):
            self.on_event(m.GameEvent(kind="error",
                          message="Cannot arm: not connected / offsets unresolved. See Diagnostics."))
            return
        self.config.enabled = not self.config.enabled
        self._sync_enable_button()
        self.config.save()
        state = "armed" if self.config.enabled else "disarmed"
        self.on_event(m.GameEvent(kind="info", message=f"Auto-potion {state}."))

    # -------------------------------------------------------------- tabs
    def _build_tabs(self):
        self.tabs = ctk.CTkTabview(self, corner_radius=10)
        self.tabs.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        for name in ("Dashboard", "Triggers", "Keys", "Diagnostics", "Log"):
            self.tabs.add(name)
        self._build_dashboard(self.tabs.tab("Dashboard"))
        self._build_triggers(self.tabs.tab("Triggers"))
        self._build_keys(self.tabs.tab("Keys"))
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
                     "slots (Triggers → Keys). Arm with the button top-right.")
        w.hint(parent, help_text).pack(anchor="w", padx=12, pady=(14, 0))

    def _update_dashboard(self, snap: m.PlayerSnapshot):
        """Refresh the character info, stat bars, and potion counter."""
        if not self.connected:
            return
        if snap.in_game:
            self.char_label.configure(
                text=f"{snap.name or 'Unknown'}  ·  {snap.class_name}  ·  Lvl {snap.level}")
            self.state_label.configure(text="In game" + ("  ·  menus open (paused)"
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

        if snap.merc_alive:
            self.merc_bar.set(snap.merc_hp_percent / 100)
            self.merc_bar.configure(progress_color=w.color_for_percent(snap.merc_hp_percent))
            self.merc_read.configure(text=f"{snap.merc_hp}/{snap.merc_max_hp}  ({snap.merc_hp_percent}%)")
        else:
            self.merc_bar.set(0)
            self.merc_read.configure(text="no merc")

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

        w.heading(body, "Cooldowns (seconds)").pack(anchor="w", padx=12, pady=(14, 4))
        self._cooldown_sliders: dict[str, object] = {}
        for key, label in (("heal", "Health potion"), ("mana", "Mana potion"),
                           ("rejuv", "Rejuv"), ("merc_heal", "Merc health"),
                           ("merc_rejuv", "Merc rejuv")):
            frame, _ = w.labeled_slider(
                body, label, 0.5, 12.0, self.config.cooldown(key),
                lambda v, k=key: self._on_cooldown(k, v), step=0.5, fmt="{:.1f}s")
            frame.pack(fill="x", padx=12, pady=2)
            self._cooldown_sliders[key] = frame

        ctk.CTkButton(body, text="Reset to defaults", fg_color="#444",
                      hover_color="#555", command=self._reset_triggers).pack(anchor="w", padx=12, pady=14)

    def _on_threshold(self, key, value):
        self.config.thresholds[key] = int(round(value))
        self.config.save()

    def _on_cooldown(self, key, value):
        self.config.cooldowns[key] = round(float(value), 1)
        self.config.save()

    def _sync_sliders(self):
        """Push config values into every trigger/cooldown slider."""
        for k, frame in self._trigger_sliders.items():
            frame.set_value(self.config.threshold(k))  # type: ignore[attr-defined]
        for k, frame in self._cooldown_sliders.items():
            frame.set_value(self.config.cooldown(k))  # type: ignore[attr-defined]

    def _reset_triggers(self):
        from d2r.config import DEFAULTS
        self.config.thresholds = dict(DEFAULTS["thresholds"])
        self.config.cooldowns = dict(DEFAULTS["cooldowns"])
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
            for a in self._key_buttons:
                self._refresh_key_button(a)
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
        w.heading(parent, "Belt key bindings").pack(anchor="w", padx=12, pady=(10, 4))
        self._key_buttons: dict[str, ctk.CTkButton] = {}
        for action, label in ACTION_NAMES.items():
            row = ctk.CTkFrame(parent, fg_color="transparent")
            row.pack(fill="x", padx=12, pady=3)
            ctk.CTkLabel(row, text=label, width=200, anchor="w").pack(side="left")
            btn = ctk.CTkButton(row, text="", width=120,
                               command=lambda a=action: self._start_capture(a))
            btn.pack(side="right")
            self._key_buttons[action] = btn
            self._refresh_key_button(action)

        w.hint(parent, "Click a binding, then press any key in-game would use. "
                      "Merc actions are sent with the Shift modifier (D2R's "
                      "feed-merc binding). Match these to your in-game belt layout.").pack(
                          anchor="w", padx=12, pady=(6, 14))

        w.heading(parent, "Behaviour").pack(anchor="w", padx=12, pady=(4, 4))
        self._focus_switch = ctk.CTkSwitch(parent, text="Auto-focus game window before pressing keys",
                                          command=self._on_focus)
        self._focus_switch.pack(anchor="w", padx=12, pady=4)
        self._focus_switch.select() if self.config.behavior.get("auto_focus_game", True) else self._focus_switch.deselect()

        self._sound_switch = ctk.CTkSwitch(parent, text="Play a chime on each potion",
                                          command=self._on_sound)
        self._sound_switch.pack(anchor="w", padx=12, pady=4)
        self._sound_switch.select() if self.config.behavior.get("sound", True) else self._sound_switch.deselect()

        self._pause_switch = ctk.CTkSwitch(parent, text="Pause while inventory/stash/menus are open",
                                          command=self._on_pause)
        self._pause_switch.pack(anchor="w", padx=12, pady=4)
        self._pause_switch.select() if self.config.behavior.get("pause_when_menus_open", True) else self._pause_switch.deselect()

        # Poll interval (responsiveness vs CPU).
        self._poll_frame, _ = w.labeled_slider(
            parent, "Watch refresh interval", 100, 500,
            float(self.config.behavior.get("poll_interval_ms", 150)),
            lambda v: self._on_poll_interval(v), step=50, fmt="{:.0f} ms")
        self._poll_frame.pack(fill="x", padx=12, pady=(8, 2))

        # Global arm/disarm hotkey (preset quick-pick + custom capture).
        hot = ctk.CTkFrame(parent, fg_color="transparent")
        hot.pack(anchor="w", padx=12, pady=(8, 0), fill="x")
        ctk.CTkLabel(hot, text="Global arm/disarm hotkey",
                     font=ctk.CTkFont(size=12)).pack(side="left")
        self._hotkey_preset = ctk.CTkOptionMenu(hot, values=HOTKEY_PRESETS, width=150, height=28)
        self._hotkey_preset.pack(side="left", padx=(10, 0))
        self._hotkey_preset.set(self.config.behavior.get("toggle_hotkey", "")
                                or "Disabled")
        self._hotkey_preset.configure(command=self._on_hotkey)
        self._hotkey_bind_btn = ctk.CTkButton(hot, text="Bind custom…", width=100, height=28,
                                              command=self._start_hotkey_capture)
        self._hotkey_bind_btn.pack(side="left", padx=(6, 0))
        self._hotkey_off_btn = ctk.CTkButton(hot, text="Off", width=44, height=28,
                                             fg_color="#7a4a4a", hover_color="#8c5555",
                                             command=self._disable_hotkey)
        self._hotkey_off_btn.pack(side="left", padx=(6, 0))
        self._hotkey_state = ctk.CTkLabel(hot, text="", font=ctk.CTkFont(size=11),
                                          text_color=GOOD)
        self._hotkey_state.pack(side="left", padx=(8, 0))
        self._hotkey_state.bind("<Button-1>", lambda e: self._refresh_hotkey())

        ctk.CTkButton(parent, text="Reset to defaults", fg_color="#444",
                      hover_color="#555", command=self._reset_keys).pack(anchor="w", padx=12, pady=14)

    # ----------------------------------------------------- key capturing
    def _refresh_key_button(self, action: str) -> None:
        """Update a binding button's label to its current key."""
        btn = self._key_buttons.get(action)
        if btn:
            btn.configure(text=vk_name(self._resolve_current(action)))

    def _resolve_current(self, action: str) -> int:
        """VK code currently bound to an action (0 = unbound/invalid)."""
        from d2r.keys import resolve_key
        return resolve_key(self.config.key(action)) or 0

    def _start_capture(self, action: str) -> None:
        """Enter click-to-bind mode: the next key press rebinds 'action'."""
        if self._capturing:
            return
        self._capturing = action
        btn = self._key_buttons[action]
        btn.configure(text="Press a key…")
        self.focus_force()
        self.bind("<Key>", self._on_capture_key)

    def _on_capture_key(self, event) -> None:
        """Finish a rebind: store the captured key under the pending action."""
        action = self._capturing
        if not action:
            return
        self.unbind("<Key>")
        self._capturing = None
        code = int(getattr(event, "keycode", 0))
        if code:
            # Store the friendly key name when known, else the raw VK hex.
            self.config.keys[action] = vk_name(code)
            self.config.save()
        self._refresh_key_button(action)

    def _on_key(self, action, value):
        """Programmatic binding override (kept for consistency/testing)."""
        self.config.keys[action] = value
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

    # ------------------------------------------------------- global hotkey
    def _on_hotkey(self, value):
        """User picked a hotkey preset (or Disabled).  Re-register it."""
        if value == "Disabled":
            value = ""
        self.config.behavior["toggle_hotkey"] = value
        self.config.save()
        self._refresh_hotkey()

    def _disable_hotkey(self):
        """Turn the global hotkey off entirely."""
        self._on_hotkey("Disabled")

    def _start_hotkey_capture(self):
        """Click-to-bind a custom combo: track held modifiers until a key lands."""
        if self._capturing:
            return
        self._capturing = "hotkey"
        self._held_mods: set[str] = set()
        self._hotkey_bind_btn.configure(text="Press combo…")
        self.focus_force()
        self.bind("<KeyPress>", self._on_hotkey_capture_key)
        self.bind("<KeyRelease>", self._on_hotkey_capture_release)

    def _on_hotkey_capture_release(self, event):
        mod = hotkey_mod_from_keysym(getattr(event, "keysym", ""))
        if mod:
            self._held_mods.discard(mod)

    def _on_hotkey_capture_key(self, event):
        """Finish a hotkey capture: build 'Ctrl+Alt+F12' from held modifiers."""
        if self._capturing != "hotkey":
            return
        keysym = getattr(event, "keysym", "")
        mod = hotkey_mod_from_keysym(keysym)
        if mod:
            self._held_mods.add(mod)
            return
        self.unbind("<KeyPress>")
        self.unbind("<KeyRelease>")
        self._capturing = None
        self._hotkey_bind_btn.configure(text="Bind custom…")
        spec = spec_for(keysym, frozenset(self._held_mods))
        if not spec:
            self._hotkey_state.configure(text="unsupported key", text_color=DANGER)
            return
        self.config.behavior["toggle_hotkey"] = spec
        self.config.save()
        self._emit_log(f"Global hotkey set to {spec}.", "info")
        self._refresh_hotkey()

    def _refresh_hotkey(self):
        """(Re)register the global arm/disarm hotkey from config."""
        spec = self.config.behavior.get("toggle_hotkey", "")
        self.hotkey = None
        parsed = parse_hotkey(spec)
        if not parsed:
            label = "off" if not spec else f"{spec} (invalid)"
            self._hotkey_state.configure(text=label, text_color="gray60")
            self._hotkey_preset.set(spec if spec in HOTKEY_PRESETS
                                    else ("Disabled" if not spec else "Custom…"))
            return
        mods, vk = parsed
        listener = HotkeyListener(mods, vk, self._hotkey_toggle)
        ok = listener.start()
        if ok:
            self.hotkey = listener
            self._hotkey_state.configure(text=f"{spec} (registered)", text_color=GOOD)
            self._hotkey_preset.set(spec if spec in HOTKEY_PRESETS else "Custom…")
            self._emit_log(f"Global hotkey {spec} registered.", "info")
        else:
            self._hotkey_state.configure(text="failed (in use?)", text_color=DANGER)
            self._emit_log(f"Could not register hotkey {spec} (already in use?).", "error")

    def _hotkey_toggle(self):
        """Global-hotkey callback: arm/disarm, marshalled to the main thread."""
        self.after(0, self._toggle_enabled)

    def _reset_keys(self):
        """Restore default key bindings and behaviour switches."""
        from d2r.config import DEFAULTS
        self.config.keys = dict(DEFAULTS["keys"])
        self.config.behavior = dict(DEFAULTS["behavior"])
        for a in self._key_buttons:
            self._refresh_key_button(a)
        self._focus_switch.select() if self.config.behavior.get("auto_focus_game", True) else self._focus_switch.deselect()
        self._sound_switch.select() if self.config.behavior.get("sound", True) else self._sound_switch.deselect()
        self._pause_switch.select() if self.config.behavior.get("pause_when_menus_open", True) else self._pause_switch.deselect()
        self._poll_frame.set_value(float(self.config.behavior.get("poll_interval_ms", 150)))
        self._hotkey_preset.set(self.config.behavior.get("toggle_hotkey", "") or "Disabled")
        self.config.save()
        self._refresh_hotkey()

    # --------------------------------------------------------- diagnostics
    def _build_diagnostics(self, parent):
        top = ctk.CTkFrame(parent, fg_color="transparent")
        top.pack(fill="x", padx=12, pady=(10, 4))
        ctk.CTkButton(top, text="Run offset scan & read test",
                      command=self._run_scan).pack(side="left")
        self.diag_hint = ctk.CTkLabel(top, text="", text_color="gray60")
        self.diag_hint.pack(side="left", padx=12)

        w.hint(parent, "If 'UnitTable' is NOT RESOLVED or 'plausible: NO', the byte signatures "
                      "in d2r/offsets.py do not match build 3.0.91636 yet. Send the output below "
                      "and we can add the correct pattern.").pack(anchor="w", padx=12, pady=(4, 6))

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
                self._try_connect()
            if self.reader is not None:
                lines = self.reader.diagnose()
            elif self.proc is not None:
                temp = GameReader(self.proc)
                lines = temp.diagnose()
            else:
                lines = ["Could not attach to D2R.exe. Start the game first."]
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
    def _reconnect(self):
        """Force a fresh attach + offset resolution (disconnect first)."""
        self._disconnect()
        self._try_connect()

    def _try_connect(self):
        """Attach to D2R, resolve offsets, and start the watcher (idempotent)."""
        if self.connected:
            return
        try:
            proc = Process.attach()
            reader = GameReader(proc)
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
            self._set_status("Game not running", WARN)
        except Exception as exc:
            self._set_status("Attach failed", DANGER)
            self.on_event(m.GameEvent(kind="error", message=f"Attach failed: {exc}"))

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
            else:
                now = time.time()
                if now - self._last_connect_attempt > 3:
                    self._last_connect_attempt = now
                    self._try_connect()
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


def run():
    app = MainApp()
    app.mainloop()
