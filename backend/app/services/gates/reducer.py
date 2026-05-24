"""Phase 2 Wave 2B — strictest-wins gate ruling reducer.

The evaluator collects one ``Ruling`` per gate that ``applies()``. The
SDK / API needs exactly one. This module provides the reduction:

* ``BLOCK``        beats ``REQUIRE_HITL`` beats ``ALLOW``.
* On effect ties, the earlier-in-pack gate wins (deterministic;
  debuggable; "the first gate to BLOCK is the one we tell the user
  about" matches operator intuition).

Pure function, no DB, no schemas. Easy to unit-test in isolation.
"""

from __future__ import annotations

from ...schemas.gate import Ruling, RulingEffect

# Rank the three effects from least to most strict. Higher number = more
# restrictive. Kept as a dict (not a sort key on the Enum itself) so a
# future ``RulingEffect.WARN`` slotted between ALLOW and REQUIRE_HITL
# only touches this table.
_EFFECT_RANK: dict[RulingEffect, int] = {
    RulingEffect.ALLOW: 0,
    RulingEffect.REQUIRE_HITL: 1,
    RulingEffect.BLOCK: 2,
}


def reduce_rulings(
    rulings: list[Ruling], gate_order: list[str]
) -> Ruling:
    """Pick the strictest ruling; break ties by first-in-pack-order.

    Parameters
    ----------
    rulings:
        Non-empty list of rulings produced by gates that ``applies()``
        returned True for. Empty input is a programming error — the
        evaluator handles "no gate triggered" by short-circuiting to a
        synthetic ALLOW before calling here.
    gate_order:
        The pack's ``gate_order`` — names in evaluation order. Used
        purely as the same-effect tie-breaker. Names not in
        ``gate_order`` sort to the end (defensive; shouldn't happen).

    Returns
    -------
    The single winning ``Ruling``. Returned object is one of the
    inputs (no copy / no mutation) so downstream code that needs to
    attach a ``review_id`` (HITL materialization) can do so with
    ``ruling.model_copy(update=…)`` without surprising aliasing.
    """
    if not rulings:
        raise ValueError(
            "reduce_rulings called with empty list — caller must short-"
            "circuit ALLOW when no gate applied"
        )
    # Map gate_name → its index in the pack so tie-breaking is O(1).
    order_index = {name: i for i, name in enumerate(gate_order)}
    # Sentinel for unknown gate names: sort after every legitimate gate.
    unknown_rank = len(gate_order)

    def sort_key(r: Ruling) -> tuple[int, int]:
        # Sort by effect rank *descending* (so highest-rank effect lands
        # first) then by pack order *ascending* (so earliest gate wins
        # the tie). Python's stable sort keeps ordering deterministic
        # for synthetic rulings with the same key.
        return (
            -_EFFECT_RANK[r.effect],
            order_index.get(r.gate_name or "", unknown_rank),
        )

    return sorted(rulings, key=sort_key)[0]


__all__ = ["reduce_rulings"]
