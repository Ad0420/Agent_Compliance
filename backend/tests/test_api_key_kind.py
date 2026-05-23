"""APIKey ``kind`` split tests (Phase 1 PR 1).

Phase 1 PR 1 introduces ``kind`` (``test`` vs ``live``) with a default of
``test`` and a CHECK constraint. BAA-gating on ``kind='live'`` lands in
Phase 1 PR 4 — this PR is column-level only.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models import APIKey, Organization


@pytest.mark.asyncio
async def test_api_key_default_kind_is_test(db_session):
    """New keys default to ``kind='test'`` when not specified."""
    org = Organization(name="ak-default")
    db_session.add(org)
    await db_session.flush()

    key = APIKey(
        org_id=org.id,
        name="my-key",
        key_hash="h_" + "a" * 60,
        key_prefix="al_test_p",
    )
    db_session.add(key)
    await db_session.commit()
    await db_session.refresh(key)

    assert key.kind == "test"


@pytest.mark.asyncio
async def test_api_key_explicit_live_accepted(db_session):
    """A key with ``kind='live'`` is accepted at the schema level —
    BAA-gating is a separate concern in PR 4."""
    org = Organization(name="ak-live")
    db_session.add(org)
    await db_session.flush()

    key = APIKey(
        org_id=org.id,
        name="prod-key",
        key_hash="h_live_" + "b" * 55,
        key_prefix="al_live_p",
        kind="live",
    )
    db_session.add(key)
    await db_session.commit()
    await db_session.refresh(key)

    assert key.kind == "live"


@pytest.mark.asyncio
async def test_api_key_invalid_kind_rejected(db_session):
    """Anything other than ``test`` / ``live`` must raise IntegrityError
    (CHECK constraint enforcement)."""
    org = Organization(name="ak-bad-kind")
    db_session.add(org)
    await db_session.flush()

    key = APIKey(
        org_id=org.id,
        name="bogus",
        key_hash="h_bogus_" + "c" * 55,
        key_prefix="al_xx_p",
        kind="staging",
    )
    db_session.add(key)
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_existing_keys_via_generate_default_test(db_session):
    """The generate_api_key service path produces ``kind='test'`` keys
    by default (it does not specify ``kind``, so server_default applies).
    This is the analogue of the migration's backfill behaviour:
    pre-Phase-1 keys all land in the safe sandbox bucket."""
    from app.services.auth import generate_api_key

    org = Organization(name="ak-gen")
    db_session.add(org)
    await db_session.commit()

    raw_key, api_key = await generate_api_key(
        db_session, org.id, "via-service", ["read"]
    )
    assert api_key.kind == "test"


@pytest.mark.asyncio
async def test_api_key_kind_index_exists(db_session):
    """The composite (org_id, kind) index must be present on the table."""
    from sqlalchemy import inspect

    def _check(sync_conn):
        insp = inspect(sync_conn)
        indexes = {ix["name"] for ix in insp.get_indexes("api_keys")}
        return "idx_api_keys_org_kind" in indexes

    conn = await db_session.connection()
    has_index = await conn.run_sync(_check)
    assert has_index
