"""Game memory reader - player / mercenary vitals and open-menu state.

This is a faithful port of the Go reference reader (Hefero/D2R-AutoPotion-Go),
using the **client-side unit hash table** rather than the server unit tables.
That is the approach the original tool used and the only one proven to work
across D2R 3.x builds; the previous Python attempt switched to hardcoded server
offsets and that is where it broke.

Unit struct offsets are engine-stable; the only thing that moves between builds
is the base of the unit table, which :mod:`d2r.offsets` resolves by signature
scanning.  If a build changes the structure itself, the UI Diagnostics tab will
show the read as failed/implausible so it is easy to catch.
"""

from __future__ import annotations

import struct
import time

from . import models as m
from .offsets import Offsets, calculate_offsets, _is_likely_ptr, _unit_looks_valid
from .process import Process


class GameReader:
    def __init__(self, proc: Process,
                 codes: m.PotionCodes | None = None,
                 merc_txtfiles: frozenset | None = None,
                 config: "AppConfig | None" = None):
        """Attach to a game process, resolve offsets, and prepare the state
        trackers (running maxima + manual max overrides for % computation).

        ``codes`` is the potion txtFileNo table (defaults to the built-in
        Infernal Edition codes) and ``merc_txtfiles`` the hireling ids to match
        for the merc (defaults to Guard + Infernal hireling) - both come from
        the active combo in config when a user calibrates a different build."""
        self.proc = proc
        self.config = config
        self.codes: m.PotionCodes = codes if codes is not None else m.default_potion_codes(
            class_heal_group=config.class_heal_group() if config else None,
            class_mana_group=config.class_mana_group() if config else None,
            rejuv_restore_percent=config.rejuv_restore_percent() if config else None,
        )
        self.merc_txtfiles: frozenset = merc_txtfiles if merc_txtfiles is not None else m.MERC_TXTFILES_DEFAULT
        self.offsets: Offsets = calculate_offsets(proc)
        # A signature hit can be a false positive (e.g. a coincidental byte match
        # in an unrelated module).  Verify the resolved UnitTable actually points
        # at a client unit table; if not, drop it so the structural scan runs.
        if self.offsets.UnitTable and not self._unit_table_looks_real():
            self.offsets.UnitTable = 0
            if "UnitTable" not in self.offsets.unresolved:
                self.offsets.unresolved.append("UnitTable")
        # Running maxima so the HP/MP bars follow Battle-Orders boosts (Go logic).
        self._max_life = 0
        self._max_mana = 0
        self._max_merc = 0
        # Which hireling the observed merc max belongs to; a new hireling resets
        # the tracker so an old (higher) max can't over-report a weaker one.
        self._merc_unit_id = 0
        # Manual max override (config "max_override"): when > 0 it is used directly
        # as the denominator so the % is correct even before the observed max latches.
        self.max_override = {"player_hp": 0, "player_mp": 0, "merc_hp": 0}

    def _unit_table_looks_real(self) -> bool:
        """Cheap sanity check: at least one hash bucket must point at a structure
        that looks like a live unit.  Requires the player to be *in a game*."""
        if not self.offsets.UnitTable:
            return False
        base = self._base()
        for i in range(m.UNIT_TABLE_ENTRIES):
            p = self.proc.read_u64(base + self.offsets.UnitTable + i * 8)
            if p and _is_likely_ptr(p) and _unit_looks_valid(self.proc, p):
                return True
        return False

    # ------------------------------------------------------------------ utils
    def _base(self) -> int:
        return self.proc.module_base

    def read_expansion_flag(self) -> int:
        """LoD/expansion flag. D2R is always expansion content, so when the
        Expansion signature is unavailable we default to expansion (0x70 check)."""
        if not self.offsets.Expansion:
            return 1
        p = self.proc.read_ptr(self._base() + self.offsets.Expansion)
        if not p:
            return 1
        return self.proc.read_u16(p + 0x5C) or 1

    # ----------------------------------------------------------- stat arrays
    def _read_stats(self, stat_ptr: int, count: int) -> dict:
        """Read a unit stat array into {stat_id: raw_value}.

        Layout: array base, then 8-byte entries [layer:2][enum:2][value:4].  We
        skip the 2-byte layer and read enum (u16) + value (u32).
        """
        if not stat_ptr or count == 0 or count > 512:
            return {}
        buf = self.proc.read_bytes(stat_ptr + 0x2, count * 8)
        if len(buf) < count * 8:
            return {}
        out: dict = {}
        for i in range(count):
            off = i * 8
            if off + 6 > len(buf):
                break
            sid = int.from_bytes(buf[off:off + 2], "little")
            val = int.from_bytes(buf[off + 2:off + 6], "little")
            out[sid] = val
        return out

    def _read_unit_states(self, unit: int) -> frozenset:
        """Active state ids for a unit (poison, freeze, shrines, ...).

        States are 6 x u32 inside the stats-list-ex struct; each bit is one
        state id.  Never raises: any read failure yields an empty set."""
        slex = self.proc.read_ptr(unit + m.UNIT_OFFSET_STATSLISTEX)
        if not slex:
            return frozenset()
        words = [self.proc.read_u32(slex + m.STATSLIST_STATES_OFFSET + i * 4)
                 for i in range(6)]
        if not any(words):
            return frozenset()
        out = []
        for i, word in enumerate(words):
            for bit in range(32):
                if word & (1 << bit):
                    out.append(32 * i + bit)
        return frozenset(out)

    # ------------------------------------------------------------- player
    def _find_player_unit(self) -> tuple[int, bool]:
        """Walk the client player hash table for the local player unit.

        Returns (unit_address, is_corpse).  The local player is the unit whose
        inventory header carries the main-player marker.
        """
        base = self._base()
        expansion = self.read_expansion_flag()
        main_check_off = m.INV_MAIN_CHECK_EXP if expansion else m.INV_MAIN_CHECK
        for i in range(m.UNIT_TABLE_ENTRIES):
            addr = base + self.offsets.UnitTable + i * 8
            unit = self.proc.read_u64(addr)
            while unit:
                inventory = self.proc.read_ptr(unit + m.UNIT_OFFSET_INVENTORY)
                path = self.proc.read_ptr(unit + m.UNIT_OFFSET_PATH)
                x = self.proc.read_u16(path + m.PATH_OFFSET_X) if path else 0
                y = self.proc.read_u16(path + m.PATH_OFFSET_Y) if path else 0
                if inventory and x and y:
                    base_check = self.proc.read_u16(inventory + main_check_off)
                    is_corpse = self.proc.read_u8(unit + m.UNIT_OFFSET_IS_CORPSE)
                    if base_check > 0:
                        return unit, is_corpse == 1
                unit = self.proc.read_ptr(unit + m.UNIT_OFFSET_NEXT)
        return 0, False

    def _player_class(self, unit: int) -> str:
        """Player class id lives in the unit's txtFileNo union field (+0x04); the
        +0x174 slot is the monster class category and reads 0 for players."""
        for off in (m.UNIT_OFFSET_TXTFILE, m.UNIT_OFFSET_CLASS):
            cid = self.proc.read_u32(unit + off)
            if 0 <= cid < len(m.CLASS):
                return m.CLASS[cid]
        return "Unknown"

    def _read_player(self, unit: int) -> dict:
        path = self.proc.read_ptr(unit + m.UNIT_OFFSET_PATH)
        x = self.proc.read_u16(path + m.PATH_OFFSET_X) if path else 0
        y = self.proc.read_u16(path + m.PATH_OFFSET_Y) if path else 0
        unit_data = self.proc.read_ptr(unit + m.UNIT_OFFSET_UNIT_DATA)
        name = self.proc.read_string(unit_data) if unit_data else ""

        stats_list_ex = self.proc.read_ptr(unit + m.UNIT_OFFSET_STATSLISTEX)
        stat_ptr = self.proc.read_ptr(stats_list_ex + m.STATSLIST_STAT_PTR)
        stat_count = self.proc.read_ptr(stats_list_ex + m.STATSLIST_STAT_COUNT)
        raw = self._read_stats(stat_ptr, stat_count)
        # Shift the encoded stats to display values (Go: value >> 8).
        stats = {sid: (val >> 8 if sid in m.SHIFTED_STATS else val)
                 for sid, val in raw.items()}

        return {
            "unit_id": self.proc.read_u32(unit + m.UNIT_OFFSET_UNIT_ID),
            "name": name,
            "x": x, "y": y,
            "class": self._player_class(unit),
            "stats": stats,
        }

    # ------------------------------------------------------------- merc
    # Hireling txtFileNo values.  338 = standard NPC_GUARD; 271 = the Infernal
    # Edition (Warlock) hireling.  Overridable per combo (self.merc_txtfiles)
    # via the Calibrate tab for other builds / merc types.
    MERC_TXTFILES = m.MERC_TXTFILES_DEFAULT

    def _read_merc(self) -> dict | None:
        """Read the mercenary unit, or None when no merc unit is in the world.

        Returns dict with hp, max_hp, name, type, level.  The hireling is matched
        by txtFileNo (stable across ticks).  A corpse unit keeps the stats, so a
        dead-but-hired merc yields hp=0 rather than jumping to a nearby monster.
        When no known hireling id is present we fall back to the nearest living
        unit with Life/MaxLife stats (last resort only)."""
        base = self._base()
        table = base + self.offsets.UnitTable + m.UNIT_TABLE_MONSTER_OFFSET

        pu, _ = self._find_player_unit()
        px = py = 0
        if pu:
            ppath = self.proc.read_ptr(pu + m.UNIT_OFFSET_PATH)
            px = self.proc.read_u16(ppath + m.PATH_OFFSET_X) if ppath else 0
            py = self.proc.read_u16(ppath + m.PATH_OFFSET_Y) if ppath else 0

        matched = None      # (unit, raw_stats, txt)
        matched_corpse = False
        best_raw = None
        best_dist = float("inf")
        for i in range(m.UNIT_TABLE_ENTRIES):
            unit = self.proc.read_u64(table + i * 8)
            while unit:
                txt = self.proc.read_u32(unit + m.UNIT_OFFSET_TXTFILE)
                is_corpse = self.proc.read_u8(unit + m.UNIT_OFFSET_IS_CORPSE) == 1
                stats_list_ex = self.proc.read_ptr(unit + m.UNIT_OFFSET_STATSLISTEX)
                sp = self.proc.read_ptr(stats_list_ex + m.STATSLIST_STAT_PTR) if stats_list_ex else 0
                sc = self.proc.read_ptr(stats_list_ex + m.STATSLIST_STAT_COUNT) if stats_list_ex else 0
                raw = self._read_stats(sp, sc)
                has_life = m.STAT["Life"] in raw and m.STAT["MaxLife"] in raw
                if txt in self.merc_txtfiles and has_life:
                    if not is_corpse:
                        # Living hireling always wins over a corpse found earlier.
                        matched = (unit, raw, txt)
                        matched_corpse = False
                        break
                    if matched is None:
                        matched = (unit, raw, txt)
                        matched_corpse = True
                    unit = self.proc.read_ptr(unit + m.UNIT_OFFSET_NEXT)
                    continue
                if has_life and not is_corpse:
                    upath = self.proc.read_ptr(unit + m.UNIT_OFFSET_PATH)
                    mx = self.proc.read_u16(upath + m.PATH_OFFSET_X) if upath else 0
                    my = self.proc.read_u16(upath + m.PATH_OFFSET_Y) if upath else 0
                    d = (mx - px) ** 2 + (my - py) ** 2
                    if d < best_dist:
                        best_dist = d
                        best_raw = raw
                unit = self.proc.read_ptr(unit + m.UNIT_OFFSET_NEXT)
            if matched is not None and not matched_corpse:
                break
        if matched is not None:
            unit, raw, txt = matched
        elif best_raw is not None:
            unit, raw, txt = 0, best_raw, 0
        else:
            return None
        raw = dict(raw)
        if unit:
            # The base MaxLife stat is the un-geared max.  The stats-list's
            # second (merged/item) block carries the true max incl. gear
            # bonuses, so a full merc shows e.g. 199/199 not 189/199.
            slex = self.proc.read_ptr(unit + m.UNIT_OFFSET_STATSLISTEX)
            if slex:
                item_raw = self._read_stats(
                    self.proc.read_ptr(slex + m.STATSLIST_ITEM_STAT_PTR),
                    self.proc.read_ptr(slex + m.STATSLIST_ITEM_STAT_COUNT))
                item_max = item_raw.get(m.STAT["MaxLife"], 0)
                if item_max > raw.get(m.STAT["MaxLife"], 0):
                    raw[m.STAT["MaxLife"]] = item_max
        hp, max_hp = self._merc_values(raw)
        level = raw.get(m.STAT["Level"], 0)
        # The hireling's generated name is a UI resource string, not a field on
        # the unit (reading unit+0x2C as UTF-16 only ever yields garbage), so we
        # label the merc by its type instead.
        return {
            "hp": hp, "max_hp": max_hp,
            "raw_life": raw.get(m.STAT["Life"], 0),
            "raw_max_life": raw.get(m.STAT["MaxLife"], 0),
            "unit_id": self.proc.read_u32(unit + m.UNIT_OFFSET_UNIT_ID) if unit else 0,
            "name": "",
            "type": m.MERC_TYPE.get(txt, f"Hireling ({txt})"),
            "level": level,
        }

    @staticmethod
    def _track_max(prev_max: int, stat: int, current: int) -> int:
        """Tracked max HP/MP: shrink to ``stat`` when at/over it, else grow.

        The MaxLife/MaxMana stat is the un-geared base, so when the player is at
        or above it the observed value wins (gear bonuses) and unequipping a +max
        item lets the max fall back down.  Below the stat (damaged) the max only
        grows."""
        if current >= stat:
            return max(stat, current)
        return max(prev_max, stat, current)

    @staticmethod
    def _merc_values(raw: dict) -> tuple[int, int]:
        """Convert raw merc stats into (life_display, max_display).

        MaxLife is stored shifted (<<8).  Life at or below 0x8000 is reported by
        the engine as a 0..1 fraction of max scaled to [0, 0x8000] (display
        values 0..max), so it is scaled back proportionally; only values ABOVE
        0x8000 are a plain shifted value (128+).  The fraction hits exactly
        0x8000 at FULL HP, which is why the boundary is inclusive: an old
        ``< 0x8000`` check read a full merc as 128 (128/189 = 67%)."""
        raw_max = raw.get(m.STAT["MaxLife"], 0)
        max_disp = raw_max >> 8
        if max_disp <= 0:
            return 0, 0
        raw_life = raw.get(m.STAT["Life"], 0)
        if raw_life <= 32768:
            life_disp = int(raw_life / 32768.0 * max_disp)
        else:
            life_disp = raw_life >> 8
        return life_disp, max_disp

    # ------------------------------------------------------------- potions
    def _read_item_counts(self) -> m.PotionCounts:
        """Count belt + personal-inventory potions from the client item table.

        Mirrors the location logic in the Go reference (pkg/memory/item.go):
        itemLoc 2 == belt; itemLoc 0 == inventory only when the owner is the
        local player, the item is on the inventory page (invPage 0) and not
        flagged as vendor/trade.  Counts are best-effort: any unreadable frame
        just reports ``ok=False`` instead of failing the snapshot."""
        counts = m.PotionCounts()
        if not self.offsets.UnitTable:
            return counts
        base = self._base()
        table = base + self.offsets.UnitTable + m.UNIT_TABLE_ITEM_OFFSET

        main_id = 0
        pu, _ = self._find_player_unit()
        if pu:
            main_id = self.proc.read_u32(pu + m.UNIT_OFFSET_UNIT_ID)

        buckets = self.proc.read_bytes(table, m.UNIT_TABLE_ENTRIES * 8)
        if len(buckets) < m.UNIT_TABLE_ENTRIES * 8:
            return counts

        # Column -> [(slot X, txt)] for the local player's belt potions.  The
        # vendor grid shares loc 2 in this build, so we only keep items owned by
        # the player (owner == main unit id).
        belt_cols: dict[int, list] = {c: [] for c in range(len(m.BELT_COLUMN_KEYS))}
        belt_filled: list[int] = []
        belt_rows = 0
        seen = 0
        for i in range(m.UNIT_TABLE_ENTRIES):
            unit = int.from_bytes(buckets[i * 8:i * 8 + 8], "little")
            while unit and seen < 512:
                seen += 1
                # One batched read per item: header (type..next ptr).
                buf = self.proc.read_bytes(unit, 0x160)
                if len(buf) < 0x158:
                    break
                if int.from_bytes(buf[0x00:0x04], "little") == m.ITEM_UNIT_TYPE:
                    txt = int.from_bytes(buf[0x04:0x08], "little")
                    kind = self.codes.kind(txt)
                    loc = int.from_bytes(buf[0x0C:0x10], "little")
                    ud = int.from_bytes(buf[0x10:0x18], "little")
                    owner = self.proc.read_u32(ud + m.ITEM_UNIT_DATA_OFFSET_OWNER) if ud else 0
                    if loc == m.ITEM_LOC_BELT and (not main_id or owner == main_id):
                        # The whole belt slot is recorded even when the potion is
                        # not yet classified (unknown game version/mods): the
                        # slot then counts as filled (correct empty-slot geometry)
                        # and the watcher can fall back to a best-effort keypress
                        # on a critical stat instead of sitting idle at 0%.
                        if kind:
                            counts.belt[kind] += 1
                        path = int.from_bytes(buf[0x38:0x40], "little")
                        slot_x = self.proc.read_u16(path + m.ITEM_PATH_OFFSET_X) if path else -1
                        col = slot_x % len(m.BELT_COLUMN_KEYS) if slot_x >= 0 else 0
                        belt_cols.setdefault(col, []).append((slot_x, txt))
                        if slot_x >= 0:
                            belt_filled.append(slot_x)
                            if kind:
                                counts.belt_slots[slot_x] = kind
                    elif loc == m.ITEM_LOC_INVENTORY and main_id and kind:
                        if ud:
                            page = self.proc.read_u8(ud + m.ITEM_UNIT_DATA_OFFSET_INVPAGE)
                            flags = self.proc.read_u32(ud + m.ITEM_UNIT_DATA_OFFSET_FLAGS)
                            if (owner == main_id and page == 0 and not (flags & 0x2000)):
                                counts.inventory[kind] += 1
                    elif loc == m.ITEM_LOC_EQUIPPED and owner == main_id:
                        # The equipped belt (any class of belt) tells us the grid.
                        if m.belt_rows_for(txt):
                            belt_rows = m.belt_rows_for(txt)
                unit = int.from_bytes(buf[0x150:0x158], "little")

        counts.belt_filled = sorted(set(belt_filled))
        # Belt rows: known belt item id, else the tallest occupied row, else 1.
        if not belt_rows and counts.belt_filled:
            belt_rows = counts.belt_filled[-1] // 4 + 1
        counts.belt_rows = belt_rows or 1
        counts.belt_empty = m.belt_empty_slots(counts.belt_rows, counts.belt_filled)

        for col_idx, entries in belt_cols.items():
            if not entries or not (0 <= col_idx < len(counts.columns)):
                continue
            column = counts.columns[col_idx]
            # Only potions in row 0 (slot_x 0-3) are drinkable via key press
            row0_entries = [e for e in entries if e[0] < 4]
            column.count = len(row0_entries)
            if not row0_entries:
                continue
            # The drinkable potion is the one in row 0 (lowest slot_x in row 0)
            next_txt = min(row0_entries, key=lambda e: e[0])[1]
            column.txt = next_txt
            column.kind = self.codes.kind(next_txt)
            column.grade = self.codes.grade(next_txt)

        counts.codes = self.codes
        counts.ok = seen > 0
        return counts

    def inventory_potions(self) -> list[dict]:
        """Personal-inventory potions with their grid cell (page 0 only).

        Each entry is ``{"unit_id", "txt", "kind", "grade", "x", "y"}`` where
        x/y are the inventory grid cell (0-based) used by the refill clicker.
        Returns [] when the item table is unavailable."""
        out: list[dict] = []
        if not self.offsets.UnitTable:
            return out
        base = self._base()
        table = base + self.offsets.UnitTable + m.UNIT_TABLE_ITEM_OFFSET
        main_id = 0
        pu, _ = self._find_player_unit()
        if pu:
            main_id = self.proc.read_u32(pu + m.UNIT_OFFSET_UNIT_ID)
        buckets = self.proc.read_bytes(table, m.UNIT_TABLE_ENTRIES * 8)
        if len(buckets) < m.UNIT_TABLE_ENTRIES * 8 or not main_id:
            return out
        seen = 0
        for i in range(m.UNIT_TABLE_ENTRIES):
            unit = int.from_bytes(buckets[i * 8:i * 8 + 8], "little")
            while unit and seen < 512:
                seen += 1
                buf = self.proc.read_bytes(unit, 0x160)
                if len(buf) < 0x158:
                    break
                if int.from_bytes(buf[0x00:0x04], "little") != m.ITEM_UNIT_TYPE:
                    unit = int.from_bytes(buf[0x150:0x158], "little")
                    continue
                txt = int.from_bytes(buf[0x04:0x08], "little")
                kind = self.codes.kind(txt)
                if not kind:
                    unit = int.from_bytes(buf[0x150:0x158], "little")
                    continue
                loc = int.from_bytes(buf[0x0C:0x10], "little")
                ud = int.from_bytes(buf[0x10:0x18], "little")
                owner = self.proc.read_u32(ud + m.ITEM_UNIT_DATA_OFFSET_OWNER) if ud else 0
                if loc == m.ITEM_LOC_INVENTORY and owner == main_id and ud:
                    page = self.proc.read_u8(ud + m.ITEM_UNIT_DATA_OFFSET_INVPAGE)
                    flags = self.proc.read_u32(ud + m.ITEM_UNIT_DATA_OFFSET_FLAGS)
                    if page == 0 and not (flags & 0x2000):
                        path = int.from_bytes(buf[0x38:0x40], "little")
                        if path:
                            out.append({
                                "unit_id": int.from_bytes(buf[0x08:0x0C], "little"),
                                "txt": txt, "kind": kind,
                                "grade": self.codes.grade(txt),
                                "x": self.proc.read_u16(path + m.ITEM_PATH_OFFSET_X),
                                "y": self.proc.read_u16(path + m.ITEM_PATH_OFFSET_Y),
                            })
                unit = int.from_bytes(buf[0x150:0x158], "little")
        return out

    def belt_items(self) -> list[dict]:
        """Belt potions with their belt slot index, for calibration hover
        detection (mirrors :meth:`inventory_potions` for the belt panel).

        Each entry is ``{"unit_id", "txt", "kind", "grade", "slot", "x", "y"}``
        where ``slot`` is the belt slot index (row * 4 + column).  The refill
        calibration uses this to tie a hovered belt potion to a belt grid cell;
        the inventory click grid and the belt panel solve their own origins."""
        out: list[dict] = []
        if not self.offsets.UnitTable:
            return out
        base = self._base()
        table = base + self.offsets.UnitTable + m.UNIT_TABLE_ITEM_OFFSET
        main_id = 0
        pu, _ = self._find_player_unit()
        if pu:
            main_id = self.proc.read_u32(pu + m.UNIT_OFFSET_UNIT_ID)
        buckets = self.proc.read_bytes(table, m.UNIT_TABLE_ENTRIES * 8)
        if len(buckets) < m.UNIT_TABLE_ENTRIES * 8:
            return out
        seen = 0
        for i in range(m.UNIT_TABLE_ENTRIES):
            unit = int.from_bytes(buckets[i * 8:i * 8 + 8], "little")
            while unit and seen < 512:
                seen += 1
                buf = self.proc.read_bytes(unit, 0x160)
                if len(buf) < 0x158:
                    break
                if int.from_bytes(buf[0x00:0x04], "little") != m.ITEM_UNIT_TYPE:
                    unit = int.from_bytes(buf[0x150:0x158], "little")
                    continue
                txt = int.from_bytes(buf[0x04:0x08], "little")
                kind = self.codes.kind(txt)
                if not kind:
                    unit = int.from_bytes(buf[0x150:0x158], "little")
                    continue
                loc = int.from_bytes(buf[0x0C:0x10], "little")
                ud = int.from_bytes(buf[0x10:0x18], "little")
                owner = self.proc.read_u32(ud + m.ITEM_UNIT_DATA_OFFSET_OWNER) if ud else 0
                if loc == m.ITEM_LOC_BELT and (not main_id or owner == main_id):
                    path = int.from_bytes(buf[0x38:0x40], "little")
                    if path:
                        slot = self.proc.read_u16(path + m.ITEM_PATH_OFFSET_X)
                        out.append({
                            "unit_id": int.from_bytes(buf[0x08:0x0C], "little"),
                            "txt": txt, "kind": kind,
                            "grade": self.codes.grade(txt),
                            "slot": slot,
                            "x": slot,
                            "y": self.proc.read_u16(path + m.ITEM_PATH_OFFSET_Y),
                        })
                unit = int.from_bytes(buf[0x150:0x158], "little")
        return out

    def hovered_item_unit(self) -> int:
        """Unit id of the item the mouse is hovering over, or 0 when none.

        Reads the engine's Hover struct (12 bytes at the UI base): u16 hovered
        flag, u32 hovered unit type, u32 hovered unit id.  Used by the refill
        click-position calibration to tie a grid cell to a screen position."""
        if not self.offsets.Hover:
            return 0
        try:
            buf = self.proc.read_bytes(self._base() + self.offsets.Hover, 12)
            if len(buf) != 12:
                return 0
            flag, utype, unit_id = struct.unpack("<H2xII", buf)
            if not flag or utype != m.ITEM_UNIT_TYPE:
                return 0
            return unit_id
        except Exception:
            return 0

    # ------------------------------------------------------- calibration scan
    def scan_item_codes(self) -> dict:
        """Raw per-slot belt + inventory txtFileNos for the Calibrate tab.

        Unlike :meth:`_read_item_counts` (which only classifies known potions)
        this reports *every* item the player owns, so the user can match the
        code of a potion they placed in a known belt corner:
        ``{"ok", "error", "belt": [{"x", "txt"}], "inventory": {txt: count}}``."""
        out: dict = {"ok": False, "error": "", "belt": [], "inventory": {}}
        if not self.offsets.UnitTable:
            out["error"] = "UnitTable offset not resolved."
            return out
        try:
            base = self._base()
            table = base + self.offsets.UnitTable + m.UNIT_TABLE_ITEM_OFFSET
            main_id = 0
            pu, _ = self._find_player_unit()
            if pu:
                main_id = self.proc.read_u32(pu + m.UNIT_OFFSET_UNIT_ID)
            buckets = self.proc.read_bytes(table, m.UNIT_TABLE_ENTRIES * 8)
            if len(buckets) < m.UNIT_TABLE_ENTRIES * 8:
                out["error"] = "Could not read the item table."
                return out
            seen = 0
            for i in range(m.UNIT_TABLE_ENTRIES):
                unit = int.from_bytes(buckets[i * 8:i * 8 + 8], "little")
                while unit and seen < 512:
                    seen += 1
                    buf = self.proc.read_bytes(unit, 0x160)
                    if len(buf) < 0x158:
                        break
                    if int.from_bytes(buf[0x00:0x04], "little") != m.ITEM_UNIT_TYPE:
                        unit = int.from_bytes(buf[0x150:0x158], "little")
                        continue
                    txt = int.from_bytes(buf[0x04:0x08], "little")
                    loc = int.from_bytes(buf[0x0C:0x10], "little")
                    ud = int.from_bytes(buf[0x10:0x18], "little")
                    owner = self.proc.read_u32(ud + m.ITEM_UNIT_DATA_OFFSET_OWNER) if ud else 0
                    if loc == m.ITEM_LOC_BELT and (not main_id or owner == main_id):
                        path = int.from_bytes(buf[0x38:0x40], "little")
                        x = self.proc.read_u16(path + m.ITEM_PATH_OFFSET_X) if path else -1
                        out["belt"].append({"x": x, "txt": txt})
                    elif loc == m.ITEM_LOC_INVENTORY and main_id and owner == main_id:
                        out["inventory"][txt] = out["inventory"].get(txt, 0) + 1
                    unit = int.from_bytes(buf[0x150:0x158], "little")
            out["ok"] = seen > 0
        except Exception as exc:
            out["error"] = str(exc)
        return out

    # -------------------------------------------------------------- menu calibration
    def _get_ui_base(self) -> int:
        """Return the live UI struct base address.

        Uses calibrated address if available, otherwise falls back to pointer
        chase from GameData (most reliable) or signature scan."""
        if hasattr(self, "_ui_base_cached") and self._ui_base_cached:
            return self._ui_base_cached
        # Calibrated address from config
        if self.config is not None:
            calibrated = self.config.calibrated_ui_address()
            if calibrated:
                self._ui_base_cached = calibrated
                return calibrated
        # Pointer chase: GameData -> +0x8 = UI struct (works on all known builds)
        if self.offsets.GameData:
            game_data_addr = self._base() + self.offsets.GameData
            ptr = self.proc.read_u64(game_data_addr + 0x8)
            if ptr and self.proc.module_base <= ptr < self.proc.module_base + self.proc.module_size + 0x10000000:
                test_buf = self.proc.read_bytes(ptr - 0xA, 0x16D)
                if len(test_buf) == 0x16D:
                    self._ui_base_cached = ptr
                    return ptr
        # Fallback: signature scan result
        if self.offsets.UI:
            return self._base() + self.offsets.UI
        return 0

    def _get_flag_map(self) -> dict[str, int] | None:
        """Return calibrated flag index map {menu_name: byte_index}.
        
        Only returns menus that have been calibrated. Uncalibrated menus
        are not included to avoid false positives from wrong default indices.
        """
        if self.config is not None:
            fmap = self.config.calibrated_ui_flags()
            if fmap:
                return fmap
        return None

    def open_menus(self) -> dict:
        """Read the UI panel flags using calibrated struct address + flag map."""
        ui = self._get_ui_base()
        if not ui:
            return {}
        buf = self.proc.read_bytes(ui - 0xA, 0x16D)
        if len(buf) != 0x16D:
            return {}
        fmap = self._get_flag_map()
        if not fmap:
            return {}
        menus = {}
        # Get baseline (closed) values from config
        closed_values = self.config.calibrated_ui_closed_values() if self.config else {}
        for name, idx in fmap.items():
            if idx >= len(buf):
                menus[name] = False
                continue
            current_val = buf[idx]
            if name in closed_values:
                # Compare against baseline: consider "open" if value changes significantly
                closed_val = closed_values[name]
                if closed_val == 0:
                    # If baseline was 0, any non-zero is open
                    menus[name] = current_val != 0
                else:
                    # Check for significant change in either direction
                    diff = abs(current_val - closed_val)
                    # Threshold: 25% of closed value or 20, whichever is larger
                    threshold = max(20, closed_val // 4)
                    menus[name] = diff > threshold
            else:
                # Fallback: non-zero check
                menus[name] = current_val != 0
        menus["MapShown"] = self.proc.read_u8(ui) != 0
        return menus

    def calibrate_ui(self, progress_cb: callable = None) -> dict | None:
        """Interactive UI calibration - detects Inventory flag index by watching changes.

        Simple process:
        1. Baseline (all menus closed)
        2. Open Inventory -> detect which index changes
        3. Close Inventory -> verify

        Returns dict with 'address' and 'flags' {menu_name: byte_index}.
        Only Inventory is calibrated (most common/needed); other menus use defaults.
        """
        from . import models as m

        if progress_cb:
            progress_cb("base")
        ui = self._get_ui_base()
        if not ui:
            return None

        # Test read
        test = self.proc.read_bytes(ui - 0xA, 0x16D)
        if len(test) != 0x16D:
            return None

        # Single baseline: all menus closed
        if progress_cb:
            progress_cb("baseline")
        time.sleep(2.0)
        buf_base = self.proc.read_bytes(ui - 0xA, 0x16D)
        if len(buf_base) != 0x16D:
            return None

        # Calibrate Inventory only (most common/needed)
        menu_name = "Inventory"
        
        # Open Inventory
        if progress_cb:
            progress_cb(f"open:{menu_name}")
        time.sleep(3.0)  # user opens inventory
        buf_open = self.proc.read_bytes(ui - 0xA, 0x16D)
        if len(buf_open) != 0x16D:
            return None

        # Find ALL indices that changed (not just 0->non-zero)
        changed = [(i, buf_base[i], buf_open[i]) for i in range(0x16D) if buf_base[i] != buf_open[i]]
        if not changed:
            # Fallback to default index
            from . import models as m
            fmap = {menu_name: m.MENU_FLAGS.get(menu_name, 0)}
        else:
            # Pick the index with the largest change magnitude (most reliable)
            # Prefer indices that went 0->non-zero, but accept any significant change
            best_idx = None
            best_score = -1
            for idx, old_val, new_val in changed:
                score = abs(new_val - old_val)
                if old_val == 0 and new_val != 0:
                    score += 100  # strong preference for 0->non-zero
                if score > best_score:
                    best_score = score
                    best_idx = idx

            if best_idx is not None:
                fmap = {menu_name: best_idx}
            else:
                from . import models as m
                fmap = {menu_name: m.MENU_FLAGS.get(menu_name, 0)}

        # Close Inventory
        if progress_cb:
            progress_cb(f"close:{menu_name}")
        time.sleep(2.0)

        # Verify final baseline (all closed)
        buf_final = self.proc.read_bytes(ui - 0xA, 0x16D)
        if len(buf_final) != 0x16D:
            return None

        # Store baseline values for open_menus comparison
        closed_values = {menu_name: buf_base[best_idx] if best_idx is not None else buf_base[m.MENU_FLAGS.get(menu_name, 0)]}
        return {"address": ui, "flags": fmap, "closed_values": closed_values}

    # ----------------------------------------------------------- snapshot
    def snapshot(self) -> m.PlayerSnapshot:
        """Read one frame of player/merc/menu state.

        Never raises: any failure is folded into ``snap.error`` so the watcher
        loop and UI always get a value.  HP/MP percentages are computed against
        the effective max (manual override, else the running observed max)."""
        snap = m.PlayerSnapshot()
        if not self.offsets.UnitTable:
            snap.error = "UnitTable offset not resolved (signature scan failed)."
            return snap
        try:
            unit, _ = self._find_player_unit()
            if not unit:
                snap.in_game = False
                if self.offsets.UI:
                    snap.menus_open = self._menus_blocking(self.open_menus())
                return snap

            p = self._read_player(unit)
            stats = p["stats"]
            # Restore amounts are class-dependent; keep the potion table in sync
            # with the character that is actually playing.
            self.codes.player_class = p["class"]
            life = stats.get(m.STAT["Life"], 0)
            max_life = stats.get(m.STAT["MaxLife"], 0)
            mana = stats.get(m.STAT["Mana"], 0)
            max_mana = stats.get(m.STAT["MaxMana"], 0)

            # Effective max HP/MP = running observed maximum, seeded by the MaxLife
            # stat (which is the base WITHOUT item/skill bonuses).  Gear/charm
            # bonuses are NOT in the stat, so once the player is ever at full the
            # observed life (e.g. 131 with gear) becomes the true max.  The max
            # grows while damaged, but shrinks back when at/over the base stat so
            # unequipping a +max item reads as the new lower max (never as damage).
            max_life_stat = stats.get(m.STAT["MaxLife"], 0)
            max_mana_stat = stats.get(m.STAT["MaxMana"], 0)
            self._max_life = self._track_max(self._max_life, max_life_stat, life)
            self._max_mana = self._track_max(self._max_mana, max_mana_stat, mana)

            eff_max_hp = self.max_override.get("player_hp") or self._max_life or 1
            eff_max_mp = self.max_override.get("player_mp") or self._max_mana or 1
            hp_pct = max(0, min(100, int(life / eff_max_hp * 100)))
            mp_pct = max(0, min(100, int(mana / eff_max_mp * 100)))

            snap.name = p["name"]
            snap.unit_id = p["unit_id"]
            snap.class_name = p["class"]
            snap.level = stats.get(m.STAT["Level"], 0)
            snap.in_game = True
            snap.hp = life
            snap.max_hp = eff_max_hp
            snap.mana = mana
            snap.max_mana = eff_max_mp
            snap.hp_percent = hp_pct
            snap.mana_percent = mp_pct
            snap.states = self._read_unit_states(unit)
            snap.poisoned = m.STATE_POISON in snap.states
            merc = self._read_merc()
            if merc is not None:
                # The merc's Life is a fraction of max, so a full merc reads
                # life == max after the boundary fix.  A new hireling (unit id
                # change) resets the observed max so an old hireling's higher
                # max can't over-report the new one.
                if merc.get("unit_id") != self._merc_unit_id:
                    self._merc_unit_id = merc.get("unit_id", 0)
                    self._max_merc = 0
                self._max_merc = max(self._max_merc, merc["max_hp"], merc["hp"])
                eff_merc_max = self.max_override.get("merc_hp") or self._max_merc or 1
                snap.merc_hp = merc["hp"]
                snap.merc_max_hp = eff_merc_max
                snap.merc_hp_percent = int(merc["hp"] / eff_merc_max * 100)
                snap.merc_name = merc["name"]
                snap.merc_type = merc["type"]
                snap.merc_level = merc["level"]

            snap.potion_counts = self._read_item_counts()

            if self.offsets.UI:
                menus = self.open_menus()
                snap.menus_open = self._menus_blocking(menus)
                snap.open_menu_names = [k for k, v in menus.items() if v]
        except Exception as exc:  # never crash the watcher loop
            snap.error = str(exc)
        return snap

    @staticmethod
    def _menus_blocking(menus: dict) -> bool:
        """True if any panel is open that should suppress potion use."""
        return any(menus.get(name) for name in m.BLOCKING_MENUS)

    def in_game(self) -> bool:
        """True if a player unit is present in the game world right now."""
        unit, _ = self._find_player_unit()
        return unit > 0

    def discover(self) -> int:
        """Build-agnostic UnitTable lookup (structural scan across all modules).
        Returns the absolute address or 0. Updates self.offsets on success.

        The resolved ``off`` is *module-relative*; we store it that way and point
        the reader at the module it lives in (re-resolving signatures there) so
        that ``_base() + UnitTable`` lands on the real table (no double base)."""
        from .offsets import discover_unit_table, calculate_offsets
        modules = [(b, s, n) for b, s, n in getattr(self.proc, "all_modules", [])]
        stats: dict = {}
        base, off = discover_unit_table(self.proc, modules=modules, stats=stats)
        if base:
            # The table lives inside module `base`.  Make that the active module
            # and re-resolve the other signatures (UI/Expansion/...) against it so
            # everything is consistent.
            if self.proc.module_base != base:
                self.proc.module_base = base
                self.offsets = calculate_offsets(self.proc)
            self.offsets.module_base = base
            self.offsets.UnitTable = off  # module-relative
            self.offsets.module_name = self._module_name_for(base)
            self.offsets.matched["UnitTable"] = "structural-scan"
            if "UnitTable" in self.offsets.unresolved:
                self.offsets.unresolved.remove("UnitTable")
            self.offsets.struct_stats = stats
            return base + off
        self.offsets.struct_stats = stats
        return 0

    def _module_name_for(self, base: int) -> str:
        """Look up a module's name by its base address."""
        for b, _, n in getattr(self.proc, "all_modules", []):
            if b == base:
                return n
        return self.offsets.module_name

    # ---------------------------------------------------------- diagnostics
    def diagnose(self) -> list[str]:
        """Human-readable report: which signatures resolved and what the reads see.

        This is the tool we use to confirm the build's offsets are correct, and to
        tell a *read failure* (module not readable) from a *pattern mismatch*.
        """
        lines: list[str] = []
        o = self.offsets
        lines.append("=== Process / module ===")
        try:
            from .process import get_process_name
            lines.append(f"  process    : pid {getattr(self.proc, 'pid', '?')}  exe={get_process_name(self.proc.pid)!r}  module={o.module_name or '?'}")
        except Exception:
            lines.append(f"  process    : pid {getattr(self.proc, 'pid', '?')}  ({o.module_name or '?'})")
        lines.append(f"  base       : 0x{o.module_base:X}")
        lines.append(f"  module size: 0x{o.module_size:X}  ({o.module_size:,} bytes)")
        lines.append(f"  bytes read : {o.memory_len:,}  ({'OK' if o.memory_len else 'FAILED - cannot read game memory'})")
        mods = getattr(self.proc, "all_modules", [])
        if mods:
            game_mods = [n for _, _, n in mods
                         if n.lower().endswith("d2r.exe")]
            lines.append(f"  game modules: {game_mods if game_mods else 'NONE -- attached module may be wrong!'}")
            if len(mods) <= 40:
                lines.append("  all modules: " + ", ".join(n for _, _, n in mods))

        lines.append("")
        lines.append("=== Signature scan (hits per candidate) ===")
        if o.memory_len == 0:
            lines.append("  No module bytes were read - the signatures were never tested.")
            lines.append("  -> Check you are running the game and that this tool has read")
            lines.append("     access (try launching as Administrator).")
            return lines

        for name in ("UnitTable", "UI", "Expansion", "Hover", "GameData", "Roster"):
            val = getattr(o, name)
            report = o.scan_report.get(name)
            if report:
                detail = ", ".join(f"{c}={h}hit" for c, h in report)
            else:
                detail = "not tested"
            lines.append(f"  {name:10s}: 0x{val:X}  [{detail}]")

        if not o.UnitTable:
            lines.append("")
            lines.append("  UnitTable NOT resolved by signatures. Will attempt the")
            lines.append("  build-agnostic structural scan (needs you IN A GAME).")
            off = self.discover()
            if off:
                lines.append(f"  structural scan FOUND UnitTable at 0x{off:X}.")
            else:
                lines.append("  structural scan found nothing - make sure you are in a game,")
                lines.append("  then re-run this scan.")
            lines.append("")
            lines.append("  structural-scan diagnostics:")
            for k, v in sorted(o.struct_stats.items()):
                if k == "by_module":
                    continue
                lines.append(f"    {k:16s}: {v}")
            for mod, ms in o.struct_stats.get("by_module", {}).items():
                lines.append(f"    module {mod}:")
                for kk, vv in sorted(ms.items()):
                    lines.append(f"        {kk:16s}: {vv}")

        if not o.UnitTable:
            return lines

        lines.append("")
        lines.append("=== Player read ===")
        unit, corpse = self._find_player_unit()
        if not unit:
            lines.append("  player unit : not found (not in game, or offsets wrong)")
            return lines
        lines.append(f"  player unit : 0x{unit:X}  corpse={corpse}")
        lines.append(f"  class raw   : +0x04(txt)={self.proc.read_u32(unit + m.UNIT_OFFSET_TXTFILE)}"
                     f"  +0x174(CLASS)={self.proc.read_u32(unit + m.UNIT_OFFSET_CLASS)}")
        tbl = self._base() + self.offsets.UnitTable
        buckets = [self.proc.read_u64(tbl + i * 8) for i in range(m.UNIT_TABLE_ENTRIES)]
        populated = sum(1 for b in buckets if 0x10000 <= b < 0x800000000000)
        lines.append(f"  UnitTable   : 0x{tbl:X}  buckets={m.UNIT_TABLE_ENTRIES} populated={populated}")

        # Diagnostic: walk the monster table and report the txtFileNo distribution
        # plus readable names (the merc is normally txtFileNo 338 = NPC_GUARD, but
        # the Infernal Edition may use a different id).
        mtable = tbl + m.UNIT_TABLE_MONSTER_OFFSET
        mcounts: dict = {}
        merc_seen = None
        scanned = 0
        for i in range(m.UNIT_TABLE_ENTRIES):
            u = self.proc.read_u64(mtable + i * 8)
            while u and scanned < 600:
                scanned += 1
                t = self.proc.read_u32(u + m.UNIT_OFFSET_TXTFILE)
                ic = self.proc.read_u8(u + m.UNIT_OFFSET_IS_CORPSE)
                mcounts[t] = mcounts.get(t, 0) + 1
                if t in self.merc_txtfiles:
                    merc_seen = (u, ic)
                u = self.proc.read_ptr(u + m.UNIT_OFFSET_NEXT)
        lines.append(f"  MonsterTable: txtFileNo counts (scanned {scanned} units) = {mcounts}")
        if merc_seen:
            lines.append(f"    merc({sorted(self.merc_txtfiles)}) unit=0x{merc_seen[0]:X} isCorpse={merc_seen[1]}")
        # Dump every monster unit's name so we can identify the merc's real id.
        lines.append("  MonsterTable: units (txtFileNo, name, isCorpse, hasLife) =")
        dumped = 0
        for i in range(m.UNIT_TABLE_ENTRIES):
            u = self.proc.read_u64(mtable + i * 8)
            while u and dumped < 40:
                dumped += 1
                t = self.proc.read_u32(u + m.UNIT_OFFSET_TXTFILE)
                ic = self.proc.read_u8(u + m.UNIT_OFFSET_IS_CORPSE)
                data_ptr = self.proc.read_ptr(u + m.UNIT_OFFSET_UNIT_DATA)
                name = self.proc.read_string(data_ptr) if data_ptr else ""
                slex = self.proc.read_ptr(u + m.UNIT_OFFSET_STATSLISTEX)
                has_life = False
                if slex:
                    sp = self.proc.read_ptr(slex + m.STATSLIST_STAT_PTR)
                    sc = self.proc.read_ptr(slex + m.STATSLIST_STAT_COUNT)
                    raw = self._read_stats(sp, sc)
                    has_life = m.STAT["Life"] in raw and m.STAT["MaxLife"] in raw
                lines.append(f"      txt={t} name={name!r} corpse={ic} life={has_life}")
                u = self.proc.read_ptr(u + m.UNIT_OFFSET_NEXT)

        p = self._read_player(unit)
        stats = p["stats"]
        life = stats.get(m.STAT["Life"], 0)
        max_life = stats.get(m.STAT["MaxLife"], 0)
        mana = stats.get(m.STAT["Mana"], 0)
        max_mana = stats.get(m.STAT["MaxMana"], 0)
        level = stats.get(m.STAT["Level"], 0)
        plausible = (0 < max_life < 100_000 and 0 <= life <= max_life + 5000
                     and 0 < max_mana < 100_000 and 0 < level < 100)
        lines.append(f"  name        : {p['name']!r}")
        lines.append(f"  class/level : {p['class']} / {level}")
        lines.append(f"  HP          : {life} / {max_life}")
        lines.append(f"  MP          : {mana} / {max_mana}")
        lines.append(f"  plausible   : {'YES' if plausible else 'NO  <-- check offsets!'}")

        lines.append("")
        lines.append("=== Mercenary read ===")
        merc = self._read_merc()
        if merc is None:
            lines.append("  merc        : not found (no hireling in the world / not hired)")
        else:
            m_pct = int(merc["hp"] / merc["max_hp"] * 100) if merc["max_hp"] else 0
            lines.append(f"  merc HP     : {merc['hp']} / {merc['max_hp']} ({m_pct}%)")
            lines.append(f"    raw       : Life=0x{merc['raw_life']:X} ({merc['raw_life']})"
                         f"  MaxLife=0x{merc['raw_max_life']:X} ({merc['raw_max_life']})"
                         f"  unitId={merc['unit_id']}")
            lines.append(f"  merc type   : {merc['type']}   level: {merc['level']}   name: {merc['name']!r}")

        lines.append("")
        lines.append("=== Open menus ===")
        menus = self.open_menus()
        open_now = [k for k, v in menus.items() if v]
        lines.append(f"  open        : {open_now if open_now else 'none'}")

        lines.append("")
        lines.append("=== Potions (belt / inventory) ===")
        lines.append("  active codes: " + ("custom combo" if self.codes.entries
                     else "built-in Infernal defaults") +
                     f"  ({len(self.codes.entries)} txtFileNos)")
        counts = self._read_item_counts()
        if not counts.ok:
            lines.append("  item table unreadable (offsets unresolved or not in a game)")
        else:
            lines.append(f"  belt      : {counts.fmt_belt()}")
            for col in counts.columns:
                if col.count:
                    lines.append(f"    {col.key}: {col.count}x txt={col.txt} ({col.kind}, grade {col.grade})")
            lines.append(f"  inventory : {counts.fmt_inventory()}")
            lines.append("  item units (txtFileNo, kind, loc, owner):")
            table = self._base() + self.offsets.UnitTable + m.UNIT_TABLE_ITEM_OFFSET
            dumped = 0
            for i in range(m.UNIT_TABLE_ENTRIES):
                u = self.proc.read_u64(table + i * 8)
                while u and dumped < 30:
                    dumped += 1
                    if self.proc.read_u32(u + m.ITEM_OFFSET_TYPE) == m.ITEM_UNIT_TYPE:
                        txt = self.proc.read_u32(u + m.ITEM_OFFSET_TXTFILE)
                        loc = self.proc.read_u32(u + m.ITEM_OFFSET_LOCATION)
                        ud = self.proc.read_ptr(u + m.ITEM_OFFSET_UNIT_DATA)
                        owner = self.proc.read_u32(ud + m.ITEM_UNIT_DATA_OFFSET_OWNER) if ud else 0
                        lines.append(f"      txt={txt} kind={self.codes.kind(txt)} loc={loc} owner={owner}")
                    u = self.proc.read_ptr(u + m.ITEM_OFFSET_NEXT)
        return lines
