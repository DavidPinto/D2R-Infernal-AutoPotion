# agents.md — D2R Infernal Auto Potion

Agentic-AI working notes. Keep this file short and current: update the *Goals* and
*Build state* sections as the project moves. This is the contract for how work is done here.

## Workspace / permissions

- **Allowed to read/write** (no permission needed): the current working directory
  `Documents\D2R Auto Potion Go` (including the project repo), the Windows temp
  folder (`C:\Users\david\AppData\Local\Temp\opencode`), and the game folder
  `D:\Games\Diablo II Resurrected Infernal Edition` when needed.
- **Everything else** (any other folder, file, or memory region, plus writing
  game memory) requires explicit permission for THAT task.  Permission for one
  task does not carry over to another (e.g. reading folder X for Y does not
  allow reading folder X for Z or writing there).  Never hammer the slower /
  smaller storage devices without asking.
- **Read-only game-memory probes** of the running D2R process (the tool's own
  `GameReader`, `diagnose()`, belt/inventory scans) are part of normal app
  operation and are always allowed.  NEVER send keys or enable the watcher
  during dev.
- **Cleanup** (temp probers, deprecated hunts, dead code) is deferred to the
  feature-complete version of the app - do not delete anything yet.

## Project

Python belt-potion automation for Diablo II Resurrected (Infernal Edition). Watches
HP/Mana/Merc in game memory, presses belt keys via `SendInput`. **stdlib + customtkinter
only** — no new third-party deps without asking. Ported from
[Hefero/D2R-AutoPotion-Go](https://github.com/Hefero/D2R-AutoPotion-Go).

## Commands

```pwsh
python main.py               # run the UI
python main.py --version
python -m unittest discover -s tests   # test suite (stdlib unittest, no game needed)
python -m compileall -q main.py d2r ui tests
git add -A && git commit -m "..."      # commit after EVERY completed iteration
```

## Conventions

- No code comments unless they explain a non-obvious "why" (offsets, ctypes quirks, engine
  behavior). Keep them short.
- Version lives only in `d2r/version.py`. Bump + CHANGELOG.md + README.md on release.
- Config accessors must fall back to safe defaults; nothing may raise a KeyError on bad data.
- Cross-thread UI work MUST go through `widget.after(0, ...)` and be guarded; a UI hiccup
  must never kill the watcher thread.
- Win32 calls via ctypes need explicit `argtypes`/`restype` (64-bit LPARAM truncation bug).
- Watcher decision logic is pure — unit-test it with a fake reader/sender, never SendInput.
- Persisted config stores profiles; built-in presets are code constants, not disk.

## Best practices for agents

- **Verify live when safe**: the game is often running. Read-only probes (`GameReader`,
  `diagnose()`, belt/merc reads) are safe. NEVER send keys or enable the watcher during dev.
- **Probe before guessing offsets** (belt columns, merc fields). Write a throwaway script
  under `%TEMP%\opencode` if needed. Confirm txtFileNo/item struct fields against the live game.
- **One iteration = one commit.** Make a change, add/adjust tests, run the suite, commit.
- **Test the pure logic**, not the OS. UI builds are smoke-tested headless (construct +
  `after`-destroy), never driven.
- Preserve behavior/format of the existing tool; evolve, don't rewrite without asking.

## Goals / tasks

- **v1.3.0 Iteration 4 (user calibration) — in progress**:
  end users can define a named "game version / mods" combo that teaches the app
  the potion txtFileNo codes (and optional merc hireling txtFileNo) their build
  uses, instead of relying on the built-in Infernal table.  New Calibrate tab:
  guided instructions, potion kind+grade rows, belt/inventory code scanner
  (place a known potion in a belt corner, scan, enter its txt), combos stored in
  config, live apply (reader re-armed with the combo's codes), merc txtFileNo
  field, Diagnostics reports the active combo's codes.
- **Done**: v1.0.0 baseline, v1.1.0 potion monitoring / profiles / presets / event log /
  session stats / global hotkey (landed 2026-08-14).
- **Done (v1.2.0)**: Iteration 1 (user-customizable global hotkey, presets at
  top of Triggers, persistent profile strip), Iteration 2 (4th column + grade
  mechanics), Iteration 3 (grade-aware selection, corrected Infernal codes
  +15, multi-key bindings, out-of-stock guard) — all landed 2026-08-14.
- **Confirmed**: player/merc unit offsets match the Go reference build exactly
  (same `unit-hash-v3` signature, unit struct + stat offsets, `<<8` stat
  shift); only the item txtFileNo codes moved (+15).  Calibrate tab covers
  codes + merc id; if a future build breaks player/merc offsets the Diagnostics
  offset scan pinpoints which signature failed.

## Build state

- Version `1.3.0`. Test suite: 45 tests green (PotionCodes/combos coverage
  added).  Belt + inventory + player + merc live-verified against pid 20048
  (Sylus, Warlock 20) — belt decodes Q={Thawing, Light Mana}, R={Stamina,
  Antidote}, W/E empty; inventory = Light/Mana Mana ×2 + Rejuv ×3.
