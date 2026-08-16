# D2R Infernal Auto Potion

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Automatic belt-potion use for **Diablo II: Resurrected — Infernal Edition**
(build `21854151`, in-game `3.0.91636 PROD-RELEASE`), written in **Python**.

A clean, from-scratch port of the original Go reference tool
([Hefero/D2R-AutoPotion-Go](https://github.com/Hefero/D2R-AutoPotion-Go),
kept with credit).  It watches your HP / Mana / Mercenary in game memory and
presses the correct belt keys for you.

> **Version:** `1.8.3-beta` — see [CHANGELOG.md](CHANGELOG.md).
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
  bars, threshold sliders + a real potion-values table and safety-margin slider,
  click-to-bind keys, a manual max-HP calibrator, and a **Diagnostics** tab that
  reads the live game state so you can verify (and we can fix) the offsets for a
  specific build.
- **Potion monitoring.** The Dashboard shows live belt + inventory potion counts
  (Healing / Mana / Rejuvenation / Other) read from the client's item table, so
  you can see what's left without tabbing in.
- **Grade-aware potion use.** The watcher reads exactly which potion each belt
  column will drink next and presses the *smallest* grade that covers the HP/MP
  deficit — it won't burn a Full Rejuvenation when a Minor would do.
- **Calibrate for your build.** Potions are identified by base-item `txtFileNo`
  codes, which differ between versions/mods (the Infernal Edition renumbers
  classic D2R by +15).  The **Calibrate** tab reads the codes itself: put a known
  potion in all 4 belt corners, press *Scan belt corners*, and the app learns and
  remembers that potion (and its whole family) for your build — no code edits
  needed.
- **Full QWER belt support.** The app drinks by pressing your belt's own
  hotkeys (Q/W/E/R) and reads each belt slot to see which potion it holds — no
  per-potion key bindings to configure.  It picks the grade-appropriate column
  per tick and skips the action when no managed column holds a usable potion.
- **Profiles & presets.** Save/load named profiles, or apply one-click presets
  (Leveling / Boss farming / Conservative / Mana-heavy) from the *Triggers*
  tab.
- **Persistent log & session stats.** Every event is appended to
  `config/autopotion.log` (auto-rotated, survives restarts); the Dashboard
  shows per-action potion counts, uptime, and errors for the current session.
- **Optional global hotkey.** A system-wide enable/disable toggle, set from a
  single button next to the enable/disable toggle on the top bar.  Click it and
  press a combo (Ctrl/Alt/Shift + a key); Esc clears it.  Works from anywhere —
  even while the game is focused.  Off by default.
- **Managed belt columns.** The *Keys* tab lets you uncheck belt columns the app
  is allowed to touch — unchecked columns are never drunk from or refilled, so
  you keep manual control of them (default: all four Q/W/E/R managed).
- **Automatic belt refill & reordering.** While your inventory panel is open, the
  app moves potions around: empty managed belt slots are refilled from the
  inventory, and a potion sitting in the wrong column is moved to the column
  that wants it.  Each step is two clicks (pick it up, drop it in the slot),
  throttled, and only runs when the game window is the foreground window.
  Click positions are measured once by hovering two potion cells and pressing
  F8 — both the inventory page and the belt panel need a known grid.  No
  resolution-specific constants.
- **Smart potion choice (smart tier).** The watcher decides from the *whole
  managed belt*, not just one column: HP+MP both critical → rejuv; only HP
  low → heal when a heal that fully covers the deficit is on the belt (else
  rejuv); only MP low → the mana equivalent; non-critical → heal and mana fire
  independently.  On by default, off switch on the *Keys* tab.
- **Belt plan (per-slot layout).** The *Keys* tab has a 4×4 belt grid — set each
  slot to Any / HP / Mana / Rejuv.  Smart-tier refill fills an empty slot with
  the layout kind, else restocks the kind that already dominates that column,
  else the family you last drank, else any potion — and moves a potion that
  ended up in the wrong column to the column that wants it.
- **Safe by default.** Pauses while inventory / stash / vendor / menus are open,
  never presses keys outside a live game, tracks Battle Orders when computing
  HP/MP percentages, and defaults to **disabled** — you enable it deliberately.

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
4. Click **DISABLED** (top-right) to enable.  The button turns green (**ENABLED**).
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

## Key bindings

The app uses your belt's own hotkeys — **Q / W / E / R** in D2R's remastered
controls.  It reads each belt slot to see which potion it holds, so there is
**nothing to bind**: any managed column can serve any potion type, and the
watcher picks the grade-appropriate column per tick.

Mercenary potions are given with the belt hotkey **plus a modifier** — D2R's
feed-merc binding, **Shift by default**.  Set it to your in-game feed-merc key
(Shift / Ctrl / Alt) on the *Keys* tab → *Mercenary potion modifier*.

If your belt is bound to different keys in D2R, the app still presses Q/W/E/R —
re-map your in-game belt hotkeys to match (the app has no per-potion bindings).

### Managed belt columns

The *Keys* tab has a checkbox per belt column (Q/W/E/R).  Uncheck a column to
keep the app entirely off it — it will **not** drink from that column and will
**not** refill it, so you keep manual control of potions there.  All columns are
managed by default.

## Belt refill from inventory

The *Keys* tab also has a **Belt refill** section.  When enabled, the app keeps
your belt topped up: while the **inventory panel is open**, if a managed belt
slot is empty, it clicks a matching potion from your inventory into the belt —
restocking the family you last drank first, other families after.  One click per
tick, throttled, and only while the game window is the **foreground** window, so
clicks always land on the game.

Clicking a potion in D2R fills the first empty belt slot the engine chooses, so
the app drives the *potion choice* (it tracks the belt's fill order).  With the
**smart tier** on, that choice follows your **Belt plan**: each empty slot is
filled per your per-slot layout, else restocked to the kind dominating that
column, else the family you last drank, else any potion.

**One-time click calibration.** The app must know where inventory cells are on
screen (varies by resolution/window size).  With your inventory open in-game:

1. Click **Calibrate…** on the *Keys* tab.
2. Hover the mouse over a potion in your inventory and press **F8**.
3. Hover over a *different* potion and press **F8** again.
4. Click **Finish & save**.

The app reads the hovered item's grid cell from memory, pairs it with the cursor
position, and solves the grid (cell size + origin).  **Clear** removes the
mapping.  The *Keys* tab also shows your belt's live size (4×1 to 4×4 slots)
and how many slots are filled/free.

## Triggers (defaults)

| Action               | Threshold            |
|----------------------|----------------------|
| Health potion        | HP ≤ 80%             |
| Mana potion          | MP ≤ 60%             |
| Rejuvenation         | HP ≤ 25% **or** MP < 25% |
| Merc health potion   | Merc HP ≤ 60%        |
| Merc rejuv potion    | Merc HP ≤ 20%        |

| Merc rejuv potion    | Merc HP ≤ 20%        |

All adjustable in the UI (*Triggers* tab), which also has a **Safety margin (%)**

### Desperation mode

When enabled (Triggers tab → **Desperation mode**), and HP drops to or below the
Rejuvenation threshold (HP ≤ 25% by default), the app will:

1. Look for a **rejuvenation potion** in rows 1-3 (slots 4-15) of any **managed**
   belt column.
2. Verify **no empty slots** exist between that rejuv and row 0 (potions only drop
   potion-to-potion in D2R).
2. Confirm **row 0 has a potion** (the one you’ll drink to make the rejuv drop).
3. Press the key for that column to drink the row-0 potion, causing the rejuv to
   drop into row 0.
3. On the next tick (or when HP is still critical), the rejuv is now in row 0
   and will be drunk for the instant heal.

**WASTEFUL** - this mode may drink multiple potions (heal/mana) to clear a path
to a rejuv.  It respects empty slots (potions don’t drop through empty space).
Only enable if you accept wasting potions to survive.

**Use case:** You have a Full Rejuvenation in slot 5 (row 1, column W) but your
Q/W/E columns have mana/heal potions in row 0.  With Desperation mode on, the
app will drink the Q/W/E potions so the rejuv falls down, then drink the rejuv.

**Limitations:** Only works for rejuvenation potions.  Does not drink through
empty slots (the rejuv won’t fall through gaps).  May consume many potions per
cycle.  Disable for normal play.
slider: a same-or-stronger potion may be drunk again once the one in effect is
half consumed, and this margin is how long a *weaker* potion is held back after
the in-effect potion finishes restoring (rejuvenation is instant and ignores it).

### How potions actually work here

Potions restore a class-dependent amount **over time** — they are not instant
except rejuvenation.  The character's class is read from the live game each
snapshot, so restore amounts always match who is playing.  Per-class restore
amounts:

| Heal potion | Duration | Druid/Necro/Sorc/Warlock | Amazon/Assassin/Paladin | Barbarian |
|-------------|----------|--------------------------|-------------------------|-----------|
| Minor       | 7.68 s   | 30                       | 45                      | 60        |
| Light       | 6.40 s   | 60                       | 90                      | 120       |
| Healing     | 6.84 s   | 100                      | 150                     | 200       |
| Greater     | 7.68 s   | 180                      | 270                     | 360       |
| Super       | 10.24 s  | 320                      | 480                     | 640       |

| Mana potion | Duration | Barbarian | Amazon/Assassin/Paladin | Druid/Necro/Sorc/Warlock |
|-------------|----------|-----------|-------------------------|--------------------------|
| Minor       | 5.12 s   | 20        | 30                      | 40                       |
| Light       | 5.12 s   | 40        | 60                      | 80                       |
| Mana        | 5.12 s   | 80        | 120                     | 160                      |
| Greater     | 5.12 s   | 150       | 225                     | 300                      |
| Super       | 5.12 s   | 250       | 375                     | 500                      |

Rejuvenation restores **35%** of max HP+MP instantly (Full Rejuvenation 100%).

### Manual max-HP calibration

The game's `MaxLife` stat reports the **base** value — item/skill bonuses (and
Battle Orders) aren't always included.  The tool tracks the *running observed
max* (the Go tool does the same), which latches the true value once you're at
full HP, and shrinks back to the base when you remove a +max item (so that never
reads as damage).  If you want it correct immediately, use the **Manual max
(0 = auto)** fields on the *Dashboard* tab to enter your real geared HP / MP /
Merc HP; the percentages (and therefore potion thresholds) are then computed
against those values.  The overrides persist in `config/config.json`.

## Calibration (your build's potion codes)

The app identifies potions by their base-item `txtFileNo` code.  These are
**version/mods-specific** — the Infernal Edition renumbered the classic D2R item
table by +15 (`587→602`, `593→608`, `515→530`, …), and other mods renumber
differently.  If your potions show up as `other` on the Dashboard, or you run a
different version, teach the app the correct codes with the **Calibrate** tab —
no code numbers to type:

1. In-game, put ONE potion you can identify — e.g. a **Minor Mana** or **Minor
   Health** potion, available from the start — in ALL 4 corners of your belt.
2. Pick that same potion in the list and click **Scan belt corners**.  The app
   reads the belt slots in memory itself, finds the code that appears in every
   corner, saves it, and auto-fills the rest of that potion's family (Minor →
   Full) from the code gap.
3. Repeat for any other potion you use (rejuvenations, full grades, …).
   Everything you've taught it is listed under **Learned so far**.

Calibration is stored in `config/config.json` as a "Calibrated build" profile
that stays active after a restart.  **Clear calibration** returns to the built-in
Infernal defaults.  Restore amounts are derived from kind+grade, so custom codes
get the same behavior as built-ins (minor 30 → full 100%, rejuv 35%/100%).

**Player / merc offsets do NOT need calibration** — they match the Go reference
build exactly (same `unit-hash-v3` signature and unit struct offsets) and are
located by signature scan.  The only item-specific value besides potions is your
hireling's `txtFileNo` (default `338, 271`): if the Dashboard shows *no merc*
while one is hired, set it on the Calibrate tab (the Diagnostics tab dumps every
monster `txtFileNo` so you can find it).  If player/merc values ever read wrong,
run the Diagnostics offset scan — it reports exactly which signature failed.

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
`lifewatcher`, with grade-aware column selection:

```
HP% <= rejuv_at_life  OR  MP% < rejuv_at_mana  → rejuv
elif HP% <= heal_at                             → health potion
elif MP% <= mana_at                             → mana potion
if merc alive:
    merc HP% <= merc_rejuv_at                   → modifier + rejuv
    elif merc HP% <= merc_heal_at               → modifier + heal
```

(The merc modifier is Shift by default and is configurable on the *Keys* tab.)

With the **smart tier** on (default), the watcher instead calls `plan_consume`
over the whole *managed* belt: it takes rejuv when HP and MP are both in the
rejuv range, drinks a specific heal/mana only when that kind is on a managed
belt slot and fully covers the deficit (smallest sufficient grade), and falls
back to rejuv otherwise.  For each potion the watcher computes the HP/MP deficit,
then across the *managed* belt columns picks the smallest potion grade that covers
it (strongest if none cover); it skips the action entirely when the managed
columns hold no usable potion.  Belt columns are read per-slot from the item
table — column = `X % 4` (`Q`/`W`/`E`/`R`) and next-to-drink is the lowest `X`
in that column, matching how the game shifts potions down the belt.

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
- **Belt refill placement.** Clicking a potion in D2R fills the first empty belt
  slot the engine picks, so the refill drives the potion choice, not an exact
  slot.  It only acts while the inventory panel is open and only clicks when the
  game window is the foreground window.
- **Smart tier not yet live-verified.** Smart consume + layout refill are
  covered by unit tests but the equipped-belt/inventory reads behind them were
  verified on the dumb tier (Iteration A); the merc auto-potion path is
  unchanged and likewise still needs an end-to-end in-game check.
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

Run the tests with `python -m unittest discover -s tests`.

## Disclaimer

Single-player quality-of-life tool.  Use at your own risk; Blizzard's terms of
service apply to online play.
