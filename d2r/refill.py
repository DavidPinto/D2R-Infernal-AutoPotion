"""Pure refill-planning logic (no Win32, no game memory).

Given the belt's empty slots and the potions sitting in the inventory, pick the
next potion to click into the belt.  The engine places a clicked inventory
potion into the first empty belt slot it wants to fill, so the app controls the
choice of *which potion to click*, not the exact slot.  All decisions here are
pure and unit-tested; the watcher executes the plan.
"""

from __future__ import annotations

from collections import Counter

from . import models as m

# Kinds the refill will auto-move.  Utility potions (stamina, ...) are left
# alone - the user moves those manually.
REFILLABLE_KINDS = {"heal", "mana", "rejuv"}


def refillable_potions(potions: list[dict]) -> list[dict]:
    """Inventory potions the refill is willing to click, lowest grade first."""
    picked = [p for p in potions if p.get("kind") in REFILLABLE_KINDS]
    return sorted(picked, key=lambda p: (p.get("grade", 99), p.get("y", 0), p.get("x", 0)))


def plan_refills(belt_empty: list[int], potions: list[dict],
                 last_kind: str | None = None) -> list[dict]:
    """Plan one potion click per empty belt slot (basic refill).

    Prefers a potion of the same family as the one that was just drunk
    (``last_kind``) so the belt naturally restocks what gets consumed; falls back
    to the next potion in inventory order (lowest grade first).  Empty slots are
    processed in the belt's fill order so the plan stays stable across ticks.
    Returns a list of ``{"slot", "potion"}`` decisions (caller clicks one per
    tick to stay under the game's input limits)."""
    slots = belt_fill_order([s for s in belt_empty if s >= 0])
    pool = refillable_potions(potions)
    if not slots or not pool:
        return []
    # Same-family potions first (restock what was just drunk), then any others.
    ordered = pool if not last_kind else (
        [p for p in pool if p["kind"] == last_kind]
        + [p for p in pool if p["kind"] != last_kind])
    if not ordered:
        return []
    plan = []
    for slot in slots:
        if not ordered:
            break
        potion = ordered.pop(0)
        plan.append({"slot": int(slot), "potion": potion})
    return plan


def belt_fill_order(belt_empty: list[int]) -> list[int]:
    """The order the engine fills empty belt slots (bottom row first).

    D2R places a clicked potion into the lowest empty slot scanning bottom row
    left-to-right, then the row above.  Keeping the same order here means the
    plan's ``slot`` matches what the game actually fills, which the layout-aware
    uses to drive a per-slot layout.  Slots with an unknown row are kept at the
    end in ascending order."""
    cols = len(m.BELT_COLUMN_KEYS)
    rows = {}
    for x in belt_empty:
        if x >= 0:
            rows.setdefault(x // cols, []).append(x)
    order = []
    for row in sorted(rows):
        order.extend(sorted(rows[row]))
    return order


# --------------------------------------------------- layout-aware planners
def _allowed_for(managed) -> tuple:
    """Belt column keys the app may use: every managed column.

    Since 1.8.0 there are no per-potion key bindings - the watcher reads each
    belt slot and drinks from whichever managed column holds the right potion,
    so any managed column may serve any action."""
    managed = set(managed)
    return tuple(k for k in m.BELT_COLUMN_KEYS if k in managed)


def _managed_indices(managed) -> set:
    """Column indices (0..3) for a mixed list of column keys and/or indices."""
    valid = {k: i for i, k in enumerate(m.BELT_COLUMN_KEYS)}
    out: set = set()
    for k in managed or ():
        if isinstance(k, int):
            out.add(k)
        elif k in valid:
            out.add(valid[k])
    return out


def _belt_covering(kind: str, deficit: int, max_value: int, pc, allowed_keys) -> bool:
    """True when a potion of ``kind`` on the belt (in ``allowed_keys`` columns)
    restores at least ``deficit``.  Unreadable belt -> False (cannot confirm).

    ``choose_belt_column`` returns the *strongest* column even when nothing
    covers, so the chosen column's actual restore amount must be checked."""
    if not getattr(pc, "ok", False):
        return False
    idx = pc.choose_belt_column(kind, deficit, max_value, allowed_keys=allowed_keys)
    if idx is None:
        return False
    col = next((c for c in pc.columns if c.index == idx), None)
    if col is None:
        return False
    codes = pc.codes if pc.codes is not None else m.default_potion_codes()
    return codes.restore(col.txt, max_value) >= deficit


def _belt_has_kind(kind: str, pc, managed) -> bool:
    """True when the belt has a drinkable potion of ``kind`` in a managed column."""
    if not getattr(pc, "ok", False):
        return False
    idx = _managed_indices(managed)
    return any(c.kind == kind and c.count > 0 and c.index in idx
               for c in pc.columns)


def plan_consume(hp_percent, mana_percent, hp_def, mp_def, max_hp, max_mana,
                 pc, managed, heal_at, mana_at, rejuv_life, rejuv_mana) -> tuple:
    """Smart player-potion plan for one tick (pure).

    Returns ``(acts, missing)``.  Each act is ``{"action", "kind", "deficit",
    "max_value", "reason"}``; the watcher feeds ``deficit``/``max_value`` back
    into the column picker (smallest covering grade wins there).  ``missing``
    lists kinds that were wanted but no potion of that kind is on the belt.

    Smart rules:
      * Both stats in the rejuv range -> rejuv; without one on the belt, drink
        heal AND mana (anything that is there rather than nothing).
      * Only HP is low -> a covering heal, else a rejuv, else ANY heal on a
        managed column even if it cannot fully cover (a potion sitting in the
        "wrong" slot is still drunk, never wasted).
      * Only mana is low -> the mana equivalent.
      * Non-critical: heal and mana fire independently at their thresholds.
    When the belt is unreadable the plan falls back to the plain thresholds
    (rejuv wins if critical, heal/mana at their thresholds); the watcher presses
    the action's fallback key since no column can be picked."""
    acts: list[dict] = []
    missing: list[str] = []
    hp_critical = hp_percent <= rejuv_life
    mp_critical = mana_percent < rejuv_mana
    both_reason = f"HP {hp_percent}% / MP {mana_percent}%"

    def act(kind: str, deficit: int, max_value: int, reason: str) -> None:
        acts.append({"action": kind, "kind": kind, "deficit": deficit,
                     "max_value": max_value, "reason": reason})

    if not getattr(pc, "ok", False):
        # Belt unreadable: the fallback key for each action is pressed.  Pick the
        # action that matches the critical stat so a mana crisis drinks a mana
        # potion (W), not a rejuv that may not even exist.
        if hp_critical and mp_critical:
            act("rejuv", max(hp_def, mp_def), max(max_hp, max_mana), both_reason)
        elif hp_critical:
            act("heal", hp_def, max_hp, f"HP {hp_percent}%")
        elif mp_critical:
            act("mana", mp_def, max_mana, f"MP {mana_percent}%")
        else:
            if hp_percent <= heal_at:
                act("heal", hp_def, max_hp, f"HP {hp_percent}%")
            if mana_percent <= mana_at:
                act("mana", mp_def, max_mana, f"MP {mana_percent}%")
        return acts, missing

    allowed = _allowed_for(managed)

    def critical_one(kind: str, deficit: int, max_value: int, reason: str) -> None:
        """One stat is critical: a covering potion of that kind, else a rejuv
        (which covers both), else any potion of that kind even under-strength,
        else report it as missing."""
        if _belt_covering(kind, deficit, max_value, pc, allowed):
            act(kind, deficit, max_value, reason)
        elif _belt_has_kind("rejuv", pc, managed):
            act("rejuv", max(hp_def, mp_def), max(max_hp, max_mana), both_reason)
        elif _belt_has_kind(kind, pc, managed):
            act(kind, deficit, max_value, reason)
        else:
            missing.append(kind)

    if hp_critical or mp_critical:
        if hp_critical and not mp_critical:
            critical_one("heal", hp_def, max_hp, f"HP {hp_percent}%")
        elif mp_critical and not hp_critical:
            critical_one("mana", mp_def, max_mana, f"MP {mana_percent}%")
        else:
            if _belt_has_kind("rejuv", pc, managed):
                act("rejuv", max(hp_def, mp_def), max(max_hp, max_mana), both_reason)
            else:
                fired = False
                for kind, deficit, max_value in (("heal", hp_def, max_hp),
                                                 ("mana", mp_def, max_mana)):
                    if _belt_has_kind(kind, pc, managed):
                        act(kind, deficit, max_value, both_reason)
                        fired = True
                if not fired:
                    missing.append("rejuv")
    else:
        if hp_percent <= heal_at:
            act("heal", hp_def, max_hp, f"HP {hp_percent}%")
        if mana_percent <= mana_at:
            act("mana", mp_def, max_mana, f"MP {mana_percent}%")

    return acts, missing


def plan_moves(belt_content: dict, layout: dict, belt_empty: list,
               belt_rows: int | None = None) -> list[dict]:
    """Relocate potions sitting in the wrong belt column (layout-aware).

    ``belt_content`` maps belt slot X -> potion kind.  A refillable potion is
    "misplaced" when its own column prefers a different kind (per-slot layout
    first, then the dominant kind already in the column).  When a column that
    wants this potion's kind has an empty slot, the potion is moved there —
    a two-click move (pick it up, drop it into the empty slot), so the engine
    never has to guess where a dragged-in potion belongs.

    Returns one dict per move: ``{"action": "move", "from", "to", "kind"}``.
    The watcher executes one move per tick against fresh belt data, so the plan
    only ever needs to be correct for the next single move."""
    cols = len(m.BELT_COLUMN_KEYS)
    content = {int(s): k for s, k in (belt_content or {}).items()
               if isinstance(s, int) and s >= 0 and k in REFILLABLE_KINDS}
    if not content:
        return []

    def column_desired(c: int) -> str | None:
        # A layout pin anywhere in the column beats the column's dominant kind.
        for slot in range(c, 16, cols):
            kind = (layout or {}).get(slot)
            if kind in REFILLABLE_KINDS:
                return kind
        kinds = [k for s, k in content.items() if s % cols == c]
        return Counter(kinds).most_common(1)[0][0] if kinds else None

    empty_by_col: dict[int, list] = {}
    for s in (belt_empty or []):
        if isinstance(s, int) and s >= 0:
            empty_by_col.setdefault(s % cols, []).append(s)

    moves: list[dict] = []
    for slot in sorted(content):
        kind = content[slot]
        own_col = slot % cols
        if column_desired(own_col) == kind:
            continue
        for c in range(cols):
            if c == own_col or not empty_by_col.get(c):
                continue
            if column_desired(c) != kind:
                continue
            target = min(empty_by_col[c])
            empty_by_col[c].remove(target)
            moves.append({"action": "move", "from": slot, "to": target, "kind": kind})
            break
    return moves


def desired_kind_for_slot(slot_x: int, layout: dict, belt_content: dict) -> str | None:
    """What potion kind the user wants in belt slot ``slot_x``.

    Preference chain (first hit wins):
      1. user-defined per-slot layout (layout[slot_x]).
      2. the dominant kind already in that column (restock the belt column in
         place - keeps the same "type" of potion there).
    Returns None when neither applies (the refill then falls back to the family
    last drunk, then to any potion)."""
    if layout and layout.get(slot_x) in REFILLABLE_KINDS:
        return layout[slot_x]
    cols = len(m.BELT_COLUMN_KEYS)
    col = slot_x % cols
    kinds = [k for s, k in (belt_content or {}).items()
             if s >= 0 and s % cols == col and k in REFILLABLE_KINDS]
    if kinds:
        return Counter(kinds).most_common(1)[0][0]
    return None


def plan_layout_refill(belt_empty: list[int], belt_content: dict, potions: list[dict],
                       layout: dict, last_kind: str | None = None) -> list[dict]:
    """Layout-aware belt refill plan: one click per empty slot (in fill order).

    For each empty slot the desired kind comes from :func:`desired_kind_for_slot`
    (layout -> column family); the potion clicked is the lowest-grade inventory
    potion of that kind.  When the desired kind is out of stock, falls back to
    the family last drunk (``last_kind``), then to any remaining potion.  Returns
    ``[{"slot", "potion"}, ...]``; the caller clicks one per tick."""
    slots = belt_fill_order([s for s in belt_empty if s >= 0])
    if not slots:
        return []
    by_kind: dict = {}
    for p in refillable_potions(potions):
        by_kind.setdefault(p["kind"], []).append(p)
    if not by_kind:
        return []
    plan = []
    for slot in slots:
        kind = desired_kind_for_slot(slot, layout, belt_content)
        pick = None
        if kind and by_kind.get(kind):
            pick = by_kind[kind].pop(0)
        if pick is None and last_kind and by_kind.get(last_kind):
            pick = by_kind[last_kind].pop(0)
        if pick is None:
            remaining = [p for lst in by_kind.values() for p in lst]
            if not remaining:
                break
            pick = min(remaining, key=lambda p: (p.get("grade", 99), p.get("y", 0), p.get("x", 0)))
            by_kind[pick["kind"]].remove(pick)
        plan.append({"slot": int(slot), "potion": pick})
    return plan
