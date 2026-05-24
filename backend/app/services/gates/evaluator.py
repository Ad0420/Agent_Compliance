"""Phase 2 Wave 2A — stub gate evaluator.

``evaluate_gates`` is the single funnel that ``POST /v1/gates/evaluate``
calls. It is the contract every downstream gate pack plugs into.

Wave 2A scope (this PR): stub — returns ``ALLOW`` for every input. No
ApprovalRecord creation, no PHI inspection, no RxNorm/DEA lookups, no
BAA freshness check. The point of this PR is to lock the interface so
Wave 2B PRs (A2 real gates, A3 review-routing, A5 ApprovalRecord
extension, B1 SDK ``@vera.gate`` decorator, C1 dashboard) can be written
against a merged endpoint shape.

Wave 2B PR A2 (next): ClinicalScribePack — new-diagnosis gate,
controlled-substance gate (RxNorm + DEA list), stale-BAA gate. That PR
replaces this stub wholesale with a registry-driven evaluator that
reduces multiple gate results via **strictest-gate-wins**:

* ``BLOCK``         (any gate blocks → block)
* ``REQUIRE_HITL``  (no block, any gate requires HITL → HITL)
* ``ALLOW``         (no gate blocks or requires HITL → allow)

The SDK's ``@vera.gate`` decorator (Wave 2B PR B1) consumes
``Ruling.effect`` for routing. Keep this module's signature stable so
that PR doesn't need rework.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from ...schemas.gate import GateEvaluateRequest, Ruling, RulingEffect


async def evaluate_gates(
    session: AsyncSession,
    org_id: str,
    request: GateEvaluateRequest,
) -> Ruling:
    """Evaluate all registered gate packs against the proposed action.

    Phase 2 Wave 2A: stub — returns ``ALLOW`` for every input. Real
    gates land in Wave 2B PR A2 (ClinicalScribePack: new diagnosis,
    controlled substance via RxNorm + DEA list, stale BAA).

    The strictest-gate-wins reduction
    (``BLOCK > REQUIRE_HITL > ALLOW``) will live here once multiple
    gates exist. For now, single-result no-op.

    The ``session`` and ``org_id`` parameters are accepted (and
    intentionally unused in the stub) so the signature matches what
    Wave 2B will need — gates will load org-scoped state (BAA freshness,
    customer scopes, DEA-list cache) via the session.
    """
    # session / org_id / request intentionally accepted but unused in the
    # Wave 2A stub. Wave 2B PR A2 wires them through to the gate registry.
    del session, org_id, request

    return Ruling(
        effect=RulingEffect.ALLOW,
        reason="no_gates_registered",
        reason_detail=(
            "Phase 2 stub evaluator. ClinicalScribePack lands in Wave 2B "
            "PR A2."
        ),
    )
