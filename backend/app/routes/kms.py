"""KMS key history endpoint (Phase 3 Wave 3A.a).

``GET /v1/kms/keys`` returns the full key history for the
deployment — used by Wave 3C's ``vera verify --offline`` to fetch
the public-key chain so it can validate signatures from retired
asymmetric keys without contacting Vera.

Auth: ``require_permission("read")`` — any valid API key or
Clerk-authenticated dashboard user can see the history. The
``public_key_pem`` field is public by definition (it's a public key
for asymmetric KMS) and NULL for HMAC, so there is no secret leakage
risk in this endpoint.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import APIKey
from ..schemas.kms_key import KmsKeyHistoryResponse, KmsKeyResponse
from ..services.auth import require_permission
from ..services.kms import get_key_history

router = APIRouter(prefix="/kms", tags=["kms"])


@router.get("/keys", response_model=KmsKeyHistoryResponse)
async def list_kms_keys_endpoint(
    active_only: bool = False,
    session: AsyncSession = Depends(get_db),
    auth: tuple[str, APIKey | None] = Depends(require_permission("read")),
):
    """List every KMS key that has signed in this deployment.

    Query params
    ------------
    active_only : bool
        If True, filter to keys with ``is_active=True``. Default False
        (return all keys including retired ones — that's the audit
        trail value).
    """
    # auth tuple unpacked just to validate the dependency, not used —
    # KMS history is deployment-wide, not per-org.
    _ = auth
    rows = await get_key_history(session, active_only=active_only)
    return KmsKeyHistoryResponse(
        keys=[KmsKeyResponse.model_validate(r) for r in rows],
        total=len(rows),
    )
