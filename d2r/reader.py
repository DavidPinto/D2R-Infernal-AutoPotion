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

from . import models as m
from .offsets import Offsets, calculate_offsets, _is_likely_ptr, _unit_looks_valid
from .process import Process


class GameReader:
    def __init__(self, proc: Process):
        """Attach to a game process, resolve offsets, and prepare the state
        trackers (running maxima + manual max overrides for % computation)."""
        self.proc = proc
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
    # Edition (Warlock) hireling.  Add more here if a different merc type is hired.
    MERC_TXTFILES = frozenset({338, 271})

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
                if txt in self.MERC_TXTFILES and has_life:
                    if matched is None:
                        matched = (unit, raw, txt)
                        matched_corpse = is_corpse
                    if not is_corpse:
                        break  # living hireling identified
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
        hp, max_hp = self._merc_values(raw)
        level = raw.get(m.STAT["Level"], 0)
        name = ""
        if unit:
            ud = self.proc.read_ptr(unit + m.UNIT_OFFSET_UNIT_DATA)
            name = self.proc.read_string(ud) if ud else ""
        # Monster names are usually encoded (not plain strings); only keep a
        # name that is clean printable ASCII so the UI never shows garbage.
        if name and any(ord(c) < 32 or ord(c) > 126 for c in name):
            name = ""
        return {
            "hp": hp, "max_hp": max_hp,
            "name": name,
            "type": m.MERC_TYPE.get(txt, f"Hireling ({txt})"),
            "level": level,
        }

    @staticmethod
    def _merc_values(raw: dict) -> tuple[int, int]:
        """Convert raw merc stats into (life_display, max_display).

        MaxLife is stored shifted (<<8).  Life *below* 0x8000 is reported by the
        engine as a 0..1 fraction of max (display values 0-127), so it is scaled
        back proportionally; from 0x8000 up it is a plain shifted value (128+)."""
        raw_max = raw.get(m.STAT["MaxLife"], 0)
        max_disp = raw_max >> 8
        if max_disp <= 0:
            return 0, 0
        raw_life = raw.get(m.STAT["Life"], 0)
        if raw_life < 32768:
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
                    kind = m.potion_kind(int.from_bytes(buf[0x04:0x08], "little"))
                    if kind:
                        loc = int.from_bytes(buf[0x0C:0x10], "little")
                        ud = int.from_bytes(buf[0x10:0x18], "little")
                        owner = self.proc.read_u32(ud + m.ITEM_UNIT_DATA_OFFSET_OWNER) if ud else 0
                        if loc == m.ITEM_LOC_BELT and (not main_id or owner == main_id):
                            counts.belt[kind] += 1
                            path = int.from_bytes(buf[0x38:0x40], "little")
                            slot_x = self.proc.read_u16(path + m.ITEM_PATH_OFFSET_X) if path else -1
                            col = slot_x % len(m.BELT_COLUMN_KEYS) if slot_x >= 0 else 0
                            belt_cols.setdefault(col, []).append((slot_x, int.from_bytes(buf[0x04:0x08], "little")))
                        elif loc == m.ITEM_LOC_INVENTORY and main_id:
                            if ud:
                                page = self.proc.read_u8(ud + m.ITEM_UNIT_DATA_OFFSET_INVPAGE)
                                flags = self.proc.read_u32(ud + m.ITEM_UNIT_DATA_OFFSET_FLAGS)
                                if (owner == main_id and page == 0 and not (flags & 0x2000)):
                                    counts.inventory[kind] += 1
                unit = int.from_bytes(buf[0x150:0x158], "little")

        for col_idx, entries in belt_cols.items():
            if not entries or not (0 <= col_idx < len(counts.columns)):
                continue
            column = counts.columns[col_idx]
            column.count = len(entries)
            next_txt = min(entries, key=lambda e: e[0])[1]   # lowest slot = next drunk
            column.txt = next_txt
            column.kind = m.potion_kind(next_txt)
            column.grade = m.potion_grade(next_txt)

        counts.ok = seen > 0
        return counts

    # -------------------------------------------------------------- menus
    def open_menus(self) -> dict:
        """Read the UI panel flags (inventory, stash, vendor, chat, ...).

        Each flag is a byte in the UI struct; 'MapShown' is a separate byte at
        the UI base.  Returns a dict of {menu_name: bool}."""
        if not self.offsets.UI:
            return {}
        ui = self._base() + self.offsets.UI
        buf = self.proc.read_bytes(ui - 0xA, 0x16D)
        if len(buf) != 0x16D:
            return {}
        menus = {}
        for name, idx in m.MENU_FLAGS.items():
            menus[name] = buf[idx] != 0
        menus["MapShown"] = self.proc.read_u8(ui) != 0
        return menus

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
            life = stats.get(m.STAT["Life"], 0)
            max_life = stats.get(m.STAT["MaxLife"], 0)
            mana = stats.get(m.STAT["Mana"], 0)
            max_mana = stats.get(m.STAT["MaxMana"], 0)

            # Effective max HP/MP = running observed maximum, seeded by the MaxLife
            # stat (which is the base WITHOUT item/skill bonuses).  Gear/charm
            # bonuses are NOT in the stat, so once the player is ever at full the
            # observed life (e.g. 131 with gear) becomes the true max.  We only
            # grow the tracked max; we never shrink it (damage must not lower the
            # max, and buff expiry only slightly over-reports until next full heal).
            max_life_stat = stats.get(m.STAT["MaxLife"], 0)
            max_mana_stat = stats.get(m.STAT["MaxMana"], 0)
            self._max_life = max(self._max_life, max_life_stat, life)
            self._max_mana = max(self._max_mana, max_mana_stat, mana)

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
            merc = self._read_merc()
            if merc is not None:
                # Merc max also gets the gear-bonus treatment: the MaxLife stat is
                # base-only, so track the running observed max (seeded by the stat
                # and the current life) the same way we do for the player.
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
                         if any(n.lower().endswith(g.lower()) for g in
                                ("d2r.exe", "d2rmm.exe", "diablo ii resurrected.exe"))]
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
                if t == m.NPC_GUARD:
                    merc_seen = (u, ic)
                u = self.proc.read_ptr(u + m.UNIT_OFFSET_NEXT)
        lines.append(f"  MonsterTable: txtFileNo counts (scanned {scanned} units) = {mcounts}")
        if merc_seen:
            lines.append(f"    merc(338) unit=0x{merc_seen[0]:X} isCorpse={merc_seen[1]}")
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
            lines.append(f"  merc type   : {merc['type']}   level: {merc['level']}   name: {merc['name']!r}")

        lines.append("")
        lines.append("=== Open menus ===")
        menus = self.open_menus()
        open_now = [k for k, v in menus.items() if v]
        lines.append(f"  open        : {open_now if open_now else 'none'}")

        lines.append("")
        lines.append("=== Potions (belt / inventory) ===")
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
                        lines.append(f"      txt={txt} kind={m.potion_kind(txt)} loc={loc} owner={owner}")
                    u = self.proc.read_ptr(u + m.ITEM_OFFSET_NEXT)
        return lines
