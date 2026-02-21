from typing import Optional
from pydantic import BaseModel


class ChainVerificationResult(BaseModel):
    is_valid: bool
    records_checked: int
    first_invalid_sequence: Optional[int] = None
    message: str


class RecordVerificationResult(BaseModel):
    record_id: str
    record_hash_valid: bool
    chain_link_valid: bool
    message: str
