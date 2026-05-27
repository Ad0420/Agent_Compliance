"""GeneratedTemplate — per-org Markdown template rows for the Phase 5
counsel-attestation flow.

Phase 5 PR A. Five Markdown documents are deterministically generated
from an Organization's onboarding-wizard answers and persisted here
(one row per ``(org_id, template_key)`` pair). Customer admins edit the
``markdown_body`` in the dashboard, then click "Counsel attested" — at
which point we stamp ``attested_at``, ``attested_by_user_id``,
``attested_by_name`` and persist the SHA-256 of the body so the surface
can later prove "this exact text was attested at this exact moment."

Atomic attestation triple
-------------------------
``attested_at``, ``attested_by_user_id``, ``attested_by_name``, and
``content_hash_at_attestation`` are written together by the
``POST /v1/templates/{key}/attest`` handler. The PUT handler clears all
four together when ``markdown_body`` changes — there is no codepath that
sets one without the others. The DB does not enforce the invariant via
CHECK (we want flexibility to migrate the hash format without a
constraint dance) but the application layer is the single writer.

Idempotent re-generation
------------------------
``POST /v1/templates/generate`` is idempotent: rows missing for a key
get inserted, rows present-but-not-attested get their body refreshed,
and rows present-AND-attested are skipped (never destroy attested work).
The route layer is the policy boundary; this model just carries the
state.

Per-key uniqueness
------------------
``(org_id, template_key)`` is a unique pair — one template body per key
per org. The Phase 5 wave doesn't ship versioning; if we later add it,
the new table will be ``generated_template_versions`` keyed by
``generated_template_id`` so the v1 unique index stays meaningful.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class GeneratedTemplate(Base):
    __tablename__ = "generated_templates"
    __table_args__ = (
        # Phase 5 PR A — one template body per (org, template_key) pair.
        # Enforced at the DB so a concurrent ``POST /generate`` race
        # cannot insert two rows for the same key.
        UniqueConstraint(
            "org_id",
            "template_key",
            name="uq_generated_templates_org_key",
        ),
        # List-by-org query ("show me all my templates") — used by
        # ``GET /v1/templates``. The unique index above already covers
        # ``WHERE org_id = ?`` on Postgres + SQLite (leading-column scan),
        # but we add an explicit single-column index too because the list
        # endpoint sorts by template_key alphabetically rather than by
        # the composite key order.
        Index(
            "idx_generated_templates_org",
            "org_id",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    org_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    # One of the five values in
    # ``app.services.templates.TEMPLATE_KEYS``. Stored as VARCHAR (not
    # ENUM) so adding a sixth template key is a one-line service change,
    # not a migration. The application layer validates the value on
    # every write.
    template_key: Mapped[str] = mapped_column(String(64), nullable=False)
    # The current editable Markdown body. Re-generation overwrites this
    # unless ``attested_at`` is set (see route docstring).
    markdown_body: Mapped[str] = mapped_column(Text, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    # ``onupdate=func.now()`` so an UPDATE bumps the column without the
    # route handler having to remember. PUT relies on this; the attest
    # route relies on it too (an attestation IS an update).
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    # ── Attestation triple — all set together, all cleared together ──
    attested_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )
    # Clerk ``sub`` claim for Clerk-session attestations, APIKey.id for
    # API-key attestations. We don't FK either — the row should outlive
    # the credential.
    attested_by_user_id: Mapped[Optional[str]] = mapped_column(
        String(128), nullable=True
    )
    # Human-entered reviewer name (e.g. "Jane Doe, General Counsel").
    # Separate from ``attested_by_user_id`` so the dashboard can render
    # "Attested by Jane Doe" without a Clerk REST lookup.
    attested_by_name: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )
    # SHA-256 hex of ``markdown_body`` at the moment of attestation.
    # Persisted so the dashboard can render "attested at this exact
    # content" with confidence — and so a future evidence-export can
    # surface the hash alongside the body. The PUT handler clears this
    # alongside the other attestation fields when the body changes.
    content_hash_at_attestation: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )
