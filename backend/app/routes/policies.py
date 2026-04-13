from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import Policy, PolicyViolation
from ..schemas.policy import (
    PolicyCreate,
    PolicyListResponse,
    PolicyResponse,
    PolicyUpdate,
    ViolationListResponse,
    ViolationResolve,
    ViolationResponse,
)
from ..services.auth import require_permission

router = APIRouter(prefix="/policies", tags=["policies"])


# ── Policy CRUD ─────────────────────────────────────────────────────────────


@router.post("", response_model=PolicyResponse, status_code=201)
async def create_policy(
    data: PolicyCreate,
    session: AsyncSession = Depends(get_db),
    auth: tuple[str, object] = Depends(require_permission("admin")),
):
    """Create a new policy for the organization. Requires admin key."""
    org_id, _ = auth
    policy = Policy(
        org_id=org_id,
        name=data.name,
        description=data.description,
        condition_type=data.condition_type,
        condition_params=data.condition_params,
        action=data.action,
        severity=data.severity,
        is_active=data.is_active,
    )
    session.add(policy)
    await session.commit()
    await session.refresh(policy)
    return PolicyResponse.model_validate(policy)


@router.get("", response_model=PolicyListResponse)
async def list_policies(
    session: AsyncSession = Depends(get_db),
    auth: tuple[str, object] = Depends(require_permission("read")),
    is_active: Optional[bool] = Query(default=None),
):
    """List all policies for the organization."""
    org_id, _ = auth
    stmt = select(Policy).where(Policy.org_id == org_id)
    if is_active is not None:
        stmt = stmt.where(Policy.is_active == is_active)
    stmt = stmt.order_by(Policy.created_at.desc())

    result = await session.execute(stmt)
    policies = result.scalars().all()

    count_stmt = select(func.count()).select_from(Policy).where(Policy.org_id == org_id)
    if is_active is not None:
        count_stmt = count_stmt.where(Policy.is_active == is_active)
    total_result = await session.execute(count_stmt)
    total = total_result.scalar() or 0

    return PolicyListResponse(
        policies=[PolicyResponse.model_validate(p) for p in policies],
        total=total,
    )


@router.patch("/{policy_id}", response_model=PolicyResponse)
async def update_policy(
    policy_id: str,
    data: PolicyUpdate,
    session: AsyncSession = Depends(get_db),
    auth: tuple[str, object] = Depends(require_permission("admin")),
):
    """Update a policy. Supports partial update. Requires admin key."""
    org_id, _ = auth
    policy = await session.get(Policy, policy_id)
    if policy is None or policy.org_id != org_id:
        raise HTTPException(status_code=404, detail="Policy not found")

    if data.name is not None:
        policy.name = data.name
    if data.description is not None:
        policy.description = data.description
    if data.condition_params is not None:
        policy.condition_params = data.condition_params
    if data.action is not None:
        policy.action = data.action
    if data.severity is not None:
        policy.severity = data.severity
    if data.is_active is not None:
        policy.is_active = data.is_active

    policy.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    await session.commit()
    await session.refresh(policy)
    return PolicyResponse.model_validate(policy)


@router.delete("/{policy_id}", status_code=204)
async def delete_policy(
    policy_id: str,
    session: AsyncSession = Depends(get_db),
    auth: tuple[str, object] = Depends(require_permission("admin")),
):
    """Delete a policy. Requires admin key."""
    org_id, _ = auth
    policy = await session.get(Policy, policy_id)
    if policy is None or policy.org_id != org_id:
        raise HTTPException(status_code=404, detail="Policy not found")
    await session.delete(policy)
    await session.commit()


# ── Violations ──────────────────────────────────────────────────────────────


@router.get("/violations", response_model=ViolationListResponse)
async def list_violations(
    session: AsyncSession = Depends(get_db),
    auth: tuple[str, object] = Depends(require_permission("read")),
    severity: Optional[str] = Query(default=None),
    resolved: Optional[bool] = Query(default=None),
    policy_id: Optional[str] = Query(default=None),
    record_id: Optional[str] = Query(default=None),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
):
    """List policy violations for the organization with optional filters."""
    org_id, _ = auth
    stmt = select(PolicyViolation).where(PolicyViolation.org_id == org_id)
    count_stmt = select(func.count()).select_from(PolicyViolation).where(PolicyViolation.org_id == org_id)

    if severity is not None:
        stmt = stmt.where(PolicyViolation.severity == severity)
        count_stmt = count_stmt.where(PolicyViolation.severity == severity)
    if resolved is True:
        stmt = stmt.where(PolicyViolation.resolved_at.is_not(None))
        count_stmt = count_stmt.where(PolicyViolation.resolved_at.is_not(None))
    elif resolved is False:
        stmt = stmt.where(PolicyViolation.resolved_at.is_(None))
        count_stmt = count_stmt.where(PolicyViolation.resolved_at.is_(None))
    if policy_id is not None:
        stmt = stmt.where(PolicyViolation.policy_id == policy_id)
        count_stmt = count_stmt.where(PolicyViolation.policy_id == policy_id)
    if record_id is not None:
        stmt = stmt.where(PolicyViolation.record_id == record_id)
        count_stmt = count_stmt.where(PolicyViolation.record_id == record_id)

    stmt = stmt.order_by(PolicyViolation.triggered_at.desc()).limit(limit).offset(offset)

    result = await session.execute(stmt)
    violations = result.scalars().all()

    total_result = await session.execute(count_stmt)
    total = total_result.scalar() or 0

    return ViolationListResponse(
        violations=[ViolationResponse.model_validate(v) for v in violations],
        total=total,
    )


@router.patch("/violations/{violation_id}/resolve", response_model=ViolationResponse)
async def resolve_violation(
    violation_id: str,
    data: ViolationResolve,
    session: AsyncSession = Depends(get_db),
    auth: tuple[str, object] = Depends(require_permission("admin")),
):
    """Mark a violation as resolved. Requires admin key."""
    org_id, _ = auth
    violation = await session.get(PolicyViolation, violation_id)
    if violation is None or violation.org_id != org_id:
        raise HTTPException(status_code=404, detail="Violation not found")
    if violation.resolved_at is not None:
        raise HTTPException(status_code=409, detail="Violation is already resolved")

    violation.resolved_at = datetime.now(timezone.utc).replace(tzinfo=None)
    violation.resolved_by = data.resolved_by
    await session.commit()
    await session.refresh(violation)
    return ViolationResponse.model_validate(violation)
