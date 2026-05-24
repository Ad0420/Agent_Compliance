"""Phase 2 Wave 2B — Gate 3: stale_baa_blocks_action.

Blocks any clinical action when the org does not have an active,
scoped Business Associate Agreement on file. HIPAA prohibits the
disclosure of PHI to a business associate without an executed BAA.

Citation: ``45 CFR 164.502(e)`` (the prohibition itself; 164.504(e)
covers required contents of the agreement, which is a separate concern).

Why this gate runs FIRST in the pack
-------------------------------------
Three reasons:

1. **Cheap.** ``is_org_baa_active`` is cached with a 60 s TTL, so the
   common hot path is a dict lookup.
2. **Often blocks.** Brand-new orgs and lapsed BAAs both trip this
   gate. Running it first means we skip the PHI-adjacent scans
   (Gate 1 / Gate 2) on payloads we'd refuse anyway.
3. **Action-agnostic.** Every clinical action discloses PHI in some
   form (input_data fields, target_resource references). A missing
   BAA is a hard prohibition regardless of action shape.

The reducer's strictest-wins guarantees BLOCK beats HITL beats ALLOW
even if Gate 3 ran *last* in the pack — order is a runtime
optimisation, not a correctness requirement.
"""

from __future__ import annotations

from typing import Final

from ...schemas.gate import Ruling, RulingEffect
from ...services.baa import is_org_baa_active
from ..base import Gate, GateContext


class StaleBaaGate:
    """Gate 3 — BLOCKs every action when the org's BAA is missing/expired.

    Relies on the shared ``services.baa.is_org_baa_active`` cache so
    repeated requests in the same 60 s window cost a single DB
    round-trip across the entire pack (and across the live-key auth
    path that runs earlier in the request).
    """

    name: Final[str] = "stale_baa_blocks_action"

    def applies(self, ctx: GateContext) -> bool:
        # BAA freshness is action-agnostic. Always evaluate.
        # ``is_org_baa_active`` is cheap (cached) so no early-out heuristics
        # buy us anything.
        return True

    async def evaluate(self, ctx: GateContext) -> Ruling:
        # bypass_cache=False — the create-key path uses bypass_cache=True
        # because freshness matters more than latency at mint time, but
        # the gate runs per-action and the 60 s TTL is acceptable.
        is_active = await is_org_baa_active(ctx.session, ctx.org_id)

        if is_active:
            return Ruling(
                effect=RulingEffect.ALLOW,
                reason="baa_current",
                gate_name=self.name,
            )

        # Deep-link the fix_url to the specific customer when the request
        # carries a tenant_id — the operator can land directly on the
        # right row in /customers to upload the BAA. Without a tenant_id,
        # fall back to the customer list page.
        if ctx.request.tenant_id:
            fix_url = f"/customers/{ctx.request.tenant_id}"
        else:
            fix_url = "/customers"

        return Ruling(
            effect=RulingEffect.BLOCK,
            reason="stale_baa",
            reason_detail=(
                "Your organization does not have an active Business "
                "Associate Agreement (BAA) on file. HIPAA prohibits the "
                "disclosure of PHI to a business associate without an "
                "executed BAA."
            ),
            citation="45 CFR 164.502(e)",
            fix_url=fix_url,
            gate_name=self.name,
        )


__all__ = ["StaleBaaGate"]
