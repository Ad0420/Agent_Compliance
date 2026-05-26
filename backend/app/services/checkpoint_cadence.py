"""Checkpoint-cadence helpers — Phase 3 Wave 3A.b.

Two small surfaces:

* ``maybe_promote_org_to_hourly_cadence`` — invoked by
  ``services.auth.generate_api_key`` when a ``kind='live'`` key is
  minted. If the org is currently on the default ``'daily'`` cadence,
  bump it to ``'hourly'`` so the regulator-facing "less than 1 hour of
  unverified actions" claim holds. Skips orgs whose admins have
  explicitly opted into ``'disabled'`` or are already on ``'hourly'``
  (the function is idempotent for both cases).

* ``cadence_threshold`` — convert a cadence string into the
  ``timedelta`` the checkpoint sweeper uses as its "is this org due?"
  threshold. ``None`` means "never auto-create" — the sweeper skips.

Both are intentionally separate from ``services.checkpoint`` so the
checkpoint creation surface (which already participates in the
per-org lock + KMS signing dance) doesn't get tangled with cadence
policy. The sweeper is the only caller that needs both.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Organization

logger = logging.getLogger("vera.checkpoint_cadence")


# Threshold lookup — the sweeper uses ``now - last_checkpoint_at >=
# threshold`` to decide whether an org is due.  Match the v1-test-plan
# row: hourly → 24 checkpoints/day; daily → 1.
_THRESHOLDS: dict[str, Optional[timedelta]] = {
    "hourly": timedelta(hours=1),
    "daily": timedelta(hours=24),
    "disabled": None,
}


def cadence_threshold(cadence: str) -> Optional[timedelta]:
    """Return the timedelta the sweeper compares against, or None.

    ``None`` is the explicit "don't auto-create" signal.  Unknown
    cadence strings (which shouldn't reach here once the CHECK
    constraint is in place) treat as ``None`` so the sweeper degrades
    safely rather than throwing inside its loop.
    """
    return _THRESHOLDS.get(cadence)


async def maybe_promote_org_to_hourly_cadence(
    session: AsyncSession, org_id: str
) -> bool:
    """Promote ``org.checkpoint_cadence`` to ``'hourly'`` if currently
    ``'daily'``.

    Returns True if the row was updated, False otherwise.  Idempotent:
    re-running on an already-hourly or disabled row is a no-op.  Safe
    to call from inside ``generate_api_key`` after the api_keys row is
    committed — the failure path there logs and swallows.

    Only ``'daily'`` orgs get promoted: an explicit ``'disabled'``
    operator choice is preserved (the cadence sweeper still won't run
    for them; the operator made a deliberate decision).
    """
    org = await session.get(Organization, org_id)
    if org is None:
        # Defensive — the caller just inserted an api_keys row that
        # FK's to this org_id, so this branch should never fire. Log
        # and bail so we don't crash the live-key creation flow.
        logger.warning(
            "maybe_promote_org_to_hourly_cadence: org %s not found", org_id
        )
        return False

    if org.checkpoint_cadence != "daily":
        return False

    org.checkpoint_cadence = "hourly"
    await session.commit()
    await session.refresh(org)
    logger.info(
        "checkpoint cadence promoted for org %s: daily -> hourly", org_id
    )
    return True
