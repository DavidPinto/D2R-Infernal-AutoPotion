"""Real-time poison-state scanner for the D2R Infernal Auto Potion project.

Run while playing (read-only, never sends input):

    python tools\\poison_scan.py

It polls the player's unit-states bitfield ~20x/second and logs:
  * every state-id transition (appeared / disappeared) with timestamps,
  * the raw 6x u32 state words (so unmapped bits are still visible),
  * HP trajectory,
  * stat-list ids that appear/disappear vs the session baseline (the
    poison-length stat should show up here while poisoned).

Console output stays quiet while you play (transitions only); every sample
goes to config/poison_scan.log.  Ctrl+C stops and prints a summary.
Auto-stops after 10 minutes.
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
                        "config", "poison_scan.log")
POLL_SEC = 0.05
MAX_RUN_SEC = 600.0

STATE_NAMES = {
    0: "None", 1: "Freeze", 2: "Poison", 3: "Resistfire", 4: "Resistcold",
    5: "Resistlightning", 6: "Resistmagic", 7: "Playerbody", 8: "Resistall",
    19: "SkillMove", 43: "Stamina", 70: "Warmth", 87: "Justhit",
    104: "Healthpot", 124: "Manapot", 196: "Antidote", 199: "Staminapot",
}


def sname(sid: int) -> str:
    return f"{sid}:{STATE_NAMES.get(sid, '?')}"


def main() -> int:
    sys.stdout.reconfigure(line_buffering=True)
    pids = find_d2r_processes()
    if not pids:
        print("D2R.exe is not running - start the game, then run this again.")
        return 1
    proc = Process.attach(pids[0])
    r = GameReader(proc)
    if not r.offsets.ok:
        print("Offsets unresolved - run this while in a game.")
        return 1

    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    log = open(LOG_PATH, "w", encoding="utf-8")
    print(f"Watching for poison-state transitions ({POLL_SEC * 1000:.0f} ms poll).")
    print(f"Full sample log: {LOG_PATH}")
    print("Get poisoned now - Ctrl+C to stop and summarise.\n")

    unit, _ = r._find_player_unit()
    if not unit:
        print("Not in a game (no player unit). Run while in-game.")
        return 1

    slex = proc.read_ptr(unit + m.UNIT_OFFSET_STATSLISTEX)
    baseline_stats: set = set()

    def snapshot_states():
        slex_now = proc.read_ptr(unit + m.UNIT_OFFSET_STATSLISTEX) or slex
        words = [proc.read_u32(slex_now + m.STATSLIST_STATES_OFFSET + i * 4)
                 for i in range(6)]
        sp = proc.read_ptr(slex_now + m.STATSLIST_STAT_PTR)
        sc = proc.read_ptr(slex_now + m.STATSLIST_STAT_COUNT)
        raw = r._read_stats(sp, sc)
        hp = raw.get(m.STAT["Life"], 0) >> 8
        return words, raw, hp

    prev_words, prev_raw, prev_hp = snapshot_states()
    baseline_stats = set(prev_raw)
    prev_states = {32 * i + b for i, w in enumerate(prev_words)
                   for b in range(32) if w & (1 << b)}
    t0 = time.monotonic()
    transitions: list[tuple[float, str, str]] = []
    hp_min = hp_max = prev_hp

    try:
        while time.monotonic() - t0 < MAX_RUN_SEC:
            time.sleep(POLL_SEC)
            words, raw, hp = snapshot_states()
            now = time.monotonic() - t0
            hp_min, hp_max = min(hp_min, hp), max(hp_max, hp)

            states = {32 * i + b for i, w in enumerate(words)
                      for b in range(32) if w & (1 << b)}
            appeared, disappeared = states - prev_states, prev_states - states

            new_stat_ids = sorted(set(raw) - baseline_stats)
            gone_stat_ids = sorted(baseline_stats - set(raw))

            line = (f"t={now:7.2f} hp={hp:>4} states={[sname(s) for s in sorted(states)]} "
                    f"words={[f'{w:08x}' for w in words]}")
            if new_stat_ids:
                line += f" stat+={ {sid: raw[sid] for sid in new_stat_ids} }"
            if gone_stat_ids:
                line += f" stat-={gone_stat_ids}"
            log.write(line + "\n")

            for sid in sorted(appeared):
                msg = f">>> t={now:7.2f}  STATE APPEARED  {sname(sid)}"
                print(msg)
                log.write(msg + "\n")
                transitions.append((now, "appeared", sname(sid)))
            for sid in sorted(disappeared):
                msg = f">>> t={now:7.2f}  STATE GONE      {sname(sid)}"
                print(msg)
                log.write(msg + "\n")
                transitions.append((now, "gone", sname(sid)))
            if new_stat_ids or gone_stat_ids:
                msg = (f">>> t={now:7.2f}  STATS changed  "
                       f"+{ {sid: raw[sid] for sid in new_stat_ids} } -{gone_stat_ids}")
                print(msg)
                log.write(msg + "\n")

            prev_states, prev_raw, prev_hp = states, raw, hp
    except KeyboardInterrupt:
        pass
    finally:
        runtime = time.monotonic() - t0
        summary = [
            "",
            "=== SUMMARY ===",
            f"runtime: {runtime:.1f}s   samples in log: {LOG_PATH}",
            f"hp range while watching: {hp_min} .. {hp_max}",
            "transitions:",
        ]
        summary += [f"  t={t:7.2f}  {kind:9s} {sid}" for t, kind, sid in transitions]
        text = "\n".join(summary)
        print(text)
        log.write(text + "\n")
        log.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
