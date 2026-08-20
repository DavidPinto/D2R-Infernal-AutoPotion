"""Game data structures and constants.

Ported from the Go reference project (Hefero/D2R-AutoPotion-Go).  The numerical
values here are stable across D2R client builds (they are the engine's own enum
ids), which is what makes a single tool work on many versions.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# --- Stat IDs (Diablo 2 stat codes) -----------------------------------------
STAT = {
    "Strength": 0,
    "Energy": 1,
    "Dexterity": 2,
    "Vitality": 3,
    "StatPoints": 4,
    "SkillPoints": 5,
    "Life": 6,
    "MaxLife": 7,
    "Mana": 8,
    "MaxMana": 9,
    "Stamina": 10,
    "MaxStamina": 11,
    "Level": 12,
}

# Stats whose raw value is encoded as (display_value << 8).
SHIFTED_STATS = {
    STAT["Life"], STAT["MaxLife"], STAT["Mana"], STAT["MaxMana"],
    STAT["Stamina"], STAT["MaxStamina"],
}

# --- State IDs ---------------------------------------------------------------
# Battle Orders (index 32) temporarily raises the effective max life/mana, so
# the percentage tracker has to follow the boosted maximum instead of the base.
STATE_BATTLE_ORDERS = 32

# --- NPC ids ----------------------------------------------------------------
# The player's hired mercenary is the "Guard" unit (txtFileNo 338) in the
# monster hash table; 271 is the Infernal Edition (Warlock) hireling.
NPC_GUARD = 338

# Friendly hireling-type labels by txtFileNo.  The monster *name* is not a plain
# string on the client, so the type id is what we label the merc with (the real
# name is read from the unit's UTF-16 name field when available).  271 is the
# Infernal Edition Act 1 hireling (a Rogue - "Klaudia"), NOT a Warlock.
MERC_TYPE = {
    271: "Rogue Scout",
    336: "Rogue Scout",       # classic Act 1
    338: "Desert Mercenary",  # classic Act 2 (also the D2R guard default)
    339: "Desert Mercenary",
    340: "Desert Mercenary",
    341: "Iron Wolf",         # classic Act 3
    342: "Iron Wolf",
    343: "Iron Wolf",
    344: "Barbarian",         # classic Act 5
    345: "Barbarian",
    346: "Barbarian",
}

# --- Unit hash-table layout --------------------------------------------------
# The client keeps one hash table per unit type.  Each sub-table is 128 buckets
# of 8 bytes (a pointer), i.e. 0x400 bytes apart.
UNIT_TABLE_ENTRIES = 128
UNIT_TABLE_PLAYER_OFFSET = 0x0
UNIT_TABLE_MONSTER_OFFSET = 0x400
UNIT_TABLE_ITEM_OFFSET = 0x1000

# --- Item unit structure offsets (item units share the unit layout) ----------
# Ported from the Go reference (pkg/memory/item.go) and verified against the
# same engine layout the unit reader already uses.  itemLoc is what tells us
# whether an item sits in the belt (2) or the inventory (0).
ITEM_OFFSET_TYPE = 0x00          # unit type; 4 == item
ITEM_OFFSET_TXTFILE = 0x04       # base-item id (potion families live in a band)
ITEM_OFFSET_UNIT_ID = 0x08
ITEM_OFFSET_LOCATION = 0x0C      # 0 inv, 1 equipped, 2 belt, 3 ground, ...
ITEM_OFFSET_UNIT_DATA = 0x10     # -> item data (owner, inv page, flags)
ITEM_OFFSET_PATH = 0x38
ITEM_OFFSET_STATSLISTEX = 0x88
ITEM_OFFSET_NEXT = 0x150
ITEM_OFFSET_IS_CORPSE = 0x1A6
# Belt/inventory position lives in the item path: X is the belt slot index
# (column = X % 4, row = X // 4), which is what maps slots to the Q/W/E/R keys.
ITEM_PATH_OFFSET_X = 0x10
ITEM_PATH_OFFSET_Y = 0x14

ITEM_UNIT_TYPE = 4
ITEM_UNIT_DATA_OFFSET_OWNER = 0x0C
ITEM_UNIT_DATA_OFFSET_INVPAGE = 0x55
ITEM_UNIT_DATA_OFFSET_FLAGS = 0x18

ITEM_LOC_INVENTORY = 0
ITEM_LOC_EQUIPPED = 1
ITEM_LOC_BELT = 2
ITEM_LOC_GROUND = 3
ITEM_LOC_CURSOR = 4
ITEM_LOC_DROPPING = 5
ITEM_LOC_SOCKET = 6

# Belt potions are bound to the four belt columns Q/W/E/R.
POTION_SLOTS = ("heal", "mana", "rejuv")
BELT_COLUMN_KEYS = ("Q", "W", "E", "R")

# Base-item txtFileNo bands for potions.  IMPORTANT: these are the *Infernal
# Edition* (Warlock expansion) values, which renumbered the classic D2R item
# table by +15 (587 -> 602, 593 -> 608, 515 -> 530, ...).  The Go reference's
# classic codes do NOT match this build; the reader only classifies potions it
# actually sees, so a wrong band simply shows as "unknown" instead of crashing.
#   602..606  Minor/Light/Healing/Greater/Super Healing Potion
#   607..611  Minor/Light/Mana/Greater/Super Mana Potion
#   530, 531  Rejuvenation / Full Rejuvenation Potion
#   528, 529, 532  Stamina / Antidote / Thawing (drinkable, but not keyed)
POTION_TXTFILE_HEAL = frozenset(range(602, 607))
POTION_TXTFILE_MANA = frozenset(range(607, 612))
POTION_TXTFILE_REJUV = frozenset({530, 531})
POTION_TXTFILE_OTHER = frozenset({528, 529, 532})

POTION_KIND_BY_TXTFILE: dict[int, str] = {}
for _t in POTION_TXTFILE_HEAL:
    POTION_KIND_BY_TXTFILE[_t] = "heal"
for _t in POTION_TXTFILE_MANA:
    POTION_KIND_BY_TXTFILE[_t] = "mana"
for _t in POTION_TXTFILE_REJUV:
    POTION_KIND_BY_TXTFILE[_t] = "rejuv"
for _t in POTION_TXTFILE_OTHER:
    POTION_KIND_BY_TXTFILE[_t] = "other"

# Weakest -> strongest grade order per family (grade-aware column selection).
# These are the *default* codes for the Infernal Edition build; users may teach
# the app different codes for their version/mods via the Calibrate tab (see
# PotionCodes + config "combos").
POTION_GRADES: dict[str, list[int]] = {
    "heal": [602, 603, 604, 605, 606],
    "mana": [607, 608, 609, 610, 611],
    "rejuv": [530, 531],
}
POTION_GRADE_INDEX: dict[int, int] = {
    txt: grade for kinds in POTION_GRADES.values()
    for grade, txt in enumerate(kinds)
}

# Restore semantics by (kind, grade), so user-calibrated codes get the correct
# amounts without hard-coding each txtFileNo.  Potions restore over a duration
# (rejuvenation is instant) and the total restored depends on BOTH the grade and
# the drinking character's class group:
#   heal groups: 0 = Druid/Necro/Sorc/Warlock, 1 = Amazon/Assassin/Paladin,
#                2 = Barbarian
#   mana groups: 0 = Barbarian, 1 = Amazon/Assassin/Paladin,
#                2 = Druid/Necro/Sorc/Warlock
# These are the real in-game figures (verified 2026).  The earlier hard-coded
# 30/60/120/200 and the "grade 4 == Full heal, 100% of max" idea were wrong:
# grade 4 is Super (320/480/640) and there is no "Full" heal/mana potion.
POTION_KINDS = ("heal", "mana", "rejuv", "other")
# Each row: (duration_seconds, group0_restore, group1_restore, group2_restore).
POTION_HEAL_TABLE = (
    (7.68, 30, 45, 60),     # Minor Healing Potion
    (6.40, 60, 90, 120),    # Light Healing Potion
    (6.84, 100, 150, 200),  # Healing Potion
    (7.68, 180, 270, 360),  # Greater Healing Potion
    (10.24, 320, 480, 640), # Super Healing Potion
)
POTION_MANA_TABLE = (
    (5.12, 20, 30, 40),     # Minor Mana Potion
    (5.12, 40, 60, 80),     # Light Mana Potion
    (5.12, 80, 120, 160),   # Mana Potion
    (5.12, 150, 225, 300),  # Greater Mana Potion
    (5.12, 250, 375, 500),  # Super Mana Potion
)
POTION_TABLES = {"heal": POTION_HEAL_TABLE, "mana": POTION_MANA_TABLE}
# Character class -> restore group per family (used when a class is unknown ->
# group 1, the middle column of the tables above).
CLASS_HEAL_GROUP = {
    "Amazon": 1, "Sorceress": 0, "Necromancer": 0, "Paladin": 1,
    "Barbarian": 2, "Druid": 0, "Assassin": 1, "Warlock": 0,
}
CLASS_MANA_GROUP = {
    "Amazon": 1, "Sorceress": 2, "Necromancer": 2, "Paladin": 1,
    "Barbarian": 0, "Druid": 2, "Assassin": 1, "Warlock": 2,
}
CLASS_GROUPS = {"heal": CLASS_HEAL_GROUP, "mana": CLASS_MANA_GROUP}
# Character class names by class byte (D2R 3.x).  Unknown classes fall back to str(cls).
CLASS_NAMES = [
    "Amazon", "Sorceress", "Necromancer", "Paladin",
    "Barbarian", "Druid", "Assassin", "Warlock",
]
# Rejuvenation potions restore this % of max life AND max mana, instantly.
REJUV_RESTORE_PERCENT = (35, 100)

# Action labels for UI/logging.
ACTION_LABELS = {
    "heal": "Health potion",
    "mana": "Mana potion",
    "rejuv": "Rejuvenation potion",
    "merc_heal": "Merc health potion",
    "merc_rejuv": "Merc rejuv potion",
}

# Default hireling txtFileNos (player-owned NPC): 338 Guard (classic D2R),
# 271 the Infernal Edition Warlock hireling.  Users can override per combo.
MERC_TXTFILES_DEFAULT = frozenset({338, 271})


@dataclass
class PotionEntry:
    """One user-defined potion: its base-item txtFileNo + family + grade."""
    txt: int
    kind: str      # "heal" | "mana" | "rejuv" | "other"
    grade: int     # 0-based within kind; -1 for "other"
    # Optional custom restore/duration override (per txtFileNo)
    # If provided, these override the built-in tables for this specific txt.
    restore_override: dict[int, int] | None = None  # {class_group: restore}
    duration_override: float | None = None


class PotionCodes:
    """Lookup table that maps potion txtFileNos to kind/grade/restore.

    Built from a list of :class:`PotionEntry` (empty -> unknown potions are
    ignored, never mis-classified).  The built-in Infernal codes are produced by
    :func:`default_potion_codes`; the Calibrate tab replaces that table with the
    user's own codes for their game version/mods.

    Optional override tables (from config) allow per-build customization without
    code changes: class groups, rejuv %, custom restore/duration per txtFileNo."""
    def __init__(self, entries: list[PotionEntry] | None = None,
                 class_heal_group: dict[str, int] | None = None,
                 class_mana_group: dict[str, int] | None = None,
                 rejuv_restore_percent: tuple[int, int] | None = None):
        self.entries: dict[int, PotionEntry] = {}
        for e in entries or []:
            if e.kind in POTION_KINDS and (e.grade >= 0 or e.kind == "other"):
                self.entries[e.txt] = e
        # Optional override tables (None = use built-in defaults)
        self._class_heal_group = class_heal_group
        self._class_mana_group = class_mana_group
        self._rejuv_restore_percent = rejuv_restore_percent
        self.player_class: str = ""

    def kind(self, txt: int) -> str | None:
        e = self.entries.get(txt)
        return e.kind if e else None

    def grade(self, txt: int) -> int:
        e = self.entries.get(txt)
        return e.grade if e else -1

    def _group(self, kind: str, player_class: str) -> int:
        """Restore group (0..2) for a kind; unknown class -> middle group."""
        pc = (player_class or self.player_class or "")
        if kind == "heal" and self._class_heal_group:
            return self._class_heal_group.get(pc, 1)
        if kind == "mana" and self._class_mana_group:
            return self._class_mana_group.get(pc, 1)
        return CLASS_GROUPS.get(kind, {}).get(pc, 1)

    def restore(self, txt: int, max_value: int, player_class: str = "") -> int:
        """HP/mana a potion restores in total (over its duration) at ``max_value``."""
        e = self.entries.get(txt)
        if not e:
            return 0
        if e.kind == "rejuv":
            if e.restore_override:
                grp = self._group("rejuv", player_class)
                if grp in e.restore_override:
                    return e.restore_override[grp]
            # Missing group in the per-class override: fall back to the % table
            # (the override dict is NOT a percentage tuple — do not index it).
            pct = self._rejuv_restore_percent
            if pct and 0 <= e.grade < len(pct):
                return max(0, int(max_value * pct[e.grade] / 100))
            if 0 <= e.grade < len(REJUV_RESTORE_PERCENT):
                return max(0, int(max_value * REJUV_RESTORE_PERCENT[e.grade] / 100))
            return 0
        row = POTION_TABLES.get(e.kind)
        if row and 0 <= e.grade < len(row):
            grp = self._group(e.kind, player_class)
            if e.restore_override and grp in e.restore_override:
                return e.restore_override[grp]
            return row[e.grade][1 + grp]
        return 0

    def duration(self, txt: int, player_class: str = "") -> float:
        """Seconds a potion takes to deliver its restore (0.0 == instant)."""
        e = self.entries.get(txt)
        if not e or e.kind == "rejuv":
            return 0.0
        if e.duration_override is not None:
            return e.duration_override
        row = POTION_TABLES.get(e.kind)
        if row and 0 <= e.grade < len(row):
            return row[e.grade][0]
        return 0.0

    def restore_percent(self, txt: int) -> int | None:
        """Percentage-of-max restore for rejuv grades; None for every other potion."""
        e = self.entries.get(txt)
        if not e or e.kind != "rejuv":
            return None
        if 0 <= e.grade < len(REJUV_RESTORE_PERCENT):
            return REJUV_RESTORE_PERCENT[e.grade]
        return None

    def grade_names(self, kind: str) -> list[str]:
        """Sorted potion grade labels for a kind (UI dropdowns)."""
        if kind == "other":
            return ["utility"]
        if kind == "heal":
            return ["minor", "light", "healing", "greater", "super"]
        if kind == "mana":
            return ["minor", "light", "mana", "greater", "super"]
        return ["rejuv", "full rejuv"]


def default_potion_codes(
    class_heal_group: dict[str, int] | None = None,
    class_mana_group: dict[str, int] | None = None,
    rejuv_restore_percent: tuple[int, int] | None = None,
) -> PotionCodes:
    """The built-in Infernal Edition potion table (single source of truth).

    Optional override tables allow per-build customization without code changes."""
    entries: list[PotionEntry] = []
    for kind, txts in POTION_GRADES.items():
        for grade, txt in enumerate(txts):
            entries.append(PotionEntry(txt=txt, kind=kind, grade=grade))
    for txt in POTION_TXTFILE_OTHER:
        entries.append(PotionEntry(txt=txt, kind="other", grade=-1))
    return PotionCodes(
        entries,
        class_heal_group=class_heal_group,
        class_mana_group=class_mana_group,
        rejuv_restore_percent=rejuv_restore_percent,
    )


def belt_corner_codes(slots: dict) -> set[int]:
    """txtFileNos sitting in the belt *corner* slots (the edge slots of every
    row: column 0 and column 3).  Used by the calibration wizard."""
    return {txt for x, txt in slots.items() if x >= 0 and x % 4 in (0, 3)}


def corner_potion_code(slots: dict) -> int | None:
    """The single txtFileNo present in EVERY belt corner slot, else None.

    The wizard asks the user to put one known potion in all corners; this is
    what identifies that potion's code for the current build."""
    corners = {x: txt for x, txt in slots.items() if x >= 0 and x % 4 in (0, 3)}
    if len(corners) < 4:
        return None
    vals = set(corners.values())
    return vals.pop() if len(vals) == 1 else None


def infer_potion_family(kind: str, anchor_txt: int, anchor_grade: int,
                        existing=()) -> list[PotionEntry]:
    """Fill in a potion family's codes assuming they are consecutive (true for
    classic D2R and the Infernal +15 renumber): anchoring e.g. Light Mana (608,
    grade 1) yields Minor..Full Mana 607..611.  Codes already in ``existing`` are
    never re-claimed.  Returns new PotionEntry objects."""
    existing = set(existing)
    if kind == "other":
        return [] if anchor_txt in existing else [PotionEntry(anchor_txt, kind, -1)]
    grades = POTION_GRADES.get(kind)
    if not grades:
        return []
    base = anchor_txt - anchor_grade
    out: list[PotionEntry] = []
    for g in range(len(grades)):
        t = base + g
        if t > 0 and t not in existing:
            out.append(PotionEntry(t, kind, g))
    return out


# Belt txtFileNo -> number of belt rows (4 columns x 1..4 rows).  Classic D2R
# ids plus the Infernal +15 renumber for the same belts (the equipped Light Belt
# in this build kept its classic id 345, so both sets are accepted).
BELT_ROWS_BY_TXTFILE: dict[int, int] = {
    # 2 rows: Sash / Light Belt / Demonhide Sash / Sharkskin Belt / Spiderweb / Vampirefang
    344: 2, 345: 2, 390: 2, 391: 2, 460: 2, 461: 2,
    # 3 rows: Belt / Heavy Belt / Mesh Belt / Battle Belt / Mithril Coil / Troll Belt
    346: 3, 347: 3, 392: 3, 393: 3, 462: 3, 463: 3,
    # 4 rows: Plated Belt / War Belt / Colossus Girdle
    348: 4, 394: 4, 464: 4,
    # Infernal +15 renumber guesses (unused ids are harmless).
    359: 2, 360: 2, 405: 2, 406: 2, 475: 2, 476: 2,
    361: 3, 362: 3, 407: 3, 408: 3, 477: 3, 478: 3,
    363: 4, 409: 4, 479: 4,
}


def belt_rows_for(txt: int) -> int | None:
    """Rows (1..4) for an equipped belt's txtFileNo, or None when unknown."""
    return BELT_ROWS_BY_TXTFILE.get(txt)


def belt_empty_slots(belt_rows: int, filled: list) -> list[int]:
    """Belt slot indices (X) with no potion, for a belt of ``belt_rows`` rows.

    The belt grid is 4 columns wide; slot X = row * 4 + column.  Only slots that
    exist on this belt (0 .. rows*4-1) are considered."""
    total = max(1, int(belt_rows)) * 4
    have = set(int(x) for x in filled)
    return [x for x in range(total) if x not in have]


def solve_grid_mapping(samples, cell: float | None = None) -> tuple[float, float, float] | None:
    """Solve the screen mapping ``screen = origin + grid * cell`` for a click grid.

    ``samples`` are ``(grid_x, grid_y, screen_x, screen_y)`` tuples captured while
    the mouse hovered over a known grid cell (grid coords come from the item
    struct, screen coords from the cursor).  When ``cell`` is known (a previous
    calibration) a single sample solves the origin; otherwise at least two samples
    on *different* grid cells are needed to solve cell size + origin by
    least squares.  Returns ``(cell, origin_x, origin_y)`` or None."""
    if not samples or (cell is None and len(samples) < 2):
        return None
    sx = [float(s[2]) for s in samples]
    sy = [float(s[3]) for s in samples]
    gx = [float(s[0]) for s in samples]
    gy = [float(s[1]) for s in samples]
    if cell is None:
        mx, my = sum(gx) / len(gx), sum(gy) / len(gy)
        num = sum(sx[i] * (gx[i] - mx) + sy[i] * (gy[i] - my) for i in range(len(samples)))
        den = sum((gx[i] - mx) ** 2 + (gy[i] - my) ** 2 for i in range(len(samples)))
        if den <= 0:
            return None
        cell = num / den
    if cell <= 0:
        return None
    ox = sum(sx[i] - gx[i] * cell for i in range(len(samples))) / len(samples)
    oy = sum(sy[i] - gy[i] * cell for i in range(len(samples))) / len(samples)
    return cell, ox, oy


def potion_entries_from_lists(rows) -> list[PotionEntry]:
    """Build PotionEntry objects from persisted rows.
    Accepts both legacy [[txt, kind, grade], ...] and new
    [[txt, kind, grade, restore_override, duration_override], ...] formats.
    Invalid rows are dropped; later rows override earlier ones for a txt."""
    out: list[PotionEntry] = []
    for row in rows or []:
        try:
            txt = int(row[0])
            kind = str(row[1]).strip().lower()
            grade = int(row[2])
            restore_override = None
            duration_override = None
            if len(row) > 3 and row[3]:
                if isinstance(row[3], dict):
                    restore_override = {int(k): int(v) for k, v in row[3].items()}
            if len(row) > 4 and row[4] is not None:
                duration_override = float(row[4])
        except (TypeError, ValueError, IndexError):
            continue
        if kind in POTION_KINDS and (grade >= 0 or kind == "other"):
            out.append(PotionEntry(txt=txt, kind=kind, grade=grade,
                                    restore_override=restore_override,
                                    duration_override=duration_override))
    return out


def potion_kind(txt_file: int) -> str | None:
    """'heal' | 'mana' | 'rejuv' | 'other' for a potion txtFileNo, else None."""
    return POTION_KIND_BY_TXTFILE.get(txt_file)


def potion_grade(txt_file: int) -> int:
    """Grade index for a potion txt (0 = weakest); -1 when not a known grade."""
    return POTION_GRADE_INDEX.get(txt_file, -1)


def potion_restore(txt_file: int, max_value: int) -> int:
    """HP/mana a potion restores at ``max_value`` (default middle class group)."""
    return default_potion_codes().restore(txt_file, max_value)


@dataclass
class BeltColumn:
    """One of the four belt columns (Q/W/E/R), as read from the item table.

    ``txt``/``kind``/``grade`` describe the potion that would be drunk NEXT from
    this column (the lowest X slot in it); ``count`` is every potion stacked in
    the column.  An empty column has kind None and grade -1."""
    key: str = "?"
    index: int = 0
    txt: int | None = None
    kind: str | None = None
    grade: int = -1
    count: int = 0

# --- Structure offsets inside a unit (D2R 3.x client layout) -----------------
# These are the engine struct offsets.  They are extremely stable across D2R
# patches; only the *patterns* that locate the table base change.
UNIT_OFFSET_UNIT_ID = 0x08
UNIT_OFFSET_TXTFILE = 0x04
UNIT_OFFSET_UNIT_DATA = 0x10
UNIT_OFFSET_PATH = 0x38
UNIT_OFFSET_STATSLISTEX = 0x88
UNIT_OFFSET_INVENTORY = 0x90
UNIT_OFFSET_NEXT = 0x150
UNIT_OFFSET_IS_CORPSE = 0x1A6
UNIT_OFFSET_CLASS = 0x174

PATH_OFFSET_X = 0x02
PATH_OFFSET_Y = 0x06

STATSLIST_STAT_PTR = 0x30
STATSLIST_STAT_COUNT = 0x38
# Second stat block on the same stats-list: the merged/item list that carries
# the true maximums including gear bonuses (the base list only has the un-geared
# values).  Verified live: merc base MaxLife = 189<<8, item MaxLife = 199<<8.
STATSLIST_ITEM_STAT_PTR = 0xA8
STATSLIST_ITEM_STAT_COUNT = 0xB0

# Inventory header field that is non-zero only for the *main* (local) player.
INV_MAIN_CHECK = 0x30
INV_MAIN_CHECK_EXP = 0x70

# Unit class ids (data/class.go).  Index 7 (Warlock) is the Infernal Edition
# expansion class added on top of the original seven.
CLASS = [
    "Amazon", "Sorceress", "Necromancer", "Paladin",
    "Barbarian", "Druid", "Assassin", "Warlock",
]

# --- UI menu flags (open_menus byte indices, base = UI - 0xA) ---------------
MENU_FLAGS = {
    "Inventory": 0x01,
    "Character": 0x02,
    "SkillSelect": 0x03,
    "SkillTree": 0x04,
    "Chat": 0x05,
    "NPCInteract": 0x08,
    "QuitMenu": 0x09,
    "NPCShop": 0x0B,
    "Stash": 0x18,
    "Anvil": 0x0D,
    "Waypoint": 0x13,
    "Cube": 0x19,
    "MercInventory": 0x1E,
    "QuestLog": 0x0E,
}

# A panel is "blocking" when pressing a belt key would be wasted / harmful.
BLOCKING_MENUS = {
    "Inventory", "Character", "SkillTree", "NPCInteract", "NPCShop",
    "Stash", "Anvil", "Waypoint", "Cube", "MercInventory", "QuitMenu",
    "SkillSelect", "Chat", "QuestLog",
}


@dataclass
class PotionCounts:
    """How many drinkable potions are in the belt vs the personal inventory.

    Keys are the POTION_SLOTS families plus "other" (utility potions that do not
    map to a belt key).  ``ok`` is False when the item table could not be read
    (offsets unresolved, or item struct not verified on a build)."""
    belt: dict = field(default_factory=lambda: {k: 0 for k in ("heal", "mana", "rejuv", "other")})
    inventory: dict = field(default_factory=lambda: {k: 0 for k in ("heal", "mana", "rejuv", "other")})
    columns: list = field(default_factory=lambda: [
        BeltColumn(key=k, index=i) for i, k in enumerate(BELT_COLUMN_KEYS)])
    ok: bool = False
    # Belt refill bookkeeping: how many rows the equipped belt has, which slot
    # X values hold a potion, which are free, and the per-slot potion kind
    # (slot X -> "heal"/"mana"/"rejuv"/"other").  belt_slots is what the smart
    # layout/ratio refill uses to account for the belt's current content.
    belt_rows: int = 1
    belt_filled: list = field(default_factory=list)
    belt_empty: list = field(default_factory=list)
    belt_slots: dict = field(default_factory=dict)
    # PotionCodes used for grade/restore decisions (set by the reader from the
    # active combo); None -> the built-in Infernal defaults.
    codes: object = None

    def choose_belt_column(self, kind: str, deficit: int, max_value: int,
                           allowed_keys: tuple = BELT_COLUMN_KEYS) -> int | None:
        """Best belt-column index for ``kind`` to cover a ``deficit`` of ``max_value``.

        Among the bound columns holding a potion of ``kind``, prefers the smallest
        grade whose restore covers the deficit; when none does, uses the strongest
        available.  Returns None when no usable column exists."""
        codes = self.codes if self.codes is not None else default_potion_codes()
        candidates = [
            c for c in self.columns
            if c.kind == kind and c.count > 0 and c.grade >= 0
            and c.key in allowed_keys and codes.restore(c.txt, max_value) > 0
        ]
        if not candidates:
            return None
        covering = [c for c in candidates if codes.restore(c.txt, max_value) >= deficit]
        if covering:
            return min(covering, key=lambda c: c.grade).index
        return max(candidates, key=lambda c: c.grade).index

    def belt_total(self) -> int:
        return sum(self.belt.values())

    def inventory_total(self) -> int:
        return sum(self.inventory.values())

    def fmt_belt(self) -> str:
        if not self.ok:
            return "unknown"
        parts = [f"{self.belt.get(k, 0)} {k}" for k in POTION_SLOTS]
        parts.append(f"{self.belt.get('other', 0)} other")
        return "  ".join(parts)

    def fmt_inventory(self) -> str:
        if not self.ok:
            return "unknown"
        parts = [f"{self.inventory.get(k, 0)} {k}" for k in POTION_SLOTS]
        parts.append(f"{self.inventory.get('other', 0)} other")
        return "  ".join(parts)


@dataclass
class PlayerSnapshot:
    name: str = ""
    unit_id: int = 0
    class_name: str = ""
    level: int = 0
    in_game: bool = False
    hp: int = 0
    max_hp: int = 0
    mana: int = 0
    max_mana: int = 0
    hp_percent: int = 100
    mana_percent: int = 100
    merc_hp: int = 0
    merc_max_hp: int = 0
    merc_hp_percent: int = 0   # 0 == no merc (or dead)
    merc_name: str = ""        # usually empty (monster names are not plain strings)
    merc_type: str = ""        # friendly hireling type label
    merc_level: int = 0
    potion_counts: PotionCounts = field(default_factory=PotionCounts)
    menus_open: bool = False
    open_menu_names: list = field(default_factory=list)
    error: str = ""

    @property
    def alive(self) -> bool:
        """True while in a game and the player has HP (i.e. not dead)."""
        return self.in_game and self.hp > 0

    @property
    def merc_alive(self) -> bool:
        """True when a mercenary is hired AND currently alive (dead merc: no waste)."""
        return self.merc_max_hp > 0 and self.merc_hp > 0


@dataclass
class GameEvent:
    """One potion action, consumed by the UI log."""

    kind: str            # heal | mana | rejuv | merc_heal | merc_rejuv | info | error | status
    message: str = ""
    hp: int = 0
    mana: int = 0
    hp_percent: int = 0
    mana_percent: int = 0
    merc_percent: int = 0
    timestamp: float = 0.0
