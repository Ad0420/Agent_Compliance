from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import Agent, APIKey
from ..schemas.agent import AgentCreate, AgentResponse
from ..services.auth import require_permission

router = APIRouter(prefix="/agents", tags=["agents"])


def _agent_to_response(agent: Agent) -> AgentResponse:
    return AgentResponse(
        id=agent.id,
        org_id=agent.org_id,
        name=agent.name,
        description=agent.description,
        metadata=agent.metadata_ or {},
        created_at=agent.created_at,
    )


@router.post("", response_model=AgentResponse)
async def create_agent(
    data: AgentCreate,
    session: AsyncSession = Depends(get_db),
    auth: tuple[str, APIKey] = Depends(require_permission("write")),
):
    org_id, _ = auth
    agent = Agent(
        org_id=org_id,
        name=data.name,
        description=data.description,
        metadata_=data.metadata,
    )
    session.add(agent)
    await session.commit()
    await session.refresh(agent)
    return _agent_to_response(agent)


@router.get("", response_model=list[AgentResponse])
async def list_agents(
    session: AsyncSession = Depends(get_db),
    auth: tuple[str, APIKey] = Depends(require_permission("read")),
):
    org_id, _ = auth
    result = await session.execute(
        select(Agent).where(Agent.org_id == org_id).order_by(Agent.created_at)
    )
    agents = result.scalars().all()
    return [_agent_to_response(a) for a in agents]


@router.get("/{agent_id}", response_model=AgentResponse)
async def get_agent(
    agent_id: str,
    session: AsyncSession = Depends(get_db),
    auth: tuple[str, APIKey] = Depends(require_permission("read")),
):
    org_id, _ = auth
    result = await session.execute(
        select(Agent).where(Agent.id == agent_id, Agent.org_id == org_id)
    )
    agent = result.scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    return _agent_to_response(agent)
