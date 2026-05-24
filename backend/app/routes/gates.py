"""Phase 2 Wave 2A — POST /v1/gates/evaluate route.

Exposes the Ruling contract over HTTP. The Wave 2A endpoint delegates
to the stub ``evaluate_gates`` service, which always returns
``RulingEffect.ALLOW`` — the goal is to ship the wire shape so 5
downstream PRs (A2/A3/A5 backend, B1 SDK, C1 dashboard) can be written
against a merged endpoint.

Requires ``write`` permission: gates will eventually mutate the review
queue (creating an ``ApprovalRecord`` when ``effect=REQUIRE_HITL``, in
Wave 2B PR A2 / A5), and read-only callers must not be able to enqueue
review work or trigger PHI inspection paths. Even in the stub,
``write`` is the correct floor.

The SDK's ``@vera.gate`` decorator (Wave 2B PR B1) consumes
``Ruling.effect`` for routing:
* ``ALLOW``        → proceed
* ``REQUIRE_HITL`` → block on the returned ``review_id``
* ``BLOCK``        → refuse outright, surface ``citation``/``fix_url``

The strictest-gate-wins reduction
(``BLOCK > REQUIRE_HITL > ALLOW``) is the future intent across multiple
registered gate packs — see ``app/services/gates/evaluator.py``.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..schemas.gate import GateEvaluateRequest, Ruling
from ..services.auth import require_permission
from ..services.gates import evaluate_gates

router = APIRouter(prefix="/gates", tags=["gates"])


@router.post("/evaluate", response_model=Ruling)
async def evaluate_gates_route(
    data: GateEvaluateRequest,
    session: AsyncSession = Depends(get_db),
    auth: tuple[str, object] = Depends(require_permission("write")),
) -> Ruling:
    """Evaluate all registered gates against a proposed action.

    Phase 2 Wave 2A: returns ``RulingEffect.ALLOW`` with
    ``reason='no_gates_registered'`` for every input. Real gate logic
    (ClinicalScribePack — new diagnosis, controlled substance, stale
    BAA) lands in Wave 2B PR A2 and replaces the stub wholesale.

    Future ``REQUIRE_HITL`` rulings will carry a ``review_id`` pointing
    to a freshly-created ``ApprovalRecord`` — the SDK's ``@vera.gate``
    decorator polls that ID until the human reviewer decides.
    """
    org_id, _ = auth
    return await evaluate_gates(session, org_id, data)
