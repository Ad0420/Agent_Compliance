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
    action_class: str | None = None,
    agent_name: str = "scribe-agent",
):
    """Build N ActionRecords + M Approvals (with linked request_record_id).

    Each approval picks the i-th action record as its request_record so
    the PdfContext's join (Approval → ActionRecord → Customer) matches.

    ``action_class`` is the auto-discovery signal that drives
    ``CustomerAgent.agent_type`` — pass ``"scribe"`` to seed a Customer
    whose AI Coverage Matrix row shows captured + covered=True.
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
                agent_name=agent_name,
                action_class=action_class,
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


# ╔══════════════════════════════════════════════════════════════════════╗
# ║ Phase 4 Wave 2 A2 — Scope coverage matrix + Merkle proof attachments  ║
# ╚══════════════════════════════════════════════════════════════════════╝


async def _seed_customer_agent(
    db_session,
    *,
    customer_id: str,
    agent_type: str,
    source: str = "declared",
):
    """Insert a single ``CustomerAgent`` row directly.

    Used by the "detected but not captured" half of the Coverage Matrix
    test, where we want a CustomerAgent row in the DB without seeding
    any ActionRecord for that agent_type.
    """
    from app.models import CustomerAgent

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    ca = CustomerAgent(
        customer_id=customer_id,
        agent_type=agent_type,
        first_seen_at=now,
        last_seen_at=now,
        source=source,
        confidence="high",
        status="active",
    )
    db_session.add(ca)
    await db_session.commit()
    await db_session.refresh(ca)
    return ca


def _extract_attachments(pdf_bytes: bytes) -> dict[str, bytes]:
    """Return embedded-file attachments keyed by filename.

    pypdf's ``PdfReader.attachments`` returns a ``LazyDict`` whose
    values are bytes objects. We materialise to a regular dict so
    tests can index into it with the expected ``proof-<hash>.json``
    keys.
    """
    reader = PdfReader(io.BytesIO(pdf_bytes))
    out: dict[str, bytes] = {}
    for name, value in reader.attachments.items():
        # pypdf returns a list of bytes for the (rare) case of multiple
        # files sharing a name. Take the first — our writer never
        # re-uses a filename.
        if isinstance(value, list):
            out[name] = value[0]
        else:
            out[name] = value
    return out


# ── A2.1: Scope page renders the AI Coverage Matrix ──────────


@pytest.mark.asyncio
async def test_scope_page_renders_coverage_matrix(
    async_client, org_and_key, db_session
):
    """Scribe captured + prior_auth detected-but-silent → both visible."""
    org, raw_key, _ = org_and_key
    customer = await _seed_customer(
        db_session,
        org_id=org.id,
        tenant_id="cleveland_clinic",
        display_name="Cleveland Clinic",
    )
    await _seed_active_baa(db_session, org_id=org.id, customer_id=customer.id)
    # scribe: auto-discovered via action_class="scribe" → CustomerAgent
    # row + captured ActionRecord.
    await _seed_actions_and_approvals(
        db_session,
        org_id=org.id,
        tenant_id="cleveland_clinic",
        action_count=3,
        approval_count=1,
        action_class="scribe",
    )
    # prior_auth: a CustomerAgent row with zero ActionRecords for this
    # agent_type in the window. Detected ✓, Vera coverage ✗.
    await _seed_customer_agent(
        db_session, customer_id=customer.id, agent_type="prior_auth"
    )

    today = date.today()
    resp = await async_client.post(
        f"/v1/audits/{customer.id}",
        json={
            "date_from": (today - timedelta(days=30)).isoformat(),
            "date_to": today.isoformat(),
            "sections": ["scope"],
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200, resp.text
    text = _extract_text(resp.content)
    # The matrix header and both agent_type rows must render.
    assert "AI coverage" in text or "coverage matrix" in text.lower()
    assert "scribe" in text
    assert "prior_auth" in text


# ── A2.2: Blunt scope line on partial coverage ───────────────


@pytest.mark.asyncio
async def test_scope_page_blunt_scope_line_when_partial_coverage(
    async_client, org_and_key, db_session
):
    """Partial coverage → "covers scribe only" / "are excluded"."""
    org, raw_key, _ = org_and_key
    customer = await _seed_customer(
        db_session,
        org_id=org.id,
        tenant_id="cleveland_clinic",
    )
    await _seed_active_baa(db_session, org_id=org.id, customer_id=customer.id)
    await _seed_actions_and_approvals(
        db_session,
        org_id=org.id,
        tenant_id="cleveland_clinic",
        action_count=2,
        approval_count=0,
        action_class="scribe",
    )
    await _seed_customer_agent(
        db_session, customer_id=customer.id, agent_type="prior_auth"
    )

    today = date.today()
    resp = await async_client.post(
        f"/v1/audits/{customer.id}",
        json={
            "date_from": (today - timedelta(days=30)).isoformat(),
            "date_to": today.isoformat(),
            "sections": ["scope"],
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200, resp.text
    text = _extract_text(resp.content)
    # The exact wording is brittle; check the two load-bearing pieces.
    assert "scribe" in text
    assert "prior_auth" in text
    # "covers ... only" pattern + "excluded" — both required by the
    # blunt-scope sentence for partial coverage.
    assert "only" in text.lower()
    assert "excluded" in text.lower()


# ── A2.3: All covered → inclusive copy ───────────────────────


@pytest.mark.asyncio
async def test_scope_page_all_covered_uses_inclusive_copy(
    async_client, org_and_key, db_session
):
    """Every detected agent is covered → "covers all detected" copy."""
    org, raw_key, _ = org_and_key
    customer = await _seed_customer(
        db_session,
        org_id=org.id,
        tenant_id="cleveland_clinic",
    )
    await _seed_active_baa(db_session, org_id=org.id, customer_id=customer.id)
    # Only one agent_type, with captured actions → all covered.
    await _seed_actions_and_approvals(
        db_session,
        org_id=org.id,
        tenant_id="cleveland_clinic",
        action_count=2,
        approval_count=0,
        action_class="scribe",
    )

    today = date.today()
    resp = await async_client.post(
        f"/v1/audits/{customer.id}",
        json={
            "date_from": (today - timedelta(days=30)).isoformat(),
            "date_to": today.isoformat(),
            "sections": ["scope"],
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200, resp.text
    text = _extract_text(resp.content)
    assert "covers all detected" in text.lower() or "all detected AI" in text


# ── A2.4: Customer with zero agents ──────────────────────────


@pytest.mark.asyncio
async def test_scope_page_zero_agents(
    async_client, org_and_key, db_session
):
    """No CustomerAgent rows → "No AI agents detected" placeholder."""
    org, raw_key, _ = org_and_key
    customer = await _seed_customer(
        db_session,
        org_id=org.id,
        tenant_id="empty_clinic",
    )
    await _seed_active_baa(db_session, org_id=org.id, customer_id=customer.id)

    today = date.today()
    resp = await async_client.post(
        f"/v1/audits/{customer.id}",
        json={
            "date_from": (today - timedelta(days=30)).isoformat(),
            "date_to": today.isoformat(),
            "sections": ["scope"],
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200, resp.text
    text = _extract_text(resp.content)
    assert "No AI agents detected" in text


# ── A2.5: Merkle reference sentence in Scope page ────────────


@pytest.mark.asyncio
async def test_scope_page_merkle_reference_sentence(
    async_client, org_and_key, db_session
):
    """When a checkpoint exists → Scope cites `vera verify --merkle-proof`."""
    org, raw_key, _ = org_and_key
    customer = await _seed_customer(
        db_session,
        org_id=org.id,
        tenant_id="cleveland_clinic",
    )
    await _seed_active_baa(db_session, org_id=org.id, customer_id=customer.id)
    await _seed_actions_and_approvals(
        db_session,
        org_id=org.id,
        tenant_id="cleveland_clinic",
        action_count=3,
        approval_count=0,
        action_class="scribe",
    )
    # Seal the chain so the Scope page has a checkpoint root to cite.
    from app.models import Checkpoint
    from sqlalchemy import select as _select

    await create_checkpoint(db_session, org.id)
    cp = (
        await db_session.execute(
            _select(Checkpoint).where(Checkpoint.org_id == org.id)
        )
    ).scalars().first()
    assert cp is not None and cp.merkle_root

    today = date.today()
    resp = await async_client.post(
        f"/v1/audits/{customer.id}",
        json={
            "date_from": (today - timedelta(days=30)).isoformat(),
            "date_to": today.isoformat(),
            "sections": ["scope"],
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200, resp.text
    text = _extract_text(resp.content)
    # Sentence anchors: the CLI invocation + the 12-char root prefix.
    assert "vera verify --merkle-proof" in text
    root_short = cp.merkle_root[:12]
    assert root_short in text


# ── A2.6: PDF carries Merkle proof attachments ───────────────


@pytest.mark.asyncio
async def test_pdf_has_merkle_attachments(
    async_client, org_and_key, db_session
):
    """Sealed checkpoint → exactly N proof-<hash>.json attachments."""
    org, raw_key, _ = org_and_key
    customer = await _seed_customer(
        db_session,
        org_id=org.id,
        tenant_id="cleveland_clinic",
    )
    await _seed_active_baa(db_session, org_id=org.id, customer_id=customer.id)
    records = await _seed_actions_and_approvals(
        db_session,
        org_id=org.id,
        tenant_id="cleveland_clinic",
        action_count=3,
        approval_count=0,
        action_class="scribe",
    )
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
    attachments = _extract_attachments(resp.content)
    assert len(attachments) == 3
    # Every filename follows the convention.
    for name in attachments:
        assert name.startswith("proof-")
        assert name.endswith(".json")
    # Spot-check: the attachment body parses as JSON with the
    # expected proof fields, and matches what ``build_proof`` returns
    # for the underlying record.
    import json as _json

    from app.services.merkle_proof import build_proof

    sample = next(iter(attachments.values()))
    parsed = _json.loads(sample.decode("utf-8"))
    assert "merkle_root" in parsed
    assert "merkle_path" in parsed
    assert "action_record_id" in parsed
    # The PDF-side payload should match build_proof's payload exactly.
    record = records[0]
    expected_short = record.id.replace("-", "")[:12]
    expected_filename = f"proof-{expected_short}.json"
    assert expected_filename in attachments
    fresh_payload = await build_proof(db_session, record=record)
    direct = _json.dumps(fresh_payload.to_dict(), sort_keys=True).encode("utf-8")
    assert attachments[expected_filename] == direct


# ── A2.7: Pending-proof records skipped with appendix note ──


@pytest.mark.asyncio
async def test_pdf_skips_pending_proofs_gracefully(
    async_client, org_and_key, db_session
):
    """3 sealed + 2 unsealed → 3 attachments + appendix mentions 2 pending."""
    org, raw_key, _ = org_and_key
    customer = await _seed_customer(
        db_session,
        org_id=org.id,
        tenant_id="cleveland_clinic",
    )
    await _seed_active_baa(db_session, org_id=org.id, customer_id=customer.id)
    # Seal the chain after the first 3 records.
    await _seed_actions_and_approvals(
        db_session,
        org_id=org.id,
        tenant_id="cleveland_clinic",
        action_count=3,
        approval_count=0,
        action_class="scribe",
    )
    await create_checkpoint(db_session, org.id)
    # Two more records land AFTER the seal — they're in the tail.
    await _seed_actions_and_approvals(
        db_session,
        org_id=org.id,
        tenant_id="cleveland_clinic",
        action_count=2,
        approval_count=0,
        action_class="scribe",
    )

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
    attachments = _extract_attachments(resp.content)
    assert len(attachments) == 3
    text = _extract_text(resp.content)
    # "2 records ... not yet checkpointed" message in the technical
    # appendix. We assert the count + the load-bearing fragment, not
    # an exact wording.
    assert "2" in text
    assert "not yet checkpointed" in text


# ── A2.8: Too many records → 413 ─────────────────────────────


@pytest.mark.asyncio
async def test_pdf_too_many_records_returns_413(
    async_client, org_and_key, db_session, monkeypatch
):
    """Cap lowered to 5, 10 records seeded → 413 too_many_records_for_pdf."""
    from app.services.pdf import context as _pdf_context

    monkeypatch.setattr(_pdf_context, "_RECORDS_HARD_CAP", 5)

    org, raw_key, _ = org_and_key
    customer = await _seed_customer(
        db_session,
        org_id=org.id,
        tenant_id="cleveland_clinic",
    )
    await _seed_active_baa(db_session, org_id=org.id, customer_id=customer.id)
    await _seed_actions_and_approvals(
        db_session,
        org_id=org.id,
        tenant_id="cleveland_clinic",
        action_count=10,
        approval_count=0,
        action_class="scribe",
    )

    today = date.today()
    resp = await async_client.post(
        f"/v1/audits/{customer.id}",
        json={
            "date_from": (today - timedelta(days=30)).isoformat(),
            "date_to": today.isoformat(),
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 413, resp.text
    body = resp.json()
    assert body["code"] == "too_many_records_for_pdf"
    assert body.get("record_count") == 10
    assert body.get("cap") == 5


# ── A2.9: Checkpoint pending → Scope falls back gracefully ──


@pytest.mark.asyncio
async def test_scope_page_checkpoint_pending_text_when_no_checkpoint_in_range(
    async_client, org_and_key, db_session
):
    """Records but no checkpoint → "Checkpoint pending" copy in Scope."""
    org, raw_key, _ = org_and_key
    customer = await _seed_customer(
        db_session,
        org_id=org.id,
        tenant_id="cleveland_clinic",
    )
    await _seed_active_baa(db_session, org_id=org.id, customer_id=customer.id)
    await _seed_actions_and_approvals(
        db_session,
        org_id=org.id,
        tenant_id="cleveland_clinic",
        action_count=3,
        approval_count=0,
        action_class="scribe",
    )
    # Deliberately do NOT call create_checkpoint().

    today = date.today()
    resp = await async_client.post(
        f"/v1/audits/{customer.id}",
        json={
            "date_from": (today - timedelta(days=30)).isoformat(),
            "date_to": today.isoformat(),
            "sections": ["scope"],
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200, resp.text
    text = _extract_text(resp.content)
    assert "Checkpoint pending" in text


# ╔══════════════════════════════════════════════════════════════════════╗
# ║ Hotfix — PDF table layout (Coverage Matrix + Audit Controls)         ║
# ║                                                                       ║
# ║ Bug 1: Coverage Matrix header cells were plain strings with no       ║
# ║   colWidths, so labels collided ("Vera coverageCapture").            ║
# ║ Bug 2: Audit Controls right column was a plain str → ReportLab       ║
# ║   doesn't word-wrap plain strs in Table cells, so sentences clipped  ║
# ║   at the page edge ("via SHA-", "all reco", "staff_a", "configu").   ║
# ║ Fix:    Wrap header + body cells in Paragraph + pass explicit        ║
# ║   colWidths so ReportLab reflows the text inside each cell.          ║
# ╚══════════════════════════════════════════════════════════════════════╝


@pytest.mark.asyncio
async def test_scope_coverage_matrix_uses_explicit_column_widths(
    async_client, org_and_key, db_session
):
    """Coverage Matrix header labels render as distinct tokens, not merged.

    The pre-fix rendering produced concatenated runs like
    ``Vera coverageCapture`` because adjacent narrow cells had no
    word-wrap and butted up against each other. Asserting that each
    label appears AND the concatenated form does not appear is the
    most stable cross-pypdf-version check available — the column
    widths themselves are not exposed in the extracted text stream.
    """
    org, raw_key, _ = org_and_key
    customer = await _seed_customer(
        db_session,
        org_id=org.id,
        tenant_id="cleveland_clinic",
        display_name="Cleveland Clinic",
    )
    await _seed_active_baa(db_session, org_id=org.id, customer_id=customer.id)
    # Seed at least one captured agent so the matrix renders the
    # full header row (the no-data branch skips the table entirely).
    await _seed_actions_and_approvals(
        db_session,
        org_id=org.id,
        tenant_id="cleveland_clinic",
        action_count=3,
        approval_count=1,
        action_class="scribe",
    )

    today = date.today()
    resp = await async_client.post(
        f"/v1/audits/{customer.id}",
        json={
            "date_from": (today - timedelta(days=30)).isoformat(),
            "date_to": today.isoformat(),
            "sections": ["scope"],
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200, resp.text
    text = _extract_text(resp.content)

    # pypdf inserts newlines wherever a Paragraph cell wraps a label
    # onto a second visual line (e.g. "Vera\ncoverage" when the cell
    # is narrower than the label). The fix specifically *wants* that
    # wrapping — what we want to assert is that the label is no
    # longer fused into the next column. Collapsing whitespace gives
    # us a stable substring to check against without coupling the
    # test to ReportLab's wrap point heuristics.
    collapsed = " ".join(text.split())

    for label in (
        "Agent type",
        "Detected",
        "Vera coverage",
        "Capture",
        "HITL gates",
        "PDF included",
        "Posture included",
    ):
        assert label in collapsed, (
            f"expected header label {label!r} in collapsed PDF text"
        )

    # The pre-fix bug: adjacent header labels merged into one token
    # because the cells were too narrow and the strings did not wrap.
    # These exact concatenations were visible in the user-reported
    # screenshot. The collapsed form still contains a single space
    # between cell tokens — only the *fused* pre-fix runs are absent.
    assert "Vera coverageCapture" not in collapsed
    assert "PDF includePosture included" not in collapsed
    # And the raw extracted text (no collapsing) also must not contain
    # the fused runs — they would only appear if cells overflowed
    # horizontally into one another.
    assert "Vera coverageCapture" not in text
    assert "PDF includePosture included" not in text


@pytest.mark.asyncio
async def test_audit_controls_right_column_does_not_truncate(
    async_client, org_and_key, db_session
):
    """Every Audit Controls row renders its full text — no mid-word clip.

    The pre-fix rendering put a plain ``str`` into the right-column
    cell. ReportLab does not word-wrap plain strings inside ``Table``
    cells, so the long Implementation sentences ran off the right
    margin and clipped mid-word: "via SHA-" instead of "via SHA-256",
    "all reco" instead of "all records sealed", and so on.

    Wrapping the value in a ``Paragraph`` plus pinning ``colWidths``
    on the Table is the fix.
    """
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
            "date_from": (today - timedelta(days=30)).isoformat(),
            "date_to": today.isoformat(),
            "sections": ["audit_controls"],
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200, resp.text
    text = _extract_text(resp.content)

    # The "tell" tokens from the user screenshot — these were the
    # *truncation suffixes* that disappeared before the fix. After the
    # fix, the full continuation must be visible.
    #
    # pypdf occasionally inserts a newline at the wrap point, so we
    # collapse whitespace before substring-checking. We don't lower-
    # case because the casing in the source is what we expect to
    # render — any case fold would mask a font-substitution regression.
    collapsed = " ".join(text.split())

    # Row 1 — "Activity recording": the SHA-256 suffix must survive.
    assert (
        "predecessor via SHA-256" in collapsed
    ), "Activity recording row truncated before SHA-256"

    # Row 2 — "Tamper evidence": the "Merkle root of all records sealed"
    # phrase used to clip at "all reco".
    assert (
        "Merkle root of all records sealed in the interval" in collapsed
    ), "Tamper evidence row truncated before 'records sealed'"

    # Row 3 — "Activity examination": "staff_audit_log" used to clip at
    # "staff_a".
    assert (
        "staff_audit_log" in collapsed
    ), "Activity examination row truncated before 'staff_audit_log'"

    # Row 4 — "Authentication of activity origin": "the chain hash
    # binds those fields cryptographically" used to clip at "the chain
    # hash binds ".
    assert (
        "the chain hash binds those fields cryptographically" in collapsed
    ), "Authentication row truncated before 'cryptographically'"

    # Row 5 — "Retention": "when configured" used to clip at "when
    # configu".
    assert (
        "when configured" in collapsed
    ), "Retention row truncated before 'configured'"


@pytest.mark.asyncio
async def test_scope_coverage_matrix_escapes_paragraph_markup(
    async_client, org_and_key, db_session
):
    """An ``agent_type`` with ``&`` / ``<`` does not crash the renderer.

    The hotfix wraps ``agent_type`` in a ``Paragraph`` flowable to get
    word-wrap. ``Paragraph`` parses a tiny HTML-ish subset (``<b>``,
    ``<font>``, ``&amp;`` …) so unescaped metacharacters in the cell
    value raise ``ValueError`` and 500 the endpoint.

    ``action_class`` (which auto-discovery promotes into
    ``CustomerAgent.agent_type``) is only ``Optional[str]`` at the
    schema layer with no character-class restriction. A malicious or
    sloppy SDK caller posting ``"hr&admissions"`` is a regression
    surface this test guards against.
    """
    org, raw_key, _ = org_and_key
    customer = await _seed_customer(
        db_session,
        org_id=org.id,
        tenant_id="cleveland_clinic",
        display_name="Cleveland Clinic",
    )
    await _seed_active_baa(db_session, org_id=org.id, customer_id=customer.id)
    # Seed a CustomerAgent row with metacharacters in agent_type. We
    # bypass the auto-discovery path and insert directly — the ORM
    # validator lower+strips but does NOT restrict the character class,
    # which is exactly the surface we want to test.
    await _seed_customer_agent(
        db_session,
        customer_id=customer.id,
        agent_type="hr&<admissions>",
    )

    today = date.today()
    resp = await async_client.post(
        f"/v1/audits/{customer.id}",
        json={
            "date_from": (today - timedelta(days=30)).isoformat(),
            "date_to": today.isoformat(),
            "sections": ["scope"],
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    # The render must succeed (not 500). The escaped agent_type label
    # should appear in the extracted text — pypdf decodes the encoded
    # entities back to their literal characters, so we assert on the
    # plain form.
    assert resp.status_code == 200, resp.text
    text = _extract_text(resp.content)
    collapsed = " ".join(text.split())
    assert "hr&<admissions>" in collapsed
