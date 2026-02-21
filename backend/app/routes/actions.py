from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from ..database import get_db
from ..models import ActionRecord, APIKey
from ..schemas.action import (
    ActionRecordCreate,
    ActionRecordResponse,
    ActionRecordBatchCreate,
    ActionRecordListResponse,
)
from ..services.auth import require_permission
from ..services.chain import build_and_insert_record, build_and_insert_batch

router = APIRouter(prefix="/actions", tags=["actions"])


def _record_to_response(record: ActionRecord) -> ActionRecordResponse:
    return ActionRecordResponse(
        id=record.id,
        org_id=record.org_id,
        sequence_number=record.sequence_number,
        previous_hash=record.previous_hash,
        record_hash=record.record_hash,
        recorded_at=record.recorded_at,
        agent_name=record.agent_name,
        agent_version=record.agent_version,
        agent_id=record.agent_id,
        model_id=record.model_id,
        model_version=record.model_version,
        framework=record.framework,
        framework_version=record.framework_version,
        action_type=record.action_type,
        action_name=record.action_name,
        action_description=record.action_description,
        action_timestamp=record.action_timestamp,
        target_system=record.target_system,
        target_resource=record.target_resource,
        authorized_by=record.authorized_by,
        authorization_scope=record.authorization_scope,
        delegation_chain=record.delegation_chain or [],
        result=record.result,
        error_message=record.error_message,
        duration_ms=record.duration_ms,
        input_data=record.input_data or {},
        policies_applied=record.policies_applied or [],
        environment=record.environment or {},
        outcome=record.outcome or {},
        reasoning=record.reasoning or {},
        metadata=record.metadata_ or {},
    )


@router.post("", response_model=ActionRecordResponse)
async def create_action(
    data: ActionRecordCreate,
    session: AsyncSession = Depends(get_db),
    auth: tuple[str, APIKey] = Depends(require_permission("write")),
):
    org_id, _ = auth
    record = await build_and_insert_record(session, org_id, data)
    return _record_to_response(record)


@router.post("/batch", response_model=list[ActionRecordResponse])
async def create_action_batch(
    data: ActionRecordBatchCreate,
    session: AsyncSession = Depends(get_db),
    auth: tuple[str, APIKey] = Depends(require_permission("write")),
):
    org_id, _ = auth
    records = await build_and_insert_batch(session, org_id, data.records)
    return [_record_to_response(r) for r in records]


def _escape_like(s: str) -> str:
    """Escape special LIKE pattern characters."""
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


@router.get("", response_model=ActionRecordListResponse)
async def list_actions(
    agent_name: Optional[str] = None,
    action_type: Optional[str] = None,
    result: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    authorized_by: Optional[str] = None,
    search: Optional[str] = Query(default=None, max_length=200),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db),
    auth: tuple[str, APIKey] = Depends(require_permission("read")),
):
    org_id, _ = auth

    query = select(ActionRecord).where(ActionRecord.org_id == org_id)
    count_query = select(func.count(ActionRecord.id)).where(ActionRecord.org_id == org_id)

    if agent_name:
        query = query.where(ActionRecord.agent_name == agent_name)
        count_query = count_query.where(ActionRecord.agent_name == agent_name)
    if action_type:
        query = query.where(ActionRecord.action_type == action_type)
        count_query = count_query.where(ActionRecord.action_type == action_type)
    if result:
        query = query.where(ActionRecord.result == result)
        count_query = count_query.where(ActionRecord.result == result)
    if authorized_by:
        query = query.where(ActionRecord.authorized_by == authorized_by)
        count_query = count_query.where(ActionRecord.authorized_by == authorized_by)
    if start_date:
        query = query.where(ActionRecord.action_timestamp >= start_date)
        count_query = count_query.where(ActionRecord.action_timestamp >= start_date)
    if end_date:
        query = query.where(ActionRecord.action_timestamp <= end_date)
        count_query = count_query.where(ActionRecord.action_timestamp <= end_date)
    if search:
        escaped = _escape_like(search)
        pattern = f"%{escaped}%"
        search_filter = ActionRecord.action_name.ilike(pattern)
        query = query.where(search_filter)
        count_query = count_query.where(search_filter)

    total_result = await session.execute(count_query)
    total = total_result.scalar()

    query = query.order_by(ActionRecord.sequence_number.desc()).limit(limit).offset(offset)
    records_result = await session.execute(query)
    records = records_result.scalars().all()

    return ActionRecordListResponse(
        records=[_record_to_response(r) for r in records],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{record_id}", response_model=ActionRecordResponse)
async def get_action(
    record_id: str,
    session: AsyncSession = Depends(get_db),
    auth: tuple[str, APIKey] = Depends(require_permission("read")),
):
    org_id, _ = auth
    result = await session.execute(
        select(ActionRecord).where(
            ActionRecord.id == record_id,
            ActionRecord.org_id == org_id,
        )
    )
    record = result.scalar_one_or_none()
    if record is None:
        raise HTTPException(status_code=404, detail="Action record not found")
    return _record_to_response(record)
