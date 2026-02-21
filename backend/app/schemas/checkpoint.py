from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class CheckpointResponse(BaseModel):
    id: str
    org_id: str
    sequence_at_checkpoint: int
    hash_at_checkpoint: str
    merkle_root: Optional[str] = None
    key_id: Optional[str] = None
    created_at: datetime
    signature: str
    verified_at: Optional[datetime] = None
    is_valid: Optional[bool] = None

    model_config = {"from_attributes": True}


class CheckpointVerificationResult(BaseModel):
    checkpoint_id: str
    sequence: int
    hash: str
    merkle_root: Optional[str] = None
    is_valid: bool
    verified_at: str


class CheckpointListResponse(BaseModel):
    checkpoints: list[CheckpointResponse]
    total: int


class CheckpointVerifyAllResponse(BaseModel):
    results: list[CheckpointVerificationResult]
    all_valid: bool
    total_checked: int
