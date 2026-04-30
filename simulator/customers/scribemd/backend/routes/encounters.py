"""Encounter routes — create, list, fetch single."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from simulator.customers.scribemd.backend.auth import require_session
from simulator.customers.scribemd.backend.db import get_session
from simulator.customers.scribemd.backend.models import Encounter
from simulator.customers.scribemd.backend.schemas import (
    CreateEncounterRequest,
    CreateEncounterResponse,
    EncounterListResponse,
    EncounterSnapshot,
)
from simulator.customers.scribemd.backend.workflow_runner import (
    new_encounter_id,
    start_workflow,
)
from simulator.customers.scribemd.fixtures.encounters import ALL_ENCOUNTERS


router = APIRouter(prefix="/api/encounters", tags=["encounters"])


@router.post("", response_model=CreateEncounterResponse, status_code=status.HTTP_201_CREATED)
async def create_encounter(
    body: CreateEncounterRequest,
    session: AsyncSession = Depends(get_session),
    _user: str = Depends(require_session),
) -> CreateEncounterResponse:
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
    if body.fixture and body.fixture not in ALL_ENCOUNTERS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown fixture {body.fixture!r}.",
        )

    encounter_id = new_encounter_id()
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

    row = Encounter(
        id=encounter_id,
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
        encounter_db_id=encounter_id,
        fixture_key=fixture_key,
        custom=custom_dict,
    )

    return CreateEncounterResponse(id=encounter_id, status="running")


@router.get("", response_model=EncounterListResponse)
async def list_encounters(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
    _user: str = Depends(require_session),
) -> EncounterListResponse:
    total = await session.scalar(select(func.count()).select_from(Encounter))
    rows_result = await session.execute(
        select(Encounter)
        .order_by(Encounter.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = rows_result.scalars().all()
    return EncounterListResponse(
        encounters=[EncounterSnapshot(**row.to_dict()) for row in rows],
        total=int(total or 0),
        limit=limit,
        offset=offset,
    )


@router.get("/{encounter_id}", response_model=EncounterSnapshot)
async def get_encounter(
    encounter_id: str,
    session: AsyncSession = Depends(get_session),
    _user: str = Depends(require_session),
) -> EncounterSnapshot:
    row = await session.get(Encounter, encounter_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Encounter not found.")
    return EncounterSnapshot(**row.to_dict())
