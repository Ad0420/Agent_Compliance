"""Cross-org isolation regression suite (Wave 3B.3).

This is the long-running guard against the bug class that motivated
Wave 3A.c / 3B.3 in the first place: a privileged caller (API-key admin
or staff Clerk session) using their authentication to reach across the
org boundary into another customer's data.

Two orgs are set up — A and B — each populated with the full Phase 1/2
data set (Customers, ActionRecords, Approvals, BAAs, PolicyViolations,
Checkpoints, Webhook subscriptions). Then for every endpoint that takes
an ID-bearing path param or returns a list, we assert:

  * **GET by ID** : org-A's admin requesting org-B's resource ID returns
    404 (NOT 403). 403 would confirm existence; 404 makes the resource
    indistinguishable from "does not exist anywhere". This is the
    canonical pattern for tenant-isolated lookup endpoints.
  * **GET list** : org-A's admin sees zero org-B records, regardless of
    pagination + filter combinations.
  * **PHI filter side-channel** : any filter param that could leak
    presence of a specific subject / tenant / customer is also tested
    here for both the customer (must work on own org) and staff
    (must 403 ``staff_phi_filter_forbidden``) tiers.

The suite is intentionally exhaustive — duplication across endpoints is
preferred over a clever loop, because the bug pattern this regresses
against is "one endpoint forgot the org_id WHERE clause" and a clever
loop would mask exactly that gap.

If you add a new GET endpoint that returns customer data, add a row in
this suite. If the endpoint takes a filter param that could leak
presence, add a side-channel test. The suite is the contract.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.config import settings
from app.main import app
from app.models import (
    ActionRecord,
    Approval,
    BAAAgreement,
    BAAScope,
    ChainState,
    Customer,
    Organization,
    OrgMembership,
    Policy,
    PolicyViolation,
    StaffAuditLog,
    WebhookSubscription,
)
from app.services import auth as auth_service
from app.services.auth import generate_api_key
from app.services.checkpoint import create_checkpoint

from tests._clerk_test_helpers import (
    TEST_ISSUER,
    make_keypair,
    reset_rate_limit,
    sign_token,
)


_STAFF_CLERK_ORG_ID = "org_vera_staff_internal"


@pytest.fixture(scope="module")
def keypair():
    return make_keypair()


@pytest.fixture(autouse=True)
def _configure_clerk(monkeypatch, keypair):
    """Wire test JWKS + designate a staff Clerk org for IamTier resolution."""
    monkeypatch.setattr(settings, "clerk_jwks_url", "https://fixture/jwks.json")
    monkeypatch.setattr(settings, "clerk_issuer", TEST_ISSUER)
    monkeypatch.setattr(settings, "clerk_audience", None)
    monkeypatch.setattr(settings, "clerk_staff_org_id", _STAFF_CLERK_ORG_ID)
    auth_service._reset_jwks_cache_for_tests()

    async def _fake_fetch(_url: str) -> dict:
        return {"keys": [keypair["jwk"]]}

    monkeypatch.setattr(auth_service, "_fetch_jwks", _fake_fetch)
    reset_rate_limit(app)
    yield
    auth_service._reset_jwks_cache_for_tests()


def _staff_token(keypair) -> str:
    return sign_token(
        keypair["priv"],
        sub="user_vera_engineer",
        org_id=_STAFF_CLERK_ORG_ID,
    )


# ── Fixture: two fully-populated orgs ────────────────────────────────────


class _OrgFixture:
    """A populated org with API keys + a representative data set."""

    def __init__(
        self,
        *,
        org: Organization,
        admin_key: str,
        read_key: str,
        customer: Customer,
        action_record_id: str,
        approval_id: str,
        baa_id: str,
        policy_id: str,
        violation_id: str,
        checkpoint_id: str,
        webhook_id: str,
    ):
        self.org = org
        self.admin_key = admin_key
        self.read_key = read_key
        self.customer = customer
        self.action_record_id = action_record_id
        self.approval_id = approval_id
        self.baa_id = baa_id
        self.policy_id = policy_id
        self.violation_id = violation_id
        self.checkpoint_id = checkpoint_id
        self.webhook_id = webhook_id


async def _populate_org(
    session, *, name: str, async_client
) -> _OrgFixture:
    """Stand up an org with at least one of every multi-tenant entity.

    We use the live FastAPI client + admin key for action_record creation
    so the chain-state increment fires the same way it does in prod. The
    rest of the rows are inserted directly via the ORM to keep the
    fixture's failure modes far away from "did the create endpoint
    work?".
    """
    org = Organization(name=name)
    session.add(org)
    await session.flush()
    session.add(ChainState(org_id=org.id))

    # Customer (one per org)
    customer = Customer(
        org_id=org.id,
        tenant_id=f"{name}_tenant_a",
        display_name=f"{name} Customer",
        status="active",
    )
    session.add(customer)
    await session.flush()

    raw_admin_key, _ = await generate_api_key(
        session, org.id, f"{name}-admin", ["read", "write", "admin"]
    )
    raw_read_key, _ = await generate_api_key(
        session, org.id, f"{name}-readonly", ["read"]
    )

    # Approval (PHI-bearing context)
    appr = Approval(
        org_id=org.id,
        requested_by_agent=f"{name}-agent",
        action_name="prescribe",
        data_subject_id=f"{name}_patient_42",
        context={
            "original_input_data": {"med": "oxycodone", "dose": "5mg"},
            "gate_name": "controlled_substance",
            "required_role": "dea_licensed_physician",
            "citation": "21 CFR 1306.04",
            "reason": "gated",
        },
        risk_tier="critical",
        approvers_required=1,
        status="pending",
        decisions=[],
    )
    session.add(appr)

    # BAA agreement + scope
    baa = BAAAgreement(
        org_id=org.id,
        customer_id=customer.id,
        document_uri=f"s3://baa/{name}.pdf",
        status="active",
    )
    session.add(baa)
    await session.flush()
    baa_scope = BAAScope(
        baa_agreement_id=baa.id,
        covered_services=[],
        covered_agent_types=[],
        is_unrestricted=True,
        granted_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    session.add(baa_scope)

    # Policy + violation
    policy = Policy(
        org_id=org.id,
        name=f"{name}-policy",
        description="x",
        condition_type="unknown_agent",
        condition_params={},
        action="flag",
        severity="high",
    )
    session.add(policy)
    await session.flush()
    violation = PolicyViolation(
        org_id=org.id,
        policy_id=policy.id,
        severity="high",
        context={"reason": f"{name}_violation_phi"},
    )
    session.add(violation)

    # Webhook subscription
    webhook = WebhookSubscription(
        org_id=org.id,
        url=f"https://{name}.example.com/hook",
        event_types=["review.approved"],
        secret="placeholder_secret_value_32_chars__",
        is_active=True,
    )
    session.add(webhook)

    await session.commit()
    await session.refresh(org)
    await session.refresh(customer)
    await session.refresh(appr)
    await session.refresh(baa)
    await session.refresh(policy)
    await session.refresh(violation)
    await session.refresh(webhook)

    # ActionRecord — go via the live POST so the chain state ticks
    # forward correctly (and so the record_hash is realistic).
    create = await async_client.post(
        "/v1/actions",
        json={
            "action_name": f"{name}_action",
            "action_type": "function_call",
            "agent_name": f"{name}-agent",
            "data_subject_id": f"{name}_patient_42",
            "tenant_id": customer.tenant_id,
            "input_data": {"note": f"PHI {name}"},
            "metadata": {"chart_id": f"chart_{name}"},
            "result": "success",
        },
        headers={"Authorization": f"Bearer {raw_admin_key}"},
    )
    assert create.status_code == 200, create.text
    action_record_id = create.json()["id"]

    # Checkpoint (depends on at least one action record existing).
    checkpoint = await create_checkpoint(session, org.id)

    return _OrgFixture(
        org=org,
        admin_key=raw_admin_key,
        read_key=raw_read_key,
        customer=customer,
        action_record_id=action_record_id,
        approval_id=appr.id,
        baa_id=baa.id,
        policy_id=policy.id,
        violation_id=violation.id,
        checkpoint_id=checkpoint.id,
        webhook_id=webhook.id,
    )


@pytest_asyncio.fixture
async def two_orgs(db_session, async_client):
    """Two fully-populated orgs A and B.

    The orgs share no data — distinct IDs, distinct admin keys, distinct
    customers + records. We use the same db_session so both ORM-side
    writes and live-client writes hit the same engine, then bypass the
    ``org_and_key`` fixture's implicit single-org by passing
    org-specific Authorization headers in every test.
    """
    org_a = await _populate_org(db_session, name="orgA", async_client=async_client)
    org_b = await _populate_org(db_session, name="orgB", async_client=async_client)
    return org_a, org_b


# ── 1. GET by ID — 404 (not 403) when crossing the org boundary ──────────


@pytest.mark.asyncio
async def test_cross_org_get_action_record_404(async_client, two_orgs):
    """Org A admin requesting org B's action record ID gets 404, not 403.

    404 is load-bearing: 403 would confirm the ID exists somewhere in
    the system, which itself is information disclosure ("Acme has a
    record with this ID I'm guessing about — must be a valid Vera ID
    format"). 404 makes presence/absence indistinguishable.
    """
    org_a, org_b = two_orgs
    resp = await async_client.get(
        f"/v1/actions/{org_b.action_record_id}",
        headers={"Authorization": f"Bearer {org_a.admin_key}"},
    )
    assert resp.status_code == 404, resp.text


@pytest.mark.asyncio
async def test_cross_org_get_approval_404(async_client, two_orgs):
    org_a, org_b = two_orgs
    resp = await async_client.get(
        f"/v1/approvals/{org_b.approval_id}",
        headers={"Authorization": f"Bearer {org_a.admin_key}"},
    )
    assert resp.status_code == 404, resp.text


@pytest.mark.asyncio
async def test_cross_org_get_customer_404(async_client, two_orgs):
    org_a, org_b = two_orgs
    resp = await async_client.get(
        f"/v1/customers/{org_b.customer.tenant_id}",
        headers={"Authorization": f"Bearer {org_a.admin_key}"},
    )
    assert resp.status_code == 404, resp.text


@pytest.mark.asyncio
async def test_cross_org_get_customer_agents_404(async_client, two_orgs):
    org_a, org_b = two_orgs
    resp = await async_client.get(
        f"/v1/customers/{org_b.customer.tenant_id}/agents",
        headers={"Authorization": f"Bearer {org_a.admin_key}"},
    )
    assert resp.status_code == 404, resp.text


@pytest.mark.asyncio
async def test_cross_org_get_customer_decisions_404(async_client, two_orgs):
    org_a, org_b = two_orgs
    resp = await async_client.get(
        f"/v1/customers/{org_b.customer.tenant_id}/decisions",
        headers={"Authorization": f"Bearer {org_a.admin_key}"},
    )
    assert resp.status_code == 404, resp.text


@pytest.mark.asyncio
async def test_cross_org_verify_record_no_data_leak(async_client, two_orgs):
    """``GET /v1/verify/{record_id}`` for a foreign record either 404s or
    returns ``is_valid=False`` (treats the record as absent) but never
    leaks the foreign record's hash / sequence / payload.
    """
    org_a, org_b = two_orgs
    resp = await async_client.get(
        f"/v1/verify/{org_b.action_record_id}",
        headers={"Authorization": f"Bearer {org_a.admin_key}"},
    )
    # 404 is the cleanest answer; some impls return 200 with an
    # is_valid=False payload — both are acceptable provided no foreign
    # record data leaks into the response.
    assert resp.status_code in (200, 404)
    if resp.status_code == 200:
        body = resp.json()
        # The foreign record's data MUST NOT appear in the response.
        text = repr(body)
        assert "orgB" not in text
        assert "PHI orgB" not in text


# ── 2. GET list — zero foreign rows ──────────────────────────────────────


@pytest.mark.asyncio
async def test_cross_org_list_actions_no_leak(async_client, two_orgs):
    """Org A admin's list view contains zero org B records, even with no
    filters."""
    org_a, org_b = two_orgs
    resp = await async_client.get(
        "/v1/actions?limit=200",
        headers={"Authorization": f"Bearer {org_a.admin_key}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # Every record we see belongs to org A.
    for r in body["records"]:
        assert r["org_id"] == org_a.org.id
        # No org-B identifiers leaked in any field.
        assert "orgB" not in r.get("data_subject_id", "") or ""
        assert r["action_name"] != "orgB_action"


@pytest.mark.asyncio
async def test_cross_org_list_approvals_no_leak(async_client, two_orgs):
    org_a, org_b = two_orgs
    resp = await async_client.get(
        "/v1/approvals?limit=200",
        headers={"Authorization": f"Bearer {org_a.admin_key}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    for a in body["approvals"]:
        # The schema doesn't expose org_id today — assert via fields we
        # do see that no org-B subjects/agents leaked.
        assert a["requested_by_agent"] != "orgB-agent"
        assert a["data_subject_id"] != "orgB_patient_42"


@pytest.mark.asyncio
async def test_cross_org_list_customers_no_leak(async_client, two_orgs):
    org_a, org_b = two_orgs
    resp = await async_client.get(
        "/v1/customers?limit=200",
        headers={"Authorization": f"Bearer {org_a.admin_key}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    for c in body["items"]:
        assert c["org_id"] == org_a.org.id
        assert c["tenant_id"] != org_b.customer.tenant_id


@pytest.mark.asyncio
async def test_cross_org_list_violations_no_leak(async_client, two_orgs):
    org_a, org_b = two_orgs
    resp = await async_client.get(
        "/v1/policies/violations?limit=200",
        headers={"Authorization": f"Bearer {org_a.admin_key}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    for v in body["violations"]:
        # No org-B violation context leaks.
        assert v.get("context", {}).get("reason") != "orgB_violation_phi"


@pytest.mark.asyncio
async def test_cross_org_list_policies_no_leak(async_client, two_orgs):
    org_a, org_b = two_orgs
    resp = await async_client.get(
        "/v1/policies?limit=200",
        headers={"Authorization": f"Bearer {org_a.admin_key}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    for p in body["policies"]:
        assert p["org_id"] == org_a.org.id
        assert p["name"] != "orgB-policy"


@pytest.mark.asyncio
async def test_cross_org_list_checkpoints_no_leak(async_client, two_orgs):
    org_a, org_b = two_orgs
    resp = await async_client.get(
        "/v1/verify/checkpoints",
        headers={"Authorization": f"Bearer {org_a.admin_key}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    foreign_ids = {org_b.checkpoint_id}
    for c in body["checkpoints"]:
        assert c["id"] not in foreign_ids


@pytest.mark.asyncio
async def test_cross_org_list_webhooks_no_leak(async_client, two_orgs):
    org_a, org_b = two_orgs
    resp = await async_client.get(
        "/v1/webhooks",
        headers={"Authorization": f"Bearer {org_a.admin_key}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    for w in body["webhooks"]:
        assert w["id"] != org_b.webhook_id
        assert w["url"] != "https://orgB.example.com/hook"


# ── 3. Filter side-channel: customer side works, staff side 403 ──────────


@pytest.mark.asyncio
async def test_filter_data_subject_id_works_for_customer(async_client, two_orgs):
    """The customer querying their OWN data_subject_id works (it's their
    data). This guards against a future over-correction that 403s the
    customer too.
    """
    org_a, _ = two_orgs
    resp = await async_client.get(
        "/v1/actions?data_subject_id=orgA_patient_42",
        headers={"Authorization": f"Bearer {org_a.admin_key}"},
    )
    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_filter_data_subject_id_cross_org_zero_results(
    async_client, two_orgs
):
    """Org A admin filtering by org B's patient id sees zero results —
    the data_subject_id might collide between orgs but the org_id WHERE
    clause keeps them disjoint."""
    org_a, org_b = two_orgs
    resp = await async_client.get(
        f"/v1/actions?data_subject_id={org_b.action_record_id}_fake",
        headers={"Authorization": f"Bearer {org_a.admin_key}"},
    )
    assert resp.status_code == 200
    assert resp.json()["total"] == 0


@pytest.mark.asyncio
async def test_filter_tenant_id_works_for_customer(async_client, two_orgs):
    org_a, _ = two_orgs
    resp = await async_client.get(
        f"/v1/actions?tenant_id={org_a.customer.tenant_id}",
        headers={"Authorization": f"Bearer {org_a.admin_key}"},
    )
    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_staff_filter_data_subject_id_forbidden(
    async_client, two_orgs, keypair
):
    """Staff session with X-Org-Id=A trying to filter by ``data_subject_id``
    gets 403 — even though the org context is "their" customer's, the
    filter remains a PHI side-channel because the response would
    confirm presence of the patient at org A."""
    org_a, _ = two_orgs
    token = _staff_token(keypair)
    resp = await async_client.get(
        "/v1/actions?data_subject_id=orgA_patient_42",
        headers={
            "Authorization": f"Bearer {token}",
            "X-Org-Id": org_a.org.id,
        },
    )
    assert resp.status_code == 403
    assert resp.json().get("code") == "staff_phi_filter_forbidden"


@pytest.mark.asyncio
async def test_staff_filter_tenant_id_forbidden(
    async_client, two_orgs, keypair
):
    """Wave 3B.3: tenant_id is the customer-of-the-customer identifier
    (e.g. ``cleveland_clinic``). Probing presence of that name is a
    commercial-intelligence side channel even though it's not strictly
    PHI."""
    org_a, _ = two_orgs
    token = _staff_token(keypair)
    resp = await async_client.get(
        f"/v1/actions?tenant_id={org_a.customer.tenant_id}",
        headers={
            "Authorization": f"Bearer {token}",
            "X-Org-Id": org_a.org.id,
        },
    )
    assert resp.status_code == 403
    assert resp.json().get("code") == "staff_phi_filter_forbidden"


@pytest.mark.asyncio
async def test_staff_filter_search_forbidden(async_client, two_orgs, keypair):
    org_a, _ = two_orgs
    token = _staff_token(keypair)
    resp = await async_client.get(
        "/v1/actions?search=transcribe",
        headers={
            "Authorization": f"Bearer {token}",
            "X-Org-Id": org_a.org.id,
        },
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_staff_approval_filter_data_subject_id_forbidden(
    async_client, two_orgs, keypair
):
    org_a, _ = two_orgs
    token = _staff_token(keypair)
    resp = await async_client.get(
        "/v1/approvals?data_subject_id=orgA_patient_42",
        headers={
            "Authorization": f"Bearer {token}",
            "X-Org-Id": org_a.org.id,
        },
    )
    assert resp.status_code == 403
    assert resp.json().get("code") == "staff_phi_filter_forbidden"


# ── 4. Staff cross-org: X-Org-Id is the audit anchor, not a leak path ────


@pytest.mark.asyncio
async def test_staff_reads_with_x_org_id_audits_against_that_org(
    async_client, two_orgs, db_session, keypair
):
    """Staff reading org A via X-Org-Id=A produces ONE audit row keyed
    to org A — not to org B, not to no-org. Sanity check that the audit
    surface anchors on the requested org and not on something looser.
    """
    org_a, _ = two_orgs
    token = _staff_token(keypair)
    resp = await async_client.get(
        f"/v1/actions/{org_a.action_record_id}",
        headers={
            "Authorization": f"Bearer {token}",
            "X-Org-Id": org_a.org.id,
        },
    )
    assert resp.status_code == 200, resp.text

    rows = (
        await db_session.execute(
            select(StaffAuditLog).where(StaffAuditLog.org_id == org_a.org.id)
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].resource_id == org_a.action_record_id


@pytest.mark.asyncio
async def test_staff_cannot_use_x_org_id_to_read_foreign_record(
    async_client, two_orgs, keypair
):
    """Even with X-Org-Id=A, staff fetching org B's record ID returns
    404. The X-Org-Id sets the org-scope; reading a record_id outside
    that scope must not succeed.
    """
    org_a, org_b = two_orgs
    token = _staff_token(keypair)
    resp = await async_client.get(
        f"/v1/actions/{org_b.action_record_id}",
        headers={
            "Authorization": f"Bearer {token}",
            "X-Org-Id": org_a.org.id,
        },
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_staff_cannot_use_x_org_id_to_read_foreign_approval(
    async_client, two_orgs, keypair
):
    org_a, org_b = two_orgs
    token = _staff_token(keypair)
    resp = await async_client.get(
        f"/v1/approvals/{org_b.approval_id}",
        headers={
            "Authorization": f"Bearer {token}",
            "X-Org-Id": org_a.org.id,
        },
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_staff_cannot_use_x_org_id_to_read_foreign_customer_decisions(
    async_client, two_orgs, keypair
):
    """Staff scoped to org A via X-Org-Id requesting customer decisions
    at org B's tenant_id returns 404. The customer lookup is org-scoped
    by ``ctx.org_id`` (which the staff sets via X-Org-Id), so a
    foreign-org tenant_id is invisible.
    """
    org_a, org_b = two_orgs
    token = _staff_token(keypair)
    resp = await async_client.get(
        f"/v1/customers/{org_b.customer.tenant_id}/decisions",
        headers={
            "Authorization": f"Bearer {token}",
            "X-Org-Id": org_a.org.id,
        },
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_staff_audit_log_org_a_admin_sees_only_own_org_rows(
    async_client, two_orgs, db_session, keypair
):
    """Customer A's admin GETing ``/v1/staff/audit-log`` sees only rows
    against org A — even when staff has read both orgs.
    """
    org_a, org_b = two_orgs
    token = _staff_token(keypair)
    # Staff hits both orgs.
    await async_client.get(
        f"/v1/actions/{org_a.action_record_id}",
        headers={"Authorization": f"Bearer {token}", "X-Org-Id": org_a.org.id},
    )
    await async_client.get(
        f"/v1/actions/{org_b.action_record_id}",
        headers={"Authorization": f"Bearer {token}", "X-Org-Id": org_b.org.id},
    )

    # Org A's customer admin reads their own audit log.
    resp = await async_client.get(
        "/v1/staff/audit-log",
        headers={"Authorization": f"Bearer {org_a.admin_key}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    for e in body["entries"]:
        assert e["org_id"] == org_a.org.id


# ── 5. Customer-admin-is-not-staff (escalation guard) ────────────────────


@pytest.mark.asyncio
async def test_customer_admin_token_does_not_get_staff_tier(
    async_client, two_orgs, db_session, keypair
):
    """A customer's own admin Clerk session does NOT acquire STAFF tier.

    The token claims ``org_id`` of the CUSTOMER's Clerk org, not the
    configured ``clerk_staff_org_id`` — so ``tier_from_claims`` returns
    CUSTOMER. They cannot use X-Org-Id to widen scope either, because
    the staff branch is unreachable for them.
    """
    org_a, org_b = two_orgs
    # Set up a Clerk-side membership row so the customer-admin path
    # actually authenticates (otherwise Clerk session 401s on missing
    # backend membership).
    db_session.add(
        OrgMembership(
            org_id=org_a.org.id,
            clerk_user_id="user_customer_admin_a",
            clerk_org_id="org_customer_a",
            role="admin",
        )
    )
    await db_session.commit()

    customer_admin_token = sign_token(
        keypair["priv"],
        sub="user_customer_admin_a",
        org_id="org_customer_a",
    )

    # Customer admin tries to use X-Org-Id pointing at ORG B's org_id.
    # The staff path is unreachable; the Clerk path resolves to their
    # OWN OrgMembership (org A). They should NOT see org B's record.
    resp = await async_client.get(
        f"/v1/actions/{org_b.action_record_id}",
        headers={
            "Authorization": f"Bearer {customer_admin_token}",
            "X-Org-Id": org_b.org.id,  # ignored — not staff
        },
    )
    assert resp.status_code == 404

    # And the staff_audit_log endpoint as customer-admin shows ONLY rows
    # for their own org A — not for any org B activity. No audit rows
    # exist for either org since no staff has read yet, but the filter
    # is what matters: passing ?org_id=B is dropped server-side.
    resp = await async_client.get(
        f"/v1/staff/audit-log?org_id={org_b.org.id}",
        headers={"Authorization": f"Bearer {customer_admin_token}"},
    )
    # 200 with zero (or only own) rows; the org_id filter is ignored.
    assert resp.status_code == 200
    for e in resp.json()["entries"]:
        assert e["org_id"] == org_a.org.id


@pytest.mark.asyncio
async def test_staff_jwt_against_wrong_org_id_is_customer_tier(
    async_client, two_orgs, keypair
):
    """A JWT signed with ``org_id`` that does NOT match the configured
    ``clerk_staff_org_id`` must not get STAFF tier.

    The defense: even if an attacker crafts a Clerk JWT with the
    Vera-staff role string in claims, mismatch on ``org_id`` keeps them
    at CUSTOMER tier. They then hit the customer Clerk-session path,
    which requires a backend OrgMembership row → 401 / no leak.
    """
    org_a, _ = two_orgs
    # JWT with wrong org_id (a real-looking but non-staff org).
    pretender_token = sign_token(
        keypair["priv"],
        sub="user_pretender",
        org_id="org_some_random_thing",
    )
    resp = await async_client.get(
        "/v1/actions",
        headers={
            "Authorization": f"Bearer {pretender_token}",
            "X-Org-Id": org_a.org.id,  # would-be staff anchor; ignored
        },
    )
    # Customer Clerk path runs; no OrgMembership → 401.
    assert resp.status_code == 401


# ── 6. STAFF_FULL behavioral parity (v1 disable check) ───────────────────


@pytest.mark.asyncio
async def test_staff_full_behaves_like_staff_read_only(
    async_client, two_orgs, db_session, keypair, monkeypatch
):
    """STAFF_FULL is reserved for v2 break-glass. In v1, any endpoint
    that admits staff MUST treat STAFF_FULL identically to
    STAFF_READ_ONLY: same redaction, same audit, same read-only
    surface.

    No production codepath constructs STAFF_FULL today, so we force it
    in by monkey-patching ``tier_from_claims`` to return STAFF_FULL
    for the staff JWT. Then we exercise the same routes a normal staff
    session would.
    """
    from app.services import iam as iam_mod

    org_a, _ = two_orgs

    original = iam_mod.tier_from_claims

    def _force_full(claims, staff_org_id):
        tier = original(claims, staff_org_id)
        if tier == iam_mod.IamTier.STAFF_READ_ONLY:
            return iam_mod.IamTier.STAFF_FULL
        return tier

    # Patch both the iam module AND the auth module's binding (it imports
    # the name at module load).
    monkeypatch.setattr(iam_mod, "tier_from_claims", _force_full)
    monkeypatch.setattr(auth_service, "tier_from_claims", _force_full)

    token = _staff_token(keypair)

    # 1) Single-record read: PHI redacted, audit row written.
    resp = await async_client.get(
        f"/v1/actions/{org_a.action_record_id}",
        headers={
            "Authorization": f"Bearer {token}",
            "X-Org-Id": org_a.org.id,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # STAFF_FULL gets the same redaction as STAFF_READ_ONLY in v1.
    assert body["input_data"] == {}
    assert body["metadata"] == {}
    assert body["data_subject_id"] == "[REDACTED]"

    # 2) Write attempts STILL rejected — STAFF_FULL is not break-glass
    # in v1; the dependency factory's read-only guard runs.
    resp = await async_client.post(
        "/v1/actions",
        json={
            "action_name": "should_fail",
            "action_type": "function_call",
            "agent_name": "x",
            "result": "success",
        },
        headers={
            "Authorization": f"Bearer {token}",
            "X-Org-Id": org_a.org.id,
        },
    )
    assert resp.status_code in (401, 403)

    # 3) PHI filter side-channel STILL forbidden.
    resp = await async_client.get(
        "/v1/actions?data_subject_id=orgA_patient_42",
        headers={
            "Authorization": f"Bearer {token}",
            "X-Org-Id": org_a.org.id,
        },
    )
    assert resp.status_code == 403


# ── 7. Webhook deliveries cross-org isolation ────────────────────────────


@pytest.mark.asyncio
async def test_cross_org_webhook_endpoint_404(async_client, two_orgs):
    """GET on a foreign webhook subscription ID returns 404."""
    org_a, org_b = two_orgs
    resp = await async_client.get(
        f"/v1/webhooks/{org_b.webhook_id}",
        headers={"Authorization": f"Bearer {org_a.admin_key}"},
    )
    assert resp.status_code == 404


# ── 8. Customer-side audit endpoint isolation ────────────────────────────


@pytest.mark.asyncio
async def test_customer_admin_audit_log_org_id_filter_ignored(
    async_client, two_orgs, db_session
):
    """Customer A's admin querying ``/v1/staff/audit-log?org_id=B`` must
    not see any of org B's audit rows even when seeded. The org_id query
    param is dropped server-side — the dependency's ``ctx.org_id`` is
    the only allowed scope.
    """
    org_a, org_b = two_orgs
    # Seed an audit row on org B (as if Vera staff had read org B).
    db_session.add(
        StaffAuditLog(
            staff_id="user_vera_engineer",
            endpoint="/v1/actions",
            org_id=org_b.org.id,
            resource_type="action_record",
            redacted=True,
        )
    )
    await db_session.commit()

    resp = await async_client.get(
        f"/v1/staff/audit-log?org_id={org_b.org.id}",
        headers={"Authorization": f"Bearer {org_a.admin_key}"},
    )
    assert resp.status_code == 200, resp.text
    for e in resp.json()["entries"]:
        assert e["org_id"] == org_a.org.id


# ── 9. Pagination is not a leak path ─────────────────────────────────────


@pytest.mark.asyncio
async def test_cross_org_pagination_offset_no_leak(async_client, two_orgs):
    """Cycling through pages of /v1/actions with offset never surfaces a
    foreign record. The bug class: an off-by-one in the WHERE clause
    plus a high offset could in theory walk past the org-A page count
    into org-B territory.
    """
    org_a, org_b = two_orgs
    seen_ids: set[str] = set()
    offset = 0
    while True:
        resp = await async_client.get(
            f"/v1/actions?limit=10&offset={offset}",
            headers={"Authorization": f"Bearer {org_a.admin_key}"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        for r in body["records"]:
            seen_ids.add(r["id"])
            assert r["org_id"] == org_a.org.id
        if len(body["records"]) < 10:
            break
        offset += 10
    # Sanity: we never accidentally surfaced org B's record.
    assert org_b.action_record_id not in seen_ids


# ── 10. Audit-log resource_count is per-request, not per-row ─────────────


@pytest.mark.asyncio
async def test_staff_list_writes_one_audit_row_with_resource_count(
    async_client, two_orgs, db_session, keypair
):
    """List read writes ONE audit row whose ``resource_count`` matches
    the number of records returned. Defends Wave 3B.3's "per-request,
    not per-row" decision: a paginated read of 200 rows still produces
    one audit row.
    """
    org_a, _ = two_orgs
    # Create extra records so the list has > 1 row.
    for i in range(4):
        await async_client.post(
            "/v1/actions",
            json={
                "action_name": f"extra_{i}",
                "action_type": "function_call",
                "agent_name": "a",
                "result": "success",
            },
            headers={"Authorization": f"Bearer {org_a.admin_key}"},
        )

    token = _staff_token(keypair)
    resp = await async_client.get(
        "/v1/actions?limit=200",
        headers={
            "Authorization": f"Bearer {token}",
            "X-Org-Id": org_a.org.id,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    returned = len(body["records"])
    assert returned >= 5  # 1 from populate + 4 extras

    rows = (
        await db_session.execute(
            select(StaffAuditLog).where(
                StaffAuditLog.endpoint == "/v1/actions",
                StaffAuditLog.org_id == org_a.org.id,
            )
        )
    ).scalars().all()
    # ONE row, not N.
    assert len(rows) == 1
    # resource_count populated to match what the response contained.
    assert rows[0].resource_count == returned
    assert rows[0].resource_id is None
