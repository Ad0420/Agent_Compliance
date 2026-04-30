"""Session routes — create, list, fetch single."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from simulator.customers.triageguard.backend.auth import require_session
from simulator.customers.triageguard.backend.db import get_session
from simulator.customers.triageguard.backend.models import TriageSession
from simulator.customers.triageguard.backend.schemas import (
    CreateSessionRequest,
    CreateSessionResponse,
    SessionListResponse,
    SessionSnapshot,
)
from simulator.customers.triageguard.backend.workflow_runner import (
    new_session_id,
    start_workflow,
)
from simulator.customers.triageguard.fixtures.sessions import ALL_SESSIONS


router = APIRouter(prefix="/api/sessions", tags=["sessions"])


@router.post(
    "", response_model=CreateSessionResponse, status_code=status.HTTP_201_CREATED
)
async def create_triage_session(
    body: CreateSessionRequest,
    session: AsyncSession = Depends(get_session),
    _user: str = Depends(require_session),
) -> CreateSessionResponse:
    if not body.fixture and not body.custom:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Specify either `fixture` or `custom`.",
        )
    if body.fixture and body.custom:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Specify exactly one of `fixture` or `custom`.",
        )
    if body.fixture and body.fixture not in ALL_SESSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown fixture {body.fixture!r}.",
        )

    session_id = new_session_id()
    if body.fixture:
        source = "fixture"
        fixture_key = body.fixture
        input_payload = {"fixture": body.fixture}
        custom_dict = None
    else:
        assert body.custom is not None
        source = "custom"
        fixture_key = None
        custom_dict = body.custom.model_dump()
        input_payload = {"custom": custom_dict}

    row = TriageSession(
        id=session_id,
        source=source,
        fixture_key=fixture_key,
        status="running",
        events=[],
        input_payload=input_payload,
    )
    session.add(row)
    await session.commit()

    # Kick the background workflow. We don't await it.
    await start_workflow(
        session_db_id=session_id,
        fixture_key=fixture_key,
        custom=custom_dict,
    )

    return CreateSessionResponse(id=session_id, status="running")


@router.get("", response_model=SessionListResponse)
async def list_sessions(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
    _user: str = Depends(require_session),
) -> SessionListResponse:
    total = await session.scalar(select(func.count()).select_from(TriageSession))
    rows_result = await session.execute(
        select(TriageSession)
        .order_by(TriageSession.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = rows_result.scalars().all()
    return SessionListResponse(
        sessions=[SessionSnapshot(**row.to_dict()) for row in rows],
        total=int(total or 0),
        limit=limit,
        offset=offset,
    )


@router.get("/{session_id}", response_model=SessionSnapshot)
async def get_triage_session(
    session_id: str,
    session: AsyncSession = Depends(get_session),
    _user: str = Depends(require_session),
) -> SessionSnapshot:
    row = await session.get(TriageSession, session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found.")
    return SessionSnapshot(**row.to_dict())
