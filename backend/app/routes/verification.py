from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from ..database import get_db
from ..models import APIKey, Organization
from ..schemas.verification import ChainVerificationResult, RecordVerificationResult
from ..services.auth import require_permission
from ..services.email import send_tamper_alert
from ..services.jobs import enqueue_job
from ..services.verification import verify_chain, verify_single_record

router = APIRouter(prefix="/verify", tags=["verification"])


@router.get("", response_model=ChainVerificationResult)
async def verify_chain_endpoint(
    start_seq: Optional[int] = Query(default=None),
    end_seq: Optional[int] = Query(default=None),
    session: AsyncSession = Depends(get_db),
    auth: tuple[str, APIKey | None] = Depends(require_permission("read")),
):
    org_id, _ = auth
    result = await verify_chain(session, org_id, start_seq, end_seq)

    if not result.is_valid:
        org = await session.get(Organization, org_id)
        if org and org.alert_email:
            email_payload = {
                "org_name": org.name,
                "org_id": org_id,
                "alert_email": org.alert_email,
                "first_invalid_seq": result.first_invalid_sequence,
                "records_checked": result.records_checked,
                "detected_at": datetime.now(timezone.utc).isoformat(),
            }
            await enqueue_job(
                "email.tamper_alert",
                email_payload,
                local_runner=lambda p=email_payload: send_tamper_alert(**p),
            )

    return result


@router.get("/{record_id}", response_model=RecordVerificationResult)
async def verify_record_endpoint(
    record_id: str,
    session: AsyncSession = Depends(get_db),
    auth: tuple[str, APIKey | None] = Depends(require_permission("read")),
):
    org_id, _ = auth
    return await verify_single_record(session, org_id, record_id)
