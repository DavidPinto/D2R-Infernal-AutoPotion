# agents.md — D2R Infernal Auto Potion

Agentic-AI working notes. Keep this file short and current: update the *Goals* and
*Build state* sections as the project moves. This is the contract for how work is done here.

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

- **v1.2.0 Iteration 3 (grade-aware + 4th belt column) — landing now**:
  belt columns read per-slot from the item table (`loc==2`, owner=player; column
  = `X % 4`, next-to-drink = lowest `X`); potion txtFileNo codes corrected for
  this Infernal build (+15 shift: heal 602–606, mana 607–611, rejuv 530/531,
  utility 528/529/532); grade-aware `choose_belt_column` (smallest covering
  grade, else strongest) + out-of-stock skip; multi-key bindings (Keys tab `+`).
  Remaining: run suite + compileall, commit Iteration 3, bump is already 1.2.0,
  CHANGELOG/README updated, final release commit.
- **Done**: v1.0.0 baseline, v1.1.0 potion monitoring / profiles / presets / event log /
  session stats / global hotkey (landed 2026-08-14).
- **v1.2.0 iterations already landed**: Iteration 1 (user-customizable global
  hotkey, presets moved to top of Triggers, persistent profile strip),
  Iteration 2 (UI + mechanics for the 4th column and grade-aware selection).

## Build state

- Version `1.2.0`. Test suite: 40 tests green. Belt + inventory + player + merc
  live-verified against pid 20048 (Sylus, Warlock 20) — belt decodes
  Q={Thawing, Light Mana}, R={Stamina, Antidote}, W/E empty; inventory =
  Light/Mana Mana ×2 + Rejuv ×3. Grade-aware next-to-drink correct (Q's next is
  Thawing → never pressed for mana).
