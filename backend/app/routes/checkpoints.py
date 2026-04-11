import asyncio
from datetime import datetime, timezone
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import APIKey, Organization
from ..schemas.checkpoint import (
    CheckpointListResponse,
    CheckpointResponse,
    CheckpointVerifyAllResponse,
)
from ..services.auth import require_permission
from ..services.checkpoint import (
    create_checkpoint,
    list_checkpoints,
    verify_all_checkpoints,
)
from ..services.email import send_checkpoint_alert

router = APIRouter(prefix="/verify/checkpoints", tags=["checkpoints"])


@router.post("", response_model=CheckpointResponse)
async def create_checkpoint_endpoint(
    session: AsyncSession = Depends(get_db),
    auth: tuple[str, APIKey] = Depends(require_permission("admin")),
):
    """Create a signed checkpoint of the current chain state."""
    org_id, _ = auth
    checkpoint = await create_checkpoint(session, org_id)
    return checkpoint


@router.get("", response_model=CheckpointListResponse)
async def list_checkpoints_endpoint(
    session: AsyncSession = Depends(get_db),
    auth: tuple[str, APIKey] = Depends(require_permission("read")),
):
    """List all checkpoints for the organization."""
    org_id, _ = auth
    checkpoints = await list_checkpoints(session, org_id)
    return CheckpointListResponse(checkpoints=checkpoints, total=len(checkpoints))


@router.post("/verify", response_model=CheckpointVerifyAllResponse)
async def verify_checkpoints_endpoint(
    session: AsyncSession = Depends(get_db),
    auth: tuple[str, APIKey] = Depends(require_permission("read")),
):
    """Verify all checkpoints for the organization."""
    org_id, _ = auth
    results = await verify_all_checkpoints(session, org_id)
    all_valid = all(r["is_valid"] for r in results) if results else True

    if not all_valid:
        invalid = [r for r in results if not r["is_valid"]]
        org = await session.get(Organization, org_id)
        if org and org.alert_email:
            asyncio.create_task(
                send_checkpoint_alert(
                    org_name=org.name,
                    org_id=org_id,
                    alert_email=org.alert_email,
                    invalid_checkpoints=invalid,
                    detected_at=datetime.now(timezone.utc).isoformat(),
                )
            )

    return CheckpointVerifyAllResponse(
        results=results,
        all_valid=all_valid,
        total_checked=len(results),
    )
