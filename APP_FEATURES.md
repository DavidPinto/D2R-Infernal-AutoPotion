# D2R Infernal Auto Potion — Feature Status & Autopotion Logic Deep Dive

**Version:** 1.9.12-beta
**Date:** 2026-08-22
**Test Suite:** 146 tests passing, compileall clean, headless UI smoke OK

---

## Feature Status Matrix

| Feature | Status | Notes |
|---------|--------|-------|
| **Core: HP Potion Drinking** | ✅ Working | Unified `plan_consume` path, grade-aware, cooldown-gated |
| **Core: Mana Potion Drinking** | ✅ Working | Covering → rejuv → any present; never sits at 0% when critical |
| **Core: Rejuv Potion Drinking** | ✅ Working | Both-critical → rejuv; single-critical prefers covering → rejuv → any |
| **Waste Guard** | ✅ Working (1.9.3) | Never re-drinks while the in-effect potion's remaining restore covers the deficit; rejuv exempt (instant) |
| **Predictive Drinking** | ✅ Working (1.9.4/1.9.5) | Drain-slope pre-drink starts the potion before a bar empties; toggle on Triggers tab |
| **Poison Detection** | ✅ Working + live-confirmed (1.9.4) | Unit states bitfield (`statsListEx + 0xAF0`, state 2); poison bit confirmed against a real hit; poisoned ⇒ HP treated as at the heal line |
| **Antidote Priority** | ✅ Working (1.9.12) | Antidotes (id 529 this build / 514 classic, combo-overridable) classify as their own kind; poisoned ⇒ antidote drunk instead of a heal that tick; never preventive |
| **Merc Poison Parity** | ✅ Working (1.9.12) | Merc states read like the player's; poisoned merc gets an antidote fed first, else normal thresholds |
| **Reach Buried Rejuv** | ✅ Opt-in (was "Desperation Mode") | At critical HP, drinks through a full stack above a rejuv to reach it; default OFF — wasteful by design |
| **Core: Merc HP/Rejuv** | ✅ Working | Keyboard Shift+column verified in-game (1.9.11); critical parity with player rejuv line (1.9.7); **Give potions to mercenary** toggle (1.9.12, default on) |
| **Gamepad Input** | ✅ Working + live-confirmed (1.9.11) | Synthetic Xbox controller via `xboxgipsynthetic.dll`; Q/W/E/R → D-pad drinking and LT+direction merc feed both verified in-game; requires elevated process |
| **Grade-Aware Stacking** | ✅ Working | Same/higher grade after ½ duration; weaker after full × margin% |
| **Cooldown Gating** | ✅ Working | Derived from potion duration, config fallback when unknown; rejuv fixed 1 s gate |
| **Belt Reading (4 columns)** | ✅ Working | Reads slot X → column = X%4, row = X//4; lowest slot = next drunk |
| **Unclassified Potion Handling** | ✅ Working | Records unknown txtFileNo potions; best-effort press when critical |
| **Managed Columns (Q/W/E/R)** | ✅ Working | Per-column checkboxes; unmanaged = never touched |
| **Per-Column Hotkey Rebinding** | ✅ Working | Horizontal `[☐] [key]` entries; Enter/focus-out to save |
| **Global Enable/Disable Hotkey** | ✅ Working | One button capture (Ctrl/Alt/Shift+key); Esc clears |
| **Fast Startup / Connect Flow** | ✅ Working (1.9.8) | Attach + signature scan off the UI thread; "Game not found" status without D2R.exe; no attach attempts without the game; Connect/Reconnect button |
| **Config Profiles** | ✅ Working | Save/load/delete named profiles; persisted JSON |
| **Calibrate Wizard** | ✅ Working | Belt-corner scan → infer family → save as potion-code set |
| **Menu-Detection Calibration** | 🔴 Removed from UI (v1.9.9) | Drinking with panels open works fine — flag mapping unnecessary. Backend kept for forks (`GameReader.calibrate_ui`/`open_menus`); `pause_when_menus_open` is inert without a mapping |
| **Menu Pause (`pause_when_menus_open`)** | ⚪ Inert without mapping | Config switch retained; with no calibrated flag map the snapshot always reports panels closed |
| **Diagnostics / Offset Scan** | ✅ Working | Live signature scan; unit table / expansion / stats validation |
| **Event Log / Session Stats** | ✅ Working | Dashboard counters, per-action counts, exportable log |
| **Battle Orders Max Tracking** | ✅ Working | Running max follows BO boosts; manual override available |
| **Merc True Max (item block)** | ✅ Working | Reads merged MaxLife from stats-list item block (199 vs base 189) |
| **Enemy-Nearby Scan** | ✅ Working, urgency wired (1.9.11) | `engaged_monsters_near`: mode-based melee hostility proxy — zero false positives in town, caught real attackers; doubles the pre-drink lead when engaged |
| **Live End-to-End (real app)** | ✅ Verified 1.9.10 | Basic drinking ✓, gamepad D-pad drinking ✓, poison urgency ✓ (user-run session); mana pre-drink + potion economy partially checked |
| **Two-Tier Polling (<30 ms)** | ⚪ Not planned | Restore durations are seconds; `poll_interval_ms` slider is sufficient |
| **Belt Refill (click-to-move)** | 🔴 Hidden/Deferred | Logic kept (`plan_moves`, `plan_layout_refill`, `_exec_refill_step`), UI hidden — mouse-click placement not reliable enough yet |
| **Belt Plan Grid (smart layout)** | 🔴 Hidden/Deferred | Logic kept (`belt_layout`, `ratio`, `desired_kind_for_slot`), UI hidden |
| **Per-Potion Key Bindings** | 🔴 Removed (v1.8+) | Replaced by belt-column hotkeys — any managed column serves any potion type |

---

## Autopotion Logic — Step by Step

The watcher runs on a background thread at configurable interval (default 150 ms).
Each tick: `PotionWatcher._tick(snap)` → `_smart_tick(snap)` + `_merc_tick(snap)`.

### Data Flow Per Tick

```
GameReader.snapshot()
  → PlayerSnapshot (hp, mana, hp%, mana%, merc_hp%, potion_counts, ok,
                    columns[], states[], poisoned)
      → _effective_percents()          # predictive pre-drink clamp + poison clamp
          → plan_consume(...)
              → acts[], missing[]
                  → _act(action, kind, deficit, max_value, reason, snap, t, critical)
                      → _pick(...)             # BeltColumn | None | False (+ buried rejuv)
                      → _in_effect_covers(...) # waste guard (skips wasteful re-drink)
                      → _ready(action, t, candidate_grade)
                      → _use(action, reason, snap, column) → keyboard SendInput or gamepad report
```

### The Three Gates on Top of the Thresholds

1. **Pre-drink (predictive)** — a rolling `(t, hp, mana)` window gives a per-stat
   drain slope. If a bar would cross its threshold within the 1 s lead time, the
   decision sees it as already there so the restore-over-duration potion is
   already delivering when the bar empties. Poison puts HP on the heal line even
   with a flat slope. Toggle: *Triggers → Smart behavior → Predictive drinking*.
2. **Waste guard** — if the potion still in effect for an action has enough
   *remaining* restore (`total × (1 − elapsed/duration)`) to cover the current
   deficit, a second drink is skipped. Rejuv restores instantly and is exempt.
3. **Grade gate** — same-or-stronger grade may follow at half the in-effect
   duration; a weaker grade waits `duration × margin%`. Rejuv uses a fixed 1 s
   anti-spam gate.

---

### Test Scenario 11: Waste Guard — No Second Mana While Covered

**State:** Just drank Super Mana (grade 4, restore 375 over 5.12 s). Mana 55% (deficit 110), 3 s later.

1. `_act("mana", ...)` → `_pick` returns the Super mana column again
2. `_in_effect_covers("mana", 110, 200, t)`:
   - `elapsed = 3 < dur = 5.12`; `remaining = 375 × (1 − 3/5.12) ≈ 155 ≥ 110`
   - → **skip**: no second press (the old half-duration gate alone would have wasted one)
3. With a deficit of 300 (max mana 400): `155 < 300` → second drink fires.

### Test Scenario 12: Predictive Pre-Drink

**State:** Mana draining at −80/s (casting). Samples show 90% → 80% over 0.25 s. `mana_at = 60`.

1. `_predict_drop(max_mana=200, threshold=60, series=1)`:
   - slope −80/s; limit 120; current 160 → crosses in `(160−120)/80 = 0.5 s ≤ 1.0 s`
2. `_effective_percents` clamps MP% to 59 → `plan_consume` sees `59 ≤ 60` → mana act
3. Inside the same-grade cooldown the waste guard/cooldown still block a double-press.
4. When the drain slows, the prediction outgrows the lead and pre-drink stops.

### Test Scenario 13: Poison in a Safe Spot

**State:** Town / all enemies dead. HP 65%, flat slope (no damage detected), poisoned state set.

1. Without poison: 65% > heal_at → nothing (a human would often forget here).
2. `snap.poisoned = True` (state bit 2 of the unit states block):
   - `_effective_percents` clamps HP% to `heal_at − 1` regardless of slope
3. Heal act fires → the potion's restore-over-time out-paces the poison ticks.

### Test Scenario 14: Gamepad Merc Feed

**State:** Gamepad mode ON. Merc at/below its heal threshold, heal potion in column Q.

1. `_merc_tick` → `_act("merc_heal", ...)` → picks Q
2. `_use` → `KeySender.press("merc_heal", key="Q")` → `_press_gamepad`
3. GIP report holds `left_trigger = 255` (byte[3], probe-verified axis) together
   with the DPAD_LEFT bit (byte[1]) for the ~50 ms tap, then releases.
4. **Result:** D2R sees LT + D-pad-Left → the merc gets the potion (without LT the
   *player* would drink it).

---

## Key Code Locations

| Component | File | Key Functions |
|-----------|------|---------------|
| Belt Reading | `d2r/reader.py` | `snapshot()`, `_read_item_counts()`, `_read_unit_states()` |
| Plan Logic | `d2r/refill.py` | `plan_consume()`, `critical_one`, `_belt_covering`, `_belt_has_kind` |
| Column Picker | `d2r/models.py` | `PotionCounts.choose_belt_column()` |
| Watcher Core | `d2r/watcher.py` | `_tick`, `_smart_tick`, `_effective_percents`, `_predict_drop`, `_act`, `_pick`, `_in_effect_covers`, `_ready`, `_use` |
| Key Sender | `d2r/keys.py` | `KeySender.press()`, `_press_gamepad()`, `_gip_payload()`, `XboxSyntheticGamepad` |
| Config | `d2r/config.py` | `belt_key`, `set_belt_key`, `managed_columns`, `desperation→reach_buried_rejuv` |
| UI Keys Tab | `ui/app.py` | `_build_keys`, `_on_belt_key_entry`, `_refresh_belt_keys` |
| Connect Flow | `ui/app.py` | `_try_connect`, `_connect_worker`, `_poll` (presence-gated) |

---

## Known Limitations / Deferred

1. **Belt Refill** — Requires mouse clicks (SetCursorPos + SendInput). D2R has no keyboard alternative for moving items between inventory and belt. Click reliability insufficient so far; logic implemented, UI hidden.
2. **Belt Plan / Smart Layout** — Depends on refill. UI hidden, logic retained.
3. **Poison state bit** — Layout probe-verified live (always-on `Alignment` state reads correctly); the poison bit itself needs one natural in-game poison hit to confirm the flip.
4. **Enemy-nearby detection** — Unit-chain walk works; hostile-flag identification needs a monster-dense sample (fight).
5. **Gamepad in-game feed** — LT+D-pad merc feed probe-verified at the XInput level; a live D2R feed test with the app elevated is still outstanding.
6. **Game Build Compatibility** — Tested on Infernal `3.0.91636`. Offset signatures may need updates for future patches (Diagnostics tab provides the scan).

---

## Configuration Keys (AppConfig defaults)

```json
{
  "thresholds": { "healing_potion_at": 80, "mana_potion_at": 60,
                  "rejuv_potion_at_life": 25, "rejuv_potion_at_mana": 25,
                  "merc_healing_potion_at": 60, "merc_rejuv_potion_at": 20 },
  "cooldowns": { "heal": 4.0, "mana": 5.0, "rejuv": 2.0, "merc_heal": 6.0, "merc_rejuv": 2.0 },
  "behavior": { "enabled": false, "auto_focus_game": true, "sound": true,
                "pause_when_menus_open": true, "poll_interval_ms": 150,
                "smart": true, "predictive_drinking": true,
                "reach_buried_rejuv": false, "use_gamepad": false,
                "potion_margin_percent": 20, "toggle_hotkey": "",
                "merc_modifier": "Shift" },
  "belt_keys": { "Q": "Q", "W": "W", "E": "E", "R": "R" },
  "managed": ["Q", "W", "E", "R"],
  "combos": { "<name>": { "potions": [[txt, kind, grade], ...], "merc": [txt, ...] } },
  "combo": "",
  "max_override": { "player_hp": 0, "player_mp": 0, "merc_hp": 0 }
}
```
