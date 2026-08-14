# D2R Infernal Auto Potion

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Automatic belt-potion use for **Diablo II: Resurrected — Infernal Edition**
(build `21854151`, in-game `3.0.91636 PROD-RELEASE`), written in **Python**.

A clean, from-scratch port of the original Go reference tool
([Hefero/D2R-AutoPotion-Go](https://github.com/Hefero/D2R-AutoPotion-Go),
kept with credit).  It watches your HP / Mana / Mercenary in game memory and
presses the correct belt keys for you.

> **Version:** `1.1.0` — see [CHANGELOG.md](CHANGELOG.md).
> **Game builds:** tested on Infernal Edition `3.0.91636`.  See
> [Limitations](#limitations) below.

## Highlights

- **No AutoHotkey.** Key presses go through the native Win32 `SendInput` API
  (`d2r/keys.py`).  The only required third-party package is `customtkinter`
  for the UI (`numpy` is optional — there's a pure-stdlib fallback).
- **Patch-surviving offsets.** Memory locations are found by *byte-pattern
  (signature) scanning* the running `D2R.exe`, ported from the Go tool — no
  hardcoded addresses.  If a patch changes a signature, only `d2r/offsets.py`
  needs a new pattern.
- **Modern UI.** Dark CustomTkinter interface with live HP / Mana / Mercenary
  bars, threshold + cooldown sliders, click-to-bind keys, a manual max-HP
  calibrator, and a **Diagnostics** tab that reads the live game state so you
  can verify (and we can fix) the offsets for a specific build.
- **Potion monitoring.** The Dashboard shows live belt + inventory potion counts
  (Healing / Mana / Rejuvenation / Other) read from the client's item table, so
  you can see what's left without tabbing in.
- **Profiles & presets.** Save/load named profiles, or apply one-click presets
  (Leveling / Boss farming / Conservative / Mana-heavy) from the *Triggers*
  tab.
- **Persistent log & session stats.** Every event is appended to
  `config/autopotion.log` (auto-rotated, survives restarts); the Dashboard
  shows per-action potion counts, uptime, and errors for the current session.
- **Optional global hotkey.** A system-wide toggle (Triggers tab) arms/disarms
  the watcher from anywhere — even while the game is focused.  Disabled by
  default.
- **Safe by default.** Pauses while inventory / stash / vendor / menus are open,
  never presses keys outside a live game, tracks Battle Orders when computing
  HP/MP percentages, and defaults to **disarmed** — you arm it deliberately.

## Requirements

- Windows 10/11
- **Diablo II: Resurrected** (Infernal Edition `3.0.91636`) running
- Python 3.9+ (developed on 3.13)

```bash
pip install -r requirements.txt
```

## Run

```bash
python main.py
```

1. Start D2R and enter a character (the memory scan needs a live game).
2. The status pill turns **green (Connected)** once `D2R.exe` is found.
3. Tune thresholds on the *Triggers* tab (optional), keys on the *Keys* tab.
4. Click **DISABLED** (top-right) to arm.  The button turns green (**ARMED**).
5. Watch the bars and the log.  A chime plays on each potion use.

`python main.py --version` prints the version and exits.

### Standalone .exe

A ready-to-run Windows executable can be built with PyInstaller
(no Python install needed on the target machine):

```bash
pip install pyinstaller
python -m PyInstaller main.spec --noconfirm
# -> dist/D2RAutoPotion.exe   (single file, no console window)
```

Or just double-click `build.bat`.  The spec bundles customtkinter's theme data
and excludes `numpy` to keep the exe ~14 MB.  The windowed app stores its
settings in `config/config.json` *next to the exe*.

## Key bindings (default)

| Action             | Key | Modifier |
|--------------------|-----|----------|
| Health potion      | `Q` | —        |
| Mana potion        | `W` | —        |
| Rejuvenation       | `E` | —        |
| Merc health potion | `Q` | Shift    |
| Merc rejuv potion  | `E` | Shift    |

These match the game's **remastered-controls belt layout (QWER)**.  The tool
must send exactly the keys your belt is bound to in D2R — rebind on the *Keys*
tab if you use a different profile.  Merc actions add Shift (D2R's feed-merc
binding).  Rebind any key by clicking its button and pressing the new key.

## Triggers (defaults)

| Action               | Threshold            | Cooldown |
|----------------------|----------------------|----------|
| Health potion        | HP ≤ 80%             | 4 s      |
| Mana potion          | MP ≤ 60%             | 5 s      |
| Rejuvenation         | HP ≤ 40% **or** MP < 40% | 2 s  |
| Merc health potion   | Merc HP ≤ 60%        | 6 s      |
| Merc rejuv potion    | Merc HP ≤ 20%        | 2 s      |

All adjustable in the UI (*Triggers* tab).  Each action has a cooldown so it
can't key-spam.

### Manual max-HP calibration

The game's `MaxLife` stat reports the **base** value — item/skill bonuses (and
Battle Orders) aren't always included.  The tool tracks the *running observed
max* (the Go tool does the same), which latches the true value once you're at
full HP.  If you want it correct immediately, use the **Manual max (0 = auto)**
fields on the *Dashboard* tab to enter your real geared HP / MP / Merc HP; the
percentages (and therefore potion thresholds) are then computed against those
values.  The overrides persist in `config/config.json`.

## How it works

`GameReader` (`d2r/reader.py`) walks the game's **client-side unit hash table**
— the same approach as the original Go tool and the proven one for D2R 3.x:

- **Unit table** is located by signature (`unit-hash-v3`), re-verified
  structurally, and read relative to the `D2R.exe` module base.
- The **player unit** is found in the table's player sub-table; the
  **mercenary** is the hireling in the monster sub-table.  We match the merc by
  its `txtFileNo` (`271` for the Infernal Edition hireling, `338` for the
  standard Guard) and fall back to the nearest living unit only as a last
  resort, so the reading never jumps between the merc and nearby monsters.
- **HP / MaxHP / Mana / MaxMana** are read from the unit stat list.  Life/Mana
  are stored bit-shifted, so they're `>> 8`'d back to display values.
- **Open-menu state** is read from the UI global, so the tool pauses while a
  blocking panel is open (inventory, stash, vendor, chat, …).
- **Infernal Edition / Warlock** is supported: the Warlock class id (`7`) is
  read from the player unit's txtFileNo field (`+0x04`).

The decision loop (`d2r/watcher.py`) is a faithful port of the Go
`lifewatcher`:

```
HP% <= rejuv_at_life  OR  MP% < rejuv_at_mana  → rejuv
elif HP% <= heal_at                             → health potion
elif MP% <= mana_at                             → mana potion
if merc alive:
    merc HP% <= merc_rejuv_at                   → Shift + rejuv
    elif merc HP% <= merc_heal_at               → Shift + heal
```

Key presses are injected with `SendInput` from a background watcher thread;
before each press the tool focuses the game window (via `AttachThreadInput` +
`SetForegroundWindow`) so the key lands in the game and not the tool.

## Verifying / fixing offsets for a new build

If an update changes `D2R.exe` so a signature no longer matches, the tool shows
**"Offsets unresolved"** (or the player read looks wrong).  Open the
**Diagnostics** tab and click *Run offset scan & read test*:

- It lists every signature, which one resolved, and a read-sanity check
  (`plausible: YES/NO`) for the live player + mercenary + open menus.
- Paste that output when reporting a break; the fix is usually a one-line new
  pattern in `d2r/offsets.py::PATTERNS`.

## Limitations

- **Version-bound signatures.** The byte patterns were verified against
  Infernal Edition build `21854151` (`3.0.91636`).  A different client build
  may need updated patterns in `d2r/offsets.py`.
- **Infernal Edition focus.** The Warlock class and the `271` merc txtFileNo
  are Infernal Edition specifics; on vanilla D2R the merc id `338` is used
  (both are handled automatically).
- **Merc detection.** Only the currently hired merc type was verified live.
  If a different merc shows as "no merc", the txtFileNo set in
  `d2r/reader.py::MERC_TXTFILES` may need an extra entry (the Diagnostics tab
  lists every monster txtFileNo to make this easy).
- **Admin/elevation.** If D2R runs as Administrator while the tool does not,
  Windows (UIPI) silently blocks `SendInput` — the Log tab will show
  `Key send FAILED`.  Run the tool elevated too in that case.
- **Single-player / offline QoL.** Online play is subject to Blizzard's terms
  of service.  Use at your own risk.
- **Window focus.** The tool briefly brings the game window to the foreground
  when it uses a potion (`auto_focus_game` can be disabled in `config.json`).

## Project layout

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
  watcher.py             auto-potion decision loop + session stats
  config.py              persisted settings, profiles, presets
  log.py                 persistent auto-rotating event log
  hotkey.py              global toggle hotkey (RegisterHotKey)
ui/
  app.py                 CustomTkinter main window
  widgets.py             reusable themed widgets
tests/
  test_core.py           stdlib unittest suite (no live game needed)
```

Run the tests with `python -m unittest discover -s tests`.

## Disclaimer

Single-player quality-of-life tool.  Use at your own risk; Blizzard's terms of
service apply to online play.
