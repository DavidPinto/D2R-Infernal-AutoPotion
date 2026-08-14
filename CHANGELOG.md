# Changelog

All notable changes to the D2R Infernal Auto Potion tool.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.2.0] - 2026-08-14

Grade-aware potion use and full 4th belt column support.

### Added

- **Grade-aware potion selection** (`d2r/models.py`): each belt column now knows
  the exact potion it will drink next (txtFileNo + kind + grade), read per-slot
  from the belt item table.  The watcher picks the *smallest* grade that fully
  covers the HP/MP deficit and only falls back to the strongest available grade
  when nothing covers it.
- **4th belt column (R)** fully supported.  Belt columns are derived from the
  live belt layout instead of being hard-coded to `Q`/`W`/`E`; the QWER column
  mapping (`X % 4`) and "next-to-drink = lowest X in the column" rule match the
  game's own belt behavior (including how the game shifts potions down).
- **Multi-key bindings** (Keys tab): the `+` button adds another belt column to
  an action (e.g. `heal -> Q + R`); the watcher presses the *right* bound column
  per tick.  Config stores bindings as lists (`config.keys_for`).
- **Out-of-stock guard**: when the belt is readable but the bound columns have
  no usable potion of the needed kind, the watcher skips that action (logs it
  once) instead of blindly pressing a mismatched column.
- Corrected potion `txtFileNo` codes for the Infernal Edition build
  (items shifted +15 vs classic D2R): Healing 602–606, Mana 607–611, Rejuv
  530/531, Utility (Stamina/Antidote/Thawing) 528/529/532.  Inventory & belt
  potion counts are now accurate for this build.

### Changed

- Belt location fix: the belt is read from the client's item table (loc `2`,
  owner = player unit) — the same table as inventory — using the corrected
  codes, so the earlier "belt can't be found" hunt is obsolete.
- Diagnostics tab reports per-column belt contents (key, count, kind, grade)
  for quick verification of the live layout.

### Fixed

- Potion counts mis-reported the belt in this build (codes were wrong, so some
  kinds never matched); belt and inventory now decode correctly.
- Grade tests in the unit suite now use trigger-correct snapshots so the new
  selection rules are exercised deterministically.

## [1.1.0] - 2026-08-14

QOL / automation / UX expansion.  Zero new third-party dependencies (stdlib +
customtkinter only, same as before).

### Added

- **Potion monitoring** (Dashboard tab): live belt + inventory potion counts
  (Healing / Mana / Rejuvenation / Other) read straight from the client's item
  table.  Belt consumption is tracked as it happens.  Pure read-only
  monitoring — the Python tool remains belt-key-press only.
- **Config profiles**: save/load/delete named profiles from the Triggers tab
  (settings persist in `config/config.json`).
- **One-click presets**: `Leveling`, `Boss farming`, `Conservative`,
  `Mana-heavy` (thresholds + cooldowns only; keys are never touched).
- **Persistent event log**: every event is appended to `config/autopotion.log`
  (256 KB, auto-rotated), so history survives restarts.
- **Session stats** (Dashboard tab): potions pressed per action, uptime,
  error count, and last action.
- **Global toggle hotkey**: optional system-wide hotkey (Triggers tab) to
  toggle the watcher on/off without focusing the UI; disabled by default.
- **Tunable poll interval** (Keys tab): 100–500 ms slider to trade CPU for
  responsiveness.
- **Log tab**: Clear log + one-click export of a diagnostics bundle to
  `config/diagnostics.txt`.
- **Unit tests** (`tests/test_core.py`, stdlib `unittest`): config
  presets/profiles, watcher decision logic + cooldowns, log rotation, potion
  classification.  Run with `python -m unittest discover -s tests`.

### Fixed

- Watcher thread could be killed by a UI marshalling failure (`self.after` when
  the Tk mainloop isn't running); all cross-thread callbacks are now guarded so
  a UI hiccup can never stop potions.
- Config accessors raised `KeyError` for unknown names (e.g. an old/corrupt
  config); they now fall back to safe defaults (never trigger / no key spam /
  unbound key).
- Global hotkey registration: `DefWindowProcW` and friends had no ctypes
  prototypes, so 64-bit `LPARAM` values silently overflowed `c_int` (exceptions
  on every WM_NCCREATE); all Win32 prototypes are now declared explicitly.
- Watcher no longer assumes the reader has a `proc` (testable without a live
  game).

### Changed

- Default toggle hotkey is empty (`Disabled`) — the tool stays "safe by
  default"; enable it in the Triggers tab.
- The diagnostics item dump uses batched memory reads (one read per item
  instead of one per field).

## [1.0.0] - 2026-08-13

First publishable release.  Everything the tool needs to work on the target
build is functional.

### Added

- Full desktop UI (CustomTkinter) with tabs: Dashboard, Triggers, Keys,
  Diagnostics, Log.
- Live HP / Mana / Mercenary bars with display-shifted stat reading.
- Player unit + mercenary detection from the client unit hash table.
- Battle Orders-aware HP/MP percentage tracking (running observed max).
- Manual max-HP/MP calibration overrides (Dashboard tab) for gear bonuses the
  `MaxLife` stat under-reports.
- Click-to-bind hotkeys (player + Shift-modified merc actions).
- Diagnostics tab: offset scan + live read sanity check + monster-table dump.
- Single-file PyInstaller build (`main.spec`, `build.bat`) → windowed
  `D2RAutoPotion.exe` (~14 MB, numpy excluded).
- `python main.py --version` and a central `__version__` in `d2r/version.py`.
- `README.md`, `CHANGELOG.md`, `LICENSE`, `.gitignore`.

### Fixed

- `SendInput` silently failing: the `INPUT`/`KEYBDINPUT` ctypes structures were
  the wrong size (`dwExtraInfo` needed `ULONG_PTR`, 8 bytes, not `c_ulong`), so
  every keystroke was rejected by the OS.  The correct 64-bit layout (40-byte
  `INPUT`) is now used and send failures are surfaced in the Log tab.
- Potions never firing: the watcher decision loop referenced config keys that
  didn't exist (`rejuv_at_life` vs `rejuv_potion_at_life`), throwing a KeyError
  every tick before any potion could be sent.
- Watcher thread dying on any exception, freezing the dashboard and stopping
  potions; the loop is now guarded and errors are logged.
- UI updates from the watcher thread: all widget updates are marshalled to the
  main thread (Tkinter is not thread-safe), fixing the frozen dashboard.
- Hotkey binding: plain digits were resolved as raw VK codes (sending mouse
  buttons instead of keyboard keys); digits now map to the keyboard and raw
  VKs use `0xNN`.
- HP/MP max never dropping back to the base stat (the max is now grow-only,
  seeded by the stat) and merc % no longer jumping between the hireling and
  nearby monsters (merc pinned to its stable txtFileNo).
- Game focus: `SetForegroundWindow` from a background process was blocked, so
  keys went nowhere; the window is now focused via `AttachThreadInput`.
- Config path inside a frozen exe: settings now persist next to the exe instead
  of the (wiped) PyInstaller temp directory.
- Default window size enlarged so all trigger sliders are visible, with the
  Triggers tab wrapped in a scrollable frame.

### Changed

- Default belt keys to `Q` / `W` / `E` (remastered-controls belt layout) for
  player actions and Shift + `Q` / `E` for merc actions.
- Mercenary detection accepts the Infernal Edition hireling txtFileNo (`271`)
  alongside the standard Guard (`338`).
