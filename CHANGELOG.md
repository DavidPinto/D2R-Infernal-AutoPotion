# Changelog

All notable changes to the D2R Infernal Auto Potion tool.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.9.7-beta] - 2026-08-21

### Fixed (merc parity + gamepad merc feed)
- **Gamepad merc feed was broken**: merc actions tapped the bare D-pad, so in
  gamepad mode the *player* drank the potion instead of the merc.  The synthetic
  pad now holds **LT** while tapping (the D2R controller feed-merc binding,
  LT + potion direction).  Probe-verified on this build: GIP report byte[3] is
  the left-trigger axis (0-255) and registers via XInputGetState; byte[2]
  does not.
- **Merc rejuv now has critical parity with the player's rejuv line**: at/below
  the merc rejuv threshold the action runs as critical, enabling
  reach-buried-rejuv (same opt-in config gate — it is wasteful by design) and
  the unclassified-column best-effort so the merc no longer sits at 0% while
  potions are on an uncalibrated belt.  Merc heal at its normal threshold stays
  non-critical, matching the player's non-critical heal.
- Already shared with the player logic (verified, unchanged): grade-aware
  column picking, the waste guard (`merc_heal` keyed per action; rejuv exempt),
  same/higher-grade half-duration gate and weaker-grade margin, cooldowns,
  managed columns, out-of-stock suppression.

Test suite: **135 tests green** (4 new: GIP trigger byte, LT-held merc feed
with a recording gamepad, buried-rejuv parity with/without the opt-in);
compileall + headless UI smoke pass.

## [1.9.6-beta] - 2026-08-21

### Changed (cleanup & UI polish — no behavior changes)
- **Dead prototyping scaffolding removed from the UI**: the hidden belt-refill /
  belt-plan stubs (`_on_refill_toggle`, `_on_smart_toggle`, `_on_layout_change`,
  `_refresh_belt_plan`, `_refresh_refill_status`, `_refresh_belt_info` and the
  `_LAYOUT_*` maps) are gone, including a per-poll call to `_refresh_belt_info`
  that referenced a widget that never existed (silently swallowed by the poll
  guard).  The deferred refill *logic* in `d2r/refill.py` and its config
  accessors are untouched.
- **Clearer UI wording**: Dashboard help points to the Keys tab (not
  "Triggers → Keys"); the safety-margin hint now matches the actual gate math
  (a weaker potion waits `duration × margin`); Triggers groups the toggles
  under a "Smart behavior" heading and tightens the predictive-drinking /
  reach-buried-rejuv labels and hints; Calibrate's "Saved profiles" is now
  "Saved potion codes" with a note distinguishing them from the top-bar
  config profiles; Diagnostics hint rewritten (run in-game, all signatures
  must read RESOLVED / plausible: YES).
- **Tooltips**: new `ui/widgets.Tooltip` (hover popup, plain tkinter) wired to
  the topbar Reconnect / enable / Hotkey controls.
- **Comment pass**: watcher module docstring rewritten to the current decision
  flow (plan_consume + pre-drink + waste guard + grade gate, predictive
  toggle noted); stale "smart/plain tier" wording replaced across
  watcher/refill/config comments.
- Repo root cleaned: the one-off `patch_*.py` prototyping scripts are removed
  (the leftover `patch_docs.py` moved to the temp folder).

Test suite: **131 tests green**; compileall + headless UI smoke pass.

## [1.9.5-beta] - 2026-08-21

### Changed
- **Desperation Mode Renamed:** Renamed "Desperation Mode" to "Reach Buried Rejuv" across the UI and codebase to better reflect the underlying logic.
- **Predictive Drinking UI:** Added a visible checkbox in the Keys/Refill tab to toggle predictive drinking (drain-slope and poison anticipation) on or off. Includes a descriptive tooltip for non-technical users.
- When predictive drinking is off, potions are now consumed exactly at the threshold slider values, bypassing predictive lead logic.

## [1.9.4-beta] - 2026-08-20

### Added (granular monitoring — decision logic, no new config)
- **Poison detection via the unit states block.**  States are 6×u32 inside the
  stats-list-ex struct at `+0xAF0` (d2go reference layout, stable across D2R
  3.x builds; verified live on this build — the always-on `Alignment` state
  reads correctly, poison bit currently 0).  `GameReader._read_unit_states()`
  decodes the bitfield into the snapshot (`states`/`poisoned`).  Poison keeps
  ticking in otherwise-safe situations (town, after a fight) and slow poison
  may not register on a damage slope, so the poisoned flag alone puts HP on
  the heal line and the app drinks before it hurts.  The poison bit itself
  needs one in-game poison hit to confirm (cannot be forced during dev).
- **Drain-slope pre-drink.**  The watcher keeps a rolling (t, HP, mana) window
  and derives a per-stat drain rate.  When a stat is draining fast enough to
  cross its threshold within the 1 s pre-drink lead, the decision sees it as
  already there — so the potion (which restores *over* its duration) is
  already delivering when the bar empties, instead of the bar sitting empty
  for the delivery delay.  Stops automatically when the drain slows.
- Both feed the *normal* decision path (`plan_consume`), so cooldowns, the
  waste guard, managed columns, panic mode and out-of-stock all still
  apply unchanged; pre-drinks cannot double-press inside a cooldown.
- Injectable watcher clock (`PotionWatcher._now`) so the slope logic is
  deterministically unit-tested.

Test suite: **131 tests green** (6 new granular-monitoring tests); compileall +
headless UI smoke pass; live snapshot read validated against the running game
(player in-game, states `[105]`, `poisoned=False`).

## [1.9.3-beta] - 2026-08-20

### Fixed
- **Mana potions were wasted when an in-effect potion would restore fully.**
  The half-duration cooldown allowed a second same/higher-grade drink while
  the potion still in effect had enough remaining restore to cover the
  deficit on its own — e.g. a Super mana potion re-drunk at 3/5.12 s with
  ~155 mana still to deliver.  The watcher now skips the second drink when
  the in-effect potion's remaining restore (`total × (1 - elapsed/duration)`)
  covers the current deficit; rejuv (instant) is never gated by this.
  The old same-grade-repeat test now asserts the skip, plus a repeat fires
  when the in-effect potion can no longer cover the deficit.

### Cleanup (deferred-issue pass — cleanup policy now allows dead-code removal)
- `d2r/reader.py`: removed the shadowed dead copies of `open_menus` and
  `_get_ui_base` (the calibrated-only versions were already the live ones).
- `ui/app.py`: removed the unreachable refill-clicker calibration code
  (`_toggle_calib_capture`, `_exit_calib_capture`, `_record_calib_sample`,
  `_finish_calib`, `_clear_calib`, the `_calib_capture`/`_calib_samples`/
  `_calib_hotkey` state, and their dead branches in `_disconnect`/`_on_close`)
  plus the now-unused `input_mod`/`find_window_for_pid`/`VK` imports.
- `d2r/process.py`: explicit `argtypes`/`restype` for the Toolhelp snapshot
  family (`CreateToolhelp32Snapshot`, `Process32First/Next`,
  `Module32First/Next`) and the user32 window helpers (`EnumWindows`,
  `IsWindowVisible`, `GetWindowThreadProcessId`, `ShowWindow`,
  `GetForegroundWindow`, `SetFocus`, `SetForegroundWindow`,
  `AttachThreadInput`, `GetCurrentThreadId`).
- `README.md`: dropped the stale "F8 hover calibration" legacy-feature note.

Test suite: **127 tests green**; compileall + headless UI smoke pass.

## [1.9.2-beta] - 2026-08-20

### Fixed (full-app code review pass)
- Belt-key rebinding on the Keys tab crashed with `ModuleNotFoundError` (a
  local `from .hotkey import ...` resolved to a non-existent `ui.hotkey`; the
  working `d2r.hotkey` import was already in scope).
- `d2r/input.py` typed `GetClientRect` as an 8-byte `POINT` instead of the
  16-byte `RECT` it writes — an 8-byte buffer overflow, and
  `window_rect`/`window_client_rect` always returned a degenerate `(0,0)`
  client size (the root cause of the deferred belt-refill clicker's
  unreliability).  Live-verified: a 1280×800 window now reports exactly that.
- `d2r/watcher.py` could crash the watcher thread with `NameError` when a
  corrupt persisted `poll_interval_ms` (or a first-tick read failure) reached
  the "never crash" loop guard; the interval/snapshot are bound before the
  loop.
- `d2r/models.py` rejuv restore with a `restore_override` dict lacking the
  player's class group indexed the dict by grade (KeyError / wrong amount)
  instead of falling back to the percentage table; heal/mana restore overrides
  are now applied per class group too.
- `d2r/process.py` leaked a process-module snapshot handle (duplicate
  `CreateToolhelp32Snapshot` call).
- `d2r/keys.py` `XINPUT_GAMEPAD_B/X/Y` constants were 0x1001-0x1003 instead of
  the real XInput values 0x2000/0x4000/0x8000.
- Gamepad-mode toggle now applies to a running watcher immediately (KeySender
  cached `use_gamepad` at connect time; it reads the config on every press).
- The startup "restart as administrator" prompt now reads the saved config
  (`AppConfig.load()`), so it actually fires for users with gamepad mode on.

## [1.9.0-beta] - 2026-08-20

### Added
- **Real gamepad input via Microsoft's synthetic gamepad API** (Keys tab).
  When enabled, the app creates a real Xbox controller through
  `xboxgipsynthetic.dll` (ships with Windows 10 22H2+ cumulative updates — no
  drivers, nothing to install) and taps the D-pad for belt actions:
  Q=Left, W=Up, E=Down, R=Right.  Probe-verified end to end: the synthetic
  controller registers in XInputGetState and D-pad reports are delivered as
  real XInput button state.
- Requires the app to run **as administrator** (the API refuses non-elevated
  processes); the app now detects this at launch and offers a UAC relaunch.
- The gamepad section moved to just below the belt-hotkey (QWER) section;
  removed the obsolete controller-index field (the synthetic controller takes
  the first free XInput slot, the app cannot choose one).

### Changed
- Gamepad input now goes through the OS gamepad stack instead of keyboard
  keys — the minimap no longer moves when a potion is drunk with gamepad mode
  on.

### Fixed
- Duplicate "Watch refresh interval" slider on the Keys tab (the gamepad
  section had been inserted between two copies of the same block).
- Menu detection now only reports calibrated menus (no false positives)

## [1.8.8-beta] - 2026-08-16

### Added
- **Panic Mode** (Triggers tab checkbox).  When HP is at/below the rejuv
  threshold, bypasses normal restrictions to reach a rejuv potion:
  - Looks for a rejuv in rows 1-3 of managed belt columns
  - Requires no empty slots between the rejuv and row 0 (potions drop
    potion-to-potion)
  - Requires row 0 to have a potion (to make the rejuv drop)
  - Allows drinking row-0 potions (mana/heal) to reach the rejuv (instant
    heal)
  - **WASTEFUL** - may consume multiple potions to clear a path to the rejuv
  - Respects empty slots (potions don't drop through empty space)
  - Only activates when HP is at/below the rejuv threshold (critical)
  - UI checkbox with clear warning about wastefulness

### Changed
- Replaced "Keep Alive Mode" with "Panic Mode" (more descriptive name
  matching the wasteful nature of the feature)
- UI checkbox renamed with clear warning tooltip

### Fixed
- Menu detection now only reports calibrated menus (no false positives)

## [1.8.7-beta] - 2026-08-15

### Added
- **Configurable override tables** for all hardcoded game data tables.
  - Class heal/mana groups (which class gets which restore column)
  - Rejuv restore percentages
  - Belt rows mapping (txtFileNo → rows)
  - Per-potion restore/duration overrides (via Calibrate tab combos)
  - Persisted in config under `overrides`, applied automatically
- `PotionEntry` now supports `restore_override` (per class group) and
  `duration_override` — stored in combo potions, used instead of built-in tables

### Changed
- `PotionCodes` accepts optional override tables (`class_heal_group`,
  `class_mana_group`, `rejuv_restore_percent`) — injected from config
- `default_potion_codes()` and `potion_codes()` accept/forward override tables
- Config stores override tables in `overrides` dict; accessors added
- Potion restore/duration now checks: per-entry override → config override → built-in

### Fixed
- Config accessors now use `overrides` dict (was broken `_data` reference)
- All hardcoded game data tables now overridable — minor patches won't break users

## [1.8.6-beta] - 2026-08-15

### Added
- **Full menu calibration** in Calibrate tab ("Calibrate menus").
  Guides user to CLOSE all menus, then OPEN/CLOSE each blocking menu
  (Inventory, Stash, Character, etc.) one by one. Detects the exact byte
  index for each menu flag by measuring actual byte changes (not assuming
  0→non-zero). Persists both UI struct address AND flag index map.
  Works on ANY build — no hardcoded flag indices.

### Changed
- `GameReader.calibrate_ui()` detects flag indices by scoring actual byte
  changes (magnitude + preference for 0→non-zero). Robust across builds.
- `GameReader.open_menus()` uses calibrated flag indices when available,
  falling back to defaults. Accurate per-panel detection on all builds.
- Dashboard "menus open" indicator now accurate when calibrated.
- Default `pause_when_menus_open = true` (calibration enables reliability).

### Fixed
- Diagnostics fixed: `GameReader` accepts optional `config`.
- Calibration no longer assumes specific flag indices — learns them.

## [1.8.5-beta] - 2026-08-15

### Added
- **One-click menu calibration button** in Calibrate tab ("Calibrate menus").
  Calls `GameReader.calibrate_ui_struct()` which finds the live UI struct at
  `GameData+0x8` (verified pointer chase). Calibrated address persisted in
  config and used automatically.  Simple one-click, no F8 hovering.

### Changed
- Dashboard now **always shows "menus open"** when any blocking panel is
  detected (regardless of `pause_when_menus_open` setting).  The pause setting
  only controls whether drinking pauses.
- Default `pause_when_menus_open = true` (calibration now exists; user can
  disable if they prefer drinking with inventory open).
- Diagnostics fixed: `GameReader` accepts optional `config` parameter so
  `diagnose()` works standalone.

### Known limitation
- Menu flag indices are shifted for this Infernal build (Inventory flag reads
  0 even when open).  The live UI struct is correctly found at `GameData+0x8`,
  but flag index remapping is needed for accurate per-panel detection.
  `pause_when_menus_open` works reliably only after calibration + flag fix.

## [1.8.4-beta] - 2026-08-15

### Added
- **UI struct calibration framework** for reliable menu detection.  The `ui-v3`
  signature resolves to a ghost copy on this build; the real menu flag array
  lives in heap memory.  Added `GameReader.calibrate_ui_struct()` which scans
  for candidate structs and detects the live one by watching the inventory flag
  change (open/close inventory).  Calibrated address persisted in config
  (`calibrated_ui_address`) and used automatically on subsequent runs.
- Config accessors `calibrated_ui_address()` / `set_calibrated_ui_address()`.

### Changed
- `GameReader.open_menus()` now uses calibrated address when available,
  falling back to signature.  Eliminates false "menus open" from ghost struct.
- Dashboard "menus open (paused)" only shows when `pause_when_menus_open=true`.

### Deferred
- Full Calibrate UI tab integration (one-click calibration).  The framework
  exists; a UI button can call `reader.calibrate_ui_struct()` and persist the
  result.  Required for reliable refill feature (needs accurate inventory-open
  detection).

## [1.8.3-beta] - 2026-08-15

### Fixed
- **Menu detection (pause_when_menus_open) was broken.** The UI signature
  (`ui-v3`) matched twice in the module; the scan rejected both hits (ambiguous
  non-validated candidate), leaving `offsets.UI` unresolved and `open_menus()`
  permanently returning empty — drinking never paused for real panels, but also
  never worked correctly.  The scan now tests each hit and accepts the one that
  resolves to a readable UI struct with valid flag bytes.

### Changed
- Default `pause_when_menus_open` disabled in user config (per testing
  preference: potions work fine with inventory/stash open in this build).
- Menu flag indices appear shifted for this Infernal build (Inventory flag
  reads 0 even when open); detection is functional but inaccurate.  A proper
  structural UI scan or flag remapping is deferred.

## [1.8.2-beta] - 2026-08-15

Unified decision logic (no smart/plain tiers) and a robust best-effort fallback
so a critical stat never sits at 0% doing nothing.  Belt-hotkey UI redesigned to
a single horizontal row of `[checkbox] [key input]` pairs.

### Fixed

- **"Still not drinking at 0%" root cause addressed.**  Belt potions the app
  cannot classify (`kind == None`, i.e. the game version/mods are not calibrated)
  were silently dropped by the reader — the belt column then looked empty and
  the watcher reported "No … potion left on the belt" and pressed nothing.  The
  reader now records unidentified belt potions so the column geometry is correct
  and the watcher can act on them.
- **Best-effort fallback on a critical stat.**  When HP or mana is critical,
  no recognised potion of the wanted kind is on the managed belt, but
  unrecognised potions ARE present, the watcher presses the column holding an
  unrecognised potion as a best-effort (preferring the stat's own standard
  column: heal→Q, mana→W, rejuv→E) and warns once that the Calibrate tab should
  be taught the build's codes for exact drinking.  This guarantees a potion is
  always drunk when the stat is at the rejuv line, even with uncalibrated codes.
- **Reader: unclassified belt potions** now fill the slot and the per-column
  counter, so `belt_empty` / `belt_slots` geometry stays accurate when the
  active combo does not yet know a potion's txtFileNo.

### Changed

- **No tiers — one decision path.**  The legacy "plain tier" (`_plain_tick`)
  is removed; `_tick` runs only the unified `plan_consume` logic regardless of
  the (now-vestigial) `behavior.smart` flag.  The dead `_plain_tick` method and
  the misleading `test_smart_disabled_uses_plain_tier` test are gone.
- **Belt-hotkey UI is horizontal single-char inputs.**  Replaced the vertical
  `[tickbox] [Column -> Key button]` rows with one horizontal row: for each of
  Q/W/E/R a checkbox and a single character text input showing the bound key —
  nothing more.  Type a key and press Enter (or focus out) to rebind; blank /
  Esc / Delete restores the default.  The old button-capture flow is removed.
- `_smart_tick` now passes a `critical` flag into `_act` (so the best-effort
  fallback fires only on the rejuv-critical line, never on a routine threshold
  dip) and drives `_act` for `missing` kinds too (previously only logged).

### Added

- Comprehensive combination tests: critical heal/mana/rejuv with
  readable/unreadable belts, classified vs unclassified potions, the
  best-effort fallback, managed-column gating of the fallback, and tier-
  independence (the `smart` flag no longer changes behaviour).  Test suite:
  **118 tests green** (compileall + headless UI smoke pass).

## [1.8.1-beta] - 2026-08-15

Core drinking bug fixes and a UI clean-up.  Versioning now uses small
increments with a beta suffix so we stop creeping toward 2.0 while features are
still settling.  The **belt refill** and **belt-plan** features are deferred and
hidden from the UI until they can be made reliable — the app now focuses on
rock-solid HP / Mana / Merc potion drinking for the eventual 2.0 release.

### Fixed

- **Mana potions now drink at near-0% mana.**  Plain tier (smart disabled) used
  to sit on the rejuv check when only mana was critical and no rejuv was on the
  belt — it now falls back to a mana potion instead of doing nothing.  The smart
  tier's single-critical path also prefers a covering potion, then rejuv, then
  any potion of the wanted kind (never wasted), so under-strength potions are
  still drunk when rejuv is absent.
- **Belt hotkey UI fixed.**  Each column is now a clean `[tickbox] [bind-key
  button]` row — the button shows `Column -> Key` and is the only control next
  to its checkbox (the old redundant double-letter layout is gone).

### Changed

- **Belt refill & belt-plan UI hidden.**  D2R only moves items with the mouse
  (no keyboard alternative), and the click-place refill could not be made
  reliable yet, so both sections are removed from the *Keys* tab for now.  The
  drinking logic, managed-column hotkeys, and the enable/disable + single-button
  global hotkey all remain fully active.
- **"Arm/Armed" → "enable/disable"** (top-right toggle is **ENABLED/DISABLED**;
  all help text and logs updated).  **Global hotkey is one button** next to the
  toggle (click, press Ctrl/Alt/Shift + a key, Esc clears).  **Per-column belt
  hotkeys** editable next to each managed checkbox — the watcher presses the
  rebound key when it drinks from that column, and the unreadable-belt fallback
  keys honour the rebinds.

### Added

- `AppConfig.belt_key()` / `set_belt_key()` / `belt_keys_map()` (persisted
  `belt_keys` section; Esc/Delete/unknown names reset to the default letter) and
  `HotkeyListener` unique per-instance window class names.
- Unit tests for the belt-key accessors, the plain-tier mana fallback, and the
  rejuv-ordering fix.  Test suite: **110 tests green** (compileall + headless
  UI smoke pass).

## [1.8.0] - 2026-08-15

Keys tab reworked: no more per-potion key bindings, configurable feed-to-merc
modifier, belt mix removed.

### Changed

- **No more per-potion key bindings.** The old Health / Mana / Rejuv / Merc
  key rows on the *Keys* tab are gone.  The app drinks by pressing the belt's
  own hotkeys (Q/W/E/R) and reads each belt slot to see which potion it holds,
  so there is nothing to bind — any managed column can serve any potion type.
  The deprecated `keys` config section stays empty (old configs/profiles still
  load; it is simply unused).
- **Keys tab streamlined.** New layout: *Belt columns & hotkeys* (the managed
  Q/W/E/R checkboxes, which now double as the hotkey set), *Mercenary potion
  modifier*, *Belt refill*, *Belt plan (smart)* and *Behaviour* — every hint
  rewritten to match how the app actually decides.
- **Feed-to-merc modifier is user-pickable.** Merc actions press a configurable
  modifier together with the belt hotkey (default **Shift**, the same
  feed-merc binding D2R uses); you can switch to Ctrl or Alt on the *Keys* tab.
  `KeySender` reads it from `behavior["merc_modifier"]`.
- **Belt mix (ratio) removed from the UI.** The HP/Mana/Rejuv mix row and its
  Apply button are hidden.  The smart refill no longer targets a ratio — it
  fills an empty slot per the per-slot **Belt plan** layout, else restocks the
  kind dominating that column, else the family last drunk, else any potion.
  The `ratio` config field is kept for back-compat but is unused.
- Built-in fallback keys remain only for the rare case where the belt is
  unreadable (heal→Q, mana→W, rejuv→E, merc same with the modifier) — no UI.

### Added

- `AppConfig.merc_modifier()` / `set_merc_modifier()` (normalises to
  SHIFT/CTRL/ALT, default SHIFT) and `d2r.keys.resolve_modifier()`.
- `FALLBACK_KEYS` map in `d2r/keys.py`; `press_key(vk, modifier=...)` replaces
  the hard-coded `with_shift`.
- Unit tests for the modifier accessor, `resolve_modifier`, and the fallback
  keys.  Test suite: **95 tests green** (compileall + headless UI smoke pass).

## [1.7.0] - 2026-08-14

Grade-aware stacking, smarter triggers UI, and corrected merc/player maxes.

### Changed

- **Same-or-higher grade stacking.** The watcher's derived cooldown is now
  grade-aware: a potion of the *same or higher* grade may be drunk once the
  potion in effect is half consumed (keeps the strong potion's fill rate while
  topping up sooner); a *weaker* potion is still held for the full restore
  duration × the safety margin so it never drags the fill rate down.  Unknown
  grades stay conservative.  Rejuv keeps its fixed instant gate.
- **Triggers tab simplified.** The potion-values table and the character-class
  picker are removed (the class is read from the live character automatically).
  The *Safety margin (%)* slider stays, with a hint that only describes what it
  does — it gates how long a weaker potion is held back after the in-effect
  potion finishes; it is not "two potions is bad".
- **Rejuv defaults lowered to critical.** Default rejuv thresholds drop from
  40/40 to 25/25 (HP ≤ 25 or MP < 25), so rejuv is reserved for the instant
  save instead of firing on ordinary dips.
- **Merc max now includes gear.** The merc readout reads the stats-list's second
  (merged/item) stat block, so a full merc shows its true max (e.g. 199/199)
  instead of the un-geared base (189/189).  The bogus UTF-16 name read at
  unit+0x2C is gone (it only ever produced garbage like the Chinese text) — the
  hireling is labelled by its act-based type (e.g. "Rogue Scout").
- **Player max can shrink.** Removing a +max HP/MP item no longer reads as
  damage: the tracked max falls back to the base stat when the player is at/over
  it, and still only grows while damaged.

### Added

- `GameReader._track_max` (pure shrink/grow rule), stat-list item offsets
  (`STATSLIST_ITEM_STAT_PTR/COUNT`), and watcher `_last_potion_grade`.
- Unit tests for the half-duration same/higher gate, the weaker-hold margin,
  rejuv defaults, the merc merged max, and the player max shrink rule.
  Test suite: **95 tests green**.

## [1.6.0] - 2026-08-14

Corrected potion model (class-dependent restore amounts over a duration, no
weak-on-strong stacking) and the mercenary health readout.

### Changed

- **Real potion model.** Potions restore a class-dependent amount over a
  duration (per the game's column files), they no longer restore a flat point
  value and nothing is "instant" except rejuvenation:
  - Health: Minor 7.68 s, Light 6.40 s, Healing 6.84 s, Greater 7.68 s,
    Super 10.24 s.  Restore per class group (Druid/Necro/Sorc/Warlock |
    Amazon/Assassin/Paladin | Barbarian): Minor 30/45/60, Light 60/90/120,
    Healing 100/150/200, Greater 180/270/360, Super 320/480/640.
  - Mana: all 5.12 s.  Restore per class group (Barbarian |
    Amazon/Assassin/Paladin | Druid/Necro/Sorc/Warlock): Minor 20/30/40,
    Light 40/60/80, Mana 80/120/160, Greater 150/225/300, Super 250/375/500.
  - Rejuvenation heals 35% of max HP+MP instantly; Full Rejuvenation 100%.
    `606`/`611` are the **Super** grades (not "Full = 100%").
  - The class is detected from the live character each snapshot; a fixed
    override can be set (Triggers tab) for preview and drinking math.
- **No weak-on-strong stacking.** The watcher now waits one potion's restore
  duration × a safety margin (default 20 %) before drinking the same kind
  again, so two quick sips can't average the fill.  Rejuv uses a short fixed
  gate.  Config cooldowns are only a fallback while the belt potion is unknown.
- **Triggers tab redesigned.** The raw per-action cooldown sliders are gone.
  In their place: a character-class dropdown, a *Safety margin (%)* slider
  (0–100), and a live potion-values table (grade, duration, restore for the
  selected class).  Calibrate wizard labels corrected to the real grade names
  (Minor/Light/Healing/Greater/Super).

### Fixed

- **Mercenary health readout.** The engine stores merc Life as a fraction of
  max scaled to [0, 0x8000]; at full HP it is *exactly* 0x8000, which the old
  boundary check misread as a shifted value → the merc always showed 128/189
  (67%) at full health and ignored the gear bonus.  The fraction path now
  triggers at `raw ≤ 32768`; percentages and max-HP-derived values are
  correct, including at full health.
- **Mercenary hireling info.** A living hireling now always wins over a corpse
  found earlier in the unit list (dead mercs no longer shadow the real one),
  the merc's UTF-16 name is read directly from the unit, the type map is
  act-based (Rogue Scout / Desert Mercenary / Iron Wolf / Barbarian), and the
  tracking state resets when the merc unit changes.
- Class-aware potion restore is wired through the smart tier automatically
  (the reader refreshes the shared `PotionCodes.player_class` every snapshot).

### Added

- `GameReader` merc snapshot exposes `raw_life` / `raw_max_life` / `unit_id`
  and `UNIT_OFFSET_NAME`; Diagnostics dumps the raw merc life hex.
- Config `behavior["potion_margin_percent"]` (default 20) and
  `behavior["potion_class_override"]` ("" = auto), with safe accessors
  `potion_margin()` and `potion_class()`.
- `PotionCodes.duration(txt)` and class-aware `restore(txt, max_value,
  player_class="")`; `process.read_wide_string()` for UTF-16 reads.
- Unit tests for the class-dependent restore tables, potion durations,
  derived-cooldown gating, the merc full-health boundary, and the config
  accessors.

## [1.5.0] - 2026-08-14

Improved auto potion (Iteration B: smart tier — belt plan + smart consume + layout/ratio refill).

### Added

- **Smart potion choice.** A new planner (`plan_consume`) decides from the whole
  managed belt, not just the bound columns.  Rules:
  - HP *and* MP both in the rejuv range → rejuv.
  - Only HP low → drink a heal if a heal that fully covers the deficit is on a
    managed belt slot, otherwise rejuv.
  - Only MP low → drink a mana if a mana that fully covers the deficit is on a
    managed belt slot, otherwise rejuv.
  - Non-critical dips → heal and mana fire independently of each other.
  - "Covers" means the potion's restore ≥ the HP/MP deficit; the column still
    drinks the smallest sufficient grade.  Enabled by default (smart switch on
    the Keys tab; turning it off falls back to the previous dumb tier).
- **Belt plan section (Keys tab).** A 4×4 grid that mirrors the in-game belt
  (Any / HP / Mana / Rejuv per slot) plus an HP / Mana / Rejuv ratio.  Together
  they drive smart-tier refill: the kind wanted for an empty slot is  *user
  layout → dominant kind already in that column (restock in place) → biggest
  positive shortfall vs the ratio → any potion*; the potion moved is the lowest
  grade of that kind in inventory, then same-kind fallback, then any potion.
  The Keys tab is now scrollable so the whole section fits on small windows.
- Config `layout` (per-slot, 0–15) and `ratio` persisted in `config/config.json`;
  accessors `belt_layout()` / `set_belt_layout()` / `belt_ratio()` /
  `set_belt_ratio()`; `behavior["smart"]`.
- Pure, unit-tested helpers: `plan_consume`, `desired_kind_for_slot`,
  `plan_layout_refill`.

### Fixed

- `_belt_covering` now verifies the restore amount actually covers the deficit
  (`choose_belt_column` returns the strongest grade even when none covers) and
  finds columns by their own index (the columns list can be shorter than 4).
- `_belt_has_kind` matches managed columns by their key (Q/W/E/R), not their
  index.

### Known / deferred

- Smart-tier consume + layout refill are verified by unit tests but not yet
  live-verified in-game; the merc auto-potion path is unchanged from 1.4.0 and
  still needs a live game to re-verify end-to-end.

## [1.4.0] - 2026-08-14

Improved auto potion (Iteration A: managed columns + belt refill).

### Added

- **Managed belt columns**: the Keys tab lets you uncheck belt columns (Q/W/E/R)
  the app is allowed to touch.  Unchecked columns are never drunk from and never
  refilled — you keep manual control of them.  Default: all four managed.
- **Belt refill from inventory**: when enabled, the app watches your belt while
  the inventory panel is open and, if a managed belt slot is empty, clicks a
  matching potion from your inventory into it (restocking what was just drunk
  first, other families after).  One click per tick, only while the game window
  is the foreground window, and only into the columns you manage.
- **Click-position calibration wizard**: refill needs to know where inventory
  cells are on screen, which varies by resolution.  In-game, hover over a potion
  in your inventory and press F8 (twice, on different potions), then click
  *Finish & save*.  The app solves the grid (cell size + origin) from the hover
  cursor and the item's grid coordinates.  *Clear* removes it.
- **Belt slot readout** on the Keys tab: number of belt rows / slots, how many
  are filled and free (live, from the equipped belt item — supports 4×1 to 4×4).
- `AppConfig` refill section (`enabled`, calibrated click mapping, click
  interval) + `managed` column list, both persisted in `config/config.json`.
- Pure, unit-tested helpers: `belt_rows_for`, `belt_empty_slots`,
  `solve_grid_mapping`, `plan_refills` (dumb-tier choice), `belt_fill_order`.

### Changed

- The watcher's grade-aware column picker now also filters by managed columns.
- New `d2r/refill.py` (pure planning) and `d2r/input.py` (mouse + window
  helpers on Win32 SendInput/SetCursorPos; clicks only land when the game
  window is foreground).
- `GameReader` exposes `belt_rows`/`belt_filled`/`belt_empty` on
  `PotionCounts`, an `inventory_potions()` read (grid cell + unit id), and
  `hovered_item_unit()` for the calibration wizard.

### Notes

- Refill only acts while your inventory panel is open (no auto-opening the
  panel, no clicks during combat).  Clicking a potion in D2R fills the first
  empty belt slot the engine chooses, so the app drives the *potion choice* by
  the belt's fill order; a per-slot belt layout (the "smart" tier) is planned
  for the next iteration.

## [1.3.0] - 2026-08-14

User calibration: end users can teach the app their build's potion codes.

### Added

- **Calibrate tab — guided calibration wizard**: instead of typing codes, the
  user places ONE potion they can identify (e.g. Minor Health / Minor Mana) in
  ALL 4 corners of their belt, picks that potion in a dropdown and clicks
  *Scan belt corners*.  The app reads the belt slots in game memory itself,
  finds the txtFileNo that appears in every corner, saves it, and auto-fills the
  rest of that potion's family (Minor → Full) from the code gap — no code
  numbers, no addresses.
- **Learned-codes preview**: the Calibrate tab shows everything learned so far
  (txtFileNo = kind/grade) and a *Clear calibration* button that falls back to
  the built-in Infernal defaults.
- **Named profiles persisted in `config/config.json`** (`combos`): the wizard
  auto-saves into a "Calibrated build" profile that is active immediately and
  survives restarts; *Use / Delete* switch or remove any saved profile.
- **Merc hireling txtFileNo override** per profile (default `338, 271`) for
  builds whose hireling id differs — Diagnostics reports every monster txtFileNo
  so the id is discoverable.
- Diagnostics now states whether the active potion table is custom or built-in
  and reports `kind` per item against the active codes.

### Changed

- `GameReader` takes `codes` / `merc_txtfiles` (defaulting to the built-in
  Infernal table + `338/271`); the UI passes the active profile.  Config grew
  `combo`/`combos` accessors (`potion_codes()`, `merc_txtfiles_set()`).
- `PotionCounts.choose_belt_column` uses the active `PotionCodes` table instead
  of the hard-coded module constants (module-level `potion_kind/grade/restore`
  still mirror the built-in defaults).
- New pure model helpers power the wizard: `belt_corner_codes()`,
  `corner_potion_code()` (single code across all belt corners) and
  `infer_potion_family()` (consecutive family fill, never re-claims codes that
  are already learned).

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
