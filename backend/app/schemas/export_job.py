from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class ExportJobResponse(BaseModel):
    id: str
    org_id: str
    format: str
    status: str
    filters: dict
    result_uri: Optional[str] = None
    error_message: Optional[str] = None
    requested_by: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class ExportJobQueuedResponse(BaseModel):
    job_id: str
    status: str
