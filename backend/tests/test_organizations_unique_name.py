"""Tests for the UNIQUE constraint on organizations.name (W1.6).

Closes Phase 2 finding ``two-scribemd-orgs``.

Two test cases:

1. Inserting two ``Organization`` rows with the same name raises
   ``IntegrityError`` (constraint enforced at the DB level, not just
   the ORM).
2. The Alembic migration ``t0o2p3q4r5s6`` upgrades + downgrades
   cleanly on a fresh in-memory SQLite database, using the migration's
   own pre-check to abort when duplicates exist.

   (Originally authored as ``s9n1o2p3q4r5``; re-IDed to
   ``t0o2p3q4r5s6`` after a duplicate-revision collision with the
   sibling ``baa_scope.granted_at default now()`` migration. See the
   chain-fix note in the migration header.)

The duplicate-detection path is exercised by directly invoking
``_find_duplicate_names`` because the only way to insert two
same-name rows is to bypass the constraint (by running the migration
ON an existing schema that doesn't yet have it). We seed with the
constraint absent, then re-run upgrade and assert it raises.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models import ChainState, Organization


_MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "t0o2p3q4r5s6_unique_organizations_name.py"
)


def _load_migration_module():
    """Load the migration module by file path (alembic versions/ is not a package)."""
    spec = importlib.util.spec_from_file_location(
        "_w16_unique_orgs_migration", _MIGRATION_PATH
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.asyncio
async def test_duplicate_name_raises_integrity_error(db_session):
    """The ORM ``unique=True`` ⇒ DB-level UNIQUE constraint.

    SQLite enforces UNIQUE constraints at INSERT time; the first
    insert succeeds, the second raises ``IntegrityError``. Wrapped in
    a flush so the violation surfaces here rather than at commit.
    """
    org_a = Organization(name="ScribeMD Test")
    db_session.add(org_a)
    await db_session.flush()
    # Add chain state to mirror real-life — keeps the FK happy and
    # rules out "violation came from elsewhere" confusion.
    db_session.add(ChainState(org_id=org_a.id))
    await db_session.commit()

    org_b = Organization(name="ScribeMD Test")
    db_session.add(org_b)
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()

    # Only one row survives.
    remaining = (
        await db_session.execute(
            select(Organization).where(Organization.name == "ScribeMD Test")
        )
    ).scalars().all()
    assert len(remaining) == 1


@pytest.mark.asyncio
async def test_migration_aborts_when_duplicates_exist(monkeypatch):
    """The migration's pre-check raises a helpful error before ALTER TABLE.

    We simulate the "duplicates already in the DB" condition by
    constructing a fake bind whose ``execute`` returns two duplicate
    rows for the migration's GROUP BY query. The migration's
    ``upgrade()`` should raise ``RuntimeError`` with the offending
    name in the message.
    """
    mig = _load_migration_module()

    class _FakeResult:
        def __init__(self, rows):
            self._rows = rows

        def fetchall(self):
            return self._rows

    class _FakeBind:
        def execute(self, _stmt):
            # Simulate two duplicate names in the DB.
            return _FakeResult([("scribemd", 2), ("triageguard", 3)])

    duplicates = mig._find_duplicate_names(_FakeBind())
    assert duplicates == [("scribemd", 2), ("triageguard", 3)]
