"""Tests for ``POST /v1/audits/{customer_id}`` — Phase 4 Wave 1 A1.

Coverage matrix (mirrors the PR brief):

  * test_generate_pdf_happy_path — seeded Customer + actions + HITL +
    BAA + chain head → 200, application/pdf, sentinel strings present.
  * test_generate_pdf_customer_must_be_in_caller_org — cross-org → 404.
  * test_generate_pdf_baa_expired_returns_403 — error.code "baa_expired".
  * test_generate_pdf_section_toggle — sections=["cover", "scope"] →
    PDF contains scope but not § 164.312(b).
  * test_generate_pdf_no_data_renders_honest_placeholders — 0 actions →
    placeholder copy renders, no crash.
  * test_generate_pdf_iam_staff_tier_forbidden — Vera staff Clerk →
    refused with staff_read_only code.
  * test_generate_pdf_route_is_registered — URL resolution sanity.

Parsing strategy
----------------
We use ``pypdf`` (vendored sibling of pdfminer.six) to extract text
from the rendered bytes and search for sentinel strings. ReportLab
emits a non-deterministic creation timestamp into the file metadata so
byte-equality checks would be flaky; substring checks on the extracted
text are stable.
"""
from __future__ import annotations

import io
from datetime import date, datetime, timedelta, timezone

import pytest
from pypdf import PdfReader

from app.models import (
    BAAAgreement,
    BAAScope,
    ChainState,
    Customer,
    Organization,
)
from app.schemas.action import ActionRecordCreate
from app.services.auth import generate_api_key
from app.services.chain import build_and_insert_record
from app.services.checkpoint import create_checkpoint


# ── Helpers ──────────────────────────────────────────────────


def _extract_text(pdf_bytes: bytes) -> str:
    """Read every page of a PDF and concatenate the extracted text.

    pypdf's text extraction is best-effort (whitespace handling varies
    by font), so tests assert substring matches — never byte-equality.
    """
    reader = PdfReader(io.BytesIO(pdf_bytes))
    parts: list[str] = []
    for page in reader.pages:
        parts.append(page.extract_text() or "")
    return "\n".join(parts)


def _page_count(pdf_bytes: bytes) -> int:
    return len(PdfReader(io.BytesIO(pdf_bytes)).pages)


async def _seed_org_with_chain(db_session, name: str) -> Organization:
    org = Organization(name=name)
    db_session.add(org)
    await db_session.flush()
    db_session.add(ChainState(org_id=org.id))
    await db_session.commit()
    await db_session.refresh(org)
    return org


async def _seed_customer(
    db_session, *, org_id: str, tenant_id: str, display_name: str | None = None
) -> Customer:
    c = Customer(
        org_id=org_id,
        tenant_id=tenant_id,
        display_name=display_name or tenant_id,
    )
    db_session.add(c)
    await db_session.commit()
    await db_session.refresh(c)
    return c


async def _seed_active_baa(
    db_session,
    *,
    org_id: str,
    customer_id: str,
    expires_at: datetime | None = None,
    effective_at: datetime | None = None,
) -> tuple[BAAAgreement, BAAScope]:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    agreement = BAAAgreement(
        org_id=org_id,
        customer_id=customer_id,
        document_uri="s3://baa/test.pdf",
        signed_at=now - timedelta(days=30),
        effective_at=effective_at if effective_at is not None else (now - timedelta(days=29)),
        expires_at=expires_at if expires_at is not None else (now + timedelta(days=300)),
        status="active",
    )
    db_session.add(agreement)
    await db_session.flush()
    scope = BAAScope(
        baa_agreement_id=agreement.id,
        covered_services=["chart_entry"],
        covered_agent_types=["scribe"],
        is_unrestricted=True,
        granted_at=now - timedelta(days=29),
    )
    db_session.add(scope)
    await db_session.commit()
    await db_session.refresh(agreement)
    await db_session.refresh(scope)
    return agreement, scope


async def _seed_actions_and_approvals(
    db_session,
    *,
    org_id: str,
    tenant_id: str,
    action_count: int,
    approval_count: int,
):
    """Build N ActionRecords + M Approvals (with linked request_record_id).

    Each approval picks the i-th action record as its request_record so
    the PdfContext's join (Approval → ActionRecord → Customer) matches.
    """
    from app.models import Approval  # avoid early circular

    records = []
    for i in range(action_count):
        rec = await build_and_insert_record(
            db_session,
            org_id,
            ActionRecordCreate(
                action_name=f"chart_entry_{i}",
                action_type="function_call",
                agent_name="scribe-agent",
                result="success",
                tenant_id=tenant_id,
            ),
        )
        records.append(rec)

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for i in range(approval_count):
        ap = Approval(
            org_id=org_id,
            request_record_id=records[i].id if i < len(records) else None,
            requested_by_agent="scribe-agent",
            action_name="chart_entry",
            action_summary="HITL review",
            # The materialiser stashes gate metadata under ``context``;
            # we feed in the same shape so the renderer's role/gate
            # breakdown is exercised.
            context={
                "gate_name": "physician_signoff" if i % 2 == 0 else "demographic_check",
                "required_role": "attending" if i % 2 == 0 else "compliance",
                "demographic_fields_present": (i % 2 == 1),
            },
            risk_tier="high",
            approvers_required=1,
            status="approved" if i % 2 == 0 else "pending",
            decisions=[],
            requested_at=now,
        )
        db_session.add(ap)
    await db_session.commit()
    return records


# ── 1. Happy path ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_generate_pdf_happy_path(async_client, org_and_key, db_session):
    """Seeded Customer + actions + HITL + BAA + checkpoint → 200 PDF."""
    org, raw_key, _ = org_and_key
    customer = await _seed_customer(
        db_session,
        org_id=org.id,
        tenant_id="cleveland_clinic",
        display_name="Cleveland Clinic",
    )
    await _seed_active_baa(db_session, org_id=org.id, customer_id=customer.id)
    await _seed_actions_and_approvals(
        db_session,
        org_id=org.id,
        tenant_id="cleveland_clinic",
        action_count=10,
        approval_count=3,
    )
    # A sealed checkpoint so the Technical Appendix renders the real
    # KMS key id + Merkle root.
    await create_checkpoint(db_session, org.id)

    today = date.today()
    resp = await async_client.post(
        f"/v1/audits/{customer.id}",
        json={
            "date_from": (today - timedelta(days=30)).isoformat(),
            "date_to": today.isoformat(),
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("application/pdf")
    cd = resp.headers.get("content-disposition", "")
    assert "attachment" in cd
    assert "cleveland_clinic" in cd
    pdf_bytes = resp.content
    assert len(pdf_bytes) > 1000

    # Multi-page (cover + body); minimum 2 pages.
    assert _page_count(pdf_bytes) >= 2

    text = _extract_text(pdf_bytes)
    assert "HIPAA AI Audit Trail" in text
    assert "Cleveland Clinic" in text
    # § 164.312(b) sentinel — pypdf may extract the section sign as
    # "§" or "section"; we check for both variants.
    assert ("164.312(b)" in text) or ("§ 164.312" in text)
    # Chain integrity sentinel from the audit_controls table.
    assert "chain" in text.lower() or "Hash chain" in text


# ── 2. Cross-org isolation ───────────────────────────────────


@pytest.mark.asyncio
async def test_generate_pdf_customer_must_be_in_caller_org(
    async_client, org_and_key, db_session
):
    """Caller org A, Customer in org B → 404 (cross-org-safe)."""
    _, raw_key_a, _ = org_and_key
    org_b = await _seed_org_with_chain(db_session, "other-org")
    customer_b = await _seed_customer(
        db_session, org_id=org_b.id, tenant_id="secret_clinic"
    )
    today = date.today()
    resp = await async_client.post(
        f"/v1/audits/{customer_b.id}",
        json={
            "date_from": (today - timedelta(days=30)).isoformat(),
            "date_to": today.isoformat(),
        },
        headers={"Authorization": f"Bearer {raw_key_a}"},
    )
    assert resp.status_code == 404, resp.text


# ── 3. BAA expired → 403 baa_expired ─────────────────────────


@pytest.mark.asyncio
async def test_generate_pdf_baa_expired_returns_403(
    async_client, org_and_key, db_session
):
    """A Customer whose BAA already expired → 403 with baa_expired code."""
    org, raw_key, _ = org_and_key
    customer = await _seed_customer(
        db_session, org_id=org.id, tenant_id="expired_baa_clinic"
    )
    # Backdate the BAA so expires_at is in the past.
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    agreement = BAAAgreement(
        org_id=org.id,
        customer_id=customer.id,
        document_uri="s3://baa/expired.pdf",
        signed_at=now - timedelta(days=400),
        effective_at=now - timedelta(days=399),
        expires_at=now - timedelta(days=10),
        status="active",
    )
    db_session.add(agreement)
    await db_session.flush()
    scope = BAAScope(
        baa_agreement_id=agreement.id,
        covered_services=["chart_entry"],
        covered_agent_types=["scribe"],
        is_unrestricted=True,
        granted_at=now - timedelta(days=399),
    )
    db_session.add(scope)
    await db_session.commit()

    today = date.today()
    resp = await async_client.post(
        f"/v1/audits/{customer.id}",
        json={
            "date_from": (today - timedelta(days=30)).isoformat(),
            "date_to": today.isoformat(),
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 403, resp.text
    body = resp.json()
    # The exception handler flattens dict-typed detail to the top
    # level (see ``main._flatten_dict_detail``).
    assert body["code"] == "baa_expired"


# ── 4. Section toggle ────────────────────────────────────────


@pytest.mark.asyncio
async def test_generate_pdf_section_toggle(async_client, org_and_key, db_session):
    """Request with sections=["cover", "scope"] → 164.312(b) absent."""
    org, raw_key, _ = org_and_key
    customer = await _seed_customer(
        db_session,
        org_id=org.id,
        tenant_id="cleveland_clinic",
        display_name="Cleveland Clinic",
    )
    await _seed_active_baa(db_session, org_id=org.id, customer_id=customer.id)

    today = date.today()
    resp = await async_client.post(
        f"/v1/audits/{customer.id}",
        json={
            "date_from": (today - timedelta(days=7)).isoformat(),
            "date_to": today.isoformat(),
            "sections": ["cover", "scope"],
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200, resp.text
    text = _extract_text(resp.content)
    assert "HIPAA AI Audit Trail" in text
    assert "Scope" in text
    # Audit Controls section omitted → its sentinel must be absent.
    # Use the regulatory citation as the most discriminating marker
    # (the cover/scope copy never contains it).
    assert "164.312(b)" not in text


# ── 5. Empty data path renders honest placeholders ───────────


@pytest.mark.asyncio
async def test_generate_pdf_no_data_renders_honest_placeholders(
    async_client, org_and_key, db_session
):
    """Customer with zero actions → PDF still renders, placeholders honest."""
    org, raw_key, _ = org_and_key
    customer = await _seed_customer(
        db_session, org_id=org.id, tenant_id="empty_clinic"
    )
    await _seed_active_baa(db_session, org_id=org.id, customer_id=customer.id)

    today = date.today()
    resp = await async_client.post(
        f"/v1/audits/{customer.id}",
        json={
            "date_from": (today - timedelta(days=30)).isoformat(),
            "date_to": today.isoformat(),
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200, resp.text
    text = _extract_text(resp.content)
    # Demographic placeholder
    assert (
        "Demographic data not captured" in text
        or "demographic" in text.lower()
    )
    # Workforce training placeholder
    assert "No workforce training" in text or "workforce" in text.lower()
    # HITL evidence with zero events — the renderer surfaces a zero
    # count and / or a placeholder line.
    assert "HITL" in text or "Human-in-the-Loop" in text


# ── 6. Vera staff session forbidden ──────────────────────────


@pytest.mark.asyncio
async def test_generate_pdf_iam_staff_tier_forbidden(
    async_client, db_session, monkeypatch
):
    """Vera staff Clerk session → 403 with staff_read_only code."""
    from app.config import settings as _settings

    monkeypatch.setattr(_settings, "clerk_staff_org_id", "staff-org-clerk")

    async def fake_verify(token: str, **kwargs):
        return {
            "sub": "staff-user-1",
            "org_id": "staff-org-clerk",
            "iss": "clerk",
        }

    monkeypatch.setattr("app.services.auth.verify_clerk_jwt", fake_verify)

    org = await _seed_org_with_chain(db_session, "customer-org-z")
    customer = await _seed_customer(
        db_session, org_id=org.id, tenant_id="cleveland_clinic"
    )
    await _seed_active_baa(db_session, org_id=org.id, customer_id=customer.id)

    today = date.today()
    resp = await async_client.post(
        f"/v1/audits/{customer.id}",
        json={
            "date_from": (today - timedelta(days=30)).isoformat(),
            "date_to": today.isoformat(),
        },
        headers={
            "Authorization": "Bearer fake-staff-jwt",
            "X-Org-Id": org.id,
        },
    )
    assert resp.status_code == 403, resp.text
    body = resp.json()
    assert body["code"] == "staff_read_only"


# ── 7. Route is registered (URL resolution sanity) ───────────


def test_generate_pdf_route_is_registered():
    """``app.url_path_for`` resolves to the expected path.

    Guards against accidental router renames / missing include_router
    calls in ``app/main.py``.
    """
    from app.main import app

    path = app.url_path_for("generate_audit_pdf", customer_id="abc-123")
    assert path == "/v1/audits/abc-123"
