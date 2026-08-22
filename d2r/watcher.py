"""The auto-potion decision loop.

Each tick the watcher reads a snapshot and asks :func:`refill.plan_consume` for
the drinks this tick (both stats critical -> rejuv, one stat low -> a covering
potion of that kind else rejuv, else both at their thresholds).  The merc is
handled separately with its own thresholds.  On top of the plain thresholds sit
three granular layers (see _effective_percents / _in_effect_covers /
_effective_cooldown):

* pre-drink  - when a bar is draining toward its threshold fast enough to cross
               it within the lead time, drink now so the restore-over-duration
               potion is already delivering when the bar empties; poison puts
               HP on the heal line regardless of slope (toggle: predictive_drinking),
* waste guard - never re-drink while the in-effect potion's remaining restore
               still covers the deficit (rejuv is instant and exempt),
* grade gate - same-or-stronger may follow at half duration; weaker only after
               duration x margin.

When the belt content is readable, the key is chosen grade-aware: among the
managed columns the potion with the smallest grade whose restore covers the
deficit is used (strongest available when nothing covers it).  An empty or
mismatched column is never pressed (no wrong-potion waste).
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Callable, Optional

from . import models as m
from . import refill as refill_mod
from . import input as input_mod
from .config import AppConfig
from .keys import FALLBACK_KEYS, KeySender
from .process import find_window_for_pid
from .reader import GameReader

ACTION_LABELS = {
    "heal": "Health potion",
    "mana": "Mana potion",
    "rejuv": "Rejuvenation potion",
    "merc_heal": "Merc health potion",
    "merc_rejuv": "Merc rejuv potion",
}

# Potion family a drink action consumes (for refill restocking preference).
_ACTION_KIND = {
    "heal": "heal", "mana": "mana", "rejuv": "rejuv",
    "merc_heal": "heal", "merc_rejuv": "rejuv",
}

# Rejuvenation restores instantly, so it only needs a short anti-spam gate.
_REJUV_COOLDOWN = 1.0

# Granular monitoring: the recent-vitals window feeds a per-stat drain slope
# (pre-drink) and the poison state flags an otherwise-invisible tick source.
# Pre-drink lead: seconds before the bar would hit its threshold, drink now so
# the potion (restore-over-duration) is already delivering when it empties.
_VITALS_WINDOW = 16
_PRE_DRINK_LEAD = 1.0


class PotionWatcher:
    def __init__(self, reader: GameReader, config: AppConfig,
                 on_event: Optional[Callable[[m.GameEvent], None]] = None):
        """Background loop that decides when to drink.  ``on_event`` receives a
        GameEvent per potion/info/error (may run on the watcher thread — the UI
        must marshal it to the main thread)."""
        self.reader = reader
        self.config = config
        self.on_event = on_event or (lambda e: None)
        # Injectable clock (tests drive the slope deterministically).
        self._now = time.monotonic
        # Recent (t, hp, mana) samples for the drain-slope pre-drink.
        self._vitals: deque = deque(maxlen=_VITALS_WINDOW)
        pid = getattr(getattr(reader, "proc", None), "pid", None)
        self.sender = KeySender(config, pid=pid)

        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_used: dict[str, float] = {}
        # Restore duration (seconds) + potion grade of the potion most recently
        # drunk per action; 0 / -1 = unknown (belt unreadable) -> fall back to
        # the config cooldown for the gate.
        self._last_potion_dur: dict[str, float] = {}
        self._last_potion_grade: dict[str, int] = {}
        self._last_potion_txt: dict[str, int] = {}
        self._out_of_stock: set[str] = set()   # actions currently reported empty
        self._lock = threading.Lock()
        self._last_snapshot = m.PlayerSnapshot()
        self._potion_uses = 0
        # Belt refill state: last consumed family (restock preference), tick
        # timestamp for the click throttle, and one-shot warnings.
        self._last_kind: str = ""
        self._refill_last = 0.0
        self._warned: set[str] = set()

        # Session metrics (per-action counts, error count, first-tick timestamp).
        self._counts: dict[str, int] = {k: 0 for k in ACTION_LABELS}
        self._error_count = 0
        self._started = time.monotonic()
        self._last_action: Optional[tuple[str, float]] = None

        self.running = False
        self.error: Optional[str] = None

    # ------------------------------------------------------------- lifecycle
    def start(self) -> None:
        """Start the watcher thread (idempotent)."""
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="potion-watcher")
        self._thread.start()

    def stop(self) -> None:
        """Signal the loop to stop and wait for it to exit."""
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None
        self.running = False

    # ---------------------------------------------------------------- state
    def snapshot(self) -> m.PlayerSnapshot:
        """Thread-safe copy of the most recent game snapshot."""
        with self._lock:
            return self._last_snapshot

    def potion_uses(self) -> int:
        """Total potion keys successfully sent."""
        with self._lock:
            return self._potion_uses

    def counts(self) -> dict[str, int]:
        """Per-action potion counts for this session (thread-safe copy)."""
        with self._lock:
            return dict(self._counts)

    def error_count(self) -> int:
        with self._lock:
            return self._error_count

    def uptime(self) -> float:
        """Seconds since the watcher thread was created."""
        return time.monotonic() - self._started

    def last_action(self) -> Optional[tuple[str, float]]:
        """Most recent (action, monotonic-time) potion use, or None."""
        with self._lock:
            return self._last_action

    def stats(self) -> dict:
        """Summary dict for the Dashboard stats row."""
        with self._lock:
            return {
                "counts": dict(self._counts),
                "total": self._potion_uses,
                "errors": self._error_count,
                "uptime": time.monotonic() - self._started,
                "last_action": self._last_action,
            }

    def _emit(self, kind: str, message: str, snap: m.PlayerSnapshot) -> None:
        if kind == "error":
            with self._lock:
                self._error_count += 1
        try:
            self.on_event(m.GameEvent(
                kind=kind, message=message,
                hp=snap.hp, mana=snap.mana,
                hp_percent=snap.hp_percent, mana_percent=snap.mana_percent,
                merc_percent=snap.merc_hp_percent, timestamp=time.time(),
            ))
        except Exception:  # a consumer error must never kill the watcher loop
            pass

    # ------------------------------------------------------------------ loop
    def _loop(self) -> None:
        """Watcher main loop: poll a snapshot, act, sleep until the next tick.

        One tick is fully guarded so a single bad read can never kill the
        thread (which previously froze the dashboard and stopped potions)."""
        self.running = True
        self.error = None
        reported_connected = False
        # Bound before the loop so the guard below can never NameError on a
        # corrupt persisted interval (or a first-tick read failure).
        snap = m.PlayerSnapshot()
        interval = max(50, int(self.config.behavior.get("poll_interval_ms", 150))) / 1000.0

        while not self._stop.is_set():
            try:
                started = time.monotonic()
                interval = max(50, int(self.config.behavior.get("poll_interval_ms", 150))) / 1000.0
                self.reader.max_override = self.config.max_override
                snap = self.reader.snapshot()
                # A fixed class override replaces the auto-detected one; the
                # reader already refreshed codes.player_class from the game.
                override = self.config.potion_class()
                if override:
                    self.reader.codes.player_class = override

                with self._lock:
                    self._last_snapshot = snap

                if snap.error:
                    if self.error != snap.error:
                        self.error = snap.error
                        self._emit("error", snap.error, snap)

                if not reported_connected and snap.in_game:
                    reported_connected = True
                    self._emit("info", "Connected - auto potion active.", snap)
                if not snap.in_game:
                    reported_connected = False

                if self._should_act(snap):
                    self._tick(snap)

                if snap.in_game:
                    self._refill_if_open(snap)

                elapsed = time.monotonic() - started
                if elapsed < interval:
                    self._stop.wait(interval - elapsed)
            except Exception as exc:  # never let one bad tick kill the watcher
                self.error = str(exc)
                self._emit("error", f"watcher loop error: {exc}", snap if "snap" in dir() else m.PlayerSnapshot())
                self._stop.wait(interval)
        self.running = False

    def _should_act(self, snap: m.PlayerSnapshot) -> bool:
        """Gate: enabled, in a live game, player alive, and no blocking menu open."""
        if not self.config.enabled:
            return False
        if not snap.in_game or not snap.alive:
            return False
        if self.config.behavior.get("pause_when_menus_open", True) and snap.menus_open:
            return False
        return True

    def _tick(self, snap: m.PlayerSnapshot) -> None:
        """Decide which potion (if any) to drink this tick.

        One decision path (no tiers): ``plan_consume`` picks the best potion
        across the whole managed belt — a covering potion of the wanted kind,
        else a rejuv (covers both), else any potion of that kind even
        under-strength (never wasted).  When only one stat is low the specific
        potion is preferred over rejuv; when both are critical a rejuv wins,
        else the heal and mana that are present are both drunk.  The merc is
        handled separately with its own thresholds.  Each use is grade-aware:
        the best managed belt column for the deficit is chosen when the belt is
        readable."""
        self._smart_tick(snap)
        self._merc_tick(snap)

    def _smart_tick(self, snap: m.PlayerSnapshot) -> None:
        """Unified player decisions via :func:`refill.plan_consume` (no tiers)."""
        cfg = self.config
        t = self._now()
        self._vitals.append((t, snap.hp, snap.mana))
        # Melee-range fighting doubles the pre-drink lead: start potions even
        # earlier when something is actively swinging at us (validated rule:
        # mode-based engagement has zero town false positives).
        engaged = getattr(snap, "monsters_engaged", 0) > 0
        hp_pct, mp_pct = self._effective_percents(snap, t, lead=_PRE_DRINK_LEAD * (2 if engaged else 1))
        hp_def = max(0, snap.max_hp - snap.hp)
        mp_def = max(0, snap.max_mana - snap.mana)
        hp_critical = hp_pct <= cfg.threshold("rejuv_potion_at_life")
        mp_critical = mp_pct < cfg.threshold("rejuv_potion_at_mana")
        acts, missing = refill_mod.plan_consume(
            hp_percent=hp_pct, mana_percent=mp_pct,
            hp_def=hp_def, mp_def=mp_def,
            max_hp=snap.max_hp, max_mana=snap.max_mana,
            pc=snap.potion_counts, managed=self.config.managed_columns(),
            heal_at=cfg.threshold("healing_potion_at"),
            mana_at=cfg.threshold("mana_potion_at"),
            rejuv_life=cfg.threshold("rejuv_potion_at_life"),
            rejuv_mana=cfg.threshold("rejuv_potion_at_mana"),
        )
        # Reasons show the REAL percentages: the effective percents above are
        # decision inputs (pre-drink / poison clamps), not display values.
        marker = " [poison]" if snap.poisoned else ""
        for act in acts:
            if act["action"] == "heal":
                act["reason"] = f"HP {snap.hp_percent}%{marker}"
            elif act["action"] == "mana":
                act["reason"] = f"MP {snap.mana_percent}%{marker}"
            elif act["action"] == "rejuv":
                act["reason"] = (f"HP {snap.hp_percent}% / "
                                 f"MP {snap.mana_percent}%{marker}")
        for act in acts:
            kind = act["kind"]
            critical = (kind == "rejuv"
                        or (kind == "heal" and hp_critical)
                        or (kind == "mana" and mp_critical))
            self._act(act["action"], kind, act["deficit"], act["max_value"],
                      act["reason"], snap, t, critical=critical)
        # A kind reported missing is still worth a best-effort press: when the
        # belt holds potions the app cannot classify (uncalibrated codes), the
        # wanted potion may be sitting there unrecognised, so a critical stat
        # must not just sit at 0%.
        for kind in missing:
            if kind == "rejuv":
                self._act("rejuv", "rejuv", max(hp_def, mp_def),
                          max(snap.max_hp, snap.max_mana),
                          f"HP {snap.hp_percent}% / MP {snap.mana_percent}%{marker}",
                          snap, t, critical=True)
            elif kind == "heal":
                self._act("heal", "heal", hp_def, snap.max_hp,
                          f"HP {snap.hp_percent}%{marker}", snap, t, critical=True)
            elif kind == "mana":
                self._act("mana", "mana", mp_def, snap.max_mana,
                          f"MP {snap.mana_percent}%{marker}", snap, t, critical=True)

    def _merc_tick(self, snap: m.PlayerSnapshot) -> None:
        """Mercenary decisions (only when one is present and alive)."""
        cfg = self.config
        t = self._now()
        if snap.merc_alive:
            m_def = max(0, snap.merc_max_hp - snap.merc_hp)
            if snap.merc_hp_percent <= cfg.threshold("merc_rejuv_potion_at"):
                # critical=True: parity with the player's rejuv line — enables
                # reach-buried-rejuv (same config gate) and the unclassified
                # best-effort so the merc never sits at 0% with potions on belt.
                self._act("merc_rejuv", "rejuv", m_def, snap.merc_max_hp,
                          f"Merc HP {snap.merc_hp_percent}%", snap, t, critical=True)
            elif snap.merc_hp_percent <= cfg.threshold("merc_healing_potion_at"):
                self._act("merc_heal", "heal", m_def, snap.merc_max_hp,
                          f"Merc HP {snap.merc_hp_percent}%", snap, t)

    def _predict_drop(self, max_value: int, threshold_pct: int,
                      series: int = 0) -> float | None:
        """Seconds until the stat drains to ``threshold_pct`` of ``max_value``.

        Slope over the recent-vitals window (series 0 = HP, 1 = mana); None when
        the window is too short, the stat is not draining, or it is already
        at/below the line (the regular thresholds then apply, not a prediction)."""
        if max_value <= 0 or len(self._vitals) < 2:
            return None
        t0, v0 = self._vitals[0][0], self._vitals[0][1 + series]
        t1, v1 = self._vitals[-1][0], self._vitals[-1][1 + series]
        dt = t1 - t0
        if dt <= 0:
            return None
        slope = (v1 - v0) / dt
        if slope >= 0:
            return None
        limit = max_value * threshold_pct / 100.0
        if v1 <= limit:
            return 0.0
        return (v1 - limit) / (-slope)

    def _effective_percents(self, snap: m.PlayerSnapshot, now: float,
                            lead: float = _PRE_DRINK_LEAD) -> tuple:
        """HP/MP percentages after granular-urgency adjustments.

        Pre-drink: when a stat is draining toward its threshold fast enough to
        cross it within the lead time, the decision sees it as already there so
        the potion starts restoring before the bar empties (potion restore
        happens over a duration, not instantly).  Poison: damage keeps ticking
        in otherwise-safe situations (town, after a fight) and slow poison may
        not register on the slope — the state alone puts HP on the heal line so
        the app drinks before it hurts.  Both feed the normal decision path, so
        cooldowns, the waste guard, managed columns and out-of-stock still apply."""
        cfg = self.config
        if not cfg.behavior.get("predictive_drinking", True):
            return snap.hp_percent, snap.mana_percent
        hp_pct = snap.hp_percent
        mp_pct = snap.mana_percent
        dt_hp = self._predict_drop(snap.max_hp,
                                   cfg.threshold("healing_potion_at"), series=0)
        if dt_hp is not None and dt_hp <= lead:
            hp_pct = min(hp_pct, cfg.threshold("healing_potion_at") - 1)
        dt_mp = self._predict_drop(snap.max_mana,
                                   cfg.threshold("mana_potion_at"), series=1)
        if dt_mp is not None and dt_mp <= lead:
            mp_pct = min(mp_pct, cfg.threshold("mana_potion_at") - 1)
        if snap.poisoned:
            hp_pct = min(hp_pct, cfg.threshold("healing_potion_at") - 1)
        return hp_pct, mp_pct

    def _pick(self, kind: str, deficit: int, max_value: int,
              snap: m.PlayerSnapshot, critical: bool = False) -> m.BeltColumn | None | bool:
        """Choose the belt column to drink from.

        Returns the BeltColumn to drink, False when the belt is known to have no
        usable potion of ``kind`` in the managed columns (the key is NOT pressed
        rather than waste a mismatched potion), or None when the belt content is
        unreadable (the caller falls back to the action's default key)."""
        pc = snap.potion_counts
        if not pc.ok:
            return None
        # Any managed column may serve any action: the potion type is read from
        # the slot, so there are no per-potion key bindings (since 1.8.0).
        allowed = tuple(self.config.managed_columns())
        idx = pc.choose_belt_column(kind, deficit, max_value, allowed_keys=allowed)
        if idx is None:
            # Normal selection failed - try reach buried rejuv if enabled and critical
            if self.config.reach_buried_rejuv and critical and kind == "rejuv":
                idx = self._find_reachable_rejuv(snap)
                if idx is not None:
                    return next((c for c in pc.columns if c.index == idx), False)
            return False
        return next((c for c in pc.columns if c.index == idx), False)

    def _find_reachable_rejuv(self, snap: m.PlayerSnapshot) -> int | None:
        """Find a column where a rejuv is reachable by drinking potions above it.

        A rejuv is reachable if:
        - It's in row 1, 2, or 3 of a managed column
        - All slots between it and row 0 are filled (no empty slots)
        - Row 0 has a potion we can drink to make the rejuv drop down
        """
        pc = snap.potion_counts
        if not pc.ok:
            return None

        # Check each column for a reachable rejuv
        for col in pc.columns:
            if col.count == 0:  # Row 0 must have a potion to drink
                continue
            col_idx = col.index
            # Look for rejuv in rows 1-3 (slots 4-15)
            for slot in range(4, min(pc.belt_rows * 4, 16)):
                if slot // 4 <= 0:  # Only rows 1+
                    continue
                if slot % 4 != col_idx:
                    continue
                kind = pc.belt_slots.get(slot)
                if kind == "rejuv":
                    # Check no empty slots between this slot and row 0
                    reachable = True
                    for check_slot in range(4, slot):
                        if check_slot % 4 == col_idx:
                            if check_slot not in pc.belt_filled:
                                reachable = False
                                break
                    if reachable:
                        return col_idx
        return None

    def _act(self, action: str, kind: str, deficit: int, max_value: int,
             reason: str, snap: m.PlayerSnapshot, t: float,
             critical: bool = False) -> bool:
        """Grade-aware drink for one action: pick a column (or skip if the belt
        has no potion of the needed kind), apply the grade-aware gate, then press
        that column's key.  Returns True when a drink was actually attempted
        (a usable column existed and the cooldown allowed it).

        On a *critical* stat with no potion of the wanted kind on the managed
        belt, an unclassified column is still drunk as a best-effort (the potion
        may simply be uncalibrated for this build) instead of sitting at 0%."""
        col = self._pick(kind, deficit, max_value, snap, critical=critical)
        if col is False:
            if critical:
                col = self._unclassified_column(action, snap.potion_counts)
                if col is not None:
                    if not self._ready(action, t):
                        return False
                    self._out_of_stock.discard(action)
                    self._warn_once(
                        f"{action}-unclassified",
                        f"No recognised {kind} potion is on the managed belt, but "
                        f"unidentified potions are present - pressing column "
                        f"{col.key} as a best effort.  Teach the app your potion "
                        f"codes in the Calibrate tab for exact drinking.", snap)
                    self._use(action, reason, snap, column=col)
                    return True
            if action not in self._out_of_stock:
                self._out_of_stock.add(action)
                self._emit("info", f"No {kind} potion left on the belt.", snap)
            return False
        # Stock exists again: a later absence may announce itself once more.
        self._out_of_stock.discard(action)
        if isinstance(col, m.BeltColumn) and self._in_effect_covers(
                action, deficit, max_value, t):
            return False
        grade = col.grade if isinstance(col, m.BeltColumn) else -1
        if not self._ready(action, t, candidate_grade=grade):
            return False
        self._out_of_stock.discard(action)
        self._use(action, reason, snap, column=col)
        return True

    def _unclassified_column(self, action: str, pc) -> m.BeltColumn | None:
        """Managed column holding a potion the app cannot classify.

        Used only as a critical best-effort: the column's potion is on the belt
        but its txtFileNo is not in the active codes (game version/mods not
        calibrated), so the wanted kind may be sitting there unrecognised.  The
        action's standard column (heal Q / mana W / rejuv E) is tried first,
        then any unclassified managed column."""
        if not getattr(pc, "ok", False):
            return None
        managed = set(self.config.managed_indices())
        letter = FALLBACK_KEYS.get(action, "")
        if letter and letter in m.BELT_COLUMN_KEYS:
            idx = m.BELT_COLUMN_KEYS.index(letter)
            col = next((c for c in pc.columns
                        if c.index == idx and c.count > 0 and c.kind is None), None)
            if col is not None:
                return col
        return next((c for c in pc.columns
                     if c.index in managed and c.count > 0 and c.kind is None),
                    None)

    def _ready(self, action: str, now: float, candidate_grade: int = -1) -> bool:
        """True once this action's cooldown has elapsed since its last press.

        ``candidate_grade`` is the grade of the potion about to be drunk; a
        same-or-higher grade unlocks after half the in-effect potion's duration,
        a weaker one only after the full duration x margin (see
        :meth:`_effective_cooldown`)."""
        return now - self._last_used.get(action, 0.0) >= self._effective_cooldown(action, candidate_grade)

    def _effective_cooldown(self, action: str, candidate_grade: int = -1) -> float:
        """Seconds before the same potion action may fire again.

        Potions restore over a duration.  A potion of the same or higher grade
        may be drunk once the in-effect potion is half consumed (keeps the strong
        potion's fill rate while topping up sooner); a weaker or unknown-grade
        potion waits the full duration x margin so it never drags the fill rate
        down.  Rejuv is instant and uses a short fixed gate.  Config cooldowns
        are the fallback while the potion on the belt is unknown."""
        if action in ("rejuv", "merc_rejuv"):
            return _REJUV_COOLDOWN
        duration = self._last_potion_dur.get(action, 0.0)
        if duration > 0:
            last_grade = self._last_potion_grade.get(action, -1)
            if candidate_grade >= 0 and last_grade >= 0 and candidate_grade >= last_grade:
                return duration * 0.5
            return duration * self.config.potion_margin()
        return self.config.cooldown(action)

    def _in_effect_covers(self, action: str, deficit: int, max_value: int,
                          now: float) -> bool:
        """True when the potion still restoring for ``action`` has enough
        remaining restore to cover the current deficit.

        Waste guard: heal/mana potions restore over a duration, so the
        half-duration cooldown is about fill RATE, not need.  Drinking again
        while the in-effect potion alone would finish the job just burns
        potions (e.g. a Super mana potion re-drunk at 60% because its total
        restore would have topped mana up fully)."""
        if action in ("rejuv", "merc_rejuv"):
            return False
        dur = self._last_potion_dur.get(action, 0.0)
        txt = self._last_potion_txt.get(action, 0)
        if dur <= 0 or not txt:
            return False
        elapsed = now - self._last_used.get(action, 0.0)
        if elapsed <= 0 or elapsed >= dur:
            return False
        codes = getattr(self.reader, "codes", None)
        if codes is None:
            return False
        total = codes.restore(txt, max_value, codes.player_class)
        if total <= 0:
            return False
        remaining = total * (1.0 - elapsed / dur)
        return remaining >= deficit

    def _use(self, action: str, reason: str, snap: m.PlayerSnapshot,
             column: m.BeltColumn | None = None) -> None:
        """Press the key for 'action' (a specific belt column when given) and log
        the outcome (success or UIPI-block)."""
        key = self.config.belt_key(column.index) if column is not None else None
        ok = self.sender.press(action, key=key)
        now = self._now()
        self._last_used[action] = now
        self._last_kind = _ACTION_KIND.get(action, "")
        if ok:
            # Remember the drunk potion's restore duration + grade so the derived
            # cooldown can gate repeats: same/higher after half the duration,
            # weaker only after the full duration x margin.
            duration = 0.0
            grade = -1
            if column is not None and snap.potion_counts.ok:
                codes = getattr(self.reader, "codes", None)
                if column.txt and codes is not None:
                    duration = codes.duration(column.txt)
                    grade = column.grade
            self._last_potion_dur[action] = duration
            self._last_potion_grade[action] = grade
            self._last_potion_txt[action] = column.txt if column else 0
            with self._lock:
                self._potion_uses += 1
                self._counts[action] = self._counts.get(action, 0) + 1
                self._last_action = (action, now)
            self._emit(action, f"{ACTION_LABELS[action]} ({reason})", snap)
        else:
            self._emit("error", f"Key send FAILED for {ACTION_LABELS[action]} (check game is not running as admin / tool is not blocked).", snap)

    # ------------------------------------------------------------- refill
    def _warn_once(self, key: str, message: str, snap: m.PlayerSnapshot) -> None:
        if key not in self._warned:
            self._warned.add(key)
            self._emit("info", message, snap)

    def _refill_if_open(self, snap: m.PlayerSnapshot) -> None:
        """Belt refill: while the inventory panel is open, move one potion per
        interval — either relocate a potion sitting in the wrong column, or
        click a matching inventory potion into an empty managed belt slot.

        Each step is TWO clicks: pick the potion up, then drop it into the
        target belt slot (a single click only lifts the potion onto the cursor
        — that is why refills used to never actually happen).  Smart tier
        follows the per-slot layout + column-family plan; plain tier restocks
        whatever family was last drunk.  Only runs when the game window is
        foreground so the clicks land on the game, never on another app."""
        cfg = self.config
        if not cfg.refill_enabled():
            return
        if not snap.in_game or "Inventory" not in snap.open_menu_names:
            return
        inv_map = cfg.refill_mapping()
        belt_map = cfg.belt_refill_mapping()
        if not inv_map.get("calibrated") or not belt_map.get("calibrated"):
            missing = []
            if not inv_map.get("calibrated"):
                missing.append("inventory")
            if not belt_map.get("calibrated"):
                missing.append("belt panel")
            self._warn_once(
                "refill-not-calibrated",
                "Belt refill is enabled but the "
                + (" and ".join(missing))
                + " click position is not calibrated "
                "(Keys tab > Belt refill > Calibrate).", snap)
            return
        now = time.monotonic()
        if now - self._refill_last < cfg.refill_interval():
            return
        proc = getattr(self.reader, "proc", None)
        if proc is None or not proc.pid:
            return
        if not input_mod.game_foreground(proc.pid):
            return
        hwnd = find_window_for_pid(proc.pid)
        if not hwnd:
            return
        rect = input_mod.window_rect(hwnd)
        if not rect:
            return
        pc = snap.potion_counts
        if not pc.ok:
            return
        managed = cfg.managed_indices()
        cols = len(m.BELT_COLUMN_KEYS)
        empty = [x for x in pc.belt_empty if (x % cols) in managed]
        if not empty:
            return
        if self.config.smart_enabled():
            # Layout-aware refill: relocate misplaced potions first, then fill
            # empty slots per the per-slot plan (falls back to last-drunk kind).
            moves = refill_mod.plan_moves(
                pc.belt_slots, self.config.belt_layout(), pc.belt_empty)
            moves = [mv for mv in moves
                     if (mv["from"] % cols) in managed and (mv["to"] % cols) in managed]
            if moves:
                step = moves[0]
            else:
                plan = refill_mod.plan_layout_refill(
                    empty, pc.belt_slots, self.reader.inventory_potions(),
                    self.config.belt_layout(), last_kind=self._last_kind or None)
                if not plan:
                    return
                step = {"action": "refill", "slot": plan[0]["slot"],
                        "potion": plan[0]["potion"]}
        else:
            # Basic refill: restock what was just drunk, else any potion.
            plan = refill_mod.plan_refills(empty, self.reader.inventory_potions(),
                                           last_kind=self._last_kind or None)
            if not plan:
                return
            step = {"action": "refill", "slot": plan[0]["slot"],
                    "potion": plan[0]["potion"]}
        self._exec_refill_step(rect, step, inv_map, belt_map, snap)
        self._refill_last = now

    def _belt_slot_pos(self, rect, slot: int, belt_map: dict, rows: int):
        """Screen (x, y) of the centre of belt ``slot`` for a calibrated belt
        panel.  Slot X = memory row * 4 + column; the UI draws row 0 on TOP,
        so the screen row is ``(rows - 1) - memory_row``."""
        cols = len(m.BELT_COLUMN_KEYS)
        col = slot % cols
        ui_row = max(0, int(rows) - 1) - (slot // cols)
        cell = float(belt_map.get("cell", 29.0))
        return (rect[0] + float(belt_map["origin_x"]) + (col + 0.5) * cell,
                rect[1] + float(belt_map["origin_y"]) + (ui_row + 0.5) * cell)

    def _exec_refill_step(self, rect, step: dict, inv_map: dict, belt_map: dict,
                          snap: m.PlayerSnapshot) -> None:
        """Execute one refill/move step: two clicks (pickup, then drop)."""
        rows = snap.potion_counts.belt_rows
        if step.get("action") == "move":
            fx, fy = self._belt_slot_pos(rect, step["from"], belt_map, rows)
            tx, ty = self._belt_slot_pos(rect, step["to"], belt_map, rows)
            first = input_mod.click_at(fx, fy)
            second = input_mod.click_at(tx, ty) if first else False
            if first and second:
                self._emit("info", f"Refill: moved a {step['kind']} potion to the correct column.", snap)
            else:
                self._emit("error", "Belt move click failed (SendInput blocked or window lost focus).", snap)
            return
        potion = step["potion"]
        cell = float(inv_map.get("cell", 29.0))
        sx = rect[0] + float(inv_map["origin_x"]) + (float(potion["x"]) + 0.5) * cell
        sy = rect[1] + float(inv_map["origin_y"]) + (float(potion["y"]) + 0.5) * cell
        first = input_mod.click_at(sx, sy)
        second = False
        if first:
            tx, ty = self._belt_slot_pos(rect, step["slot"], belt_map, rows)
            second = input_mod.click_at(tx, ty)
        if first and second:
            self._emit("info", f"Refill: clicked a {potion['kind']} potion into the belt.", snap)
        else:
            self._emit("error", "Belt refill click failed (SendInput blocked or window lost focus).", snap)
