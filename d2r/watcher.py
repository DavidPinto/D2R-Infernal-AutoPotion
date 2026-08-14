"""The auto-potion decision loop.

Logic ported from cmd/lifewatcher/watcher.go.  Each tick it reads a snapshot and
decides which belt key to press:

    if HP% <= rejuv_at_life  OR  MP% < rejuv_at_mana : rejuv
    elif HP% <= heal_at                               : health potion
    elif MP% <= mana_at                               : mana potion
    if merc alive:
        if merc HP% <= merc_rejuv_at : Shift + rejuv   (preferred)
        elif merc HP% <= merc_heal_at: Shift + heal

When the belt content is readable, the key is chosen grade-aware: among the belt
columns bound to the action, the potion with the smallest grade whose restore
covers the deficit is used (strongest available when nothing covers it).  An
empty/mismatched column is never pressed (no wrong potion waste).
"""

from __future__ import annotations

import threading
import time
from typing import Callable, Optional

from . import models as m
from . import refill as refill_mod
from . import input as input_mod
from .config import AppConfig
from .keys import KeySender
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


class PotionWatcher:
    def __init__(self, reader: GameReader, config: AppConfig,
                 on_event: Optional[Callable[[m.GameEvent], None]] = None):
        """Background loop that decides when to drink.  ``on_event`` receives a
        GameEvent per potion/info/error (may run on the watcher thread — the UI
        must marshal it to the main thread)."""
        self.reader = reader
        self.config = config
        self.on_event = on_event or (lambda e: None)
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
        """Gate: armed, in a live game, player alive, and no blocking menu open."""
        if not self.config.enabled:
            return False
        if not snap.in_game or not snap.alive:
            return False
        if self.config.behavior.get("pause_when_menus_open", True) and snap.menus_open:
            return False
        return True

    def _tick(self, snap: m.PlayerSnapshot) -> None:
        """Decide which potion (if any) to drink this tick.

        Smart tier (default): ``plan_consume`` picks the best potion across the
        whole managed belt, preferring a specific potion over a rejuv when only
        one stat is low.  Plain tier: rejuv wins when HP or MP is critical,
        otherwise heal/mana are checked independently.  The merc is always
        handled separately with its own thresholds, heal preferred over rejuv
        when the merc is merely hurt.  Each use is grade-aware: the best managed
        belt column for the deficit is chosen when the belt is readable."""
        if self.config.smart_enabled():
            self._smart_tick(snap)
        else:
            self._plain_tick(snap)
        self._merc_tick(snap)

    def _plain_tick(self, snap: m.PlayerSnapshot) -> None:
        """Plain-tier player decisions (rejuv-wins-if-critical, then heal/mana)."""
        cfg = self.config
        t = time.monotonic()

        hp_def = max(0, snap.max_hp - snap.hp)
        mp_def = max(0, snap.max_mana - snap.mana)

        use_rejuv = (snap.hp_percent <= cfg.threshold("rejuv_potion_at_life")
                     or snap.mana_percent < cfg.threshold("rejuv_potion_at_mana"))
        if use_rejuv:
            self._act("rejuv", "rejuv", max(hp_def, mp_def), max(snap.max_hp, snap.max_mana),
                      f"HP {snap.hp_percent}% / MP {snap.mana_percent}%", snap, t)
        else:
            if snap.hp_percent <= cfg.threshold("healing_potion_at"):
                self._act("heal", "heal", hp_def, snap.max_hp, f"HP {snap.hp_percent}%", snap, t)
            if snap.mana_percent <= cfg.threshold("mana_potion_at"):
                self._act("mana", "mana", mp_def, snap.max_mana, f"MP {snap.mana_percent}%", snap, t)

    def _smart_tick(self, snap: m.PlayerSnapshot) -> None:
        """Smart-tier player decisions via :func:`refill.plan_consume`."""
        cfg = self.config
        t = time.monotonic()
        hp_def = max(0, snap.max_hp - snap.hp)
        mp_def = max(0, snap.max_mana - snap.mana)
        acts, missing = refill_mod.plan_consume(
            hp_percent=snap.hp_percent, mana_percent=snap.mana_percent,
            hp_def=hp_def, mp_def=mp_def,
            max_hp=snap.max_hp, max_mana=snap.max_mana,
            pc=snap.potion_counts, managed=self.config.managed_columns(),
            heal_at=cfg.threshold("healing_potion_at"),
            mana_at=cfg.threshold("mana_potion_at"),
            rejuv_life=cfg.threshold("rejuv_potion_at_life"),
            rejuv_mana=cfg.threshold("rejuv_potion_at_mana"),
        )
        for kind in missing:
            action = kind
            if action not in self._out_of_stock:
                self._out_of_stock.add(action)
                self._emit("info", f"No {kind} potion left on the belt.", snap)
        for act in acts:
            self._act(act["action"], act["kind"], act["deficit"], act["max_value"],
                      act["reason"], snap, t)

    def _merc_tick(self, snap: m.PlayerSnapshot) -> None:
        """Mercenary decisions (only when one is present and alive)."""
        cfg = self.config
        t = time.monotonic()
        if snap.merc_alive:
            m_def = max(0, snap.merc_max_hp - snap.merc_hp)
            if snap.merc_hp_percent <= cfg.threshold("merc_rejuv_potion_at"):
                self._act("merc_rejuv", "rejuv", m_def, snap.merc_max_hp,
                          f"Merc HP {snap.merc_hp_percent}%", snap, t)
            elif snap.merc_hp_percent <= cfg.threshold("merc_healing_potion_at"):
                self._act("merc_heal", "heal", m_def, snap.merc_max_hp,
                          f"Merc HP {snap.merc_hp_percent}%", snap, t)

    def _pick(self, kind: str, deficit: int, max_value: int,
              snap: m.PlayerSnapshot) -> m.BeltColumn | None | bool:
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
            return False
        return next((c for c in pc.columns if c.index == idx), False)

    def _act(self, action: str, kind: str, deficit: int, max_value: int,
             reason: str, snap: m.PlayerSnapshot, t: float) -> None:
        """Grade-aware drink for one action: pick a column (or skip if the belt
        has no potion of the needed kind), apply the grade-aware gate, then press
        that column's key."""
        col = self._pick(kind, deficit, max_value, snap)
        if col is False:
            if action not in self._out_of_stock:
                self._out_of_stock.add(action)
                self._emit("info", f"No {kind} potion left on the belt.", snap)
            return
        grade = col.grade if isinstance(col, m.BeltColumn) else -1
        if not self._ready(action, t, candidate_grade=grade):
            return
        self._out_of_stock.discard(action)
        self._use(action, reason, snap, column=col)

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

    def _use(self, action: str, reason: str, snap: m.PlayerSnapshot,
             column: m.BeltColumn | None = None) -> None:
        """Press the key for 'action' (a specific belt column when given) and log
        the outcome (success or UIPI-block)."""
        key = m.BELT_COLUMN_KEYS[column.index] if column is not None else None
        ok = self.sender.press(action, key=key)
        now = time.monotonic()
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
        """Belt refill: while the inventory panel is open, click one matching
        inventory potion per interval into the first empty managed belt slot.

        Plain tier restocks whatever family was last drunk; smart tier follows
        the per-slot layout + ratio plan.  Only runs when the game window is
        foreground so the click lands on the game, never on another app."""
        cfg = self.config
        if not cfg.refill_enabled():
            return
        if not snap.in_game or "Inventory" not in snap.open_menu_names:
            return
        mapping = cfg.refill_mapping()
        if not mapping.get("calibrated"):
            self._warn_once(
                "refill-not-calibrated",
                "Belt refill is enabled but click positions are not calibrated "
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
        pc = snap.potion_counts
        if not pc.ok:
            return
        managed = cfg.managed_indices()
        empty = [x for x in pc.belt_empty if (x % len(m.BELT_COLUMN_KEYS)) in managed]
        if not empty:
            return
        if self.config.smart_enabled():
            plan = refill_mod.plan_layout_refill(
                empty, pc.belt_slots, self.reader.inventory_potions(),
                self.config.belt_layout(), last_kind=self._last_kind or None)
        else:
            plan = refill_mod.plan_refills(empty, self.reader.inventory_potions(),
                                           last_kind=self._last_kind or None)
        if not plan:
            return
        choice = plan[0]
        potion = choice["potion"]
        rect = input_mod.window_rect(hwnd)
        if not rect:
            return
        cell = float(mapping.get("cell", 29.0))
        sx = rect[0] + float(mapping["origin_x"]) + (float(potion["x"]) + 0.5) * cell
        sy = rect[1] + float(mapping["origin_y"]) + (float(potion["y"]) + 0.5) * cell
        ok = input_mod.click_at(sx, sy)
        self._refill_last = now
        if ok:
            self._emit("info", f"Refill: clicked a {potion['kind']} potion to the belt.", snap)
        else:
            self._emit("error", "Belt refill click failed (SendInput blocked or window lost focus).", snap)
