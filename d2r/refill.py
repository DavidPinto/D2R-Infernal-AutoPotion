"""Pure refill-planning logic (no Win32, no game memory).

Given the belt's empty slots and the potions sitting in the inventory, pick the
next potion to click into the belt.  The engine places a clicked inventory
potion into the first empty belt slot it wants to fill, so the app controls the
choice of *which potion to click*, not the exact slot.  All decisions here are
pure and unit-tested; the watcher executes the plan.
"""

from __future__ import annotations

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
