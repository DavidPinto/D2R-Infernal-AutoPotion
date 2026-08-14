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

# Friendly hireling-type labels (the monster *name* is not readable as a plain
# string on the client, so the type id is what we can show reliably).
MERC_TYPE = {
    271: "Warlock hireling",
    338: "Guard",
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
#   602..606  Minor/Light/Greater/Super/Full Healing Potion
#   607..611  Minor/Light/Greater/Super/Full Mana Potion
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

# Restore amounts: fixed hit-points/mana for normal grades (classic D2 figures);
# the "Full" grades restore 100% of the relevant maximum; rejuvenation potions
# restore a percentage of BOTH life and mana.
POTION_RESTORE_POINTS = {
    602: 30, 603: 60, 604: 120, 605: 200,
    607: 30, 608: 60, 609: 120, 610: 200,
}
POTION_RESTORE_PERCENT = {606: 100, 611: 100, 530: 35, 531: 100}

# Restore semantics by (kind, grade), so user-calibrated codes get the correct
# amounts without hard-coding each txtFileNo.
POTION_KINDS = ("heal", "mana", "rejuv", "other")
_GRADE_RESTORE_POINTS = (30, 60, 120, 200)   # grades 0..3 of heal/mana
_FULL_GRADE_RESTORE_PERCENT = 100            # grade 4 (Full) of heal/mana
_REJUV_RESTORE_PERCENT = (35, 100)           # rejuv grades

# Default hireling txtFileNos (player-owned NPC): 338 Guard (classic D2R),
# 271 the Infernal Edition Warlock hireling.  Users can override per combo.
MERC_TXTFILES_DEFAULT = frozenset({338, 271})


@dataclass
class PotionEntry:
    """One user-defined potion: its base-item txtFileNo + family + grade."""
    txt: int
    kind: str      # "heal" | "mana" | "rejuv" | "other"
    grade: int     # 0-based within kind; -1 for "other"


class PotionCodes:
    """Lookup table that maps potion txtFileNos to kind/grade/restore.

    Built from a list of :class:`PotionEntry` (empty -> unknown potions are
    ignored, never mis-classified).  The built-in Infernal codes are produced by
    :func:`default_potion_codes`; the Calibrate tab replaces that table with the
    user's own codes for their game version/mods."""
    def __init__(self, entries: list[PotionEntry] | None = None):
        self.entries: dict[int, PotionEntry] = {}
        for e in entries or []:
            if e.kind in POTION_KINDS and (e.grade >= 0 or e.kind == "other"):
                self.entries[e.txt] = e

    def kind(self, txt: int) -> str | None:
        e = self.entries.get(txt)
        return e.kind if e else None

    def grade(self, txt: int) -> int:
        e = self.entries.get(txt)
        return e.grade if e else -1

    def restore_points(self, txt: int) -> int:
        e = self.entries.get(txt)
        if not e:
            return 0
        if e.kind == "rejuv":
            return 0
        if 0 <= e.grade < len(_GRADE_RESTORE_POINTS):
            return _GRADE_RESTORE_POINTS[e.grade]
        return 0

    def restore_percent(self, txt: int) -> int | None:
        e = self.entries.get(txt)
        if not e:
            return None
        if e.kind == "rejuv":
            return _REJUV_RESTORE_PERCENT[e.grade] if 0 <= e.grade < len(_REJUV_RESTORE_PERCENT) else None
        if e.grade == 4:
            return _FULL_GRADE_RESTORE_PERCENT
        return None

    def restore(self, txt: int, max_value: int) -> int:
        """Hit points / mana restored by a potion at a maximum of ``max_value``."""
        pct = self.restore_percent(txt)
        if pct is not None:
            return max(0, int(max_value * pct / 100))
        return self.restore_points(txt)

    def grade_names(self, kind: str) -> list[str]:
        """Sorted potion grade labels for a kind (UI dropdowns)."""
        if kind == "other":
            return ["utility"]
        labels = ["minor", "light", "greater", "super", "full"]
        if kind == "rejuv":
            labels = ["rejuv", "full rejuv"]
        return labels


def default_potion_codes() -> PotionCodes:
    """The built-in Infernal Edition potion table (single source of truth)."""
    entries: list[PotionEntry] = []
    for kind, txts in POTION_GRADES.items():
        for grade, txt in enumerate(txts):
            entries.append(PotionEntry(txt=txt, kind=kind, grade=grade))
    for txt in POTION_TXTFILE_OTHER:
        entries.append(PotionEntry(txt=txt, kind="other", grade=-1))
    return PotionCodes(entries)


def potion_entries_from_lists(rows) -> list[PotionEntry]:
    """Build PotionEntry objects from persisted [[txt, kind, grade], ...] rows.
    Invalid rows are dropped; later rows override earlier ones for a txt."""
    out: list[PotionEntry] = []
    for row in rows or []:
        try:
            txt = int(row[0])
            kind = str(row[1]).strip().lower()
            grade = int(row[2])
        except (TypeError, ValueError, IndexError):
            continue
        if kind in POTION_KINDS and (grade >= 0 or kind == "other"):
            out.append(PotionEntry(txt=txt, kind=kind, grade=grade))
    return out


def potion_kind(txt_file: int) -> str | None:
    """'heal' | 'mana' | 'rejuv' | 'other' for a potion txtFileNo, else None."""
    return POTION_KIND_BY_TXTFILE.get(txt_file)


def potion_grade(txt_file: int) -> int:
    """Grade index for a potion txt (0 = weakest); -1 when not a known grade."""
    return POTION_GRADE_INDEX.get(txt_file, -1)


def potion_restore(txt_file: int, max_value: int) -> int:
    """Hit points / mana restored by a potion at a maximum of ``max_value``."""
    pct = POTION_RESTORE_PERCENT.get(txt_file)
    if pct is not None:
        return max(0, int(max_value * pct / 100))
    return POTION_RESTORE_POINTS.get(txt_file, 0)


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
