"""The auto-potion decision loop.

Logic ported from cmd/lifewatcher/watcher.go.  Each tick it reads a snapshot and
decides which belt key to press:

    if HP% <= rejuv_at_life  OR  MP% < rejuv_at_mana : rejuv
    elif HP% <= heal_at                               : health potion
    elif MP% <= mana_at                               : mana potion
    if merc alive:
        if merc HP% <= merc_rejuv_at : Shift + rejuv   (preferred)
        elif merc HP% <= merc_heal_at: Shift + heal
"""

from __future__ import annotations

import threading
import time
from typing import Callable, Optional

from . import models as m
from .config import AppConfig
from .keys import KeySender
from .reader import GameReader

ACTION_LABELS = {
    "heal": "Health potion",
    "mana": "Mana potion",
    "rejuv": "Rejuvenation potion",
    "merc_heal": "Merc health potion",
    "merc_rejuv": "Merc rejuv potion",
}


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
        self._lock = threading.Lock()
        self._last_snapshot = m.PlayerSnapshot()
        self._potion_uses = 0

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

        Rejuvenation wins when HP or MP is critical; otherwise heal/mana are
        checked independently (a frame can legitimately drink both).  The merc
        is handled separately with its own thresholds, heal preferred over
        rejuv when the merc is merely hurt."""
        cfg = self.config
        t = time.monotonic()

        use_rejuv = (snap.hp_percent <= cfg.threshold("rejuv_potion_at_life")
                     or snap.mana_percent < cfg.threshold("rejuv_potion_at_mana"))
        if use_rejuv and self._ready("rejuv", t):
            self._use("rejuv", f"HP {snap.hp_percent}% / MP {snap.mana_percent}%", snap)
        else:
            if snap.hp_percent <= cfg.threshold("healing_potion_at") and self._ready("heal", t):
                self._use("heal", f"HP {snap.hp_percent}%", snap)
            if snap.mana_percent <= cfg.threshold("mana_potion_at") and self._ready("mana", t):
                self._use("mana", f"MP {snap.mana_percent}%", snap)

        # Mercenary (only when one is present).
        if snap.merc_alive:
            if snap.merc_hp_percent <= cfg.threshold("merc_rejuv_potion_at") and self._ready("merc_rejuv", t):
                self._use("merc_rejuv", f"Merc HP {snap.merc_hp_percent}%", snap)
            elif snap.merc_hp_percent <= cfg.threshold("merc_healing_potion_at") and self._ready("merc_heal", t):
                self._use("merc_heal", f"Merc HP {snap.merc_hp_percent}%", snap)

    def _ready(self, action: str, now: float) -> bool:
        """True once this action's cooldown has elapsed since its last press."""
        return now - self._last_used.get(action, 0.0) >= self.config.cooldown(action)

    def _use(self, action: str, reason: str, snap: m.PlayerSnapshot) -> None:
        """Press the key for 'action' and log the outcome (success or UIPI-block)."""
        ok = self.sender.press(action)
        now = time.monotonic()
        self._last_used[action] = now
        if ok:
            with self._lock:
                self._potion_uses += 1
                self._counts[action] = self._counts.get(action, 0) + 1
                self._last_action = (action, now)
            self._emit(action, f"{ACTION_LABELS[action]} ({reason})", snap)
        else:
            self._emit("error", f"Key send FAILED for {ACTION_LABELS[action]} (check game is not running as admin / tool is not blocked).", snap)
