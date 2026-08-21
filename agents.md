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
  operation and are always allowed.  NEVER send keys, NEVER send mouse clicks,
  and NEVER enable the watcher during dev — keys and clicks (including the
  belt-refill clicker) are runtime-only features.  The refill clicker itself
  refuses to click unless the game window is the foreground window.
- **Cleanup** (temp probers, deprecated hunts, dead code) is allowed now that
  the core app is feature-complete and stable: remove dead code and throwaway
  probes when they are found, keep the notes above current, and never touch
  logic that is runtime-active without a test.

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

- **In progress (planned iterations, probe-first)**:
  - **Enemy-nearby unit scan**: walk the 128-entry unit table chains (`UNIT_OFFSET_NEXT`) — probe walks fine (found 7 units incl. the player), but the live sample had no monsters/NPCs in range; needs a fight to identify the hostile-flag byte(s) (class/corpse/mode/state) before the urgency logic can use it.
  - **Poll-rate**: the watcher loop rate stays `poll_interval_ms` (slider, down to ~30 ms safely); the pre-drink/poison logic works at any rate.  A true two-tier loop (fast vitals / slow full snapshot) is only worth it if sub-30 ms matters — restore durations are seconds.

- **Done (v1.9.5-beta)**: **UI updates & predictive logic toggle**. Expose predictive drinking in UI (checkbox) with non-technical explanation; logic accurately falls back to pure threshold checks when off. Renamed "Desperation Mode" to "Reach Buried Rejuv" to clarify behavior. 131 tests green; compileall + headless UI smoke pass.
- **Done (v1.9.4-beta)**: **granular monitoring (granular monitoring — poison state + drain-slope pre-drink)**.  Poison: unit states = 6×u32 at `statsListEx + 0xAF0` (d2go reference, stable across 3.x; live-verified — `Alignment` state reads, poison bit 0).  `GameReader._read_unit_states()` → snapshot `states`/`poisoned`; poisoned ⇒ HP treated as at the heal line (poison ticks in safe spots too).  Pre-drink: rolling (t, HP, mana) window → per-stat drain slope; draining across the threshold within the 1.0 s lead ⇒ drink now so the potion is already restoring when the bar empties (mana never sits empty mid-cast).  Both route through the normal decision path (cooldowns/waste guard/panic/managed columns all still apply); injectable `_now` clock makes it unit-testable.  **131 tests green**; compileall + headless UI smoke pass; live snapshot validated (in-game, states `[105]`, not poisoned).  The poison bit needs one in-game poison hit to confirm the flip.

- **Done (v1.8.3-beta)**: **menu detection fixed + pause_when_menus_open disabled**. The `ui-v3` signature matched twice; the scan now tests each hit and accepts the one resolving to a readable UI struct. Flag indices appear shifted for this build; detection works but is inaccurate — structural UI scan deferred. User config `pause_when_menus_open = false` so drinking works with inventory/stash open. **118 tests green**; compileall + headless UI smoke pass.
- **Done (v1.8.2-beta)**: unified decision logic — **no smart/plain tiers**
  (`_plain_tick` removed; `_tick` runs only `plan_consume` regardless of the
  vestigial `behavior.smart` flag); **best-effort fallback** so a critical stat
  never sits at 0% — the reader now records unclassified belt potions (kind
  None), and when HP/MP is at the rejuv line, no recognised potion of the wanted
  kind is on the managed belt, but unrecognised potions ARE present, the watcher
  presses the column holding an unrecognised potion (preferring the stat's own
  standard column heal→Q / mana→W / rejuv→E) and warns once to use the Calibrate
  tab for exact drinking (gated to critical-only so routine dips don't waste
  potions); belt-hotkey UI redesigned to a **single horizontal row** of
  `[checkbox] [single-char key input]` pairs (4 across, nothing more — type a key
  + Enter to rebind, blank/Esc/Delete restores the default; the old
  button-capture flow is gone).  **118 tests green**; compileall + headless UI
  smoke pass; CHANGELOG/README/agents.md updated.
- **Done (v1.8.1-beta)**: mana now drinks at near-0% (plain tier falls back to a
  mana potion when rejuv is unavailable; smart tier single-critical prefers a
  covering potion → rejuv → any potion of the wanted kind, never wasted); belt
  hotkey UI redesigned to a clean `[tickbox] [bind-key button]` row (`Column ->
  Key`); **belt refill & belt-plan UI hidden** — D2R moves items only with the
  mouse and the click-place refill could not be made reliable yet, so both
  sections are deferred (logic kept, no UI) while the app focuses on solid
  drinking for the eventual 2.0; "arm/disarm" → "enable/disable" wording
  everywhere (UI button ENABLED/DISABLED, help text, logs, docs); global hotkey
  is a single click-to-capture button next to the enable toggle (Esc/Delete
  clears; status active/failed); per-column belt hotkeys editable next to the
  managed checkboxes (`config.belt_keys` + `belt_key()`/`set_belt_key()`/
  `belt_keys_map()`; watcher `_use` and `KeySender._fallback_key` honour the
  rebinds); `plan_consume` rework — a critical stat drinks ANY present potion of
  the wanted kind (under-strength included), both-critical with no rejuv drinks
  heal+mana present, `missing` only reports kinds genuinely absent; `GameReader.belt_items()`
  added; Keys-tab titles/descriptions rewritten; `HotkeyListener` unique
  per-instance window class (no `ERROR_CLASS_ALREADY_EXISTS`).  Version
  **1.8.1-beta** (small increment + beta suffix — deliberately not 1.9.0/2.0).
  **110 tests green**; compileall + headless UI smoke pass; CHANGELOG/README/agents.md
  updated.
- **Deferred (known)**: the smart tier's belt/inventory reads, the two-click
  refill/move, and the merc auto-potion path still need a live in-game
  end-to-end check (unit-tested only; runtime clicks/keypresses are never
  exercised during dev).
- **Done (v1.8.0)**: Keys tab reworked — per-potion key bindings removed
  entirely (the app drinks via the belt's own Q/W/E/R hotkeys and reads each
  slot to see which potion it holds; the managed-column checkboxes ARE the
  hotkey set, any managed column may serve any action), feed-to-merc modifier
  is user-pickable (Shift default; `behavior["merc_modifier"]` →
  `config.merc_modifier()`, `KeySender.press` reads it, `press_key(vk,
  modifier=...)` replaces hard-coded `with_shift`), Belt mix (ratio) removed
  from the UI and from the smart refill decision (`desired_kind_for_slot` is
  now layout → column-family → None; `plan_layout_refill` falls back to
  last-drunk kind → any; `plan_consume`/`_allowed_for` lost the `bound` param,
  watcher `_pick` lost `keys_for`, config `key()`/`keys_for()` removed,
  `FALLBACK_KEYS` in keys.py covers the unreadable-belt case), all Keys-tab
  texts rewritten.  Ratio config field kept for back-compat (unused).
  95 tests green; compileall + headless UI smoke pass; KeySender modifier +
  fallback sanity-verified.
- **Done (v1.7.0)**: grade-aware stacking (same-or-higher grade drinkable once
  the in-effect potion is half consumed; weaker held for duration×margin; rejuv
  fixed 1.0s gate; unknown grades conservative), Triggers tab simplified (potion
  table + class picker removed — class comes from the live character; Safety
  margin slider kept with a reworded hint), rejuv defaults lowered to 25/25,
  merc true max read from the stats-list item block (slex+0xA8/count 0xB0; live:
  base 189 → merged 199) and the bogus UTF-16 name read removed (hireling names
  are a UI resource string, not in the unit; labelled by type), player max
  shrink rule (`_track_max`), 95 tests green.  Also from v1.6.0: real potion
  model (class-dependent restore-over-duration, rejuv instant, no weak-on-strong
  stacking via duration×margin gating, class auto-detect) and the merc readout
  fix (fraction-of-max Life at the exact 0x8000 full boundary, living-over-corpse
  hireling pick, act-based type, unit-change reset).
- **v1.4.0 Iteration 5 (managed columns + belt refill) — Iteration A landed
  (v1.4.0), Iteration B landed (v1.5.0)**.  Iteration A: the app can manage all 4
  belt columns (Q/W/E/R checkboxes on the Keys tab; unmanaged columns are never
  drunk from or refilled) and a **dumb-tier belt refill**: while the inventory
  panel is open, if a managed belt slot is empty, click a matching inventory
  potion into it (restocks the family last drunk first).  One click per tick,
  throttled (default 400ms), only while the game window is the foreground window
  (`d2r/input.py` SetCursorPos + SendInput click; clicks never land while another
  window has focus).  Click positions are calibrated in-game by hovering two
  inventory potions and pressing F8 (HotkeyListener) — the hovered item's grid
  cell (Hover struct + item path X/Y) is paired with the cursor position and
  `solve_grid_mapping` least-squares solves cell size + client-relative origin
  (persisted in config refill section).  Belt rows are read from the equipped
  belt item's txtFileNo (`BELT_ROWS_BY_TXTFILE`: classic + Infernal +15 ids;
  4x1..4x4) with a fallback to the tallest occupied row.  **Iteration B (built)**:
  smart tier — `plan_consume` decides from the whole managed belt (both critical
  → rejuv; HP-only → heal if a covering heal is on a managed slot else rejuv;
  MP-only → the mana equivalent; non-critical → heal/mana fire independently),
  a per-slot 4×4 Belt plan grid + HP/Mana/Rejuv ratio on the Keys tab (scrollable),
  and layout/ratio refill (`desired_kind_for_slot`: user layout → dominant kind
  in column → biggest ratio shortfall → any; `plan_layout_refill`: lowest grade
  of desired kind → same-kind fallback → any).  Config stores `layout`/`ratio`/
  `behavior.smart`; smart defaults True.  **Deferred known issue**: the merc
  auto-potion path is unchanged from v1.4.0 and the smart tier's belt/inventory
  reads still need a live in-game end-to-end verification (unit-tested only).
- **Done**: v1.0.0 baseline, v1.1.0 potion monitoring / profiles / presets / event log /
  session stats / global hotkey (landed 2026-08-14).
- **Done (v1.2.0)**: Iteration 1 (user-customizable global hotkey, presets at
  top of Triggers, persistent profile strip), Iteration 2 (4th column + grade
  mechanics), Iteration 3 (grade-aware selection, corrected Infernal codes
  +15, multi-key bindings, out-of-stock guard) — all landed 2026-08-14.
- **Done (v1.3.0)**: Iteration 4 Calibrate wizard (user teaches potion codes
  via belt-corner scan, no code typing) — landed 2026-08-14 (commit `2f89079`).
- **Confirmed**: player/merc unit offsets match the Go reference build exactly
  (same `unit-hash-v3` signature, unit struct + stat offsets, `<<8` stat
  shift); only the item txtFileNo codes moved (+15).  Calibrate tab covers
  codes + merc id; if a future build breaks player/merc offsets the Diagnostics
  offset scan pinpoints which signature failed.
- **Belt facts confirmed live**: equipped belt keeps its classic txtFileNo
  (Light Belt = 345 → 2 rows, NOT +15); inventory potions expose grid X/Y via
  the item path (`ITEM_PATH_OFFSET_X=0x10`, `ITEM_PATH_OFFSET_Y=0x14`);
  Hover struct reads at base+offsets.Hover (u16 flag, u32 type, u32 unit id);
  client rect 2560x1440; `ITEM_LOC_INVENTORY` is 0 (loc==0 IS the inventory).

## Build state

- Version `1.9.4-beta` — **granular monitoring: poison state + drain-slope pre-drink**.  Poison: unit states bitfield read from `statsListEx + 0xAF0` (6 x u32, bit b of word i = state id; poison = state 2) via `GameReader._read_unit_states()` → `PlayerSnapshot.states`/`poisoned`; poisoned puts HP on the heal line so the app drinks before poison (which keeps ticking in town / after fights) hurts.  Pre-drink: `PotionWatcher` keeps a rolling (t, HP, mana) window (`_vitals`) and a per-stat drain slope (`_predict_drop`); a stat that would cross its threshold within the 1.0 s lead (`_PRE_DRINK_LEAD`) is treated as already there, so the restore-over-duration potion is already delivering when the bar empties.  Both flow through the normal `plan_consume` path (cooldowns, waste guard, panic, managed columns, out-of-stock all still apply) and stop when the drain slows / state clears.  `_now` is injectable (deterministic tests).  Test suite: **131 tests green** (6 new); compileall + headless UI smoke pass; live snapshot validated against the running game (in-game, states `[105]`, not poisoned).  Remaining: one in-game poison hit to confirm the bit flips; enemy-nearby scan still needs a fight sample.
- Version `1.9.3-beta` — **mana waste guard + deferred-cleanup pass**.  Fixed:
  the watcher re-drank a same/higher-grade potion once half its duration had
  passed even when the potion still in effect had enough *remaining* restore to
  cover the deficit (e.g. Super mana re-drunk at 3/5.12 s with ~155 mana left
  to deliver) — now `_in_effect_covers` skips the second drink unless the
  in-effect potion alone cannot finish the job (rejuv never gated; per-action
  `_last_potion_txt` recorded from the drunk column).  Cleanup per the relaxed
  policy: reader.py shadowed `open_menus`/`_get_ui_base` copies removed,
  ui/app.py unreachable refill-calibration methods/state/branches + unused
  imports removed (menu-calibration wizard, `_calib_status`, `_clear_calibration`
  kept — live), process.py gained explicit argtypes/restype for the Toolhelp +
  user32 window-helper family.  Test suite: **127 tests green** (3 new waste-guard
  tests + the old same-grade-repeat test now asserts the skip); compileall +
  headless UI smoke pass.
- Version `1.9.2-beta` — **full-app code-review hardening**.  Fixed: belt-key rebind crash (`from .hotkey` → non-existent `ui.hotkey`; the d2r.hotkey import was already module-scoped), `d2r/input.py` typed `GetClientRect` as an 8-byte POINT instead of the 16-byte RECT it writes (heap overflow + `window_client_rect` always (0,0) — the root cause of the deferred refill clicker's unreliability; live-verified sane rects now), watcher "never crash" guard NameError on corrupt `poll_interval_ms` (interval/snapshot bound before the loop), `d2r/models.py` rejuv `restore_override` dict indexed by grade when the class group was missing (now falls back to the % table; heal/mana overrides applied per group too), `d2r/process.py` duplicate module-snapshot call (handle leak), `XINPUT_GAMEPAD_B/X/Y` corrected to 0x2000/0x4000/0x8000, gamepad toggle applies live (KeySender reads `config.use_gamepad` every press, no connect-time cache), elevation prompt reads the saved config via `AppConfig.load()`.  Left as deferred cleanup (per policy): shadowed `open_menus`/`_get_ui_base` copies in reader.py (behavior = intended calibrated-only), unreachable `_calib_btn` references.  Test suite: **124 tests green**; compileall + headless UI smoke pass.
- Version `1.9.0-beta` — **real gamepad input via Microsoft's synthetic gamepad API** (Keys tab).  The app creates a real Xbox controller through `xboxgipsynthetic.dll` (ships with Windows 10 22H2+ cumulative updates — no drivers/installs) and taps the D-pad: Q=Left, W=Up, E=Down, R=Right.  Probe-verified end to end: CreateController(0)/Connect register in XInputGetState and a 14-byte GIP report (report type 0; DPAD_UP=0x01 at payload[1]) delivers `buttons=0x0001`.  Hard requirements: process **elevated** (E_ACCESSDENIED otherwise; app offers a UAC relaunch at startup when gamepad mode is on), STA COM on the calling thread (KeySender connects lazily from the watcher thread), xboxgipsvc auto-starts when elevated (works with the service stopped).  `d2r/keys.py`: `XboxSyntheticGamepad` (ctypes, stdlib only) + `_gip_payload()` + legacy `press_gamepad_button`; `KeySender._press_gamepad` uses a per-instance controller; the old keyboard-VK fallback (`_gamepad_button_to_vk`) is **gone**.  UI: gamepad section moved below the QWER row, duplicate poll-interval slider removed, controller-index field removed (synthetic takes the first free slot).  **Unverified**: whether D2R accepts the synthetic controller's D-pad in-game while the user's real controller occupies slot 0 — needs a live test (run app elevated, gamepad mode on, watch if the D-pad drinks).  Test suite: **121 tests green**; compileall + headless UI smoke pass.
- Version `1.8.8-beta` — **configurable override tables for all hardcoded game data**. Added `overrides` dict in config + accessors for class heal/mana groups, rejuv %, belt rows, per-potion restore/duration overrides. `PotionCodes` accepts optional overrides; `PotionEntry` supports `restore_override` + `duration_override`. Config `overrides` dict persisted, injected into `PotionCodes` via `potion_codes()`. All hardcoded tables now overridable — minor patches won't break users. Test suite: **118 tests green**; compileall + headless UI smoke pass.
- Version `1.8.7-beta` — **configurable override tables for all hardcoded game data**. Added `overrides` dict in config + accessors for class heal/mana groups, rejuv %, belt rows, per-potion restore/duration overrides. `PotionCodes` accepts optional overrides; `PotionEntry` supports `restore_override` + `duration_override`. Config `overrides` dict persisted, injected into `PotionCodes` via `potion_codes()`. All hardcoded tables now overridable — minor patches won't break users. Test suite: **118 tests green**; compileall + headless UI smoke pass.
- Version `1.8.2-beta` — **unified logic (no tiers) + best-effort critical fallback + horizontal checkbox/key-entry UI**.  No smart/plain tiers: `_plain_tick` deleted, `_tick` runs only `plan_consume` regardless of `behavior.smart`.  Reader fix: `_read_item_counts` now records unclassified belt potions (kind None) into `belt_cols`/`belt_filled` so column geometry is correct and the watcher can detect them.  Best-effort fallback: `_act` gains a `critical` flag; when `_pick` returns False on the rejuv-critical line and unrecognised potions are on the managed belt, it presses the unrecognised column (preferring the action's standard column via `FALLBACK_KEYS`: heal→Q, mana→W, rejuv→E, then any unclassified managed column) and warns once to Calibrate codes for exact drinking — a critical stat never sits at 0%.  `_smart_tick` drives `_act` for `missing` kinds too (previously only logged) and passes the critical flag.  Belt-hotkey UI: one horizontal row of `[checkbox] [single-char CTkEntry]` × 4 (Q/W/E/R); type a key + Enter / focus-out to rebind (`_on_belt_key_entry` validates via `keysym_to_key_name` + `config.set_belt_key`); blank/Esc/Delete restores default; the old button-capture flow (`_on_belt_key_capture`, `_belt_key_btns`, the `belt_key` capture branch) is removed.  Test suite: **118 tests green**; compileall + headless UI smoke pass; the belt/inventory reads, the refill/move logic, and the merc path still need a live in-game end-to-end check (deferred — logic kept, UI hidden).
- Version `1.8.1-beta` — **mana drinks at near-0% + editable belt hotkeys + one-button global hotkey + "arm" wording gone; belt refill & belt-plan UI hidden (deferred)**.  Mana fix: plain tier now falls back to a mana potion when only mana is critical and no rejuv is on the belt (previously it sat on the rejuv check and drank nothing); smart tier single-critical prefers a covering potion → rejuv → any potion of the wanted kind, so under-strength potions are still drunk when rejuv is absent (`critical_one` in `refill.plan_consume` reordered; `_plain_tick` falls back; `_act` now returns whether a drink was attempted).  Belt hotkeys: `config.belt_keys` + `belt_key()`/`set_belt_key()`/`belt_keys_map()` (Esc/Delete/unresolvable → default letter); watcher `_use` presses `config.belt_key(column.index)`; `KeySender._fallback_key` honours rebinds; UI is a clean `[tickbox] [Column -> Key button]` row.  Global hotkey: single topbar button (click, press combo, Esc clears), status active/failed; `HotkeyListener` uses a unique per-instance window class (no `ERROR_CLASS_ALREADY_ALREADY_EXISTS`).  "Arm/Armed" renamed to enable/disable in UI/logs/docs.  **Belt refill & belt-plan UI hidden**: D2R moves items only with the mouse (no keyboard alternative) and the click-place refill could not be made reliable yet, so both sections are removed from the Keys tab; the drinking logic, managed-column hotkeys, and enable/disable all stay active.  Test suite: **110 tests green**; compileall + headless UI smoke pass; the smart-tier belt/inventory reads, the refill/move logic, and the merc path still need a live in-game end-to-end check (deferred — logic kept, UI hidden).
- Version `1.8.0` — **Keys tab rework: no per-potion bindings, configurable feed-to-merc modifier, belt mix removed**.  Belt hotkeys ARE the managed columns (Q/W/E/R checkboxes; any managed column can serve any potion type since the slot's content is read each tick).  Merc actions press the belt key + a user-pickable modifier (`behavior["merc_modifier"]`, default Shift — D2R's feed-merc binding).  Belt mix (ratio) hidden from the UI and dropped from the smart refill chain (`desired_kind_for_slot`: layout → column-family → None; `plan_layout_refill`: that → last-drunk kind → any).  `plan_consume`/`_allowed_for` no longer take `bound`; watcher `_pick` uses all managed columns; `config.key()`/`keys_for()` removed; `d2r.keys.FALLBACK_KEYS` (heal Q / mana W / rejuv E, merc same + modifier) covers unreadable-belt presses.  Test suite: **95 tests green**; compileall + headless UI smoke pass; KeySender modifier resolution + fallback sanity-verified.
- Version `1.7.0` — **grade-aware stacking + trimmed Triggers tab + real merc/player maxes**.  Same-or-higher grade potions may be drunk once the in-effect potion is half consumed (`_effective_cooldown(action, candidate_grade)` → `duration*0.5`); weaker/unknown grades wait `duration * potion_margin()`; rejuv uses the fixed 1.0s gate; config cooldowns only fall back while the belt potion is unknown.  `_pick` now returns a `BeltColumn` (or False=skip / None=plain-key fallback) and `_act` does the gating, so `_ready`/`_effective_cooldown` take the candidate grade.  Triggers tab: potion-values table and class dropdown removed (class auto-detected per snapshot), Safety-margin slider kept with a hint that only describes the slider.  Rejuv defaults 40→25 (`rejuv_potion_at_life`/`_mana`).  Merc true max now from the stats-list item block (`STATSLIST_ITEM_STAT_PTR=0xA8`/`COUNT=0xB0`) — live-verified 199/199 at full vs the base 189 — and the UTF-16 name read at `UNIT_OFFSET_NAME=0x2C` is removed (that offset is not a name; hireling names are a UI resource string; merc is labelled by act-based type).  Player max HP/MP uses `_track_max` (shrinks to the base stat when at/over it, grows while damaged).  Test suite: **95 tests green**; compileall + headless UI smoke pass; live probe (pid 25000) confirms merc 199/199 + empty name + player 303/303.
- Version `1.5.0` (previous). Test suite: 84 tests green (v1.4.0 added `belt_rows_for`,
  `belt_empty_slots`, `solve_grid_mapping`, refill planner tests, config
  refill/managed-column accessors, watcher managed-column gating + last-kind
  tracking; v1.5.0 added `plan_consume`, `desired_kind_for_slot`,
  `plan_layout_refill`, config smart/layout/ratio accessors, watcher smart-tier
  tests).  compileall + headless UI smoke pass.  Belt + inventory + player +
  merc live-verified against pid 20048 (Sylus, Warlock 20) — belt corners
  {0:532, 3:528, 4:608, 7:529}; wizard round-trip verified against a temp
  config.  Refill probes live against pid 25000 (char select): offsets ok, item
  read correctly reports no game; the smart tier's equipped-belt/inventory reads
  and the merc auto-potion path still need a live in-game end-to-end check
  (deferred).
