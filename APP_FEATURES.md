# D2R Infernal Auto Potion — Feature Status & Autopotion Logic Deep Dive

**Version:** 1.8.2-beta  
**Date:** 2026-08-15  
**Test Suite:** 118 tests passing, compileall clean, headless UI smoke OK

---

## Feature Status Matrix

| Feature | Status | Notes |
|---------|--------|-------|
| **Core: HP Potion Drinking** | ✅ Working | Unified logic, grade-aware, cooldown-gated |
| **Core: Mana Potion Drinking** | ✅ Working | Fixed "not drinking at 0%" via best-effort fallback |
| **Core: Rejuv Potion Drinking** | ✅ Working | Critical both → rejuv; single-critical prefers covering → rejuv → any |
| **Core: Merc HP/Rejuv** | ✅ Working | Uses Shift+col modifier (configurable) |
| **Grade-Aware Stacking** | ✅ Working | Same/higher grade after ½ duration; weaker after full × margin |
| **Cooldown Gating** | ✅ Working | Derived from potion duration, config fallback when unknown |
| **Belt Reading (4 columns)** | ✅ Working | Reads slot X → column = X%4, row = X//4; lowest slot = next drunk |
| **Unclassified Potion Handling** | ✅ Working | Records unknown txtFileNo potions; fallback press on critical |
| **Managed Columns (Q/W/E/R)** | ✅ Working | Per-column checkboxes; unmanaged = never touched |
| **Per-Column Hotkey Rebinding** | ✅ Working | Horizontal `[☐] [key]` entries; Enter/focus-out to save |
| **Global Enable/Disable Hotkey** | ✅ Working | One button capture (Ctrl/Alt/Shift+key); Esc clears |
| **Config Profiles** | ✅ Working | Save/load/delete named profiles; persisted JSON |
| **Calibrate Wizard** | ✅ Working | Belt-corner scan → infer family → save as combo |
| **Diagnostics / Offset Scan** | ✅ Working | Live signature scan; unit table / expansion / stats validation |
| **Event Log / Session Stats** | ✅ Working | Dashboard counters, per-action counts, exportable log |
| **Battle Orders Max Tracking** | ✅ Working | Running max follows BO boosts; manual override available |
| **Merc True Max (item block)** | ✅ Working | Reads merged MaxLife from stats-list item block (199 vs base 189) |
| **Belt Refill (click-to-move)** | 🔴 Hidden/Deferred | Logic kept (`plan_moves`, `plan_layout_refill`, `_exec_refill_step`), UI hidden — D2R requires mouse clicks which aren't reliable yet |
| **Belt Plan Grid (smart layout)** | 🔴 Hidden/Deferred | Logic kept (`belt_layout`, `ratio`, `desired_kind_for_slot`), UI hidden |
| **Belt Mix / Ratio** | 🔴 Hidden/Deferred | Config field retained for back-compat; unused |
| **Per-Potion Key Bindings** | 🔴 Removed (v1.8+) | Replaced by belt-column hotkeys — any managed column serves any potion type |
| **Smart/Plain Tiers** | 🔴 Removed (v1.8.2) | Single unified `plan_consume` path; `_plain_tick` deleted; `behavior.smart` vestigial |
| **Arm/Armed Wording** | 🔴 Removed | Now "Enable/Disable" everywhere |

---

## Autopotion Logic — Step by Step

The watcher runs on a background thread at configurable interval (default 150 ms).  
Each tick: `PotionWatcher._tick(snap)` → `_smart_tick(snap)` + `_merc_tick(snap)`.

### Data Flow Per Tick

```
GameReader.read() 
  → PlayerSnapshot (hp, mana, hp%, mana%, merc_hp%, potion_counts, ok, columns[])
      → plan_consume(...) 
          → acts[], missing[]
              → _act(action, kind, deficit, max_value, reason, snap, t, critical)
                  → _pick(kind, deficit, max_value, snap) → BeltColumn | None | False
                  → _ready(action, t, candidate_grade) → bool
                  → _use(action, reason, snap, column) → SendInput press
```

---

### Test Scenario 1: HP Critical, Mana Fine, Belt Readable, Heal Present

**State:** HP 20% (≤ rejuv_life 25%), Mana 90%, Belt OK, Q=Super Heal (grade 4), W=empty, E=empty, R=empty. Managed: all.

1. `_smart_tick`: `hp_critical=True`, `mp_critical=False`
2. `plan_consume`: single HP critical → `critical_one("heal", ...)`
   - `_belt_covering("heal", deficit=320, max=400)`: `choose_belt_column("heal", 320, 400)` → finds Q (grade 4, restore 640 ≥ 320) → covering=True
   - `act("heal", deficit=320, max_value=400, reason="HP 20%")`
3. `_act("heal", "heal", 320, 400, "HP 20%", snap, t, critical=True)`:
   - `_pick("heal", 320, 400)`: `choose_belt_column` → Q (grade 4) → returns `BeltColumn(Q)`
   - `_ready("heal", t, candidate_grade=4)`: first use → ready (no prior `_last_used`)
   - `_use("heal", ..., column=Q)`: presses `config.belt_key("Q")` → SendInput VK for "Q"
   - Updates `_last_used["heal"]`, `_last_potion_dur["heal"]=10.24`, `_last_potion_grade=4`
4. **Result:** "Q" pressed, Super Heal consumed.

---

### Test Scenario 2: Mana Critical (0%), No Rejuv, Mana Present, Belt Readable

**State:** HP 85%, Mana 0% (< rejuv_mana 25%), Belt OK, Q=Minor Heal, W=Light Mana (grade 1), E=empty, R=empty. Managed: all.

1. `hp_critical=False`, `mp_critical=True`
2. `critical_one("mana", deficit=200, max=200)`:
   - `_belt_covering("mana", 200, 200)`: Light Mana restore 60 (group 1) < 200 → False
   - `_belt_has_kind("rejuv")`: False
   - `_belt_has_kind("mana")`: W has mana, count>0 → True → `act("mana", ...)`
3. `_act("mana", "mana", 200, 200, "MP 0%", snap, t, critical=True)`:
   - `_pick("mana", 200, 200)`: `choose_belt_column` → W (only mana column) → returns W
   - `_ready("mana", t, grade=1)`: ready
   - `_use`: presses `config.belt_key("W")`
4. **Result:** "W" pressed, Light Mana consumed.

---

### Test Scenario 3: Mana Critical (0%), No Classified Mana, Unclassified Potion on Belt

**State:** HP 85%, Mana 0%, Belt OK, Q=Minor Heal (classified), W=UNKNOWN txtFileNo 9999 (unclassified, kind=None), E=empty, R=empty. Managed: all.  
*This is the real-world "not drinking at 0%" bug scenario.*

1. `mp_critical=True`
2. `critical_one("mana", ...)`:
   - `_belt_covering`: no mana column → False
   - `_belt_has_kind("rejuv")`: False
   - `_belt_has_kind("mana")`: W has kind=None → False
   - `missing.append("mana")`
3. `_smart_tick` loop over `missing`:
   - `_act("mana", "mana", 200, 200, "MP 0%", snap, t, critical=True)`
3b. `_pick("mana", ...)`: `choose_belt_column` → no mana kind → returns False
4. `col is False` AND `critical=True`:
   - `_unclassified_column("mana", pc)`:
     - `FALLBACK_KEYS["mana"]` = "W" → index 1
     - Column W: count>0, kind=None, managed → **returns W**
   - `_ready("mana", t)`: ready
   - `_warn_once("mana-unclassified", ...)`: emits calibration hint once
   - `_use("mana", ..., column=W)`: presses `config.belt_key("W")`
5. **Result:** "W" pressed (best-effort), unknown potion consumed, warning logged.

---

### Test Scenario 4: Both HP & Mana Critical, No Rejuv, Both Classified Present

**State:** HP 10%, Mana 10%, Belt OK, Q=Minor Heal, W=Minor Mana, E=empty, R=empty. Managed: all.

1. `hp_critical=True`, `mp_critical=True`
2. `plan_consume` both-critical branch:
   - `_belt_has_kind("rejuv")`: False
   - `_belt_has_kind("heal")`: Q → True → `act("heal", ...)`
   - `_belt_has_kind("mana")`: W → True → `act("mana", ...)`
   - `fired=True` → no `missing`
3. `_smart_tick` acts loop:
   - `_act("heal", ...)`: picks Q, presses Q
   - `_act("mana", ...)`: picks W, presses W
4. **Result:** Both Q and W pressed (heal + mana consumed).

---

### Test Scenario 5: Non-Critical HP Dip, Unclassified Potions Present

**State:** HP 70% (≤ heal_at 80%), Mana 90%, Belt OK, Q=UNKNOWN (unclassified). Managed: all.

1. `hp_critical=False`, `mp_critical=False`
2. Non-critical branch: `hp_percent <= heal_at` → `act("heal", ...)`
3. `_act("heal", "heal", 60, 200, "HP 70%", snap, t, critical=False)`:
   - `_pick("heal", ...)`: no heal kind → returns False
   - `col is False` but `critical=False` → **no fallback**
   - Reports "No heal potion left on the belt" (once)
4. **Result:** No key pressed. Conservative — avoids wasting unrecognised potion on minor dip.

---

### Test Scenario 6: Belt Unreadable (ok=False), HP Critical

**State:** HP 10%, Mana 90%, `potion_counts.ok=False` (offsets unresolved / item table read failed).

1. `plan_consume`: `if not pc.ok:` → unreadable branch
2. `hp_critical=True` → `act("heal", deficit=..., max_hp, "HP 10%")`
3. `_act`: `_pick` → `pc.ok` False → returns `None`
4. `col is None` (not False) → grade=-1 → `_ready` → `_use(column=None)`
5. `_use`: `key = None` → `KeySender.press("heal", key=None)` → `_fallback_key("heal")` → `config.belt_key("Q")`
6. **Result:** Fallback key "Q" pressed regardless of belt content.

---

### Test Scenario 7: Grade-Aware Cooldown Gating

**State:** Just drank Super Heal (grade 4, duration 10.24s). HP dips again to 60% within 4 seconds.

1. `_act("heal", ...)` → `_pick` returns Q (Super Heal)
2. `_ready("heal", t, candidate_grade=4)`:
   - `_last_potion_dur["heal"] = 10.24`, `_last_potion_grade = 4`
   - `candidate_grade (4) >= last_grade (4)` → `effective_cooldown = 10.24 * 0.5 = 5.12s`
   - `t - _last_used["heal"] < 5.12` → **not ready**
3. `_act` returns False → no press.
4. After 6 seconds: `t - last_used ≥ 5.12` → ready → presses Q again.
5. **Result:** Same/higher grade re-drink allowed after ½ duration.

---

### Test Scenario 8: Weaker Grade Blocked Until Full Duration × Margin

**State:** Drank Super Heal (grade 4, dur 10.24s). Minor Heal (grade 0) in Q. HP dips at 8 seconds.

1. `_pick("heal", ...)` → Q (Minor Heal, grade 0)
2. `_ready("heal", t, candidate_grade=0)`:
   - `last_grade=4`, `candidate_grade=0 < last_grade` → `effective_cooldown = 10.24 * margin` (default 1.2 = 12.29s)
   - `t - last_used = 8 < 12.29` → **not ready**
3. No press until full duration × margin passes.
4. **Result:** Weaker potion never drags down fill rate.

---

### Test Scenario 9: Managed Columns Subset

**State:** HP critical, Q=Heal, W=Mana, E=Rejuv, R=Heal. Managed: only Q, W.

1. `plan_consume` receives `managed=("Q","W")` → `_allowed_for` filters columns
2. `_belt_has_kind` / `choose_belt_column` check `c.index in allowed_indices`
3. Rejuv on E (unmanaged) invisible to logic; R (unmanaged) invisible.
4. **Result:** App never presses E or R.

---

### Test Scenario 10: Per-Column Hotkey Rebinding

**Config:** `belt_keys = {"Q": "F1", "W": "2", "E": "E", "R": "R"}`

1. User types "F1" in Q entry → `_on_belt_key_entry("Q")` → `keysym_to_key_name("F1")` → "F1" → `set_belt_key("Q", "F1")`
2. Watcher `_use(column=Q)` → `config.belt_key("Q")` → "F1" → `KeySender.resolve("F1")` → VK_F1
3. **Result:** Presses F1 instead of Q for column Q.

---

## Key Code Locations

| Component | File | Key Functions |
|-----------|------|---------------|
| Belt Reading | `d2r/reader.py` | `_read_item_counts()` (lines 291-376) |
| Plan Logic | `d2r/refill.py` | `plan_consume()` (125-210), `critical_one`, `_belt_covering`, `_belt_has_kind` |
| Column Picker | `d2r/models.py` | `PotionCounts.choose_belt_column()` (513-570) |
| Watcher Core | `d2r/watcher.py` | `_tick` (222), `_smart_tick` (260), `_act` (317), `_pick` (298), `_unclassified_column` (388), `_ready` (360), `_use` (392) |
| Key Sender | `d2r/keys.py` | `KeySender.press()` (198), `_fallback_key` (217), `resolve_key` (101) |
| Config | `d2r/config.py` | `belt_key` (233), `set_belt_key` (246), `managed_columns` (209) |
| UI Keys Tab | `ui/app.py` | `_build_keys` (492), `_on_belt_key_entry` (609), `_refresh_belt_keys` (978) |

---

## Known Limitations / Deferred

1. **Belt Refill** — Requires mouse clicks (SetCursorPos + SendInput). D2R has no keyboard alternative for moving items between inventory and belt. Calibration (F8 hover) works but click reliability is insufficient for production. Logic fully implemented, UI hidden.
2. **Belt Plan / Smart Layout** — Depends on refill. UI hidden, logic retained.
3. **Merc Auto-Potion End-to-End** — Unit tested only; live in-game verification needed.
4. **Calibrate Wizard** — Works for belt-corner inference; requires user to place known potions in 4 corners.
5. **Game Build Compatibility** — Tested on Infernal 3.0.91636. Offset signatures may need update for future patches (Diagnostics tab provides scan).

---

## Configuration Keys (AppConfig)

```json
{
  "thresholds": { "healing_potion_at": 80, "mana_potion_at": 60, "rejuv_potion_at_life": 25, "rejuv_potion_at_mana": 25, "merc_healing_potion_at": 50, "merc_rejuv_potion_at": 40 },
  "cooldowns": { "heal": 4.0, "mana": 5.0, "rejuv": 1.0, "merc_heal": 4.0, "merc_rejuv": 1.0 },
  "behavior": { "smart": true, "potion_margin": 1.2, "auto_focus_game": true, "sound": true, "pause_when_menus_open": true, "poll_interval_ms": 150, "toggle_hotkey": "Ctrl+Alt+F10", "merc_modifier": "Shift" },
  "belt_keys": { "Q": "Q", "W": "W", "E": "E", "R": "R" },
  "managed": ["Q","W","E","R"],
  "combos": { "<combo_name>": { "codes": {...}, "merc_txtfiles": [...] } },
  "combo": "INFERNAL_DEFAULT",
  "max_override": { "player_hp": 0, "player_mp": 0, "merc_hp": 0 }
}
```