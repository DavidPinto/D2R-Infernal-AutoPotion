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
# monster hash table.
NPC_GUARD = 338

# --- Unit hash-table layout --------------------------------------------------
# The client keeps one hash table per unit type.  Each sub-table is 128 buckets
# of 8 bytes (a pointer), i.e. 0x400 bytes apart.
UNIT_TABLE_ENTRIES = 128
UNIT_TABLE_PLAYER_OFFSET = 0x0
UNIT_TABLE_MONSTER_OFFSET = 0x400
UNIT_TABLE_ITEM_OFFSET = 0x1000

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
    merc_hp_percent: int = 0   # 0 == no merc
    menus_open: bool = False
    open_menu_names: list = field(default_factory=list)
    error: str = ""

    @property
    def alive(self) -> bool:
        """True while in a game and the player has HP (i.e. not dead)."""
        return self.in_game and self.hp > 0

    @property
    def merc_alive(self) -> bool:
        """True when a mercenary exists (a dead-but-hired merc still has a max)."""
        return self.merc_max_hp > 0


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
