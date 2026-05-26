"""Schemas for the KMS key history endpoint (Phase 3 Wave 3A.a)."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class KmsKeyResponse(BaseModel):
    """A single row from the ``kms_keys`` history table.

    ``public_key_pem`` is ``None`` for HMAC keys (no public key exists
    for a symmetric secret). Asymmetric KMS rows carry the PEM so an
    offline verifier can validate signatures from a retired key.
    """

    key_id: str
    algorithm: str
    public_key_pem: Optional[str] = None
    created_at: datetime
    retired_at: Optional[datetime] = None
    is_active: bool

    model_config = {"from_attributes": True}


class KmsKeyHistoryResponse(BaseModel):
    """List wrapper for ``GET /v1/kms/keys``."""

    keys: list[KmsKeyResponse]
    total: int
