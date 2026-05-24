"""Phase 2 Wave 2B PR A2 — ClinicalScribePack evaluator.

``evaluate_gates`` is the single funnel that ``POST /v1/gates/evaluate``
calls. It iterates the registered ``CLINICAL_SCRIBE_PACK``, collects
per-gate ``Ruling`` objects, and reduces them via strictest-wins.

Reduction shape
---------------
* ``BLOCK``         — any gate blocks → block (cites the regulation)
* ``REQUIRE_HITL``  — no block, any gate requires HITL → HITL (a later
  commit in this PR adds the ``Approval``-row side effect)
* ``ALLOW``         — no gate blocks or requires HITL → allow

When no gate's ``applies()`` returns True for the proposed action, the
evaluator short-circuits to a synthetic ALLOW with
``reason='no_gate_triggered'`` — preserving the Wave 2A behaviour that
a non-clinical action sails through.
"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from ...packs import CLINICAL_SCRIBE_PACK
from ...packs.base import GateContext
from ...schemas.gate import GateEvaluateRequest, Ruling, RulingEffect
from .reducer import reduce_rulings

logger = logging.getLogger("vera.gates")


async def evaluate_gates(
    session: AsyncSession,
    org_id: str,
    request: GateEvaluateRequest,
) -> Ruling:
    """Evaluate ``CLINICAL_SCRIBE_PACK`` against a proposed action.

    Strictest-wins reduction over the rulings from gates whose
    ``applies()`` returned True. The next commit in this PR wires the
    HITL-materialization side effect for ``REQUIRE_HITL`` winners.
    """
    ctx = GateContext(session=session, org_id=org_id, request=request)

    rulings: list[Ruling] = []
    for gate in CLINICAL_SCRIBE_PACK.gates:
        try:
            applies = gate.applies(ctx)
        except Exception:  # pragma: no cover - defensive
            # A buggy applies() must not poison the whole pack. Log,
            # skip the gate, continue. This is a structural safeguard
            # for future gate authors; current A2 gates don't raise.
            logger.exception(
                "gate.applies.error",
                extra={"gate_name": gate.name, "org_id": org_id},
            )
            continue
        if not applies:
            continue
        try:
            ruling = await gate.evaluate(ctx)
        except Exception:
            # Same defensive posture as applies() — a single gate's
            # bug must not crash the evaluator. Skip and continue;
            # if all gates fail we'll fall through to the
            # no-gate-triggered ALLOW.
            logger.exception(
                "gate.evaluate.error",
                extra={"gate_name": gate.name, "org_id": org_id},
            )
            continue
        rulings.append(ruling)

    if not rulings:
        # No gate produced a ruling. Preserve the Wave 2A behaviour
        # that a benign / non-clinical action returns ALLOW.
        return Ruling(
            effect=RulingEffect.ALLOW,
            reason="no_gate_triggered",
        )

    winner = reduce_rulings(rulings, gate_order=CLINICAL_SCRIBE_PACK.gate_order)

    logger.info(
        "gate.evaluated",
        extra={
            "org_id": org_id,
            "winner_gate": winner.gate_name,
            "winner_effect": winner.effect.value,
            "all_gates_triggered": [r.gate_name for r in rulings],
        },
    )

    return winner
