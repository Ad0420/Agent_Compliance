from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class AgentCreate(BaseModel):
    name: str
    description: Optional[str] = None
    metadata: dict = Field(default_factory=dict)


class AgentResponse(BaseModel):
    id: str
    org_id: str
    name: str
    description: Optional[str] = None
    metadata: dict = Field(default_factory=dict)
    created_at: datetime

    model_config = {"from_attributes": True}
