"""Response schemas for ``GET /v1/dashboard/chain-integrity`` (Wave 3D.1)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


class LatestCheckpointSummaryResponse(BaseModel):
    """Trimmed checkpoint shape — only what the Home tile renders."""

    checkpoint_id: str
    sealed_at: datetime
    sequence: int
    record_count: int

    model_config = {"from_attributes": True}


class KmsKeySummaryResponse(BaseModel):
    """Current signing key surfaced by the Home tile."""

    key_id: str
    algorithm: str

    model_config = {"from_attributes": True}


class ChainIntegrityResponse(BaseModel):
    """Full Home-tile aggregator response.

    ``status`` is the green/yellow/red traffic light. ``message`` is a
    human-readable, regulator-ready one-liner — no engineering jargon.
    """

    status: Literal["ok", "warn", "error"] = Field(
        ...,
        description=(
            "Traffic-light status for the evidence trail. 'ok' = green, "
            "'warn' = yellow, 'error' = red."
        ),
    )
    message: str
    latest_checkpoint: Optional[LatestCheckpointSummaryResponse] = None
    chain_depth: int = Field(
        ...,
        ge=0,
        description="Total number of sealed checkpoints for the org.",
    )
    kms_key: Optional[KmsKeySummaryResponse] = None
    cadence: Literal["hourly", "daily", "disabled"]

    model_config = {"from_attributes": True}
