"""Tests for Phase 3 Wave 3A.b — per-org checkpoint cadence.

Covers the eng-review-finding-1D surface area end-to-end:

  * Model column shape + CHECK constraint
  * Migration ``s0p3q4r5s6t7_add_org_checkpoint_cadence`` up/down + idempotent
  * Data migration: orgs with active al_live_* keys → 'hourly'
  * ``services.auth.generate_api_key`` auto-promotes daily → hourly
    on first live-key mint (idempotent on already-hourly or disabled
    orgs)
  * ``services.checkpoint_sweeper.sweep_due_checkpoints`` honours the
    cadence thresholds (hourly: 1h, daily: 24h, disabled: never)
  * ``hourly`` org over a 24-hour simulated loop → 24 checkpoints;
    ``daily`` org → 1
  * Concurrent sweeper ticks on the same org do not double-checkpoint
    (per-org lock)
  * GET / PATCH ``/v1/organizations/me/checkpoint-cadence``: read,
    update, non-admin 403, invalid value 422 with ``valid_cadences``

The 24-hour loop tests don't use freezegun (not a project dep). They
fake "time has passed" by directly mutating ``Checkpoint.created_at``
on the most recent row — the sweeper reads that timestamp on its next
pass, so the effect is identical.
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import pytest_asyncio
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy import select

from app.models import Checkpoint, ChainState, Organization
from app.models.organization import CHECKPOINT_CADENCES
from app.schemas.action import ActionRecordCreate
from app.services.auth import generate_api_key
from app.services.chain import build_and_insert_record
from app.services.checkpoint import create_checkpoint
from app.services.checkpoint_cadence import (
    cadence_threshold,
    maybe_promote_org_to_hourly_cadence,
)
from app.services.checkpoint_sweeper import sweep_due_checkpoints


BACKEND_ROOT = Path(__file__).resolve().parent.parent
ALEMBIC_INI = BACKEND_ROOT / "alembic.ini"

REV_PREV = "r8m0n1o2p3q4"
REV_NEW = "s0p3q4r5s6t7"
MIGRATION_FILE = "s0p3q4r5s6t7_add_org_checkpoint_cadence.py"


# ── Helpers ─────────────────────────────────────────────────────────


def _make_action(**kwargs) -> ActionRecordCreate:
    defaults = {
        "action_name": "cadence_test",
        "action_type": "function_call",
        "agent_name": "cadence-agent",
        "result": "success",
    }
    defaults.update(kwargs)
    return ActionRecordCreate(**defaults)


async def _seed_org(db_session, name: str = "cadence-org") -> Organization:
    org = Organization(name=name)
    db_session.add(org)
    await db_session.flush()
    db_session.add(ChainState(org_id=org.id))
    await db_session.commit()
    await db_session.refresh(org)
    return org


async def _record_and_checkpoint(db_session, org_id: str) -> Checkpoint:
    """Seed one action record, then create a checkpoint. Returns the
    fresh Checkpoint row.
    """
    await build_and_insert_record(
        db_session, org_id, _make_action(action_name=f"cp_seed_{org_id[:8]}")
    )
    return await create_checkpoint(db_session, org_id)


async def _backdate_last_checkpoint(db_session, org_id: str, age: timedelta):
    """Pretend the most recent checkpoint for ``org_id`` happened
    ``age`` ago. Direct DB-level mutation (bypassing the immutability
    triggers, which only guard action_records — checkpoints are
    mutable per the project's existing verify_at update pattern).
    """
    result = await db_session.execute(
        select(Checkpoint)
        .where(Checkpoint.org_id == org_id)
        .order_by(Checkpoint.created_at.desc())
    )
    cp = result.scalars().first()
    assert cp is not None, "no checkpoint to backdate"
    new_ts = datetime.now(timezone.utc).replace(tzinfo=None) - age
    cp.created_at = new_ts
    await db_session.commit()


# ── Model / CHECK constraint ────────────────────────────────────────


@pytest.mark.asyncio
async def test_checkpoint_cadence_default_is_daily(db_session):
    org = await _seed_org(db_session, "default-cadence")
    # Fresh org defaults to 'daily' via Python-side default.
    assert org.checkpoint_cadence == "daily"


@pytest.mark.asyncio
async def test_checkpoint_cadence_constants_match_thresholds():
    # Defensive: the route layer's structured 422 and the sweeper's
    # threshold lookup must agree on the literal set.
    assert set(CHECKPOINT_CADENCES) == {"daily", "hourly", "disabled"}
    assert cadence_threshold("hourly") == timedelta(hours=1)
    assert cadence_threshold("daily") == timedelta(hours=24)
    assert cadence_threshold("disabled") is None
    # Defense-in-depth: unknown strings → None (sweeper skips).
    assert cadence_threshold("weekly") is None


# ── Migration ───────────────────────────────────────────────────────


@pytest.fixture
def temp_db_url(monkeypatch):
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    url = f"sqlite:///{path}"
    monkeypatch.setenv("DATABASE_URL", url)
    try:
        yield url, path
    finally:
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass


def _make_alembic_cfg(db_url: str) -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", db_url)
    return cfg


def _inspector(db_url: str):
    engine = sa.create_engine(db_url)
    return engine, sa.inspect(engine)


def _load_migration_module(filename: str):
    path = BACKEND_ROOT / "alembic" / "versions" / filename
    spec = importlib.util.spec_from_file_location(filename[:-3], path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _rerun_upgrade(db_url: str, filename: str) -> None:
    mod = _load_migration_module(filename)
    engine = sa.create_engine(db_url)
    try:
        with engine.connect() as conn:
            with conn.begin():
                from alembic.runtime.migration import MigrationContext
                from alembic.operations import Operations

                ctx = MigrationContext.configure(conn)
                with Operations.context(ctx):
                    mod.upgrade()
    finally:
        engine.dispose()


def test_migration_upgrade_creates_cadence_column(temp_db_url):
    db_url, _ = temp_db_url
    cfg = _make_alembic_cfg(db_url)
    command.upgrade(cfg, REV_NEW)

    engine, insp = _inspector(db_url)
    cols = {c["name"] for c in insp.get_columns("organizations")}
    assert "checkpoint_cadence" in cols, cols
    engine.dispose()


def test_migration_downgrade_removes_cadence_column(temp_db_url):
    db_url, _ = temp_db_url
    cfg = _make_alembic_cfg(db_url)
    command.upgrade(cfg, REV_NEW)
    command.downgrade(cfg, REV_PREV)

    engine, insp = _inspector(db_url)
    cols = {c["name"] for c in insp.get_columns("organizations")}
    assert "checkpoint_cadence" not in cols, cols
    engine.dispose()


def test_migration_existing_rows_default_to_daily(temp_db_url):
    """Pre-migration rows should backfill to 'daily'."""
    db_url, _ = temp_db_url
    cfg = _make_alembic_cfg(db_url)
    # Upgrade to the revision BEFORE this migration first so we can
    # seed an org row without the new column.
    command.upgrade(cfg, REV_PREV)

    engine = sa.create_engine(db_url)
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO organizations (id, name) VALUES "
                "('org-legacy', 'legacy-no-cadence')"
            )
        )
    engine.dispose()

    # Now apply the new migration. The existing row should pick up
    # the 'daily' default via the explicit UPDATE in the migration.
    command.upgrade(cfg, REV_NEW)

    engine = sa.create_engine(db_url)
    with engine.begin() as conn:
        cadence = conn.execute(
            sa.text(
                "SELECT checkpoint_cadence FROM organizations "
                "WHERE id = 'org-legacy'"
            )
        ).scalar_one()
    engine.dispose()
    assert cadence == "daily"


def test_migration_live_key_promotes_to_hourly(temp_db_url):
    """An org with an active al_live_* key gets promoted to 'hourly'."""
    db_url, _ = temp_db_url
    cfg = _make_alembic_cfg(db_url)
    command.upgrade(cfg, REV_PREV)

    engine = sa.create_engine(db_url)
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO organizations (id, name) VALUES "
                "('org-with-live', 'has-live-key'), "
                "('org-test-only', 'sandbox-only')"
            )
        )
        # One live key for org-with-live, one test key for both.
        conn.execute(
            sa.text(
                "INSERT INTO api_keys (id, org_id, name, key_hash, key_prefix, permissions, kind) "
                "VALUES ('k1', 'org-with-live', 'live', 'h1', 'al_live_x', '[]', 'live'), "
                "       ('k2', 'org-test-only', 'sandbox', 'h2', 'al_test_x', '[]', 'test')"
            )
        )
    engine.dispose()

    command.upgrade(cfg, REV_NEW)

    engine = sa.create_engine(db_url)
    with engine.begin() as conn:
        cadences = dict(
            conn.execute(
                sa.text(
                    "SELECT id, checkpoint_cadence FROM organizations "
                    "WHERE id IN ('org-with-live', 'org-test-only')"
                )
            ).all()
        )
    engine.dispose()
    assert cadences["org-with-live"] == "hourly"
    assert cadences["org-test-only"] == "daily"


def test_migration_is_idempotent(temp_db_url):
    """Re-running the upgrade is a no-op."""
    db_url, _ = temp_db_url
    cfg = _make_alembic_cfg(db_url)
    command.upgrade(cfg, REV_NEW)

    engine, insp = _inspector(db_url)
    cols_before = sorted(c["name"] for c in insp.get_columns("organizations"))
    engine.dispose()

    _rerun_upgrade(db_url, MIGRATION_FILE)

    engine, insp = _inspector(db_url)
    cols_after = sorted(c["name"] for c in insp.get_columns("organizations"))
    engine.dispose()
    assert cols_before == cols_after
    assert not any(c.endswith("_1") for c in cols_after), cols_after


# ── Auto-promotion on live key creation ─────────────────────────────


@pytest.mark.asyncio
async def test_live_key_creation_promotes_daily_to_hourly(db_session):
    org = await _seed_org(db_session, "promote-on-live")
    assert org.checkpoint_cadence == "daily"
    await generate_api_key(
        db_session, org.id, "first-live", ["read", "write"], kind="live"
    )
    await db_session.refresh(org)
    assert org.checkpoint_cadence == "hourly"


@pytest.mark.asyncio
async def test_live_key_promotion_is_idempotent_on_hourly(db_session):
    org = await _seed_org(db_session, "already-hourly")
    org.checkpoint_cadence = "hourly"
    await db_session.commit()
    await db_session.refresh(org)
    # Mint another live key — cadence stays 'hourly'.
    await generate_api_key(
        db_session, org.id, "second-live", ["read", "write"], kind="live"
    )
    await db_session.refresh(org)
    assert org.checkpoint_cadence == "hourly"


@pytest.mark.asyncio
async def test_live_key_promotion_preserves_disabled(db_session):
    """An org explicitly opted into 'disabled' is NOT silently promoted."""
    org = await _seed_org(db_session, "disabled-stays-disabled")
    org.checkpoint_cadence = "disabled"
    await db_session.commit()
    await db_session.refresh(org)
    await generate_api_key(
        db_session, org.id, "live-but-disabled", ["read"], kind="live"
    )
    await db_session.refresh(org)
    assert org.checkpoint_cadence == "disabled"


@pytest.mark.asyncio
async def test_test_key_creation_does_not_promote(db_session):
    org = await _seed_org(db_session, "test-key-only")
    await generate_api_key(
        db_session, org.id, "sandbox", ["read"], kind="test"
    )
    await db_session.refresh(org)
    assert org.checkpoint_cadence == "daily"


@pytest.mark.asyncio
async def test_maybe_promote_helper_idempotency(db_session):
    org = await _seed_org(db_session, "promote-helper")
    promoted = await maybe_promote_org_to_hourly_cadence(db_session, org.id)
    assert promoted is True
    # Second call on same org — already hourly, returns False.
    promoted_again = await maybe_promote_org_to_hourly_cadence(
        db_session, org.id
    )
    assert promoted_again is False


# ── Sweeper ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sweeper_hourly_creates_when_due(db_session):
    org = await _seed_org(db_session, "hourly-due")
    org.checkpoint_cadence = "hourly"
    await db_session.commit()
    await _record_and_checkpoint(db_session, org.id)

    # Backdate the last checkpoint to 65 minutes ago — over the 60m
    # threshold for 'hourly'. The sweeper must create a new one.
    await _backdate_last_checkpoint(db_session, org.id, timedelta(minutes=65))
    # Need fresh action records to make a meaningful new checkpoint.
    await build_and_insert_record(
        db_session, org.id, _make_action(action_name="post_backdate")
    )

    created = await sweep_due_checkpoints(db_session)
    assert created == 1


@pytest.mark.asyncio
async def test_sweeper_hourly_skips_when_recent(db_session):
    org = await _seed_org(db_session, "hourly-recent")
    org.checkpoint_cadence = "hourly"
    await db_session.commit()
    await _record_and_checkpoint(db_session, org.id)

    # 30 minutes ago — under the 1h threshold. No new checkpoint.
    await _backdate_last_checkpoint(db_session, org.id, timedelta(minutes=30))
    created = await sweep_due_checkpoints(db_session)
    assert created == 0


@pytest.mark.asyncio
async def test_sweeper_daily_creates_when_due(db_session):
    org = await _seed_org(db_session, "daily-due")
    # Default is already 'daily'; assert it.
    assert org.checkpoint_cadence == "daily"
    await _record_and_checkpoint(db_session, org.id)
    await _backdate_last_checkpoint(db_session, org.id, timedelta(hours=25))
    await build_and_insert_record(
        db_session, org.id, _make_action(action_name="daily_post")
    )

    created = await sweep_due_checkpoints(db_session)
    assert created == 1


@pytest.mark.asyncio
async def test_sweeper_daily_skips_when_recent(db_session):
    org = await _seed_org(db_session, "daily-recent")
    await _record_and_checkpoint(db_session, org.id)
    await _backdate_last_checkpoint(db_session, org.id, timedelta(hours=23))
    created = await sweep_due_checkpoints(db_session)
    assert created == 0


@pytest.mark.asyncio
async def test_sweeper_disabled_never_creates(db_session):
    org = await _seed_org(db_session, "disabled-never")
    org.checkpoint_cadence = "disabled"
    await db_session.commit()
    await _record_and_checkpoint(db_session, org.id)
    # Even with a wildly stale checkpoint, 'disabled' wins.
    await _backdate_last_checkpoint(db_session, org.id, timedelta(days=30))
    await build_and_insert_record(
        db_session, org.id, _make_action(action_name="disabled_post")
    )
    created = await sweep_due_checkpoints(db_session)
    assert created == 0


@pytest.mark.asyncio
async def test_sweeper_no_prior_checkpoint_treats_as_due(db_session):
    """First-ever sweep on a fresh org creates the baseline."""
    org = await _seed_org(db_session, "baseline")
    # Need at least one action record so the checkpoint is meaningful.
    await build_and_insert_record(
        db_session, org.id, _make_action(action_name="baseline_seed")
    )
    created = await sweep_due_checkpoints(db_session)
    assert created == 1


@pytest.mark.asyncio
async def test_sweeper_skips_soft_deleted_orgs(db_session):
    """Soft-deleted orgs aren't picked up by the sweeper."""
    org = await _seed_org(db_session, "soft-deleted")
    org.deleted_at = datetime.now(timezone.utc).replace(tzinfo=None)
    await db_session.commit()
    # Even with a stale checkpoint history (or none), skipped.
    await build_and_insert_record(
        db_session, org.id, _make_action(action_name="soft_del_seed")
    )
    created = await sweep_due_checkpoints(db_session)
    assert created == 0


@pytest.mark.asyncio
async def test_sweeper_hourly_produces_24_in_simulated_day(db_session):
    """Loop 24 sweeper ticks across a simulated 24-hour window for an
    hourly org. After each tick we backdate the most recent checkpoint
    by 1h to mimic time passing. Expect 24 checkpoints (1 per tick).
    """
    org = await _seed_org(db_session, "hourly-24h-loop")
    org.checkpoint_cadence = "hourly"
    await db_session.commit()

    # Seed an initial action record so checkpoints are non-trivial.
    await build_and_insert_record(
        db_session, org.id, _make_action(action_name="loop_seed")
    )

    total_created = 0
    for i in range(24):
        # Insert a fresh record before each tick so the chain has
        # something new to anchor (otherwise downstream Merkle-root
        # computation would see an empty window).
        if i > 0:
            await build_and_insert_record(
                db_session,
                org.id,
                _make_action(action_name=f"hourly_tick_{i}"),
            )
        created = await sweep_due_checkpoints(db_session)
        total_created += created
        # Advance "time" by 1h+ so the next tick is over the threshold.
        await _backdate_last_checkpoint(
            db_session, org.id, timedelta(minutes=61)
        )

    assert total_created == 24


@pytest.mark.asyncio
async def test_sweeper_daily_produces_1_in_simulated_day(db_session):
    """Same loop shape, but with cadence='daily': 24 ticks at 1h
    intervals should produce just one checkpoint (the very first; all
    others are inside the 24h threshold).
    """
    org = await _seed_org(db_session, "daily-24h-loop")
    # Default is 'daily'.
    await build_and_insert_record(
        db_session, org.id, _make_action(action_name="daily_loop_seed")
    )

    total_created = 0
    for i in range(24):
        if i > 0:
            await build_and_insert_record(
                db_session,
                org.id,
                _make_action(action_name=f"daily_tick_{i}"),
            )
        created = await sweep_due_checkpoints(db_session)
        total_created += created
        # Advance "time" by 1h. After the FIRST tick (which created
        # the baseline checkpoint), the next 23 ticks see a
        # checkpoint that's 1h, 2h, 3h, ..., 23h old — never over the
        # 24h threshold. So total should be exactly 1.
        await _backdate_last_checkpoint(
            db_session, org.id, timedelta(minutes=61)
        )

    assert total_created == 1


@pytest.mark.asyncio
async def test_sweeper_concurrent_ticks_dont_double_checkpoint(db_session):
    """Two ticks scheduled in parallel for the same hourly org must
    produce at most one new checkpoint (the per-org chain lock
    enforces serialisation inside ``create_checkpoint``).
    """
    org = await _seed_org(db_session, "concurrent-tick")
    org.checkpoint_cadence = "hourly"
    await db_session.commit()
    await _record_and_checkpoint(db_session, org.id)
    await _backdate_last_checkpoint(db_session, org.id, timedelta(hours=2))
    await build_and_insert_record(
        db_session, org.id, _make_action(action_name="conc_seed")
    )

    # Both ticks share the same session here for SQLite simplicity —
    # the lock is in-process so the test-relevant invariant (no
    # double-checkpointing) still holds. Production runs each tick
    # under its own AsyncSessionLocal session.
    results = await asyncio.gather(
        sweep_due_checkpoints(db_session),
        sweep_due_checkpoints(db_session),
    )
    # At most one of the two ticks should have created a checkpoint;
    # the other observes the fresh row and short-circuits.
    assert sum(results) == 1


# ── Endpoint: GET / PATCH /v1/organizations/me/checkpoint-cadence ──


@pytest.mark.asyncio
async def test_endpoint_get_returns_cadence(async_client, org_and_key):
    _, raw_key, _ = org_and_key
    resp = await async_client.get(
        "/v1/organizations/me/checkpoint-cadence",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"cadence": "daily"}


@pytest.mark.asyncio
async def test_endpoint_patch_updates_cadence(async_client, org_and_key):
    _, raw_key, _ = org_and_key
    resp = await async_client.patch(
        "/v1/organizations/me/checkpoint-cadence",
        json={"cadence": "hourly"},
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"cadence": "hourly"}
    # Persisted — verify via a follow-up GET (avoids cross-session
    # cache issues from sharing the in-memory SQLite engine).
    follow = await async_client.get(
        "/v1/organizations/me/checkpoint-cadence",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert follow.status_code == 200, follow.text
    assert follow.json() == {"cadence": "hourly"}


@pytest.mark.asyncio
async def test_endpoint_patch_bad_value_returns_422(async_client, org_and_key):
    _, raw_key, _ = org_and_key
    resp = await async_client.patch(
        "/v1/organizations/me/checkpoint-cadence",
        json={"cadence": "weekly"},
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 422, resp.text
    body = resp.json()
    assert body["code"] == "invalid_cadence"
    assert "valid_cadences" in body
    assert set(body["valid_cadences"]) == {"daily", "hourly", "disabled"}


@pytest_asyncio.fixture
async def reader_key(db_session, org_and_key):
    """Mint a read-only key on the same org so we can exercise the
    403-on-non-admin path against PATCH.
    """
    org, _, _ = org_and_key
    raw_key, _ = await generate_api_key(
        db_session, org.id, "reader", ["read"]
    )
    return raw_key


@pytest.mark.asyncio
async def test_endpoint_patch_non_admin_returns_403(
    async_client, reader_key
):
    resp = await async_client.patch(
        "/v1/organizations/me/checkpoint-cadence",
        json={"cadence": "hourly"},
        headers={"Authorization": f"Bearer {reader_key}"},
    )
    assert resp.status_code == 403, resp.text


@pytest.mark.asyncio
async def test_endpoint_get_works_with_read_only_key(
    async_client, reader_key
):
    resp = await async_client.get(
        "/v1/organizations/me/checkpoint-cadence",
        headers={"Authorization": f"Bearer {reader_key}"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"cadence": "daily"}
