"""Real-time heal-potion scanner: what does stat id 74 track?

Run while playing (read-only, never sends input):

    python tools\\potion_scan.py

Waits for stat 74 to appear (i.e. you drink a heal-over-time potion), then
captures its full curve at ~20 ms resolution together with HP and the
Healthpot state bit, until the stat disappears (+2 s tail).  Multiple drinks
are captured as separate blocks; Ctrl+C prints a summary and exits.

Analysis goal: decide whether stat 74 is the engine's remaining-heal pool
(would make the watcher's waste guard exact) by comparing the captured curves
against the known potion table:

    tier      duration   group0  group1  group2
    Minor       7.68 s     30      45      60
    Light       6.40 s     60      90     120
    Healing     6.84 s    100     150     200
    Greater     7.68 s    180     270     360
    Super      10.24 s    320     480     640

Full samples go to config/potion_scan.log.  Auto-stops after 10 minutes.
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from d2r.process import Process, find_d2r_processes  # noqa: E402
from d2r.reader import GameReader  # noqa: E402
from d2r import models as m  # noqa: E402

LOG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "config", "potion_scan.log")
POLL_SEC = 0.02
STAT_ID = 74
MAX_RUN_SEC = 600.0
HEALTHPOT_STATE_ID = 100   # word 3, bit 4


def main() -> int:
    sys.stdout.reconfigure(line_buffering=True)
    pids = find_d2r_processes()
    if not pids:
        print("D2R.exe is not running - start the game, then run this again.")
        return 1
    proc = Process.attach(pids[0])
    r = GameReader(proc)
    unit, _ = r._find_player_unit()
    if not unit:
        print("Not in a game (no player unit). Run while in-game.")
        return 1
    slex = proc.read_ptr(unit + m.UNIT_OFFSET_STATSLISTEX)

    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    log = open(LOG_PATH, "w", encoding="utf-8")
    print(f"Watching for stat {STAT_ID} (drink a heal-over-time potion).")
    print(f"Log: {LOG_PATH}   Ctrl+C to stop.\n")

    def read_now():
        slex_now = proc.read_ptr(unit + m.UNIT_OFFSET_STATSLISTEX) or slex
        sp = proc.read_ptr(slex_now + m.STATSLIST_STAT_PTR)
        sc = proc.read_ptr(slex_now + m.STATSLIST_STAT_COUNT)
        raw = r._read_stats(sp, sc)
        # State 100 lives in word 3 (bit 100 % 32).
        w = proc.read_u32(slex_now + m.STATSLIST_STATES_OFFSET
                          + (HEALTHPOT_STATE_ID // 32) * 4)
        healthpot = bool(w & (1 << (HEALTHPOT_STATE_ID % 32)))
        hp = raw.get(m.STAT["Life"], 0) >> 8
        return raw.get(STAT_ID), hp, healthpot

    captures: list[dict] = []
    cur: dict | None = None
    last_seen = 0.0
    t0 = time.monotonic()

    try:
        while time.monotonic() - t0 < MAX_RUN_SEC:
            time.sleep(POLL_SEC)
            val, hp, hpot = read_now()
            now = time.monotonic() - t0

            if cur is None:
                if val is not None and val > 0:
                    cur = {"start": now, "rows": [], "start_val": val,
                           "start_hp": hp}
                    msg = f">>> t={now:7.2f}  CAPTURE #{len(captures) + 1} START (stat={val}, hp={hp})"
                    print(msg)
                    log.write(msg + "\n")
            else:
                cur["rows"].append((now - cur["start"], val, hp, hpot))
                log.write(f"c{len(captures)} t={now - cur['start']:6.2f} "
                          f"s74={val} hp={hp} hpot={int(hpot)}\n")
                if val is not None and val > 0:
                    last_seen = now
                elif now - last_seen >= 2.0:   # 2 s past the last sighting
                    captures.append(cur)
                    last_val_t = cur["rows"][-1][0]
                    msg = (f">>> t={now:7.2f}  CAPTURE #{len(captures)} END  "
                           f"duration={last_val_t:.2f}s  "
                           f"stat {cur['start_val']} -> {cur['rows'][-1][1]}  "
                           f"hp {cur['start_hp']} -> {hp}")
                    print(msg)
                    log.write(msg + "\n\n")
                    cur = None
    except KeyboardInterrupt:
        pass

    summary = ["", "=== SUMMARY ===", f"captures: {len(captures)}"]
    for n, c in enumerate(captures, 1):
        vals = [(t, v) for t, v, _, _ in c["rows"] if v is not None]
        dur = vals[-1][0] if vals else 0.0
        rate = (c["start_val"] - vals[-1][1]) / dur if dur else 0.0
        hp_start = c["rows"][0][2] if c["rows"] else c["start_hp"]
        hp_end = c["rows"][-1][2] if c["rows"] else hp_start
        summary.append(
            f"#{n}: duration={dur:.2f}s  stat {c['start_val']} -> {vals[-1][1]} "
            f"(drift {-rate:+.1f}/s)  hp {hp_start} -> {hp_end}")
    text = "\n".join(summary)
    print(text)
    log.write(text + "\n")
    log.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
