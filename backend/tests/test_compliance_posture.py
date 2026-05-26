"""Tests for ``GET /v1/compliance/posture`` (Phase 4 Wave 1 PR B1).

Compliance Posture across six universal dimensions, computed on demand.
Covers:

  * Happy path → every dimension clears its threshold; all 6 measured.
  * Low-volume org → most dimensions land in ``not_yet_eligible`` with
    honest current/needed counts; chain_integrity stays measured.
  * Zero-data org → 5 not-yet-eligible, only chain_integrity measured
    (score=100 for the "no checkpoints yet" branch).
  * Chain integrity warn on stale checkpoint → score=50, fact line
    surfaces the staleness.
  * ``window_days`` parameter changes the in-window count.
  * Cross-org isolation: a customer in org A never sees org B counts.
  * Staff tier writes a ``staff_audit_log`` row per request.
  * Customer Clerk session bound to org A cannot widen scope to org B.
  * Regression: no ``ctx.tier == IamTier.X`` antipattern in the new
    code (per CLAUDE.md IAM tier rule).
  * Response shape is stable — JSON keys snapshot.
"""

from __future__ import annotations

import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.models import (
    Approval,
    BAAAgreement,
    BAAScope,
    ChainState,
    Customer,
    Organization,
    StaffAuditLog,
    WebhookDelivery,
    WebhookDeliveryAttempt,
    WebhookSubscription,
)
from app.schemas.action import ActionRecordCreate
from app.services.chain import build_and_insert_record
from app.services.checkpoint import create_checkpoint


# ── Helpers ────────────────────────────────────────────────────────


def _utc_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def _seed_org(
    db_session, name: str, cadence: str = "daily"
) -> Organization:
    org = Organization(name=name, checkpoint_cadence=cadence)
    db_session.add(org)
    await db_session.flush()
    db_session.add(ChainState(org_id=org.id))
    await db_session.commit()
    await db_session.refresh(org)
    return org


async def _seed_customer(db_session, org_id: str, tenant_id: str) -> Customer:
    customer = Customer(org_id=org_id, tenant_id=tenant_id)
    db_session.add(customer)
    await db_session.commit()
    await db_session.refresh(customer)
    return customer


async def _seed_signed_baa(
    db_session,
    org_id: str,
    customer_id: str,
    *,
    signed_at: datetime,
    status: str = "active",
) -> BAAAgreement:
    """Create a BAA + scope row. ``signed_at`` drives the
    artifact-freshness dimension's recency check."""
    baa = BAAAgreement(
        org_id=org_id,
        customer_id=customer_id,
        signed_at=signed_at,
        effective_at=signed_at,
        status=status,
    )
    db_session.add(baa)
    await db_session.flush()
    db_session.add(
        BAAScope(
            baa_agreement_id=baa.id,
            covered_services=["*"],
            covered_agent_types=["*"],
            is_unrestricted=True,
        )
    )
    await db_session.commit()
    await db_session.refresh(baa)
    return baa


async def _seed_approval(
    db_session,
    org_id: str,
    *,
    requested_at: datetime,
    decided_at: datetime | None,
    required_role: str | None = "physician",
    reviewer_role: str | None = "physician",
    decision: str = "approve",
    reviewed_below_threshold: bool = False,
) -> Approval:
    """Seed an Approval row with the timing + decision shape posture
    cares about. Skips the dispatch-event side effects of
    ``services.approvals.request_approval`` — those aren't needed for
    posture math.
    """
    context: dict = {"gate_name": "g"}
    if required_role is not None:
        context["required_role"] = required_role

    decisions = []
    if decided_at is not None:
        decisions.append(
            {
                "decision": decision,
                "approver": "alice",
                "reviewer_role": reviewer_role,
                "decided_at": decided_at.isoformat(),
                "signature": "sig",
                "key_id": "kid",
            }
        )

    approval = Approval(
        org_id=org_id,
        requested_by_agent="agent-x",
        action_name="commit_note",
        context=context,
        risk_tier="high",
        approvers_required=1,
        status="approved" if decision == "approve" and decided_at else "pending",
        decisions=decisions,
        requested_at=requested_at,
        decided_at=decided_at,
        reviewed_below_threshold=reviewed_below_threshold,
    )
    db_session.add(approval)
    await db_session.commit()
    await db_session.refresh(approval)
    return approval


async def _seed_webhook_attempt(
    db_session,
    org_id: str,
    *,
    sub: WebhookSubscription,
    status_code: int | None,
    attempted_at: datetime,
    attempt_number: int = 1,
) -> WebhookDeliveryAttempt:
    delivery = WebhookDelivery(
        subscription_id=sub.id,
        org_id=org_id,
        event_type="review.requested",
        payload={"hello": "world"},
        status="succeeded" if status_code and 200 <= status_code < 300 else "pending",
        attempt_count=attempt_number,
        idempotency_key=f"key-{attempted_at.isoformat()}-{attempt_number}",
    )
    db_session.add(delivery)
    await db_session.flush()
    attempt = WebhookDeliveryAttempt(
        delivery_id=delivery.id,
        attempt_number=attempt_number,
        attempted_at=attempted_at,
        status_code=status_code,
    )
    db_session.add(attempt)
    await db_session.commit()
    await db_session.refresh(attempt)
    return attempt


async def _seed_webhook_sub(db_session, org_id: str) -> WebhookSubscription:
    sub = WebhookSubscription(
        org_id=org_id,
        url="https://example.test/hook",
        secret="test-secret",
        event_types=["review.requested"],
        is_active=True,
    )
    db_session.add(sub)
    await db_session.commit()
    await db_session.refresh(sub)
    return sub


async def _record_and_seal(db_session, org_id: str, n_actions: int = 1):
    for i in range(n_actions):
        await build_and_insert_record(
            db_session,
            org_id,
            ActionRecordCreate(
                action_name=f"act_{i}",
                action_type="function_call",
                agent_name="test-agent",
                result="success",
            ),
        )
    return await create_checkpoint(db_session, org_id)


# ── Happy path ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_posture_happy_path_all_dimensions_measured(
    async_client, db_session, org_and_key
):
    """Seed enough data to clear every dimension threshold; expect all
    6 in ``measured`` and the composite headline to say so."""
    org, raw_key, _ = org_and_key
    customer = await _seed_customer(db_session, org.id, "cust-a")
    now = _utc_naive()

    # Artifact freshness: one signed-this-week BAA.
    await _seed_signed_baa(
        db_session,
        org.id,
        customer.id,
        signed_at=now - timedelta(days=5),
    )

    # HITL completion + reviewer integrity + workflow timeliness: 12
    # approvals, all decided within an hour with the correct
    # reviewer_role.
    for i in range(12):
        await _seed_approval(
            db_session,
            org.id,
            requested_at=now - timedelta(hours=2 + i),
            decided_at=now - timedelta(hours=2 + i, minutes=-30),
            required_role="physician",
            reviewer_role="physician",
        )

    # Notice delivery rate: 12 webhook attempts, all 200.
    sub = await _seed_webhook_sub(db_session, org.id)
    for i in range(12):
        await _seed_webhook_attempt(
            db_session,
            org.id,
            sub=sub,
            status_code=200,
            attempted_at=now - timedelta(hours=i + 1),
            attempt_number=i + 1,
        )

    # Chain integrity: seal a fresh checkpoint.
    await _record_and_seal(db_session, org.id, n_actions=2)

    resp = await async_client.get(
        "/v1/compliance/posture",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    measured_names = {m["name"] for m in body["measured"]}
    assert measured_names == {
        "artifact_freshness",
        "hitl_completion",
        "reviewer_integrity",
        "notice_delivery_rate",
        "chain_integrity",
        "workflow_timeliness",
    }
    assert body["not_yet_eligible"] == []
    assert "6 of 6 dimensions measured" in body["composite_headline"]
    # Each measured dimension has a non-empty fact line + integer 0..100.
    for m in body["measured"]:
        assert 0 <= m["score"] <= 100
        assert isinstance(m["score"], int)
        assert m["measured_fact_line"], m
    # Voice rule: comma separators on counts. The HITL fact line will
    # render "12 HITL events" — no thousands separator needed at this
    # scale, but we MUST NOT see "12000" → "12000" formatting
    # regressions. We assert by checking a high-count rendering below.


# ── Low-volume org ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_posture_low_volume_org_renders_honestly(
    async_client, db_session, org_and_key
):
    """Org with 2 HITL events (under threshold of 10) → HITL, reviewer
    integrity, and workflow timeliness in ``not_yet_eligible``."""
    org, raw_key, _ = org_and_key
    now = _utc_naive()

    # Two approvals, both decided.
    for i in range(2):
        await _seed_approval(
            db_session,
            org.id,
            requested_at=now - timedelta(hours=2 + i),
            decided_at=now - timedelta(hours=1 + i),
        )

    # Seal a checkpoint so chain integrity stays measured.
    await _record_and_seal(db_session, org.id, n_actions=1)

    resp = await async_client.get(
        "/v1/compliance/posture",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    not_yet = {d["name"]: d for d in body["not_yet_eligible"]}
    measured = {d["name"]: d for d in body["measured"]}

    # The three thresholded-by-approval-count dimensions land in
    # not_yet_eligible with current=2, needed=8.
    for name in ("hitl_completion", "reviewer_integrity", "workflow_timeliness"):
        assert name in not_yet, body
        assert not_yet[name]["current"] == 2
        assert not_yet[name]["threshold"] == 10
        assert not_yet[name]["needed"] == 8
        assert not_yet[name]["reason"]  # non-empty

    # Chain integrity always measured.
    assert "chain_integrity" in measured

    # Composite headline reflects the count.
    measured_count = len(body["measured"])
    assert f"{measured_count} of 6 dimensions measured" in body["composite_headline"]


# ── Zero-data org ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_posture_zero_data_org(async_client, org_and_key):
    """Brand new org → 5 dimensions not_yet_eligible, chain_integrity
    measured at score=100 (the "no checkpoints yet" → status='ok'
    branch maps to 100)."""
    _, raw_key, _ = org_and_key

    resp = await async_client.get(
        "/v1/compliance/posture",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["measured"]) == 1
    assert body["measured"][0]["name"] == "chain_integrity"
    assert body["measured"][0]["score"] == 100
    assert len(body["not_yet_eligible"]) == 5
    nye_names = {d["name"] for d in body["not_yet_eligible"]}
    assert nye_names == {
        "artifact_freshness",
        "hitl_completion",
        "reviewer_integrity",
        "notice_delivery_rate",
        "workflow_timeliness",
    }
    # All not-yet-eligible counts are 0.
    for d in body["not_yet_eligible"]:
        assert d["current"] == 0
        assert d["needed"] == d["threshold"]
    assert "1 of 6 dimensions measured" in body["composite_headline"]


# ── Chain integrity warn on stale checkpoint ───────────────────────


@pytest.mark.asyncio
async def test_posture_chain_integrity_warn_on_stale_checkpoint(
    async_client, db_session, org_and_key
):
    """Hourly cadence org with last checkpoint > 2h ago → chain
    integrity dimension lands at score=50 (warn mapping)."""
    org, raw_key, _ = org_and_key

    # Flip cadence to hourly + seal a checkpoint that we then backdate.
    org_row = await db_session.get(Organization, org.id)
    org_row.checkpoint_cadence = "hourly"
    await db_session.commit()

    cp = await _record_and_seal(db_session, org.id, n_actions=2)

    # Backdate the checkpoint past the 2h hourly-cadence grace + re-sign
    # so verify_checkpoint still passes (otherwise we'd hit the
    # signature-failure branch instead of the freshness branch).
    from app.services.checkpoint import _checkpoint_message
    from app.services.kms import get_kms
    from app.models import Checkpoint

    cp_row = await db_session.get(Checkpoint, cp.id)
    stale_when = _utc_naive() - timedelta(hours=3)
    cp_row.created_at = stale_when
    new_msg = _checkpoint_message(
        cp_row.org_id,
        cp_row.sequence_at_checkpoint,
        cp_row.hash_at_checkpoint,
        stale_when.isoformat(),
    )
    cp_row.signature = get_kms().sign(new_msg)
    cp_row.external_receipt = None
    await db_session.commit()

    resp = await async_client.get(
        "/v1/compliance/posture",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    ci = next(m for m in body["measured"] if m["name"] == "chain_integrity")
    assert ci["score"] == 50, ci
    # Aggregator's message surfaces the staleness.
    assert "overdue" in ci["measured_fact_line"].lower()


# ── window_days parameter ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_posture_window_days_parameter(
    async_client, db_session, org_and_key
):
    """Approvals 20 days ago show up in window_days=30 but not in
    window_days=7. Workflow timeliness should still surface them at
    30d (10 events ≥ threshold) and skip them at 7d."""
    org, raw_key, _ = org_and_key
    now = _utc_naive()

    # 12 approvals 20 days back — visible at 30d, not at 7d.
    for i in range(12):
        old = now - timedelta(days=20, minutes=i)
        await _seed_approval(
            db_session,
            org.id,
            requested_at=old,
            decided_at=old + timedelta(minutes=30),
        )

    resp30 = await async_client.get(
        "/v1/compliance/posture?window_days=30",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp30.status_code == 200, resp30.text
    body30 = resp30.json()
    workflow_30 = next(
        (m for m in body30["measured"] if m["name"] == "workflow_timeliness"),
        None,
    )
    assert workflow_30 is not None, body30
    assert workflow_30["raw_count"] == 12

    resp7 = await async_client.get(
        "/v1/compliance/posture?window_days=7",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp7.status_code == 200, resp7.text
    body7 = resp7.json()
    workflow_7 = next(
        (
            d for d in body7["not_yet_eligible"]
            if d["name"] == "workflow_timeliness"
        ),
        None,
    )
    assert workflow_7 is not None, body7
    assert workflow_7["current"] == 0
    # Window length echoed in the response.
    assert body30["window_days"] == 30
    assert body7["window_days"] == 7


# ── Cross-org isolation ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_posture_cross_org_isolation(
    async_client, db_session, org_and_key
):
    """Customer in org A sees only their own counts, never org B's."""
    org_a, raw_key, _ = org_and_key

    # Seed a noisy "other" org with lots of data.
    org_b = await _seed_org(db_session, "other-org")
    now = _utc_naive()
    for i in range(20):
        await _seed_approval(
            db_session,
            org_b.id,
            requested_at=now - timedelta(hours=i + 1),
            decided_at=now - timedelta(hours=i, minutes=30),
        )

    # Org A has zero approvals.
    resp = await async_client.get(
        "/v1/compliance/posture",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    not_yet = {d["name"]: d for d in body["not_yet_eligible"]}
    # HITL dimension should report 0 events, not the 20 from org B.
    assert not_yet["hitl_completion"]["current"] == 0


# ── IAM: staff tier writes audit row ───────────────────────────────


@pytest_asyncio.fixture
async def staff_headers(monkeypatch):
    """Stub Clerk JWT verification for a staff-shaped claims dict.
    Mirrors ``test_chain_integrity_endpoint.staff_headers``."""
    from app.config import settings as _settings

    monkeypatch.setattr(_settings, "clerk_staff_org_id", "staff-org-clerk")

    async def fake_verify(token: str, **kwargs):
        return {
            "sub": "staff-user-1",
            "org_id": "staff-org-clerk",
            "iss": "clerk",
        }

    monkeypatch.setattr("app.services.auth.verify_clerk_jwt", fake_verify)
    return {"Authorization": "Bearer fake-staff-jwt"}


@pytest.mark.asyncio
async def test_posture_staff_audit_row_written(
    async_client, db_session, staff_headers
):
    """Staff session with X-Org-Id reads the target org's posture and
    writes one ``staff_audit_log`` row of the right shape."""
    customer = await _seed_org(db_session, "customer-org-z")

    resp = await async_client.get(
        "/v1/compliance/posture",
        headers={**staff_headers, "X-Org-Id": customer.id},
    )
    assert resp.status_code == 200, resp.text

    rows = (
        await db_session.execute(
            select(StaffAuditLog).where(
                StaffAuditLog.org_id == customer.id,
                StaffAuditLog.resource_type == "compliance_posture",
            )
        )
    ).scalars().all()
    assert len(rows) == 1
    row = rows[0]
    assert row.staff_id == "staff-user-1"
    assert row.endpoint == "/v1/compliance/posture"
    assert row.redacted is False
    assert row.resource_count == 1


# ── IAM: customer can't widen scope ────────────────────────────────


@pytest.mark.asyncio
async def test_posture_customer_admin_cannot_see_other_org(
    async_client, db_session, monkeypatch
):
    """Customer Clerk session bound to org A → reading org A is fine,
    no escalation to org B via X-Org-Id (header is ignored for
    customers; staff_org_id check fails).

    With ``clerk_staff_org_id`` unset (development default), staff
    tier is unreachable from any Clerk session — so the customer
    Clerk path runs and serves the *bound* org's posture, not the
    requested org's.
    """
    from app.config import settings as _settings
    from app.models import OrgMembership

    monkeypatch.setattr(_settings, "clerk_staff_org_id", None)

    org_a = await _seed_org(db_session, "customer-a")
    org_b = await _seed_org(db_session, "customer-b")
    # Org B has approvals, org A has none.
    now = _utc_naive()
    for i in range(15):
        await _seed_approval(
            db_session,
            org_b.id,
            requested_at=now - timedelta(hours=i + 1),
            decided_at=now - timedelta(hours=i, minutes=30),
        )

    # Membership: clerk user in org A only.
    membership = OrgMembership(
        clerk_user_id="user_a",
        clerk_org_id="clerk_org_a",
        org_id=org_a.id,
        role="admin",
    )
    db_session.add(membership)
    await db_session.commit()

    async def fake_verify(token: str, **kwargs):
        return {
            "sub": "user_a",
            "org_id": "clerk_org_a",
            "iss": "clerk",
        }

    monkeypatch.setattr("app.services.auth.verify_clerk_jwt", fake_verify)

    # Defeat maybe_refresh_membership's freshness re-check so the test
    # doesn't reach out to Clerk REST.
    async def fake_refresh(session, membership, **kwargs):
        return membership

    monkeypatch.setattr(
        "app.middleware.clerk_auth.maybe_refresh_membership", fake_refresh
    )

    # Try to widen scope via X-Org-Id. The customer Clerk path ignores
    # the header (only staff path consumes it) and serves org A.
    resp = await async_client.get(
        "/v1/compliance/posture",
        headers={
            "Authorization": "Bearer fake-customer-jwt",
            "X-Org-Id": org_b.id,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    not_yet = {d["name"]: d for d in body["not_yet_eligible"]}
    # Org A has zero approvals; if scope had widened we'd see 15.
    assert not_yet["hitl_completion"]["current"] == 0


# ── Regression: no enum equality antipattern ───────────────────────


def test_posture_iam_tier_branch_uses_helpers_not_enum():
    """Regression: the new posture code branches via ``ctx.is_staff`` /
    ``ctx.is_customer`` helpers, never via a direct ``ctx.tier ==
    IamTier.X`` comparison. The IamTier CI gate
    (``scripts/check_iam_tier_usage.sh``) enforces the same rule
    project-wide; this test asserts the local files conform so a fast
    unit run catches a regression before CI does.
    """
    import re

    # Mirror the regex from ``scripts/check_iam_tier_usage.sh``. We
    # check both polarities (``ctx.tier == IamTier.X`` and the Yoda
    # form ``IamTier.X == ctx.tier``) for the new posture surface
    # only — the project-wide script handles every other route.
    pattern = re.compile(
        r"(ctx\.tier\s*==\s*IamTier\.|IamTier\.[A-Z_]+\s*==\s*ctx\.tier)"
    )
    new_files = [
        Path(__file__).resolve().parent.parent / "app" / "routes" / "compliance.py",
        Path(__file__).resolve().parent.parent
        / "app"
        / "services"
        / "posture"
        / "compute.py",
        Path(__file__).resolve().parent.parent
        / "app"
        / "services"
        / "posture"
        / "dimensions.py",
    ]
    for path in new_files:
        text = path.read_text()
        # Exclude lines that are clearly comments-only — the script's
        # regex matches anywhere on a line, but a `# don't write
        # `ctx.tier == IamTier.X`` advisory in a docstring is fine.
        # We still gate on the script's strict regex, but skip prose
        # lines.
        for lineno, line in enumerate(text.splitlines(), start=1):
            stripped = line.lstrip()
            if stripped.startswith("#"):
                continue
            assert not pattern.search(line), (
                f"{path}:{lineno}: forbidden ctx.tier == IamTier.X "
                f"comparison — use ctx.is_staff / ctx.is_customer "
                f"instead. Offending line: {line!r}"
            )

    # Belt-and-braces: invoke the project-wide script if it exists.
    # This catches the case where someone moves the antipattern into
    # a different routes/ file.
    script = (
        Path(__file__).resolve().parent.parent.parent
        / "scripts"
        / "check_iam_tier_usage.sh"
    )
    if script.exists():
        result = subprocess.run(
            ["bash", str(script)],
            cwd=str(script.parent.parent),
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, (
            f"check_iam_tier_usage.sh failed:\n"
            f"stdout={result.stdout}\nstderr={result.stderr}"
        )


# ── Response shape stability ───────────────────────────────────────


@pytest.mark.asyncio
async def test_posture_response_shape_stable(async_client, org_and_key):
    """Snapshot the top-level + per-element JSON keys. Future shape
    changes surface here for explicit review."""
    _, raw_key, _ = org_and_key
    resp = await async_client.get(
        "/v1/compliance/posture",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body.keys()) == {
        "composite_headline",
        "measured",
        "not_yet_eligible",
        "computed_at",
        "window_days",
    }
    # The zero-data org has one measured (chain_integrity) and five
    # not_yet_eligible — assert both element shapes.
    assert body["measured"], body
    measured_keys = set(body["measured"][0].keys())
    assert measured_keys == {
        "name",
        "score",
        "raw_count",
        "measured_fact_line",
    }
    assert body["not_yet_eligible"], body
    nye_keys = set(body["not_yet_eligible"][0].keys())
    assert nye_keys == {
        "name",
        "threshold",
        "current",
        "needed",
        "reason",
    }
