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
    """Plan one potion click per empty belt slot (dumb tier).

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
    plan's ``slot`` matches what the game actually fills, which the Smart tier
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


# ----------------------------------------------------------------- smart tier
def _allowed_for(bound: dict | None, managed, action: str) -> tuple:
    """Belt column keys ``action`` may actually use (bound AND managed).

    ``bound`` maps action -> [keys] (the configured key bindings); when omitted
    every managed column is allowed.  Used both by the smart consume planner and
    by the watcher's column picker so the two always agree."""
    managed = set(managed)
    keys = bound.get(action) if bound else None
    if keys is None:
        return tuple(k for k in m.BELT_COLUMN_KEYS if k in managed)
    return tuple(k for k in keys if k in managed)


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
                 pc, managed, heal_at, mana_at, rejuv_life, rejuv_mana,
                 bound=None) -> tuple:
    """Smart player-potion plan for one tick (pure).

    Returns ``(acts, missing)``.  Each act is ``{"action", "kind", "deficit",
    "max_value", "reason"}``; the watcher feeds ``deficit``/``max_value`` back
    into the column picker (smallest covering grade wins there).  ``missing``
    lists kinds that were wanted but no potion of that kind is on the belt.

    Smart rules:
      * Both stats in the rejuv range (or one critically low with no covering
        specific potion) -> rejuv.
      * Only HP is low and a covering heal sits on the belt -> heal, NOT a
        rejuv (never waste the rare rejuv on a one-stat deficit).
      * Only mana is low and a covering mana potion sits on the belt -> mana.
      * Non-critical: heal and mana fire independently at their thresholds."""
    acts: list[dict] = []
    hp_critical = hp_percent <= rejuv_life
    mp_critical = mana_percent < rejuv_mana

    if hp_critical or mp_critical:
        if hp_critical and not mp_critical:
            allowed = _allowed_for(bound, managed, "heal")
            if _belt_covering("heal", hp_def, max_hp, pc, allowed):
                acts.append({"action": "heal", "kind": "heal", "deficit": hp_def,
                             "max_value": max_hp, "reason": f"HP {hp_percent}%"})
            else:
                acts.append({"action": "rejuv", "kind": "rejuv",
                             "deficit": max(hp_def, mp_def),
                             "max_value": max(max_hp, max_mana),
                             "reason": f"HP {hp_percent}% / MP {mana_percent}%"})
        elif mp_critical and not hp_critical:
            allowed = _allowed_for(bound, managed, "mana")
            if _belt_covering("mana", mp_def, max_mana, pc, allowed):
                acts.append({"action": "mana", "kind": "mana", "deficit": mp_def,
                             "max_value": max_mana, "reason": f"MP {mana_percent}%"})
            else:
                acts.append({"action": "rejuv", "kind": "rejuv",
                             "deficit": max(hp_def, mp_def),
                             "max_value": max(max_hp, max_mana),
                             "reason": f"HP {hp_percent}% / MP {mana_percent}%"})
        else:
            acts.append({"action": "rejuv", "kind": "rejuv",
                         "deficit": max(hp_def, mp_def),
                         "max_value": max(max_hp, max_mana),
                         "reason": f"HP {hp_percent}% / MP {mana_percent}%"})
    else:
        if hp_percent <= heal_at:
            acts.append({"action": "heal", "kind": "heal", "deficit": hp_def,
                         "max_value": max_hp, "reason": f"HP {hp_percent}%"})
        if mana_percent <= mana_at:
            acts.append({"action": "mana", "kind": "mana", "deficit": mp_def,
                         "max_value": max_mana, "reason": f"MP {mana_percent}%"})

    missing = [a["kind"] for a in acts
               if a["kind"] in REFILLABLE_KINDS and not _belt_has_kind(a["kind"], pc, managed)]
    return acts, missing


def desired_kind_for_slot(slot_x: int, layout: dict, belt_content: dict, ratio: dict,
                          order=("heal", "mana", "rejuv")) -> str | None:
    """What potion kind the user wants in belt slot ``slot_x``.

    Preference chain (first hit wins):
      1. user-defined per-slot layout (layout[slot_x]).
      2. the dominant kind already in that column (restock the belt column in
         place - keeps the same "type" of potion there).
      3. a "good mix": the kind with the biggest shortfall against ``ratio``.
    Returns None when the belt is already at (or above) its target mix and no
    layout/column preference applies."""
    if layout and layout.get(slot_x) in REFILLABLE_KINDS:
        return layout[slot_x]
    cols = len(m.BELT_COLUMN_KEYS)
    col = slot_x % cols
    kinds = [k for s, k in (belt_content or {}).items()
             if s >= 0 and s % cols == col and k in REFILLABLE_KINDS]
    if kinds:
        return Counter(kinds).most_common(1)[0][0]
    counts = Counter(k for k in (belt_content or {}).values()
                     if k in REFILLABLE_KINDS)
    short = {k: int(ratio.get(k, 0)) - counts.get(k, 0) for k in REFILLABLE_KINDS}
    wanted = [k for k in order if short.get(k, 0) > 0]
    return max(wanted, key=lambda k: short[k]) if wanted else None


def plan_layout_refill(belt_empty: list[int], belt_content: dict, potions: list[dict],
                       layout: dict, ratio: dict, last_kind: str | None = None,
                       order=("heal", "mana", "rejuv")) -> list[dict]:
    """Smart-tier belt refill plan: one click per empty slot (in fill order).

    For each empty slot the desired kind comes from
    :func:`desired_kind_for_slot` (layout -> column family -> ratio mix); the
    potion clicked is the lowest-grade inventory potion of that kind.  When the
    desired kind is out of stock, falls back to the family last drunk
    (``last_kind``), then to any remaining potion.  Returns
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
        kind = desired_kind_for_slot(slot, layout, belt_content, ratio, order=order)
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
