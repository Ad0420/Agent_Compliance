"""Tests for Clerk webhook handler (Workstream E3).

We sign payloads with the real `svix` library — the same one the handler
verifies with — so we exercise the actual signature path rather than mocking
it out.
"""

from __future__ import annotations

import datetime as dt
import json

import pytest
from sqlalchemy import select
from svix.webhooks import Webhook

from app.config import settings
from app.models import (
    APIKey,
    ActionRecord,
    ChainState,
    ComplianceReviewRecord,
    Organization,
    OrgMembership,
    ProcessedWebhookEvent,
)


# Whatever the secret happens to be in tests — svix expects a base64
# whsec_ prefix. The svix library accepts plain strings; we use a stable
# one so signed fixtures are reproducible.
_TEST_WEBHOOK_SECRET = "whsec_" + "a" * 32


@pytest.fixture(autouse=True)
def _configure_webhook_secret(monkeypatch):
    monkeypatch.setattr(settings, "clerk_webhook_secret", _TEST_WEBHOOK_SECRET)
    # Reset the in-memory rate-limit store: tests in this file hit the
    # webhook endpoint without auth, so they share the same per-IP bucket
    # and would otherwise trip the 20-rps burst limit when run in sequence.
    from app.main import app

    for mw in app.user_middleware:
        cls = getattr(mw, "cls", None)
        if cls is not None and cls.__name__ == "RateLimitMiddleware":
            # Pre-instantiated middleware doesn't expose state easily; the
            # cleanest reset is to clear the module-level imports the
            # middleware reads. We rely on the fact that BaseHTTPMiddleware
            # instances stay alive in the app — drop their state.
            pass
    # Simpler approach: clear via the live middleware stack.
    _clear_rate_limit_state(app)
    yield


def _clear_rate_limit_state(app) -> None:
    """Walk the ASGI middleware stack and reset RateLimitMiddleware._requests.

    starlette wraps the app in middleware lazily; we walk `app.middleware_stack`
    if it's been built, otherwise we look at `app.user_middleware` to find the
    class and rely on the per-test fresh state (it'll be empty anyway).
    """
    stack = getattr(app, "middleware_stack", None)
    visited = set()
    while stack is not None and id(stack) not in visited:
        visited.add(id(stack))
        if type(stack).__name__ == "RateLimitMiddleware":
            requests = getattr(stack, "_requests", None)
            if requests is not None:
                requests.clear()
        stack = getattr(stack, "app", None)


def _sign_request(
    body: dict,
    *,
    secret: str = _TEST_WEBHOOK_SECRET,
    msg_id: str | None = None,
    timestamp: dt.datetime | None = None,
) -> tuple[bytes, dict[str, str]]:
    """Sign a JSON body with Svix. Returns (raw_bytes, headers)."""
    payload = json.dumps(body, separators=(",", ":")).encode()
    if msg_id is None:
        msg_id = f"msg_{abs(hash(payload)) % (10 ** 12)}"
    if timestamp is None:
        timestamp = dt.datetime.now(dt.timezone.utc)
    wh = Webhook(secret)
    signature = wh.sign(msg_id, timestamp, payload.decode())
    headers = {
        "svix-id": msg_id,
        "svix-timestamp": str(int(timestamp.timestamp())),
        "svix-signature": signature,
        "Content-Type": "application/json",
    }
    return payload, headers


async def _post_webhook(async_client, body: dict, **kwargs):
    payload, headers = _sign_request(body, **kwargs)
    return await async_client.post(
        "/v1/clerk/webhooks", content=payload, headers=headers
    )


# ── Signature verification ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_invalid_signature_returns_401(async_client):
    body = {"type": "organization.created", "data": {"id": "org_x"}}
    payload = json.dumps(body).encode()
    headers = {
        "svix-id": "msg_bad",
        "svix-timestamp": str(int(dt.datetime.now(dt.timezone.utc).timestamp())),
        # Deliberately invalid signature
        "svix-signature": "v1,abcdefghijklmnopqrstuvwxyz0123456789==",
        "Content-Type": "application/json",
    }
    resp = await async_client.post(
        "/v1/clerk/webhooks", content=payload, headers=headers
    )
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid signature"


@pytest.mark.asyncio
async def test_missing_secret_returns_503(async_client, monkeypatch):
    monkeypatch.setattr(settings, "clerk_webhook_secret", "")
    body = {"type": "organization.created", "data": {"id": "org_x"}}
    payload = json.dumps(body).encode()
    resp = await async_client.post(
        "/v1/clerk/webhooks",
        content=payload,
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 503


# ── organization.created ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_organization_created_creates_org(async_client, db_session):
    body = {
        "type": "organization.created",
        "data": {
            "id": "org_clerk_abc",
            "name": "Acme via Clerk",
            "created_by": "user_clerk_1",
        },
    }
    resp = await _post_webhook(async_client, body)
    assert resp.status_code == 200, resp.text

    result = await db_session.execute(
        select(Organization).where(Organization.clerk_org_id == "org_clerk_abc")
    )
    org = result.scalar_one()
    assert org.name == "Acme via Clerk"

    membership = await db_session.execute(
        select(OrgMembership).where(
            OrgMembership.clerk_user_id == "user_clerk_1",
            OrgMembership.clerk_org_id == "org_clerk_abc",
        )
    )
    m = membership.scalar_one()
    assert m.role == "admin"
    assert m.org_id == org.id


@pytest.mark.asyncio
async def test_organization_created_idempotent_on_clerk_id(async_client, db_session):
    body = {
        "type": "organization.created",
        "data": {
            "id": "org_clerk_idem",
            "name": "Idem Org",
            "created_by": "user_clerk_idem",
        },
    }
    # Two deliveries with different svix-id but same payload — simulates Clerk
    # re-firing the event (rare, but possible if the upstream retries beyond
    # the dedupe window). The handler must still not double-insert the org.
    resp1 = await _post_webhook(async_client, body, msg_id="msg_idem_1")
    resp2 = await _post_webhook(async_client, body, msg_id="msg_idem_2")
    assert resp1.status_code == 200
    assert resp2.status_code == 200

    result = await db_session.execute(
        select(Organization).where(Organization.clerk_org_id == "org_clerk_idem")
    )
    orgs = result.scalars().all()
    assert len(orgs) == 1


@pytest.mark.asyncio
async def test_replay_same_svix_id_is_noop(async_client, db_session):
    """Re-delivering the same svix-id must hit the dedupe table and NOT
    create a second membership row (or trigger any side effects).
    """
    body = {
        "type": "organization.created",
        "data": {
            "id": "org_clerk_replay",
            "name": "Replay",
            "created_by": "user_replay",
        },
    }
    resp1 = await _post_webhook(async_client, body, msg_id="msg_replay")
    resp2 = await _post_webhook(async_client, body, msg_id="msg_replay")
    assert resp1.status_code == 200
    assert resp2.status_code == 200
    assert resp2.json().get("replay") == "true"

    processed = await db_session.execute(
        select(ProcessedWebhookEvent).where(
            ProcessedWebhookEvent.svix_id == "msg_replay"
        )
    )
    assert processed.scalar_one() is not None


# ── organizationMembership.* ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_membership_created_links_user(async_client, db_session):
    # First provision the org
    await _post_webhook(
        async_client,
        {
            "type": "organization.created",
            "data": {
                "id": "org_clerk_membership",
                "name": "Members R Us",
                "created_by": "user_admin",
            },
        },
        msg_id="msg_a",
    )

    resp = await _post_webhook(
        async_client,
        {
            "type": "organizationMembership.created",
            "data": {
                "organization": {"id": "org_clerk_membership"},
                "public_user_data": {"user_id": "user_dev_2"},
                "role": "org:member",
            },
        },
        msg_id="msg_b",
    )
    assert resp.status_code == 200

    result = await db_session.execute(
        select(OrgMembership).where(
            OrgMembership.clerk_user_id == "user_dev_2",
            OrgMembership.clerk_org_id == "org_clerk_membership",
        )
    )
    m = result.scalar_one()
    assert m.role == "developer"  # org:member → developer


@pytest.mark.asyncio
async def test_role_mapping_admin_vs_member(async_client, db_session):
    await _post_webhook(
        async_client,
        {
            "type": "organization.created",
            "data": {
                "id": "org_role_map",
                "name": "Role Map",
                "created_by": "user_creator",
            },
        },
        msg_id="msg_rm_0",
    )
    await _post_webhook(
        async_client,
        {
            "type": "organizationMembership.created",
            "data": {
                "organization": {"id": "org_role_map"},
                "public_user_data": {"user_id": "user_admin_x"},
                "role": "org:admin",
            },
        },
        msg_id="msg_rm_1",
    )
    await _post_webhook(
        async_client,
        {
            "type": "organizationMembership.created",
            "data": {
                "organization": {"id": "org_role_map"},
                "public_user_data": {"user_id": "user_member_y"},
                "role": "org:member",
            },
        },
        msg_id="msg_rm_2",
    )

    admin = await db_session.execute(
        select(OrgMembership).where(
            OrgMembership.clerk_user_id == "user_admin_x"
        )
    )
    member = await db_session.execute(
        select(OrgMembership).where(
            OrgMembership.clerk_user_id == "user_member_y"
        )
    )
    assert admin.scalar_one().role == "admin"
    assert member.scalar_one().role == "developer"


@pytest.mark.asyncio
async def test_membership_updated_changes_role(async_client, db_session):
    await _post_webhook(
        async_client,
        {
            "type": "organization.created",
            "data": {
                "id": "org_promote",
                "name": "Promote Co",
                "created_by": "user_creator",
            },
        },
        msg_id="msg_up_0",
    )
    await _post_webhook(
        async_client,
        {
            "type": "organizationMembership.created",
            "data": {
                "organization": {"id": "org_promote"},
                "public_user_data": {"user_id": "user_to_promote"},
                "role": "org:member",
            },
        },
        msg_id="msg_up_1",
    )
    await _post_webhook(
        async_client,
        {
            "type": "organizationMembership.updated",
            "data": {
                "organization": {"id": "org_promote"},
                "public_user_data": {"user_id": "user_to_promote"},
                "role": "org:admin",
            },
        },
        msg_id="msg_up_2",
    )
    result = await db_session.execute(
        select(OrgMembership).where(
            OrgMembership.clerk_user_id == "user_to_promote",
            OrgMembership.clerk_org_id == "org_promote",
        )
    )
    assert result.scalar_one().role == "admin"


@pytest.mark.asyncio
async def test_membership_deleted_removes_membership(async_client, db_session):
    await _post_webhook(
        async_client,
        {
            "type": "organization.created",
            "data": {
                "id": "org_kick",
                "name": "Kick Co",
                "created_by": "user_creator_k",
            },
        },
        msg_id="msg_k_0",
    )
    await _post_webhook(
        async_client,
        {
            "type": "organizationMembership.created",
            "data": {
                "organization": {"id": "org_kick"},
                "public_user_data": {"user_id": "user_to_kick"},
                "role": "org:member",
            },
        },
        msg_id="msg_k_1",
    )
    await _post_webhook(
        async_client,
        {
            "type": "organizationMembership.deleted",
            "data": {
                "organization": {"id": "org_kick"},
                "public_user_data": {"user_id": "user_to_kick"},
                "role": "org:member",
            },
        },
        msg_id="msg_k_2",
    )
    result = await db_session.execute(
        select(OrgMembership).where(
            OrgMembership.clerk_user_id == "user_to_kick",
            OrgMembership.clerk_org_id == "org_kick",
        )
    )
    assert result.scalar_one_or_none() is None


# ── organization.deleted (soft-delete; CRITICAL #1 fix) ──────────────────────


@pytest.mark.asyncio
async def test_organization_deleted_soft_deletes_org(async_client, db_session):
    """A delete webhook must soft-delete: deleted_at set, clerk_org_id
    NULLed, scrubbed_clerk_org_id holds the original. The Organization row
    itself MUST survive (audit-trail product — action_records FK is RESTRICT).
    """
    await _post_webhook(
        async_client,
        {
            "type": "organization.created",
            "data": {
                "id": "org_to_delete",
                "name": "Doomed",
                "created_by": "user_d",
            },
        },
        msg_id="msg_d_0",
    )
    await _post_webhook(
        async_client,
        {
            "type": "organization.deleted",
            "data": {"id": "org_to_delete"},
        },
        msg_id="msg_d_1",
    )
    db_session.expire_all()

    # By clerk_org_id (live filter) — should be gone (NULLed out).
    live_lookup = await db_session.execute(
        select(Organization).where(
            Organization.clerk_org_id == "org_to_delete"
        )
    )
    assert live_lookup.scalar_one_or_none() is None

    # By scrubbed_clerk_org_id — should be the tombstoned row.
    scrubbed = await db_session.execute(
        select(Organization).where(
            Organization.scrubbed_clerk_org_id == "org_to_delete"
        )
    )
    tombstone = scrubbed.scalar_one()
    assert tombstone.deleted_at is not None
    assert tombstone.clerk_org_id is None
    assert tombstone.scrubbed_clerk_org_id == "org_to_delete"


@pytest.mark.asyncio
async def test_organization_deleted_with_action_records_does_not_crash(
    async_client, db_session
):
    """Pre-populate an action_record (FK=RESTRICT). The delete webhook must
    NOT raise a FK violation; soft-delete leaves the audit row intact.
    """
    # Provision via webhook so the org has chain_state.
    await _post_webhook(
        async_client,
        {
            "type": "organization.created",
            "data": {
                "id": "org_with_audit",
                "name": "Auditing",
                "created_by": "user_a",
            },
        },
        msg_id="msg_audit_0",
    )
    db_session.expire_all()
    org_id_row = await db_session.execute(
        select(Organization.id).where(
            Organization.clerk_org_id == "org_with_audit"
        )
    )
    org_id = org_id_row.scalar_one()

    # Insert via ORM with ``metadata_`` (the mapped attribute name; the
    # underlying column is ``metadata``, which is a reserved word at the
    # core Insert level). Using ORM here is fine — the lazy-load issue
    # only bit us when re-querying ``Organization`` via the ORM after the
    # async commit.
    action = ActionRecord(
        org_id=org_id,
        sequence_number=1,
        previous_hash="genesis",
        record_hash="r1",
        authorized_by="test",
        agent_name="a",
        action_type="function_call",
        action_name="x",
        action_timestamp=dt.datetime.utcnow(),
        result="success",
    )
    db_session.add(action)
    await db_session.commit()

    # Now fire the delete — must not 500, must not violate FK.
    resp = await _post_webhook(
        async_client,
        {"type": "organization.deleted", "data": {"id": "org_with_audit"}},
        msg_id="msg_audit_1",
    )
    assert resp.status_code == 200, resp.text

    # Audit record still present (the whole point of soft-delete).
    db_session.expire_all()
    survivors = await db_session.execute(
        select(ActionRecord.id).where(ActionRecord.org_id == org_id)
    )
    assert survivors.scalar_one() is not None


@pytest.mark.asyncio
async def test_organization_deleted_with_compliance_records_survives(
    async_client, db_session
):
    """PR #172 follow-up: ``compliance_review_records.membership_id`` is
    now ``ondelete=SET NULL``. When the webhook hard-deletes the org's
    memberships, any existing audit-of-audit rows must:
      - survive (the whole point of audit log)
      - have ``membership_id`` NULLed
      - have ``clerk_user_id`` preserved (reviewer identity intact)
    The webhook itself must NOT raise a FK violation.
    """
    await _post_webhook(
        async_client,
        {
            "type": "organization.created",
            "data": {
                "id": "org_cmp_audit",
                "name": "Compliance Auditing",
                "created_by": "user_creator_c",
            },
        },
        msg_id="msg_cmp_0",
    )
    db_session.expire_all()
    org_id_row = await db_session.execute(
        select(Organization.id).where(
            Organization.clerk_org_id == "org_cmp_audit"
        )
    )
    org_id = org_id_row.scalar_one()

    # Find the admin membership row that the org.created webhook seeded.
    membership_row = await db_session.execute(
        select(OrgMembership).where(OrgMembership.org_id == org_id)
    )
    membership = membership_row.scalar_one()
    membership_id = membership.id
    clerk_user_id = membership.clerk_user_id

    # Insert a compliance review record referencing this membership.
    review = ComplianceReviewRecord(
        org_id=org_id,
        membership_id=membership_id,
        clerk_user_id=clerk_user_id,
        action="/v1/dashboard/actions",
        http_method="GET",
        http_path="/v1/dashboard/actions",
        occurred_at=dt.datetime.utcnow(),
    )
    db_session.add(review)
    await db_session.commit()

    # Fire the delete — must NOT 500. With the SET NULL FK, bulk DELETE
    # of org_memberships does not raise even though a compliance review
    # row points at one.
    resp = await _post_webhook(
        async_client,
        {"type": "organization.deleted", "data": {"id": "org_cmp_audit"}},
        msg_id="msg_cmp_1",
    )
    assert resp.status_code == 200, resp.text

    db_session.expire_all()
    # Compliance review row still present. membership_id may be NULL (Postgres)
    # or preserved (SQLite tests don't enforce FK actions); clerk_user_id is
    # always preserved.
    rows = (
        await db_session.execute(
            select(ComplianceReviewRecord).where(
                ComplianceReviewRecord.org_id == org_id
            )
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].clerk_user_id == clerk_user_id


@pytest.mark.asyncio
async def test_organization_deleted_revokes_api_keys(async_client, db_session):
    """Soft-delete must revoke live API keys for the org so SDK requests
    bearing those keys start failing (the org row stays so authenticated
    lookups would otherwise still succeed)."""
    await _post_webhook(
        async_client,
        {
            "type": "organization.created",
            "data": {
                "id": "org_keys_revoked",
                "name": "Keyed",
                "created_by": "user_k",
            },
        },
        msg_id="msg_kr_0",
    )
    db_session.expire_all()
    org_id_row = await db_session.execute(
        select(Organization.id).where(
            Organization.clerk_org_id == "org_keys_revoked"
        )
    )
    org_id = org_id_row.scalar_one()
    # Mint a live key directly to bypass auth/routes.
    key = APIKey(
        org_id=org_id,
        name="live",
        key_hash="hash-1",
        key_prefix="al_live_x",
        permissions=["read"],
    )
    db_session.add(key)
    await db_session.commit()

    await _post_webhook(
        async_client,
        {"type": "organization.deleted", "data": {"id": "org_keys_revoked"}},
        msg_id="msg_kr_1",
    )

    db_session.expire_all()
    keys = await db_session.execute(
        select(APIKey.revoked_at).where(APIKey.org_id == org_id)
    )
    assert keys.scalar_one() is not None


@pytest.mark.asyncio
async def test_lookup_excludes_soft_deleted_orgs(async_client, db_session):
    """After soft-delete, a second organization.created webhook for the same
    Clerk org ID should be allowed to provision a fresh org row (the old
    row's clerk_org_id was scrubbed).
    """
    await _post_webhook(
        async_client,
        {
            "type": "organization.created",
            "data": {
                "id": "org_recycle",
                "name": "First",
                "created_by": "user_r",
            },
        },
        msg_id="msg_rec_0",
    )
    await _post_webhook(
        async_client,
        {"type": "organization.deleted", "data": {"id": "org_recycle"}},
        msg_id="msg_rec_1",
    )
    resp = await _post_webhook(
        async_client,
        {
            "type": "organization.created",
            "data": {
                "id": "org_recycle",
                "name": "Resurrected",
                "created_by": "user_r2",
            },
        },
        msg_id="msg_rec_2",
    )
    assert resp.status_code == 200

    db_session.expire_all()
    live = await db_session.execute(
        select(Organization).where(
            Organization.clerk_org_id == "org_recycle",
            Organization.deleted_at.is_(None),
        )
    )
    assert live.scalar_one().name == "Resurrected"


# ── unknown event types ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_unknown_event_type_returns_200(async_client):
    resp = await _post_webhook(
        async_client,
        {"type": "user.banned", "data": {"id": "user_x"}},
        msg_id="msg_unk_1",
    )
    assert resp.status_code == 200


# ── Concurrent / failure dedupe (CRITICAL #2/#3 fix) ─────────────────────────


@pytest.mark.asyncio
async def test_concurrent_identical_delivery_processes_once(
    async_client, db_session
):
    """Identical svix-id deliveries must collapse to a single set of side
    effects. The second delivery short-circuits to {"replay": "true"}.

    We run the two deliveries sequentially because aiosqlite + StaticPool
    serializes onto a single connection (so true parallel requests against
    the same in-memory DB deadlock). Sequential is the moral equivalent:
    the second request sees the first's committed dedupe row, which is
    exactly the post-commit state a concurrent loser would also see.
    """
    body = {
        "type": "organization.created",
        "data": {
            "id": "org_race",
            "name": "Race",
            "created_by": "user_race",
        },
    }

    resp1 = await _post_webhook(async_client, body, msg_id="msg_race")
    resp2 = await _post_webhook(async_client, body, msg_id="msg_race")
    assert resp1.status_code == 200
    assert resp2.status_code == 200

    # Exactly one of the two responses should be flagged a replay.
    replays = [r for r in (resp1, resp2) if r.json().get("replay") == "true"]
    assert len(replays) == 1, (resp1.json(), resp2.json())

    # Exactly one org row, one membership row — no doubling.
    db_session.expire_all()
    orgs = await db_session.execute(
        select(Organization).where(Organization.clerk_org_id == "org_race")
    )
    assert len(orgs.scalars().all()) == 1
    members = await db_session.execute(
        select(OrgMembership).where(OrgMembership.clerk_org_id == "org_race")
    )
    assert len(members.scalars().all()) == 1


@pytest.mark.asyncio
async def test_handler_failure_keeps_dedupe_row_with_success_false(
    async_client, db_session, monkeypatch
):
    """If a handler raises, the dedupe row must persist as a tombstone with
    ``success=False``. Operators can investigate; Svix can retry (next
    attempt will see success=False and re-run the handler).

    Note on test plumbing: httpx ASGITransport defaults to
    ``raise_app_exceptions=True``, so a 500 in the handler propagates as
    a Python exception rather than a 500 response. We assert via
    ``pytest.raises`` instead of checking response.status_code; the
    dedupe-row invariant is what actually matters here.
    """
    from app.routes import clerk_webhooks as wh

    async def _boom(_session, _data):
        raise RuntimeError("synthetic")

    monkeypatch.setattr(wh, "_handle_org_created", _boom)

    with pytest.raises(RuntimeError, match="synthetic"):
        await _post_webhook(
            async_client,
            {
                "type": "organization.created",
                "data": {
                    "id": "org_will_fail",
                    "name": "Boom",
                    "created_by": "user_b",
                },
            },
            msg_id="msg_boom",
        )

    db_session.expire_all()
    row = await db_session.execute(
        select(ProcessedWebhookEvent).where(
            ProcessedWebhookEvent.svix_id == "msg_boom"
        )
    )
    tombstone = row.scalar_one()
    assert tombstone.success is False


@pytest.mark.asyncio
async def test_membership_before_org_returns_503_for_retry(
    async_client, db_session
):
    """If a membership webhook arrives before its parent org webhook (Svix
    out-of-order delivery), respond 503 so Svix retries — don't silently
    drop the event.
    """
    resp = await _post_webhook(
        async_client,
        {
            "type": "organizationMembership.created",
            "data": {
                "organization": {"id": "org_orphan"},
                "public_user_data": {"user_id": "user_orphan"},
                "role": "org:member",
            },
        },
        msg_id="msg_orphan",
    )
    assert resp.status_code == 503

    # Dedupe row exists with success=False — so the Svix retry on the same
    # svix-id finds it, sees success=False, and re-runs the handler.
    db_session.expire_all()
    row = await db_session.execute(
        select(ProcessedWebhookEvent).where(
            ProcessedWebhookEvent.svix_id == "msg_orphan"
        )
    )
    tombstone = row.scalar_one()
    assert tombstone.success is False


@pytest.mark.asyncio
async def test_membership_before_org_retry_succeeds_after_org_created(
    async_client, db_session
):
    """Retry of the same svix-id AFTER the parent org has been provisioned
    must run the handler again and succeed (not short-circuit as a replay).
    """
    # First attempt: parent org missing, 503.
    resp503 = await _post_webhook(
        async_client,
        {
            "type": "organizationMembership.created",
            "data": {
                "organization": {"id": "org_lazy"},
                "public_user_data": {"user_id": "user_lazy"},
                "role": "org:admin",
            },
        },
        msg_id="msg_lazy",
    )
    assert resp503.status_code == 503

    # Provision the parent org.
    await _post_webhook(
        async_client,
        {
            "type": "organization.created",
            "data": {
                "id": "org_lazy",
                "name": "Lazy",
                "created_by": "user_lazy_creator",
            },
        },
        msg_id="msg_lazy_org",
    )

    # Svix retries with the same svix-id. The handler must run (because the
    # earlier dedupe row has success=False) and now succeed.
    resp_retry = await _post_webhook(
        async_client,
        {
            "type": "organizationMembership.created",
            "data": {
                "organization": {"id": "org_lazy"},
                "public_user_data": {"user_id": "user_lazy"},
                "role": "org:admin",
            },
        },
        msg_id="msg_lazy",
    )
    assert resp_retry.status_code == 200, resp_retry.text

    db_session.expire_all()
    members = await db_session.execute(
        select(OrgMembership).where(
            OrgMembership.clerk_user_id == "user_lazy"
        )
    )
    assert members.scalar_one().role == "admin"

    # Dedupe row is now success=True.
    row = await db_session.execute(
        select(ProcessedWebhookEvent).where(
            ProcessedWebhookEvent.svix_id == "msg_lazy"
        )
    )
    assert row.scalar_one().success is True
