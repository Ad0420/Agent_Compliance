from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel, Field, field_validator, model_validator


class OrganizationCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=500)


class OrganizationResponse(BaseModel):
    id: str
    name: str
    alert_email: Optional[str] = None
    created_at: datetime
    # Phase 4 Wave 2 PR A3 — white-label PDF cover. ``accent_color_hex``
    # is exposed so the dashboard can render the configured accent in the
    # "Branding" settings card without an extra fetch. ``logo_bytes`` is
    # NOT exposed here (the bytes are large + binary; the dashboard
    # pulls the logo via the dedicated GET when it lands in a sibling
    # PR). ``logo_configured`` is a boolean derived from the bytes column
    # so the UI can render an "uploaded" state without bundling the blob.
    accent_color_hex: Optional[str] = None
    logo_configured: bool = False

    model_config = {"from_attributes": True}

    @model_validator(mode="before")
    @classmethod
    def _derive_logo_configured(cls, value: Any) -> Any:
        """Compute ``logo_configured`` from the ORM row's ``logo_mime``.

        Pydantic's ``from_attributes`` mode reads named fields off the
        ORM object; ``logo_configured`` isn't a column. This pre-validator
        injects it from ``logo_mime`` when the input is an ORM row,
        and otherwise leaves dict / kwargs inputs alone so the
        constructor can still set it explicitly.

        Why ``logo_mime`` and not ``logo_bytes``? ``logo_bytes`` is a
        ``deferred=True`` column on the ORM model — accessing it forces
        SQLAlchemy to lazy-load the blob, which raises
        ``MissingGreenlet`` inside an async session. ``logo_mime`` is a
        sibling column with the same NULL-when-no-logo semantics, but
        eager-loaded, so reading it is free for every existing route
        that ``OrganizationResponse.model_validate``s an ORM row.
        """
        # Only intercept ORM-like inputs (object with the expected attrs).
        # Dicts and BaseModel instances are passed through untouched so
        # tests and explicit callers can still set ``logo_configured`` by
        # hand.
        if isinstance(value, (dict, BaseModel)):
            return value
        logo_mime = getattr(value, "logo_mime", None)
        # Wrap the ORM row in a dict that mixes the known model fields
        # with the computed flag. We can't mutate the ORM row in place
        # (SQLAlchemy treats unknown attribute assignment as a relationship
        # lookup), so build a dict and let pydantic validate from it.
        return {
            "id": getattr(value, "id", None),
            "name": getattr(value, "name", None),
            "alert_email": getattr(value, "alert_email", None),
            "created_at": getattr(value, "created_at", None),
            "accent_color_hex": getattr(value, "accent_color_hex", None),
            "logo_configured": logo_mime is not None,
        }


class AlertEmailUpdate(BaseModel):
    alert_email: Optional[str] = None

    @field_validator("alert_email")
    @classmethod
    def validate_email_format(cls, v: Optional[str]) -> Optional[str]:
        if v is None or v == "":
            return None
        v = v.strip()
        if "@" not in v or "." not in v.split("@")[-1]:
            raise ValueError("Invalid email address")
        return v


class RegisterRequest(BaseModel):
    org_name: str = Field(..., min_length=1, max_length=200)

    @field_validator("org_name")
    @classmethod
    def strip_and_require_nonempty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("org_name cannot be blank or whitespace only")
        return v


class RegisterResponse(BaseModel):
    org_id: str
    org_name: str
    api_key: str   # raw key — shown once, never stored
    key_prefix: str
    created_at: datetime
