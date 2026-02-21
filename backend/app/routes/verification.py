from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from ..database import get_db
from ..models import APIKey
from ..schemas.verification import ChainVerificationResult, RecordVerificationResult
from ..services.auth import require_permission
from ..services.verification import verify_chain, verify_single_record

router = APIRouter(prefix="/verify", tags=["verification"])


@router.get("", response_model=ChainVerificationResult)
async def verify_chain_endpoint(
    start_seq: Optional[int] = Query(default=None),
    end_seq: Optional[int] = Query(default=None),
    session: AsyncSession = Depends(get_db),
    auth: tuple[str, APIKey] = Depends(require_permission("read")),
):
    org_id, _ = auth
    return await verify_chain(session, org_id, start_seq, end_seq)


@router.get("/{record_id}", response_model=RecordVerificationResult)
async def verify_record_endpoint(
    record_id: str,
    session: AsyncSession = Depends(get_db),
    auth: tuple[str, APIKey] = Depends(require_permission("read")),
):
    org_id, _ = auth
    return await verify_single_record(session, org_id, record_id)
