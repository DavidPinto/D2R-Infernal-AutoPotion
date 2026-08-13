# Changelog

All notable changes to the D2R Infernal Auto Potion tool.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
