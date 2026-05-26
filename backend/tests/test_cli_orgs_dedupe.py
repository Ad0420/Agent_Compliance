"""W2.3 — ``python -m app.cli orgs dedupe`` maintenance CLI.

Covers the operator-facing wrapper around the cleanup SQL documented in
``backend/alembic/versions/t0o2p3q4r5s6_unique_organizations_name.py``.

The CLI itself is sync (SQLAlchemy Core via psycopg2/sqlite); these
tests use a sync engine over an in-memory SQLite file to exercise both
the happy path (merge two orgs, surviving row carries all the
re-pointed FK rows) and the refuse-to-run guards (single-row name,
``--keep`` not among matching ids, no match at all, ``--dry-run``
doesn't mutate).

The schema is materialised via the live ``Base.metadata.create_all``
so the test stays honest if a new ``org_id`` FK table is added — the
test will fail at the merge step if ``_REPOINT_TABLES`` /
``_DELETE_TABLES`` in ``app.cli`` doesn't cover it.
"""

from __future__ import annotations

import io
import uuid

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session

from app.cli import dedupe_orgs, main
from app.models import (
    APIKey,
    ActionRecord,
    Approval,
    Base,
    ChainState,
    Customer,
    Organization,
)
from app.models.org_membership import OrgMembership


@pytest.fixture()
def sync_engine(tmp_path):
    """Sync SQLite engine over a tempfile, full schema created.

    Tests need to construct the *pre-W1.6-migration* state — multiple
    org rows with the same name. The live model declares
    ``Organization.name`` as ``unique=True``, which ``create_all`` bakes
    into the CREATE TABLE statement (SQLite). We drop and recreate the
    ``organizations`` table without the UNIQUE clause so the fixture can
    insert duplicates. The CLI under test still operates on the full FK
    graph (api_keys, chain_state, customers, …) since those are created
    from the unmodified metadata.
    """
    db = tmp_path / "vera-test.db"
    engine = create_engine(f"sqlite:///{db}", future=True)

    @event.listens_for(engine, "connect")
    def _enable_fks(dbapi_conn, _record):
        cur = dbapi_conn.cursor()
        try:
            cur.execute("PRAGMA foreign_keys=ON")
        finally:
            cur.close()

    Base.metadata.create_all(engine)

    # Recreate organizations without the UNIQUE(name) constraint so we
    # can stage duplicate rows in the fixture. FKs to organizations.id
    # remain valid because the primary key is preserved.
    with engine.begin() as conn:
        conn.execute(text("PRAGMA foreign_keys=OFF"))
        conn.execute(text("DROP TABLE organizations"))
        conn.execute(text(
            "CREATE TABLE organizations ("
            " id VARCHAR(36) NOT NULL PRIMARY KEY,"
            " name VARCHAR NOT NULL,"
            " alert_email TEXT,"
            " clerk_org_id VARCHAR,"
            " deleted_at DATETIME,"
            " scrubbed_clerk_org_id VARCHAR,"
            " created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,"
            " wizard_answers JSON,"
            " wizard_completed_at DATETIME,"
            # Phase 3 Wave 3A.b — per-org checkpoint cadence (NOT NULL
            # with server default 'daily'). Brought into the dedupe
            # test fixture during the develop→main release sync; the
            # original CREATE TABLE pre-dated the column.
            " checkpoint_cadence VARCHAR(16) NOT NULL DEFAULT 'daily',"
            # Phase 3 Wave 3B.1 — customer S3 mirror export target.
            # Nullable; NULL means "no mirror configured".
            " s3_export_arn VARCHAR(512)"
            ")"
        ))
        conn.execute(text("PRAGMA foreign_keys=ON"))

    yield engine
    engine.dispose()


@pytest.fixture()
def two_dup_orgs(sync_engine):
    """Create two organizations with the same name (bypassing UNIQUE).

    The migration adds ``UNIQUE(organizations.name)`` — these tests
    construct the *pre-migration* state, so we drop the constraint
    via raw SQL on the test engine before inserting. The dedupe CLI
    is exactly the tool that lets the operator transition out of this
    pre-migration state.

    Returns ``(keep_id, delete_id, name)``. The KEEP row gets one of
    each FK-table row attached; the DELETE row gets two of each. After
    the merge the KEEP row should own all three of each.
    """
    name = "scribemd"
    keep_id = str(uuid.uuid4())
    delete_id = str(uuid.uuid4())

    with Session(sync_engine) as s:
        keep_org = Organization(id=keep_id, name=name)
        delete_org = Organization(id=delete_id, name=name)
        s.add_all([keep_org, delete_org])
        s.flush()

        # ChainState on both — the merge deletes the loser's chain_state.
        s.add(ChainState(org_id=keep_id))
        s.add(ChainState(org_id=delete_id))

        # API key on the keep side, plus two on the delete side that
        # will be re-pointed. ``key_hash`` is unique so we vary the
        # values.
        s.add(APIKey(
            org_id=keep_id, key_hash="hash-keep-1",
            key_prefix="al_test_keep1", name="k-keep",
        ))
        s.add(APIKey(
            org_id=delete_id, key_hash="hash-del-1",
            key_prefix="al_test_del1", name="k-del-1",
        ))
        s.add(APIKey(
            org_id=delete_id, key_hash="hash-del-2",
            key_prefix="al_test_del2", name="k-del-2",
        ))

        # Customers on both sides — different tenant_ids so the
        # (org_id, tenant_id) uniqueness doesn't bite us.
        s.add(Customer(org_id=keep_id, tenant_id="cust-keep-1"))
        s.add(Customer(org_id=delete_id, tenant_id="cust-del-1"))
        s.add(Customer(org_id=delete_id, tenant_id="cust-del-2"))

        s.commit()

    return keep_id, delete_id, name


def test_dedupe_happy_path_merges_fks(sync_engine, two_dup_orgs):
    keep_id, delete_id, name = two_dup_orgs

    rc = dedupe_orgs(
        sync_engine, name=name, keep=keep_id, dry_run=False, out=io.StringIO()
    )
    assert rc == 0

    # Exactly one organization row left with that name, and it's the
    # one we kept.
    with sync_engine.connect() as conn:
        rows = conn.execute(
            text("SELECT id FROM organizations WHERE name=:n"), {"n": name}
        ).fetchall()
        assert [r[0] for r in rows] == [keep_id]

        # The losing chain_state is gone; the keep row's chain_state
        # survives.
        cs_rows = conn.execute(
            text("SELECT org_id FROM chain_state WHERE org_id IN (:k, :d)"),
            {"k": keep_id, "d": delete_id},
        ).fetchall()
        assert [r[0] for r in cs_rows] == [keep_id]

        # API keys: keep side now owns all three (1 native + 2 merged).
        ak_count = conn.execute(
            text("SELECT COUNT(*) FROM api_keys WHERE org_id=:k"),
            {"k": keep_id},
        ).scalar_one()
        assert ak_count == 3

        # Customers: keep side now owns all three.
        cust_count = conn.execute(
            text("SELECT COUNT(*) FROM customers WHERE org_id=:k"),
            {"k": keep_id},
        ).scalar_one()
        assert cust_count == 3

        # And the loser has no surviving children anywhere — sanity.
        for table in ("api_keys", "customers", "chain_state"):
            cnt = conn.execute(
                text(f"SELECT COUNT(*) FROM {table} WHERE org_id=:d"),
                {"d": delete_id},
            ).scalar_one()
            assert cnt == 0, f"loser still owns rows in {table}"


def test_dedupe_dry_run_does_not_mutate(sync_engine, two_dup_orgs):
    keep_id, delete_id, name = two_dup_orgs

    buf = io.StringIO()
    rc = dedupe_orgs(
        sync_engine, name=name, keep=keep_id, dry_run=True, out=buf
    )
    assert rc == 0

    # Output contains BEGIN/COMMIT envelope + UPDATE/DELETE skeletons.
    out = buf.getvalue()
    assert "BEGIN;" in out and "COMMIT;" in out
    assert f"UPDATE api_keys SET org_id='{keep_id}' WHERE org_id='{delete_id}';" in out
    assert f"DELETE FROM organizations WHERE id='{delete_id}';" in out

    # Database unchanged: both orgs still present.
    with sync_engine.connect() as conn:
        rows = conn.execute(
            text("SELECT id FROM organizations WHERE name=:n ORDER BY id"),
            {"n": name},
        ).fetchall()
        assert {r[0] for r in rows} == {keep_id, delete_id}


def test_dedupe_refuses_when_only_one_row(sync_engine):
    """A name with only one row is a no-op — refuse loudly."""
    only_id = str(uuid.uuid4())
    with Session(sync_engine) as s:
        s.add(Organization(id=only_id, name="solo-org"))
        s.commit()

    buf = io.StringIO()
    rc = dedupe_orgs(
        sync_engine, name="solo-org", keep=only_id, dry_run=False, out=buf
    )
    assert rc == 2
    assert "only one organization" in buf.getvalue()


def test_dedupe_refuses_when_no_match(sync_engine):
    buf = io.StringIO()
    rc = dedupe_orgs(
        sync_engine,
        name="nope-not-here",
        keep=str(uuid.uuid4()),
        dry_run=False,
        out=buf,
    )
    assert rc == 2
    assert "no organizations" in buf.getvalue()


def test_dedupe_refuses_when_keep_not_in_matches(sync_engine, two_dup_orgs):
    keep_id, delete_id, name = two_dup_orgs
    bogus = str(uuid.uuid4())

    buf = io.StringIO()
    rc = dedupe_orgs(
        sync_engine, name=name, keep=bogus, dry_run=False, out=buf
    )
    assert rc == 2
    msg = buf.getvalue()
    assert "is not among the matching org ids" in msg
    # The candidates list should appear so the operator can copy/paste
    # the correct id.
    assert keep_id in msg and delete_id in msg


def test_argparse_main_rejects_missing_name(monkeypatch, capsys):
    # ``argparse`` exits 2 with a usage line when required args are
    # missing; make sure our parser wiring is well-formed.
    with pytest.raises(SystemExit) as exc:
        main(["orgs", "dedupe", "--keep=anything"])
    assert exc.value.code == 2
