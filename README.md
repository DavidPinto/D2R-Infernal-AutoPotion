# D2R Infernal Auto Potion

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Automatic belt-potion use for **Diablo II: Resurrected — Infernal Edition**
(build `21854151`, in-game `3.0.91636 PROD-RELEASE`), written in **Python**.

A clean, from-scratch port of the original Go reference tool
([Hefero/D2R-AutoPotion-Go](https://github.com/Hefero/D2R-AutoPotion-Go),
kept with credit). It watches your HP / Mana / Mercenary in game memory and
presses the correct belt keys for you.

> **Version:** `1.9.3-beta` — see [CHANGELOG.md](CHANGELOG.md).
> **Game builds:** tested on Infernal Edition `3.0.91636`. See
> [Limitations](#limitations) below.

---

## What the App Does (Current Version)

**The app automatically drinks potions from your belt** by pressing Q/W/E/R keys when your HP or Mana drops below configured thresholds. It reads your belt slots directly from game memory to know exactly which potion is in each slot, so there's no manual key binding per potion type — the app simply presses the belt key (Q/W/E/R) that currently holds the correct potion.

### Core Features (Working)

- **Auto-potion drinking** — Monitors HP/Mana/Merc HP and presses Q/W/E/R when thresholds are crossed
- **Grade-aware drinking** — Reads the exact potion in each belt slot; drinks the *smallest grade* that covers the deficit (won't burn a Full Rejuv when a Minor would do)
- **Smart tier (default)** — Considers the whole managed belt: takes Rejuv when both HP/MP critical; uses smallest sufficient heal/mana grade; falls back to Rejuv when no specific potion covers the deficit
- **Desperation Mode** — When HP is critical (at/below Rejuv threshold), can drink through potions above a Rejuv to reach it (respects empty slots, may consume multiple potions)
- **Grade-aware cooldowns** — Respects potion duration; same/higher grade can be redrunk at half duration, weaker waits full duration × margin
- **Mercenary support** — Feeds merc potions using belt key + modifier (Shift by default)
- **Live Dashboard** — Real-time HP/Mana/Merc bars, belt + inventory potion counts, per-action potion log
- **Calibration tab** — Teach the app your build's potion codes by putting a known potion in all 4 belt corners
- **Profiles & Presets** — Save/load named profiles; one-click presets (Leveling / Boss farming / Conservative / Mana-heavy)
- **Persistent log & stats** — Every potion use logged to `config/autopotion.log`; session stats on Dashboard
- **Global hotkey** — System-wide enable/disable toggle (click-to-capture)
- **Managed belt columns** — Checkbox per column (Q/W/E/R) to control which columns the app manages
- **Safe by default** — Pauses when inventory/stash/vendor/menus open; never presses keys outside live game; defaults to disabled

---

## How It Works (Brief)

1. **Reads belt slots** — Scans game memory for items in belt slots (0-15, 4 columns × up to 4 rows)
2. **Identifies potions** — Reads `txtFileNo` from each slot, maps to Heal/Mana/Rejuv/Other via calibration
3. **Tracks row 0 only** — Only the bottom row (slots 0-3) is drinkable via key press; upper rows are ignored for drinking
5. **Computes deficits** — HP deficit = maxHP - currentHP; Mana deficit = maxMana - currentMana
5. **Picks column** — Among managed columns with a usable potion in row 0, picks smallest grade that covers the deficit
6. **Presses key** — Sends Q/W/E/R via `SendInput` (Win32), focuses game window first

---

## Requirements

- Windows 10/11
- **Diablo II: Resurrected** (Infernal Edition `3.0.91636`) running
- Python 3.9+ (developed on 3.13)

```bash
pip install -r requirements.txt
```

## Quick Start

```bash
python main.py
```

1. Start D2R and enter a character
2. Status pill turns **green (Connected)** once `D2R.exe` is found
3. Tune thresholds on the *Triggers* tab (optional), keys on the *Keys* tab
4. Click **DISABLED** → **ENABLED** (green)
5. Watch the bars and the log. A chime plays on each potion use

---

## Key Concepts

### Managed Belt Columns
The *Keys* tab has a checkbox per column (Q/W/E/R). Uncheck to exclude a column — the app will never drink from or refill that column. All four are managed by default.

### Belt Rows & Drinking
- **Only row 0 (slots 0-3) is drinkable** — pressing Q/W/E/R drinks the potion in slot 0, 4, 8, 12 respectively
- Upper rows (1-3) are **not directly drinkable** — they only become drinkable after the row above is consumed and potions drop down
- The app **only counts row 0 potions** as available for drinking

### Smart Tier (Default On)
The "Smart" tier evaluates the entire managed belt:
- **Both HP & MP critical** → Rejuv
- **Only HP low** → Smallest heal grade that covers deficit (else Rejuv)
- **Only MP low** → Smallest mana grade that covers deficit (else Rejuv)
- **Non-critical** → Heal and Mana fire independently

---

## Desperation Mode

When enabled (*Triggers* tab → **Desperation mode**), and HP drops to/below the Rejuv threshold (HP ≤ 25% by default):

1. Looks for a **Rejuv in rows 1-3** (slots 4-15) of any **managed** belt column
2. Verifies **no empty slots** exist between that Rejuv and row 0 (potions drop potion-to-potion)
3. Confirms **row 0 has a potion** (to make the Rejuv drop)
4. Drinks row-0 potion → Rejuv drops → drinks Rejuv (instant heal)

**WASTEFUL** — may drink multiple potions to clear a path to a Rejuv. Respects empty slots (potions don't drop through empty space). Only enable if you accept wasting potions to survive.

**Use case:** You have a Full Rejuvenation in slot 5 (row 1, column W) but your Q/W/E columns have mana/heal potions in row 0. With Desperation mode on, the app will drink the Q/W/E potions so the Rejuv falls down, then drink the Rejuv.

**Limitations:** Only works for Rejuvenation potions. Does not drink through empty slots (the Rejuv won't fall through gaps). May consume many potions per cycle. Disable for normal play.

---

## Best Practices for End Users

### Belt Organization
- **No empty slots between potions in the same column** — Potions only drop when the slot above is consumed; empty slots block the drop
- **Keep same potion family per column** — e.g., Column Q = all Heal, Column W = all Mana, Column E = Rejuv, Column R = spare/utility
- **Fill from bottom up** — Keep row 0 filled; upper rows act as reserves that drop down
- **Avoid mixing families in one column** — The app reads the lowest slot; mixed columns cause wrong potion detection

### Calibration
1. Put ONE known potion (e.g., Minor Mana) in **all 4 belt corners** (slots 0, 4, 8, 12)
2. Select that potion type in the Calibrate tab
4. Click **Scan belt corners** → app reads the code and auto-fills the family
5. Repeat for each potion family you use (Heal, Mana, Rejuv)

### Thresholds (Defaults)
| Action | Trigger |
|--------|---------|
| Health potion | HP ≤ 80% |
| Mana potion | MP ≤ 60% |
| Rejuvenation | HP ≤ 25% **or** MP < 25% |
| Merc Health | Merc HP ≤ 60% |
| Merc Rejuv | Merc HP ≤ 20% |

Adjust on the *Triggers* tab to match your playstyle.

### Desperation Mode
Enable *Triggers → Desperation mode* **only when you accept wasting potions** to reach a Rejuv. The app will drink through row-0 potions to clear a path to a Rejuv in rows 1-3. Respects empty slots (won't drop through gaps). **Disable for normal play.**

### Manual Max HP/MP
The game's `MaxLife` stat excludes gear bonuses. The tool tracks a running observed max, but you can enter your true geared max HP/MP on the Dashboard → Manual Max (0 = auto) for correct percentages immediately.

---

## Calibration (Your Build's Potion Codes)

The Infernal Edition renumbers potion codes by +15 vs classic D2R. If potions show as `other` on the Dashboard:

1. Put ONE known potion (e.g., Minor Mana) in **all 4 belt corners** (slots 0, 4, 8, 12)
2. Select that potion type in the Calibrate tab
3. Click **Scan belt corners** — app reads the corner codes, saves it, and auto-fills the family
3. Repeat for each potion family you use (Heal, Mana, Rejuv)

Calibration is stored in `config/config.json` as a "Calibrated build" profile.

---

## Key Bindings

- **Belt keys**: Q / W / E / R (your in-game belt hotkeys)
- **Merc modifier**: Shift by default (set on *Keys* tab → *Mercenary potion modifier*)
- **Global toggle**: Set a system-wide hotkey on the top bar (click button, press combo; Esc clears)

The app presses Q/W/E/R directly — **no per-potion key binding needed**. Any managed column can serve any potion type.

---

## Verifying / Fixing Offsets for a New Build

If a D2R update breaks the tool (shows "Offsets unresolved"):

1. Open **Diagnostics** tab
2. Click **Run offset scan & read test**
3. Paste the output when reporting — the fix is usually a one-line pattern in `d2r/offsets.py::PATTERNS`

---

## Limitations

- **Version-bound signatures** — Patterns verified on Infernal Edition build `21854151` (`3.0.91636`). Other builds may need updated patterns in `d2r/offsets.py`
- **Infernal Edition focus** — Warlock class (`7`) and merc `271` are Infernal-specific; vanilla D2R uses merc `338` (both auto-detected)
- **Merc detection** — Only the standard hireling verified; other mercs may need txtFileNo added via Diagnostics tab
- **Admin/elevation** — If D2R runs as Admin but tool doesn't, Windows blocks `SendInput` (Log shows `Key send FAILED`); run tool as Admin
- **Smart tier not fully live-verified** — Unit tests pass; equipped-belt/inventory reads verified on dumb tier only; merc path experimental
- **Belt refill placement** — Clicks first empty slot engine picks; only works with inventory open + game foreground
- **Admin/elevation** — Run tool as Admin if D2R runs as Admin
- **Window focus** — Tool briefly focuses game window on potion use (`auto_focus_game` in `config.json`)

---

## Disabled / Not Working / Legacy Features

*These features exist in code but are **not functional in the current UI**:*

- **Belt refill (auto inventory→belt)** — Hidden in UI; config mapping accessors kept (no UI)
- **Belt plan / Layout refill** — 4×4 grid exists in *Keys* tab but refill is disabled; layout stored in config but unused
- **Legacy "plain tier"** — Removed in v1.8.2; `behavior.smart` retained for compat but unused
- **Per-potion key bindings (pre-1.8.0)** — Removed; old config keys (`keys.heal`, etc.) kept for compat but ignored
- **Merc auto-potion** — Experimental; uses same logic but not end-to-end verified
- **Legacy `belt_rows_for`** — Hardcoded table; runtime reads equipped belt txtFileNo instead
- **Legacy potion tables in `models.py`** — Built-in defaults; overridden by Calibrate tab combos

---

## Project Layout

```
main.py                  entry point (+ --version)
requirements.txt         customtkinter (numpy optional)
main.spec / build.bat    PyInstaller onefile build
config/config.json       persisted settings + profiles (auto-created)
d2r/
  version.py             __version__ (single source of truth)
  process.py             process discovery + ReadProcessMemory + pattern scan
  offsets.py             byte-pattern offset resolution (PATCH-SURVIVING)
  reader.py              GameReader: player / merc / menus / potion counts
  models.py              stat/state/npc constants + snapshot types
  keys.py                SendInput key simulation (NO AutoHotkey)
  input.py               mouse + window helpers for the belt refill clicker
  refill.py              pure refill-planning logic (managed columns, fill order)
  watcher.py             auto-potion decision loop + session stats
  config.py              persisted settings, profiles, presets
  log.py                 persistent auto-rotating event log
  hotkey.py              global toggle hotkey (RegisterHotKey)
ui/
  app.py                 CustomTkinter main window (incl. Calibrate tab)
  widgets.py             reusable themed widgets
tests/
  test_core.py           stdlib unittest suite (no live game needed)
```

Run tests: `python -m unittest discover -s tests`

---

## Disclaimer

Single-player quality-of-life tool. Use at your own risk; Blizzard's terms of service apply to online play.