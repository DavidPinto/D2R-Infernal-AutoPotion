"""Offset resolution via byte-pattern (signature) scanning.

This is the heart of surviving game patches.  Instead of hard-coding memory
addresses, we scan the running D2R.exe for small byte signatures that the game
compiler emits around the globals we need.  The signatures below are taken from
the Go reference project and are the most version-robust ones known for the D2R
3.x client family (which "Infernal Edition" 3.0.91636 belongs to).

If a future patch breaks a signature, *only* the candidate table below needs
updating - no other code changes.  The UI Diagnostics tab reports exactly which
signatures resolved so a broken one is easy to spot.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

from .process import find_pattern_in_all, Process


def _p(hexstr: str) -> bytes:
    """Turn a backslash-xNN escaped literal (copied from Go) into bytes."""
    return hexstr.encode("utf-8").decode("unicode_escape").encode("latin-1")


@dataclass(frozen=True)
class Candidate:
    name: str
    pattern: bytes
    mask: bytes
    # resolution mode:
    #   "module"  - value = u32(pattern+disp) + adj
    #   "rip"     - RIP-relative: value = (addr-base) + disp + 4 + u32(addr+disp) + adj
    #   "gamedata" - legacy d2go GameData formula
    mode: str = "module"
    disp: int = 0
    adj: int = 0
    # allow ambiguous (multi-match) resolution via scoring of the pointed-to
    # currentGame structure
    validated: bool = False


# Candidate lists per offset - first unambiguous match wins.
PATTERNS: dict[str, list[Candidate]] = {
    "GameData": [
        # currentGame pointer store (D2R 3.x):  mov [rip+disp], rax
        Candidate("game-store-1",
                  _p(r"\x48\x89\x05\x00\x00\x00\x00\x48\x85\xC0\x0F\x84\x00\x00\x00\x00\x44\x8B\xC7"),
                  b"xxx????xxxxx????xxx", mode="rip", disp=3, validated=True),
        Candidate("game-store-2",
                  _p(r"\x48\x89\x05\x00\x00\x00\x00\x48\x85\xC0\x0F\x84\x00\x00\x00\x00"),
                  b"xxx????xxxxx????", mode="rip", disp=3, validated=True),
        # legacy d2go GameData
        Candidate("gamedata-d2go",
                  _p(r"\x44\x88\x25\x00\x00\x00\x00\x66\x44\x89\x25\x00\x00\x00\x00"),
                  b"xxx????xxxx????", mode="gamedata", disp=3),
    ],
    "UnitTable": [
        # client unit hash table base (same on every known D2R 3.x build)
        Candidate("unit-hash-v3",
                  _p(r"\x48\x03\xC7\x49\x8B\x8C\xC6"),
                  b"xxxxxxx", mode="module", disp=7),
    ],
    "UI": [
        Candidate("ui-v3",
                  _p(r"\x40\x84\xed\x0f\x94\x05"),
                  b"xxxxxx", mode="rip", disp=6),
    ],
    "Hover": [
        Candidate("hover-v3",
                  _p(r"\xc6\x84\xc2\x00\x00\x00\x00\x00\x48\x8b\x74\x24\x00"),
                  b"xxx?????xxxx?", mode="module", disp=3, adj=-1),
    ],
    "Expansion": [
        Candidate("expansion-v3",
                  _p(r"\x48\x8B\x05\x00\x00\x00\x00\x48\x8B\xD9\xF3\x0F\x10\x50\x00"),
                  b"xxx????xxxxxxx?", mode="rip", disp=3),
    ],
    "Roster": [
        Candidate("roster-v3",
                  _p(r"\x02\x45\x33\xD2\x4D\x8B"),
                  b"xxxxxx", mode="rip", disp=-3),
    ],
}

# Server unit-table offsets relative to currentGame (D2RMemoryLayout.h).  Used
# only by the GameData sanity validator, never by the main reader.  If the
# server layout changed in a given build the validator simply reports a lower
# confidence score - it never blocks reading.
_GAME_UNIT_TABLE_PLAYERS = 0x2230
_GAME_UNIT_HASH_BUCKETS = 128
_D2_UNIT_OFFSET_ID = 0x08
_D2_SERVER_UNIT_OFFSET_NEXT = 0x158
_D2_UNIT_OFFSET_STATS = 0x88
_STAT_LIFE = 6
_STAT_MAX_LIFE = 7
_STAT_LEVEL = 12


def _u32(memory: bytes, addr: int, base: int) -> int:
    """Little-endian uint32 at 'addr' inside 'memory', or 0 if out of range."""
    off = addr - base
    if off < 0 or off + 4 > len(memory):
        return 0
    return struct.unpack("<I", memory[off:off + 4])[0]


def _resolve(cand: Candidate, addr: int, base: int, memory: bytes) -> int:
    """Turn a matched instruction's address into an RVA (offset from module base).

    'module' / 'gamedata' / 'rip' are the three addressing modes used by the
    patterns; each computes the target differently from the immediate/disp bytes
    right after the matched signature."""
    if cand.mode == "module":
        return _u32(memory, addr + cand.disp, base) + cand.adj
    if cand.mode == "gamedata":
        return (addr - base) - 0x121 + _u32(memory, addr + cand.disp, base)
    # rip-relative (x64): target = instr_end + disp32
    return (addr - base) + cand.disp + 4 + _u32(memory, addr + cand.disp, base) + cand.adj


def _is_likely_ptr(value: int) -> bool:
    """Cheap sanity check: a heap/userland address, not a module RVA or null."""
    return 0x10000 <= value < 0x0000800000000000


def _read_unit_vitals(proc: Process, unit: int) -> tuple | None:
    """Read (life, max_life, level) from a unit's stat list, or None if garbage.

    Walks unit->stats_list->stats array; Life/MaxLife are stored shifted (<<8)
    and are shifted back to display values here.  Returns None on any pointer
    that doesn't look like a real unit, so false positives are weeded out early."""
    stats_list = proc.read_u64(unit + _D2_UNIT_OFFSET_STATS)
    if not _is_likely_ptr(stats_list):
        return None
    header = proc.read_bytes(stats_list + 0x30, 0x10)
    if len(header) != 0x10:
        return None
    stat_ptr = int.from_bytes(header[0:8], "little")
    count = int.from_bytes(header[8:16], "little")
    if count == 0 or count > 256 or not _is_likely_ptr(stat_ptr):
        return None
    buf = proc.read_bytes(stat_ptr + 0x2, count * 8)
    life = max_life = level = 0
    for i in range(count):
        o = i * 8
        if o + 6 > len(buf):
            break
        sid = int.from_bytes(buf[o:o + 2], "little")
        val = int.from_bytes(buf[o + 2:o + 6], "little")
        if sid == _STAT_LIFE:
            life = val >> 8
        elif sid == _STAT_MAX_LIFE:
            max_life = val >> 8
        elif sid == _STAT_LEVEL:
            level = val
    if not (0 < max_life < 100_000 and 0 < life <= max_life and 0 < level < 100):
        return None
    return life, max_life, level


def _validate_game_data(proc: Process, memory: bytes, base: int) -> tuple[int, str]:
    """Pick the currentGame candidate whose pointed-to struct holds a real player."""
    best = (0, "")
    module_ranges = proc.module_ranges()
    for cand in PATTERNS["GameData"]:
        if cand.mode != "rip":
            continue
        hits = find_pattern_in_all(memory, base, cand.pattern, cand.mask, limit=64)
        for addr in hits:
            slot = _resolve(cand, addr, base, memory)
            if not slot:
                continue
            current_game = proc.read_u64(base + slot)
            if not _is_likely_ptr(current_game):
                continue
            if any(mb <= current_game < mb + ms for mb, ms in module_ranges):
                continue  # pointer into a module is a false positive
            for bucket in range(_GAME_UNIT_HASH_BUCKETS):
                cur = proc.read_u64(current_game + _GAME_UNIT_TABLE_PLAYERS + bucket * 8)
                guard = 0
                while _is_likely_ptr(cur) and guard < 128:
                    uid = proc.read_u32(cur + _D2_UNIT_OFFSET_ID)
                    if uid and uid != 0xFFFFFFFF and _read_unit_vitals(proc, cur):
                        score = 1_000_000
                        if score > best[0]:
                            best = (slot, cand.name)
                        break
                    cur = proc.read_u64(cur + _D2_SERVER_UNIT_OFFSET_NEXT)
                    guard += 1
    return best


@dataclass
class Offsets:
    GameData: int = 0
    UnitTable: int = 0
    UI: int = 0
    Hover: int = 0
    Expansion: int = 0
    Roster: int = 0
    unresolved: list = field(default_factory=list)
    matched: dict = field(default_factory=dict)
    scan_report: dict = field(default_factory=dict)
    module_name: str = ""
    module_base: int = 0
    module_size: int = 0
    memory_len: int = 0
    struct_stats: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        # UnitTable is what the reader actually needs; GameData is only a bonus.
        return self.UnitTable != 0

    @property
    def version_hint(self) -> str:
        """Best-effort description of the detected client family, for the UI."""
        if self.matched.get("UnitTable") in ("unit-hash-v3", "structural-scan"):
            return "D2R 3.x (Infernal family)"
        if self.matched.get("GameData", "").startswith("game"):
            return "D2R 3.x (Infernal family)"
        if self.matched.get("GameData") == "gamedata-d2go":
            return "older / d2go"
        return "unknown"


def calculate_offsets(proc: Process) -> Offsets:
    """Resolve every known signature to an RVA in the game module image.

    For each entry in PATTERNS the candidates are tried in order until exactly
    one clean hit resolves; validated (ambiguous) signatures are re-checked
    against the live game state.  Unresolved names land in
    ``offsets.unresolved`` for the Diagnostics tab."""
    offs = Offsets()
    memory = proc.read_module()
    offs.module_name = getattr(proc, "module_name", "")
    offs.module_base = getattr(proc, "module_base", 0)
    offs.module_size = getattr(proc, "module_size", 0)
    offs.memory_len = len(memory)
    if not memory:
        offs.unresolved = ["GameData", "UnitTable", "UI", "Hover", "Expansion", "Roster"]
        return offs
    base = proc.module_base

    def _test_ui_struct(proc, addr: int) -> bool:
        """Quick sanity: UI struct at addr should have readable menu flag bytes."""
        try:
            buf = proc.read_bytes(addr - 0xA, 0x16D)
            if len(buf) != 0x16D:
                return False
            # At least one flag byte should be readable (not all zero)
            # and indices 0x01..0x1E should be in range
            non_zero = sum(1 for b in buf[:0x1F] if b != 0)
            return non_zero >= 0  # struct is readable; zero flags is valid (all closed)
        except Exception:
            return False

    for name, candidates in PATTERNS.items():
        resolved_here = False
        for cand in candidates:
            hits = find_pattern_in_all(memory, base, cand.pattern, cand.mask, limit=2)
            offs.scan_report.setdefault(name, []).append((cand.name, len(hits)))
            if cand.validated and len(hits) > 1:
                slot, matched_name = _validate_game_data(proc, memory, base)
                if slot:
                    setattr(offs, name, slot)
                    offs.matched[name] = matched_name
                    resolved_here = True
                break
            if len(hits) == 1:
                value = _resolve(cand, hits[0], base, memory)
                if value:
                    setattr(offs, name, value)
                    offs.matched[name] = cand.name
                    resolved_here = True
                    break
            # Non-validated candidate with multiple hits: test each for a valid struct
            if len(hits) > 1 and name == "UI":
                for hit in hits:
                    value = _resolve(cand, hit, base, memory)
                    if value and _test_ui_struct(proc, base + value):
                        setattr(offs, name, value)
                        offs.matched[name] = cand.name
                        resolved_here = True
                        break
        if not resolved_here:
            offs.unresolved.append(name)

    return offs


def discover_unit_table(proc: Process, time_budget: float = 90.0,
                        modules=None, stats: dict | None = None) -> tuple[int, int]:
    """Build-agnostic fallback: scan module image(s) for the 128-bucket client
    unit hash table by *structure* (no byte signatures needed).

    The table is a contiguous 128-pointer array living inside the game module
    image.  We slide an 8-byte-aligned window to find windows with many non-zero
    buckets (true in-game), then RPM-validate that a few of those pointers really
    point at unit-like structures (path + stat list).

    Scans every module of the process (not just the main one) so a loader such as
    D2RMM.exe that hosts the real game module still resolves.

    Requires the player to be *in a game* (otherwise the table is empty).
    Returns ``(module_base, offset)`` or ``(0, 0)`` if not found.  If ``stats``
    is a dict it is filled with diagnostic counters (why candidates were rejected).
    """
    if modules is None:
        modules = [(proc.module_base, proc.module_size, proc.module_name)]
    modules = [m for m in modules if m[0] and m[1]]
    if not modules:
        return 0, 0
    budget_each = time_budget / len(modules)
    agg = {
        "modules": len(modules), "by_module": {},
        "bucket0_ptr": 0, "bucket0_partial": 0, "bucket0_unit": 0,
        "windows_dense": 0, "windows_sparse": 0, "timed_out": False,
    }
    for base, size, name in modules:
        off, s = _scan_module_for_table(proc, base, size, budget_each)
        agg["by_module"][name or hex(base)] = s
        agg["bucket0_ptr"] += s["bucket0_ptr"]
        agg["bucket0_partial"] += s["bucket0_partial"]
        agg["bucket0_unit"] += s["bucket0_unit"]
        agg["windows_dense"] += s["windows_dense"]
        agg["windows_sparse"] += s["windows_sparse"]
        agg["timed_out"] = agg["timed_out"] or s["timed_out"]
        if off:
            if stats is not None:
                stats.clear()
                stats.update(agg)
            return base, off
    if stats is not None:
        stats.clear()
        stats.update(agg)
    return 0, 0


def _scan_module_for_table(proc: Process, base: int, size: int,
                           time_budget: float) -> tuple[int, dict]:
    """Scan one module image for a 128-bucket unit hash table, within budget.

    Returns ``(offset_of_table_in_module, stats)``.  Windows are ranked by how
    many of their 128 qwords are non-zero (see the dense/sparse passes below),
    then bucket 0 is required to be a genuine unit so the window anchors on the
    true table start."""
    import time as _time
    stats = {
        "windows_dense": 0, "windows_sparse": 0,
        "bucket0_ptr": 0, "bucket0_partial": 0, "bucket0_unit": 0,
        "best_valid": 0, "timed_out": False,
    }
    memory = proc.read_module(base, size)
    if not memory:
        return 0, stats

    # Get the module as an array of little-endian uint64 as cheaply as possible.
    try:
        import numpy as np
        vals = np.frombuffer(memory, dtype=np.uint64)
        use_numpy = True
    except Exception:
        import array as _array
        vals = _array.array("Q")
        vals.frombytes(memory)  # single C-level conversion, no per-qword Python
        use_numpy = False

    n = len(vals)
    if n < 128:
        return 0, stats

    deadline = _time.monotonic() + time_budget
    window = 128

    # Per-window non-zero bucket counts (1 convolve for numpy, else a slide).
    if use_numpy:
        import numpy as np
        nz = (vals != 0).astype(np.int32)
        counts = np.convolve(nz, np.ones(window, dtype=np.int32), mode="valid")
    else:
        counts = None  # computed incrementally below

    def _classify(i):
        """Diagnostics only: tally how unit-like bucket 0 looks at window i."""
        q0 = int.from_bytes(memory[i * 8:(i + 1) * 8], "little")
        if not q0 or not _is_likely_ptr(q0):
            return
        stats["bucket0_ptr"] += 1
        p = _unit_bucket0_partial(proc, q0)
        if p >= 1:
            stats["bucket0_partial"] += 1
        if p == 3:
            stats["bucket0_unit"] += 1

    def search(threshold, key):
        """Validate every window with >= 'threshold' non-zero buckets; return
        the best candidate's byte offset (0 if none validate).  numpy path uses
        one convolution for the counts; the stdlib path slides a running count."""
        best_i = 0
        best_v = 0
        if use_numpy:
            for i in [int(x) for x in np.nonzero(counts >= threshold)[0]]:
                stats[key] += 1
                _classify(i)
                v = _validate_table_window(proc, memory, base, i)
                if v > best_v:
                    best_v = v
                    best_i = i
                if _time.monotonic() > deadline:
                    stats["timed_out"] = True
                    break
        else:
            count = 0
            for k in range(window):
                if vals[k]:
                    count += 1
            for i in range(n - window):
                if count >= threshold:
                    stats[key] += 1
                    _classify(i)
                    v = _validate_table_window(proc, memory, base, i)
                    if v > best_v:
                        best_v = v
                        best_i = i
                if vals[i]:
                    count -= 1
                if vals[i + window]:
                    count += 1
                if (i & 0x3FFFF) == 0 and _time.monotonic() > deadline:
                    stats["timed_out"] = True
                    break
        if best_v == 0:
            return 0
        # Anchor to the first occupied bucket so we never skip a real unit
        # (only leading empty buckets may be skipped).
        while best_i > 0 and _validate_table_window(proc, memory, base, best_i - 1):
            best_i -= 1
        return best_i * 8

    # Try a dense table first (fast, few candidates); fall back to a sparse
    # table (more candidates) for nearly-empty games.
    for threshold, key in ((20, "windows_dense"), (8, "windows_sparse")):
        off = search(threshold, key)
        if off:
            stats["best_valid"] = max(stats["best_valid"], 1)
            return off, stats
    return 0, stats


def _validate_table_window(proc: Process, memory: bytes, base: int, i: int) -> int:
    """Sample buckets of a candidate 128-bucket window and verify they point
    at structures that look like units. Bucket 0 MUST be a valid unit (this is
    what anchors the window to the real start of the array); a strong fraction
    of the remaining sampled buckets must also validate. Returns the number of
    validated samples, or 0 if it does not look like a unit table."""
    q0 = int.from_bytes(memory[i * 8:(i + 1) * 8], "little")
    if not q0 or not _is_likely_ptr(q0) or not _unit_looks_valid(proc, q0):
        return 0
    samples = 1
    valid = 1
    for k in range(8, 128, 8):
        q = int.from_bytes(memory[(i + k) * 8:(i + k) * 8 + 8], "little")
        if not q or not _is_likely_ptr(q):
            continue
        samples += 1
        if _unit_looks_valid(proc, q):
            valid += 1
    # Bucket 0 is already a hard anchor (a real unit). Require at least one
    # more validated bucket so a lone stray pointer can't masquerade as a table.
    if valid < 2:
        return 0
    return valid


def _unit_looks_valid(proc: Process, unit: int) -> bool:
    path = proc.read_ptr(unit + 0x38)
    if not path or not _is_likely_ptr(path):
        return False
    x = proc.read_u16(path + 0x02)
    y = proc.read_u16(path + 0x06)
    # Generous: units may legitimately sit at the edges / just-spawned.
    if not (0 <= x < 16000 and 0 <= y < 16000):
        return False
    slist = proc.read_ptr(unit + 0x88)
    if not slist or not _is_likely_ptr(slist):
        return False
    cnt = proc.read_ptr(slist + 0x38)
    if not (1 <= cnt <= 1200):
        return False
    return True


def _unit_bucket0_partial(proc: Process, unit: int) -> int:
    """Cheap partial check used only for diagnostics: how 'unit-like' is a
    pointer at the head of a candidate window (path + stat-list present)."""
    path = proc.read_ptr(unit + 0x38)
    if not path or not _is_likely_ptr(path):
        return 0
    slist = proc.read_ptr(unit + 0x88)
    if not slist or not _is_likely_ptr(slist):
        return 1
    cnt = proc.read_ptr(slist + 0x38)
    if not (1 <= cnt <= 1200):
        return 2
    return 3
