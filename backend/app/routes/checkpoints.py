from datetime import datetime, timezone
from fastapi import APIRouter, Depends
from pydantic import BaseModel
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
from ..services.jobs import enqueue_job

router = APIRouter(prefix="/verify/checkpoints", tags=["checkpoints"])


class CheckpointJobResponse(BaseModel):
    job_id: str
    status: str = "queued"


@router.post("", response_model=CheckpointResponse)
async def create_checkpoint_endpoint(
    session: AsyncSession = Depends(get_db),
    auth: tuple[str, APIKey | None] = Depends(require_permission("admin")),
):
    """Create a signed checkpoint of the current chain state."""
    org_id, _ = auth
    checkpoint = await create_checkpoint(session, org_id)
    return checkpoint


@router.post("/jobs", response_model=CheckpointJobResponse, status_code=202)
async def create_checkpoint_job_endpoint(
    auth: tuple[str, APIKey | None] = Depends(require_permission("admin")),
):
    """Queue a checkpoint creation job for the current organization."""
    org_id, _ = auth
    job_id = await enqueue_job("checkpoint.create", {"org_id": org_id})
    return CheckpointJobResponse(job_id=job_id)


@router.get("", response_model=CheckpointListResponse)
async def list_checkpoints_endpoint(
    session: AsyncSession = Depends(get_db),
    auth: tuple[str, APIKey | None] = Depends(require_permission("read")),
):
    """List all checkpoints for the organization."""
    org_id, _ = auth
    checkpoints = await list_checkpoints(session, org_id)
    return CheckpointListResponse(checkpoints=checkpoints, total=len(checkpoints))


@router.post("/verify", response_model=CheckpointVerifyAllResponse)
async def verify_checkpoints_endpoint(
    session: AsyncSession = Depends(get_db),
    auth: tuple[str, APIKey | None] = Depends(require_permission("read")),
):
    """Verify all checkpoints for the organization."""
    org_id, _ = auth
    results = await verify_all_checkpoints(session, org_id)
    all_valid = all(r["is_valid"] for r in results) if results else True

    if not all_valid:
        invalid = [r for r in results if not r["is_valid"]]
        org = await session.get(Organization, org_id)
        if org and org.alert_email:
            email_payload = {
                "org_name": org.name,
                "org_id": org_id,
                "alert_email": org.alert_email,
                "invalid_checkpoints": invalid,
                "detected_at": datetime.now(timezone.utc).isoformat(),
            }
            await enqueue_job(
                "email.checkpoint_alert",
                email_payload,
                local_runner=lambda p=email_payload: send_checkpoint_alert(**p),
            )

    return CheckpointVerifyAllResponse(
        results=results,
        all_valid=all_valid,
        total_checked=len(results),
    )
