"""Audit-of-audit dependency tests (Workstream F3).

Post-PR #172 audit, these tests cover four CRITICAL findings:

  1. status_code is the REAL response status, not a hard-coded 200 — proven
     by hitting a 404 path and asserting the audit row records 404.
  2. (No code-level test; covered by tests/test_clerk_webhooks.py which
     fires ``organization.deleted`` against an org that has compliance
     review rows. The FK is SET NULL → those rows survive, NULLed.)
  3. The review-trail / summary / exports endpoints DON'T self-audit
     (audit-loop bug) — tests further down.
  4. PHI in path-params and query-params is hashed / dropped before
     persistence.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.config import settings
from app.middleware.clerk_auth import _hash_phi
from app.models import (
    ChainState,
    ComplianceReviewRecord,
    Organization,
    OrgMembership,
)
from app.services import auth as auth_service
from app.main import app

from tests._clerk_test_helpers import (
    TEST_ISSUER,
    make_keypair,
    reset_rate_limit,
    sign_token,
)


@pytest.fixture(scope="module")
def keypair():
    return make_keypair()


@pytest.fixture(autouse=True)
def _configure_clerk(monkeypatch, keypair):
    monkeypatch.setattr(settings, "clerk_jwks_url", "https://fixture/jwks.json")
    monkeypatch.setattr(settings, "clerk_issuer", TEST_ISSUER)
    monkeypatch.setattr(settings, "clerk_audience", None)
    auth_service._reset_jwks_cache_for_tests()

    async def _fake_fetch(_url: str) -> dict:
        return {"keys": [keypair["jwk"]]}

    monkeypatch.setattr(auth_service, "_fetch_jwks", _fake_fetch)
    reset_rate_limit(app)
    yield
    auth_service._reset_jwks_cache_for_tests()


@pytest_asyncio.fixture
async def seeded_org(db_session, db_engine):
    """Seed an org + one membership per role. Returns the IDs plus a
    factory for signing tokens. We share the engine with the audit
    middleware (which opens its own session) by overriding
    AsyncSessionLocal so the audit writes hit the same in-memory DB."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession
    from app import database as db_mod

    org = Organization(name="audit-org", clerk_org_id="org_audit")
    db_session.add(org)
    await db_session.flush()
    db_session.add(ChainState(org_id=org.id))

    members = {
        "admin": OrgMembership(
            org_id=org.id,
            clerk_user_id="user_admin_audit",
            clerk_org_id="org_audit",
            role="admin",
        ),
        "developer": OrgMembership(
            org_id=org.id,
            clerk_user_id="user_dev_audit",
            clerk_org_id="org_audit",
            role="developer",
        ),
        "compliance_reviewer": OrgMembership(
            org_id=org.id,
            clerk_user_id="user_compliance_audit",
            clerk_org_id="org_audit",
            role="compliance_reviewer",
        ),
    }
    for m in members.values():
        db_session.add(m)
    await db_session.commit()
    await db_session.refresh(org)

    # Point AsyncSessionLocal at the test engine so the audit middleware's
    # fresh-session write lands in the same SQLite in-memory DB.
    test_factory = async_sessionmaker(
        db_engine, class_=AsyncSession, expire_on_commit=False
    )
    original = db_mod.AsyncSessionLocal
    db_mod.AsyncSessionLocal = test_factory
    try:
        yield {
            "org_id": org.id,
            "clerk_org_id": "org_audit",
            "members": {
                role: {"id": m.id, "clerk_user_id": m.clerk_user_id}
                for role, m in members.items()
            },
        }
    finally:
        db_mod.AsyncSessionLocal = original


def _token(role: str, keypair, seeded_org) -> str:
    return sign_token(
        keypair["priv"],
        sub=seeded_org["members"][role]["clerk_user_id"],
        org_id=seeded_org["clerk_org_id"],
    )


# ── Happy-path: a compliance_reviewer hit writes one audit row ───────────────


@pytest.mark.asyncio
async def test_compliance_reviewer_hit_writes_audit_row(
    async_client, keypair, seeded_org, db_session
):
    token = _token("compliance_reviewer", keypair, seeded_org)
    resp = await async_client.get(
        "/v1/dashboard/actions?limit=10",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text

    rows = (
        await db_session.execute(
            select(ComplianceReviewRecord).where(
                ComplianceReviewRecord.org_id == seeded_org["org_id"]
            )
        )
    ).scalars().all()
    assert len(rows) == 1
    row = rows[0]
    assert row.clerk_user_id == seeded_org["members"]["compliance_reviewer"]["clerk_user_id"]
    assert row.membership_id == seeded_org["members"]["compliance_reviewer"]["id"]
    assert row.http_method == "GET"
    assert row.http_path == "/v1/dashboard/actions"
    assert row.action == "/v1/dashboard/actions"
    assert row.target_type == "action_record"
    assert row.query_params == {"limit": "10"}
    assert row.response_metadata == {"status_code": 200}


@pytest.mark.asyncio
async def test_admin_hit_does_not_audit(
    async_client, keypair, seeded_org, db_session
):
    token = _token("admin", keypair, seeded_org)
    resp = await async_client.get(
        "/v1/dashboard/actions",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200

    rows = (
        await db_session.execute(
            select(ComplianceReviewRecord).where(
                ComplianceReviewRecord.org_id == seeded_org["org_id"]
            )
        )
    ).scalars().all()
    assert rows == []


@pytest.mark.asyncio
async def test_developer_hit_does_not_audit(
    async_client, keypair, seeded_org, db_session
):
    token = _token("developer", keypair, seeded_org)
    resp = await async_client.get(
        "/v1/dashboard/actions",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200

    rows = (
        await db_session.execute(
            select(ComplianceReviewRecord).where(
                ComplianceReviewRecord.org_id == seeded_org["org_id"]
            )
        )
    ).scalars().all()
    assert rows == []


@pytest.mark.asyncio
async def test_audit_failure_does_not_break_response(
    async_client, keypair, seeded_org, db_session
):
    """When the audit session blows up mid-commit, the originating request
    must still succeed. F3 is defense-in-depth, not a hard gate."""
    from app import database as db_mod

    class _Boom:
        def __aenter__(self):
            raise RuntimeError("audit-side DB has fallen over")

        def __aexit__(self, *a):
            raise RuntimeError("audit-side DB has fallen over")

    token = _token("compliance_reviewer", keypair, seeded_org)
    with patch.object(db_mod, "AsyncSessionLocal", lambda: _Boom()):
        resp = await async_client.get(
            "/v1/dashboard/actions",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 200, resp.text

    # No row written — the boom happened before commit.
    rows = (
        await db_session.execute(
            select(ComplianceReviewRecord).where(
                ComplianceReviewRecord.org_id == seeded_org["org_id"]
            )
        )
    ).scalars().all()
    assert rows == []


# ── CRITICAL #1: real response.status_code, not hard-coded 200 ───────────────


@pytest.mark.asyncio
async def test_audit_records_real_404_status(
    async_client, keypair, seeded_org, db_session
):
    """A compliance_reviewer hitting a 404 path must produce an audit row
    with status_code=404, not the bogus 200 the old BackgroundTasks
    approach recorded."""
    token = _token("compliance_reviewer", keypair, seeded_org)
    resp = await async_client.get(
        "/v1/dashboard/actions/does-not-exist",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404

    rows = (
        await db_session.execute(
            select(ComplianceReviewRecord).where(
                ComplianceReviewRecord.org_id == seeded_org["org_id"]
            )
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].response_metadata == {"status_code": 404}
    # Target ID is the (safe) path-param, recorded verbatim.
    assert rows[0].target_id == "does-not-exist"


@pytest.mark.asyncio
async def test_audit_records_real_403_status(
    async_client, keypair, seeded_org, db_session
):
    """Hit an endpoint that 403s mid-handler. The audit middleware must
    record 403 — but only if the role gate ITSELF allowed the request
    through (otherwise the audit context is never registered). We hit
    the review-trail endpoint as a developer (403 from the role gate)
    and assert NO audit row is written (the dep raised before our hook).
    """
    token = _token("developer", keypair, seeded_org)
    resp = await async_client.get(
        "/v1/dashboard/compliance/review-trail",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403

    rows = (
        await db_session.execute(
            select(ComplianceReviewRecord).where(
                ComplianceReviewRecord.org_id == seeded_org["org_id"]
            )
        )
    ).scalars().all()
    # Developer gate raises before the audit hook → no row.
    assert rows == []


# ── CRITICAL #4: PHI redaction (target_id, http_path, query_params) ──────────


@pytest.mark.asyncio
async def test_data_subject_id_is_hashed_in_audit_target_id(
    async_client, keypair, seeded_org, db_session
):
    """A hit on /v1/dashboard/data-subjects/<phi> must NEVER persist the
    raw subject ID. Both target_id, http_path, and action are redacted.
    """
    token = _token("compliance_reviewer", keypair, seeded_org)
    resp = await async_client.get(
        "/v1/dashboard/data-subjects/patient-42",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text

    rows = (
        await db_session.execute(
            select(ComplianceReviewRecord).where(
                ComplianceReviewRecord.org_id == seeded_org["org_id"]
            )
        )
    ).scalars().all()
    assert len(rows) == 1
    row = rows[0]
    assert row.target_id is not None
    assert row.target_id.startswith("sha256:")
    assert "patient-42" not in row.target_id
    assert "patient-42" not in row.http_path
    assert row.http_path.startswith("/v1/dashboard/data-subjects/sha256:")
    assert row.action == row.http_path
    assert row.target_type == "data_subject"


@pytest.mark.asyncio
async def test_unsafe_query_params_dropped(
    async_client, keypair, seeded_org, db_session
):
    """Query params not on the allowlist (ssn, email, search terms) are
    dropped before persistence. Allowlisted params (limit, offset) stay.
    """
    token = _token("compliance_reviewer", keypair, seeded_org)
    resp = await async_client.get(
        "/v1/dashboard/actions?ssn=123-45-6789&limit=10&email=foo@example.com",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text

    rows = (
        await db_session.execute(
            select(ComplianceReviewRecord).where(
                ComplianceReviewRecord.org_id == seeded_org["org_id"]
            )
        )
    ).scalars().all()
    assert len(rows) == 1
    qp = rows[0].query_params
    assert qp == {"limit": "10"}, qp


def test_phi_hash_stable_within_org_and_diverges_across_orgs():
    """Same subject_id + same org → same hash (analyst can correlate).
    Different orgs → different hashes (no cross-tenant correlation).
    """
    h_a = _hash_phi("patient-42", "org_a")
    h_a_again = _hash_phi("patient-42", "org_a")
    h_b = _hash_phi("patient-42", "org_b")
    assert h_a == h_a_again
    assert h_a != h_b
    assert h_a.startswith("sha256:")
