"""Unit tests for the strictest-wins ``reduce_rulings`` reducer.

Pure-function tests; no DB, no async, no fixtures. Validates the
strictness ordering (``BLOCK > REQUIRE_HITL > ALLOW``) and the
deterministic tie-breaker (first-in-pack-order wins).
"""

from __future__ import annotations

import pytest

from app.schemas.gate import Ruling, RulingEffect
from app.services.gates.reducer import reduce_rulings


def _allow(name: str) -> Ruling:
    return Ruling(effect=RulingEffect.ALLOW, reason="ok", gate_name=name)


def _hitl(name: str) -> Ruling:
    return Ruling(
        effect=RulingEffect.REQUIRE_HITL,
        reason="needs_review",
        gate_name=name,
    )


def _block(name: str) -> Ruling:
    return Ruling(effect=RulingEffect.BLOCK, reason="forbidden", gate_name=name)


_PACK_ORDER = ["alpha", "beta", "gamma"]


def test_single_allow_wins_trivially():
    out = reduce_rulings([_allow("alpha")], _PACK_ORDER)
    assert out.effect is RulingEffect.ALLOW
    assert out.gate_name == "alpha"


def test_single_hitl_wins_trivially():
    out = reduce_rulings([_hitl("beta")], _PACK_ORDER)
    assert out.effect is RulingEffect.REQUIRE_HITL
    assert out.gate_name == "beta"


def test_single_block_wins_trivially():
    out = reduce_rulings([_block("gamma")], _PACK_ORDER)
    assert out.effect is RulingEffect.BLOCK
    assert out.gate_name == "gamma"


def test_allow_plus_hitl_picks_hitl():
    out = reduce_rulings([_allow("alpha"), _hitl("beta")], _PACK_ORDER)
    assert out.effect is RulingEffect.REQUIRE_HITL
    assert out.gate_name == "beta"


def test_allow_plus_block_picks_block():
    out = reduce_rulings([_allow("alpha"), _block("gamma")], _PACK_ORDER)
    assert out.effect is RulingEffect.BLOCK
    assert out.gate_name == "gamma"


def test_hitl_plus_block_picks_block():
    out = reduce_rulings([_hitl("beta"), _block("gamma")], _PACK_ORDER)
    assert out.effect is RulingEffect.BLOCK
    assert out.gate_name == "gamma"


def test_all_three_picks_block():
    out = reduce_rulings(
        [_allow("alpha"), _hitl("beta"), _block("gamma")], _PACK_ORDER
    )
    assert out.effect is RulingEffect.BLOCK
    assert out.gate_name == "gamma"


def test_two_blocks_tie_break_picks_first_in_pack_order():
    """When two gates BLOCK, the earlier-in-pack gate's ruling wins."""
    out = reduce_rulings(
        [_block("gamma"), _block("alpha")], _PACK_ORDER
    )
    assert out.effect is RulingEffect.BLOCK
    assert out.gate_name == "alpha", (
        "alpha is before gamma in pack order — should win the tie"
    )


def test_two_hitls_tie_break_picks_first_in_pack_order():
    out = reduce_rulings(
        [_hitl("gamma"), _hitl("alpha"), _hitl("beta")], _PACK_ORDER
    )
    assert out.effect is RulingEffect.REQUIRE_HITL
    assert out.gate_name == "alpha"


def test_two_allows_tie_break_picks_first_in_pack_order():
    out = reduce_rulings(
        [_allow("beta"), _allow("alpha")], _PACK_ORDER
    )
    assert out.effect is RulingEffect.ALLOW
    assert out.gate_name == "alpha"


def test_unknown_gate_name_sorts_to_end_in_tie_break():
    """A gate name not in gate_order sorts after every legitimate gate.

    Defensive: shouldn't happen in production but the reducer must
    not crash if a gate produces a ruling with a stale / typo'd name.
    """
    rogue = _block("not_in_pack")
    legit = _block("beta")
    out = reduce_rulings([rogue, legit], _PACK_ORDER)
    assert out.gate_name == "beta"


def test_empty_list_raises():
    with pytest.raises(ValueError):
        reduce_rulings([], _PACK_ORDER)


def test_reducer_returns_input_object_unmutated():
    """The winner is the same object the caller passed in (not a copy).

    Important because the evaluator wraps the winner with
    ``model_copy(update={"review_id": ...})`` — it must be able to
    rely on the winner being a normal Ruling, not a fresh construction
    that elided fields.
    """
    block_ruling = _block("alpha")
    out = reduce_rulings([_allow("beta"), block_ruling], _PACK_ORDER)
    assert out is block_ruling
