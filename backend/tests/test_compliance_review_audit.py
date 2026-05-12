"""Audit-of-audit dependency tests (Workstream F3)."""
from __future__ import annotations

from unittest.mock import patch

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.config import settings
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

    # Point AsyncSessionLocal at the test engine so the audit dependency's
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


@pytest.mark.asyncio
async def test_audit_captures_path_params_as_target(
    async_client, keypair, seeded_org, db_session
):
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
    assert rows[0].target_id == "patient-42"
    assert rows[0].http_path == "/v1/dashboard/data-subjects/patient-42"
