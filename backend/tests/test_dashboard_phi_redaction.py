"""Tests for W1.2 — dashboard PHI redaction (HIPAA minimum-necessary).

Closes ``phase2-acceptance-findings::dashboard-should-not-display-phi``
(CRITICAL). The dashboard surface (Clerk-session callers) must never
see PHI fields like ``data_subject_id``, ``Approval.action_summary``,
or PHI-bearing keys on ``Approval.context`` (``encounter_id``,
``patient_mrn``, ``diagnoses``, ``medication_orders``,
``original_input_data``, etc.).

Critical non-regression: SDK callers (API-key bearer) MUST still
receive the FULL Approval shape — they need ``data_subject_id`` for
HITL polling and the full context blob for the customer's own review
surface. Breaking that breaks every integration.

Coverage matrix
---------------

Approvals endpoints (list + get-by-id):

  * Clerk session → no ``data_subject_id``, no ``action_summary``,
    ``context`` only has gate-metadata whitelist
  * Clerk session → ``encounter_id`` / ``patient_mrn`` / ``diagnoses`` /
    ``medication_orders`` / ``original_input_data`` all absent
  * Clerk session → ``decisions`` (signed votes), ``risk_tier``,
    timestamps, ``status``, ``reviewed_below_threshold`` all preserved
  * API key → full shape (regression — don't break SDK)
  * Approval with no context (legacy) → empty dict, no errors
  * Approval with fully populated gate metadata → all surfaced

Customer decisions endpoint:

  * Clerk session → no ``data_subject_id`` key in response
  * API key → full ``CustomerDecisionResponse`` shape preserved
  * Decision row with gated Approval → Ruling fields surfaced, no PHI
    passthrough from ``Approval.context``

Serializer unit tests:

  * ``serialize_approval_for_dashboard`` is pure (no DB I/O)
  * ``_safe_approval_context`` handles None / empty input
"""
from __future__ import annotations

from datetime import datetime

import pytest
import pytest_asyncio

from app.config import settings
from app.models import (
    ActionRecord,
    Approval,
    ChainState,
    Customer,
    Organization,
    OrgMembership,
)
from app.services import auth as auth_service
from app.services.dashboard_views import (
    _redact_decision,
    _safe_approval_context,
    is_dashboard_request,
    serialize_approval_for_dashboard,
    serialize_decision_for_dashboard,
)
from app.main import app

from tests._clerk_test_helpers import (
    TEST_ISSUER,
    make_keypair,
    reset_rate_limit,
    sign_token,
)


# A realistic PHI-laden Approval.context blob — mirrors what the
# clinical gate materializer (services/gates/hitl.py) actually writes
# for the new-diagnosis / controlled-substance gates.
_PHI_CONTEXT = {
    # KEEP — gate metadata
    "gate_name": "new_diagnosis_gate",
    "required_role": "attending_physician",
    "citation": "CMS Final Rule §482.24",
    "reason": "new_diagnosis_unverified",
    "effect": "require_hitl",
    "fix_url": "https://cms.gov/some-doc",
    # DROP — PHI
    "encounter_id": "enc_pancreatitis_001",
    "patient_mrn": "MRN-31504806",
    "diagnoses": ["acute pancreatitis", "dehydration"],
    "medication_orders": ["ondansetron IV PRN", "LR IV @ 100mL/hr"],
    "lab_or_imaging_orders": ["lipase", "CBC", "abdominal CT"],
    "original_input_data": {
        "transcript": "Patient presents with severe epigastric pain...",
        "note": "DRAFT: Acute pancreatitis, likely gallstone etiology",
    },
    "transcript": "Patient presents with severe epigastric pain...",
    "note": "DRAFT: Acute pancreatitis, likely gallstone etiology",
}


_PHI_SAFE_KEYS = {
    "gate_name",
    "required_role",
    "citation",
    "reason",
    "effect",
    "fix_url",
}
_PHI_UNSAFE_KEYS = {
    "encounter_id",
    "patient_mrn",
    "diagnoses",
    "medication_orders",
    "lab_or_imaging_orders",
    "original_input_data",
    "transcript",
    "note",
}


# ── Clerk fixtures ──────────────────────────────────────────────────────


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
async def clerk_seeded(db_session, db_engine, org_and_key):
    """Attach a Clerk OrgMembership to the existing org_and_key org.

    Re-uses the conftest ``org_and_key`` org so the same Customer /
    Approval rows seeded for SDK-key tests are visible to the dashboard
    user too. Returns the clerk_org_id needed by ``sign_token``.
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession
    from app import database as db_mod

    org, raw_key, api_key = org_and_key
    # Backfill clerk_org_id onto the org and add the dashboard user
    # membership so Clerk auth resolves the same org_id as the API key.
    org.clerk_org_id = "org_phi_test"
    db_session.add(
        OrgMembership(
            org_id=org.id,
            clerk_user_id="user_dashboard_phi",
            clerk_org_id="org_phi_test",
            role="admin",
        )
    )
    await db_session.commit()

    # Share AsyncSessionLocal so the Clerk membership-refresh + audit
    # writes land in the test in-memory DB.
    test_factory = async_sessionmaker(
        db_engine, class_=AsyncSession, expire_on_commit=False
    )
    original = db_mod.AsyncSessionLocal
    db_mod.AsyncSessionLocal = test_factory
    try:
        yield {
            "org_id": org.id,
            "clerk_org_id": "org_phi_test",
            "clerk_user_id": "user_dashboard_phi",
            "raw_key": raw_key,
        }
    finally:
        db_mod.AsyncSessionLocal = original


def _clerk_headers(keypair, clerk_seeded) -> dict[str, str]:
    token = sign_token(
        keypair["priv"],
        sub=clerk_seeded["clerk_user_id"],
        org_id=clerk_seeded["clerk_org_id"],
    )
    return {"Authorization": f"Bearer {token}"}


def _sdk_headers(clerk_seeded) -> dict[str, str]:
    return {"Authorization": f"Bearer {clerk_seeded['raw_key']}"}


# ── Helpers ─────────────────────────────────────────────────────────────


async def _seed_approval(
    db_session,
    *,
    org_id: str,
    context: dict | None = None,
    data_subject_id: str | None = "patient_secret_id_42",
    action_summary: str | None = (
        "Commit note for encounter MRN-31504806: 1 new diagnosis, "
        "2 controlled medications."
    ),
    request_record_id: str | None = None,
) -> Approval:
    approval = Approval(
        org_id=org_id,
        request_record_id=request_record_id,
        requested_by_agent="scribe-agent",
        action_name="commit_note",
        action_summary=action_summary,
        data_subject_id=data_subject_id,
        context=context if context is not None else dict(_PHI_CONTEXT),
        risk_tier="high",
        approvers_required=1,
        status="pending",
        decisions=[],
        requested_at=datetime(2026, 5, 24, 12, 0, 0),
    )
    db_session.add(approval)
    await db_session.commit()
    await db_session.refresh(approval)
    return approval


async def _seed_action_and_customer(
    db_session, *, org_id: str, tenant_id: str = "cleveland_clinic"
) -> ActionRecord:
    customer = Customer(
        org_id=org_id, tenant_id=tenant_id, display_name=tenant_id
    )
    db_session.add(customer)
    await db_session.commit()
    record = ActionRecord(
        org_id=org_id,
        sequence_number=1,
        previous_hash="prev",
        record_hash="hash",
        agent_name="scribe-agent",
        action_name="commit_note",
        action_type="function_call",
        action_timestamp=datetime(2026, 5, 24, 12, 0, 0),
        authorized_by="test-suite",
        tenant_id=tenant_id,
        result="pending",
    )
    db_session.add(record)
    await db_session.commit()
    await db_session.refresh(record)
    return record


# ── Pure serializer unit tests (no DB I/O) ──────────────────────────────


def test_safe_approval_context_strips_phi_keys():
    """``_safe_approval_context`` keeps only whitelisted gate metadata."""
    result = _safe_approval_context(dict(_PHI_CONTEXT))
    assert set(result.keys()) == _PHI_SAFE_KEYS
    for unsafe in _PHI_UNSAFE_KEYS:
        assert unsafe not in result, f"PHI key {unsafe!r} leaked"
    # Whitelisted values survive untouched.
    assert result["gate_name"] == "new_diagnosis_gate"
    assert result["required_role"] == "attending_physician"


def test_safe_approval_context_handles_empty_input():
    """None / empty dict / missing-keys path returns {}."""
    assert _safe_approval_context(None) == {}
    assert _safe_approval_context({}) == {}
    # Dict with ONLY unsafe keys → empty dict, not None or KeyError.
    assert _safe_approval_context({"patient_mrn": "MRN-123"}) == {}


def test_serialize_approval_for_dashboard_is_pure(db_session):
    """No DB I/O — pure transform over the ORM object's attrs."""
    # Construct an Approval without committing — confirms no session
    # access happens inside the serializer.
    approval = Approval(
        id="ap-1",
        org_id="org-1",
        requested_by_agent="agent",
        action_name="commit",
        data_subject_id="patient-42",
        action_summary="PHI-laden summary with MRN-12345",
        context=dict(_PHI_CONTEXT),
        risk_tier="high",
        approvers_required=1,
        status="pending",
        decisions=[],
        requested_at=datetime(2026, 5, 24, 12, 0, 0),
        reviewed_below_threshold=False,
    )
    result = serialize_approval_for_dashboard(approval)
    assert result["id"] == "ap-1"
    assert result["action_name"] == "commit"
    assert "data_subject_id" not in result, "data_subject_id leaked"
    assert "action_summary" not in result, "action_summary leaked (PHI)"
    assert set(result["context"].keys()) == _PHI_SAFE_KEYS
    assert result["decisions"] == []
    assert result["risk_tier"] == "high"


def test_redact_decision_strips_note_and_approver_pii():
    """W2.2 — dashboard view of ``Approval.decisions[]`` must strip the
    free-text ``note`` (PHI narrative carrier) and the ``approver`` field
    (``"{reviewer_id}:{reviewer_role}"`` — reviewer_id is customer-side
    PII). Derived ``reviewer_role`` is re-emitted so the UI can render
    'Approved by attending_physician' without the clinician's identity.
    """
    vote = {
        "decision": "approve",
        "approver": "alice@hospital.example:attending_physician",
        # PHI-laden reviewer comment from the in-band EHR review surface.
        "note": (
            "Approved — MRN-31504806 CT shows pancreatitis, treated "
            "with IV LR and ondansetron. Patient stable for discharge."
        ),
        "decided_at": "2026-05-24T13:00:00",
        "signature": "sig:abc123",
        "key_id": "kid-1",
    }
    result = _redact_decision(vote)
    assert result["decision"] == "approve"
    assert result["decided_at"] == "2026-05-24T13:00:00"
    assert result["signature"] == "sig:abc123"
    assert result["key_id"] == "kid-1"
    assert result["reviewer_role"] == "attending_physician"
    # PII / PHI carriers MUST NOT survive.
    assert "approver" not in result, "approver leaked (carries reviewer_id PII)"
    assert "note" not in result, "note leaked (PHI narrative carrier)"
    # Negative content check — no fragment of the PHI / PII survives.
    result_str = str(result)
    assert "alice@hospital.example" not in result_str
    assert "MRN-31504806" not in result_str
    assert "pancreatitis" not in result_str


def test_redact_decision_handles_legacy_approver_without_role():
    """Pre-W2.1 votes (decided via legacy /v1/approvals/{id}/decide)
    persisted ``approver`` as a plain "{name}" or "api_key:{prefix}". The
    role is unknown — emit no derived ``reviewer_role`` rather than
    inventing one. The ``approver`` is still stripped because it can
    still be PII (or an API key prefix that points at one person)."""
    legacy = {
        "decision": "reject",
        "approver": "dr-bob",
        "note": "Not authorized.",
        "decided_at": "2026-05-24T13:00:00",
        "signature": "sig:1",
        "key_id": "kid-1",
    }
    result = _redact_decision(legacy)
    assert "approver" not in result
    assert "note" not in result
    assert "reviewer_role" not in result, (
        "Should NOT invent a role when the legacy vote didn't record one."
    )
    assert result["decision"] == "reject"

    # ``api_key:xyz`` shaped approvers (cancel path) — colon present but
    # the segment after is a key prefix, not a role. Today we still emit
    # it as ``reviewer_role`` because the dashboard can't distinguish
    # these without more context; downstream renderers should treat
    # ``reviewer_role`` as advisory text. Document the behaviour so it's
    # an intentional decision, not a surprise.
    api_key_vote = {
        "decision": "cancel",
        "approver": "api_key:vera_prod",
        "decided_at": "2026-05-24T13:00:00",
        "signature": "sig:1",
        "key_id": "kid-1",
    }
    api_result = _redact_decision(api_key_vote)
    assert api_result.get("reviewer_role") == "vera_prod"
    assert "approver" not in api_result


def test_serialize_approval_for_dashboard_redacts_decisions(db_session):
    """End-to-end: serializer applies ``_redact_decision`` to every vote.

    Build an Approval with two reviewer votes — one with PHI in the
    note, one with PII in the approver — and confirm both are gone.
    """
    approval = Approval(
        id="ap-redact-1",
        org_id="org-1",
        requested_by_agent="agent",
        action_name="commit",
        data_subject_id="patient-42",
        action_summary="PHI-laden summary",
        context={},
        risk_tier="high",
        approvers_required=1,
        status="approved",
        decisions=[
            {
                "decision": "approve",
                "approver": "alice@hospital.example:attending_physician",
                "note": "MRN-31504806 — controlled substance approved.",
                "decided_at": "2026-05-24T13:00:00",
                "signature": "sig-1",
                "key_id": "kid-1",
            },
            {
                "decision": "approve",
                "approver": "drbob@hospital.example:dea_licensed_physician",
                "note": "Dual-attestation — co-signing for Schedule II.",
                "decided_at": "2026-05-24T13:05:00",
                "signature": "sig-2",
                "key_id": "kid-1",
            },
        ],
        requested_at=datetime(2026, 5, 24, 12, 0, 0),
        reviewed_below_threshold=False,
    )
    result = serialize_approval_for_dashboard(approval)
    assert len(result["decisions"]) == 2
    for vote in result["decisions"]:
        assert "approver" not in vote
        assert "note" not in vote
        assert vote["signature"].startswith("sig-")
    # Roles are surfaced — the dashboard can render the resolved status
    # ("Approved by attending_physician + dea_licensed_physician") without
    # the reviewer-id PII.
    roles = {v["reviewer_role"] for v in result["decisions"]}
    assert roles == {"attending_physician", "dea_licensed_physician"}
    # No fragment of the PHI / PII survived the serializer.
    body = str(result)
    assert "alice@hospital.example" not in body
    assert "drbob@hospital.example" not in body
    assert "MRN-31504806" not in body
    assert "controlled substance" not in body


def test_is_dashboard_request_predicate():
    """``api_key is None`` ↔ dashboard caller; populated APIKey ↔ SDK."""
    assert is_dashboard_request(None) is True
    # Any non-None object stands in for a populated APIKey row here —
    # the predicate is purely None-vs-not.
    assert is_dashboard_request(object()) is False


def test_serialize_decision_for_dashboard_returns_dict():
    """The decisions feed is already PHI-clean; serializer is a
    pass-through dict materializer for the route layer's shape contract."""
    from app.schemas.customer_decision import (
        CustomerDecisionResponse,
        CustomerDecisionRuling,
    )

    decision = CustomerDecisionResponse(
        id="ar-1",
        sequence_number=1,
        action_timestamp=datetime(2026, 5, 24, 12, 0, 0),
        agent_name="scribe-agent",
        action_name="commit_note",
        action_type="function_call",
        result="pending",
        ruling=CustomerDecisionRuling(
            effect="require_hitl",
            reason="gated",
            gate_name="new_diagnosis_gate",
            required_role="attending_physician",
        ),
    )
    result = serialize_decision_for_dashboard(decision)
    assert isinstance(result, dict)
    assert result["id"] == "ar-1"
    # No PHI keys were ever in the schema; the dict mirrors the model.
    assert "data_subject_id" not in result


# ── Approvals: dashboard (Clerk session) strips PHI ─────────────────────


@pytest.mark.asyncio
async def test_approvals_list_dashboard_strips_phi(
    async_client, db_session, clerk_seeded, keypair
):
    """Clerk dashboard GET /v1/approvals — no data_subject_id, context
    only has gate-metadata, action_summary stripped."""
    await _seed_approval(db_session, org_id=clerk_seeded["org_id"])

    resp = await async_client.get(
        "/v1/approvals", headers=_clerk_headers(keypair, clerk_seeded)
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 1
    [approval] = body["approvals"]

    assert approval["data_subject_id"] is None, "data_subject_id leaked"
    assert approval["action_summary"] is None, "action_summary leaked"
    context = approval["context"]
    for unsafe in _PHI_UNSAFE_KEYS:
        assert unsafe not in context, f"PHI key {unsafe!r} leaked in context"
    assert set(context.keys()) <= _PHI_SAFE_KEYS
    # Gate metadata preserved.
    assert context["gate_name"] == "new_diagnosis_gate"
    assert context["required_role"] == "attending_physician"
    assert context["citation"] == "CMS Final Rule §482.24"


@pytest.mark.asyncio
async def test_approvals_get_by_id_dashboard_strips_phi(
    async_client, db_session, clerk_seeded, keypair
):
    """Clerk dashboard GET /v1/approvals/{id} — same redaction as list."""
    approval = await _seed_approval(db_session, org_id=clerk_seeded["org_id"])

    resp = await async_client.get(
        f"/v1/approvals/{approval.id}",
        headers=_clerk_headers(keypair, clerk_seeded),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["data_subject_id"] is None
    assert body["action_summary"] is None
    for unsafe in _PHI_UNSAFE_KEYS:
        assert unsafe not in body["context"]
    assert body["context"]["gate_name"] == "new_diagnosis_gate"


@pytest.mark.asyncio
async def test_approvals_dashboard_preserves_operational_metadata(
    async_client, db_session, clerk_seeded, keypair
):
    """Dashboard must still see status, risk_tier, decisions, timestamps,
    and ``reviewed_below_threshold`` — they're operational metadata the
    compliance officer needs for chain-health monitoring."""
    approval = await _seed_approval(db_session, org_id=clerk_seeded["org_id"])
    approval.decisions = [
        {
            "decision": "approve",
            "approver": "dr-smith:attending_physician",
            "decided_at": "2026-05-24T13:00:00",
            "signature": "sig-abc",
            "key_id": "kid-1",
        }
    ]
    approval.risk_tier = "critical"
    approval.reviewed_below_threshold = True
    await db_session.commit()

    resp = await async_client.get(
        f"/v1/approvals/{approval.id}",
        headers=_clerk_headers(keypair, clerk_seeded),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["risk_tier"] == "critical"
    assert body["reviewed_below_threshold"] is True
    assert body["status"] == "pending"
    assert body["requested_at"] is not None
    assert len(body["decisions"]) == 1
    vote = body["decisions"][0]
    # W2.2: reviewer-id PII stripped, role derived.
    assert "approver" not in vote, "approver (reviewer_id) leaked on dashboard"
    assert vote.get("reviewer_role") == "attending_physician"
    assert vote["decision"] == "approve"
    assert vote["signature"] == "sig-abc"


@pytest.mark.asyncio
async def test_approvals_dashboard_strips_decision_note_and_approver(
    async_client, db_session, clerk_seeded, keypair
):
    """W2.2 — dashboard must strip the reviewer ``note`` (free-text PHI
    carrier) and ``approver`` (carries reviewer_id PII) from every
    ``decisions[]`` entry. The signed vote's signature + key_id stay so
    the audit chain story holds."""
    approval = await _seed_approval(db_session, org_id=clerk_seeded["org_id"])
    approval.decisions = [
        {
            "decision": "approve",
            "approver": "alice@hospital.example:attending_physician",
            "note": (
                "Approved — MRN-31504806 CT confirms pancreatitis, "
                "patient stable for discharge."
            ),
            "decided_at": "2026-05-24T13:00:00",
            "signature": "sig-1",
            "key_id": "kid-1",
        },
    ]
    await db_session.commit()

    resp = await async_client.get(
        f"/v1/approvals/{approval.id}",
        headers=_clerk_headers(keypair, clerk_seeded),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    [vote] = body["decisions"]
    assert "note" not in vote, "decisions[].note leaked (PHI narrative)"
    assert "approver" not in vote, "decisions[].approver leaked (reviewer_id PII)"
    # Role still surfaced for the read-only status indicator.
    assert vote.get("reviewer_role") == "attending_physician"
    # Negative content scan — no fragment of the PHI or PII survives.
    body_str = resp.text
    assert "alice@hospital.example" not in body_str
    assert "MRN-31504806" not in body_str
    assert "pancreatitis" not in body_str


@pytest.mark.asyncio
async def test_approvals_sdk_preserves_decision_note_and_approver(
    async_client, db_session, clerk_seeded
):
    """CRITICAL non-regression for W2.2: SDK callers (API key) MUST
    still see the full ``decisions[]`` shape — ``approver`` for HITL
    polling correlation, ``note`` for the customer's in-band review
    surface. Breaking this breaks every integration."""
    approval = await _seed_approval(db_session, org_id=clerk_seeded["org_id"])
    approval.decisions = [
        {
            "decision": "approve",
            "approver": "alice@hospital.example:attending_physician",
            "note": "Approved — MRN-31504806 CT confirms pancreatitis.",
            "decided_at": "2026-05-24T13:00:00",
            "signature": "sig-1",
            "key_id": "kid-1",
        }
    ]
    await db_session.commit()

    resp = await async_client.get(
        f"/v1/approvals/{approval.id}",
        headers=_sdk_headers(clerk_seeded),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    [vote] = body["decisions"]
    assert vote["approver"] == "alice@hospital.example:attending_physician"
    assert "MRN-31504806" in vote["note"]


@pytest.mark.asyncio
async def test_approvals_dashboard_legacy_approval_with_empty_context(
    async_client, db_session, clerk_seeded, keypair
):
    """Legacy approvals (no gate context populated) → response.context
    is {} not None, and the endpoint doesn't crash."""
    await _seed_approval(
        db_session, org_id=clerk_seeded["org_id"], context={}
    )

    resp = await async_client.get(
        "/v1/approvals", headers=_clerk_headers(keypair, clerk_seeded)
    )
    assert resp.status_code == 200, resp.text
    [approval] = resp.json()["approvals"]
    assert approval["context"] == {}


# ── Approvals: SDK (API key) preserves full shape — REGRESSION ──────────


@pytest.mark.asyncio
async def test_approvals_list_sdk_preserves_full_shape(
    async_client, db_session, clerk_seeded
):
    """CRITICAL non-regression: SDK callers (API key) MUST still see
    ``data_subject_id``, ``action_summary``, and the full ``context``
    blob. Breaking this breaks HITL polling + every in-band integration."""
    await _seed_approval(db_session, org_id=clerk_seeded["org_id"])

    resp = await async_client.get(
        "/v1/approvals", headers=_sdk_headers(clerk_seeded)
    )
    assert resp.status_code == 200, resp.text
    [approval] = resp.json()["approvals"]
    assert approval["data_subject_id"] == "patient_secret_id_42"
    assert "MRN-31504806" in approval["action_summary"]
    # Full PHI context preserved for in-band SDK consumers.
    ctx = approval["context"]
    assert ctx["patient_mrn"] == "MRN-31504806"
    assert ctx["diagnoses"] == ["acute pancreatitis", "dehydration"]
    assert ctx["encounter_id"] == "enc_pancreatitis_001"
    # Gate metadata also present (it always was).
    assert ctx["gate_name"] == "new_diagnosis_gate"


@pytest.mark.asyncio
async def test_approvals_get_by_id_sdk_preserves_full_shape(
    async_client, db_session, clerk_seeded
):
    """Same regression check on the single-fetch endpoint (SDK polling
    path)."""
    approval = await _seed_approval(db_session, org_id=clerk_seeded["org_id"])

    resp = await async_client.get(
        f"/v1/approvals/{approval.id}",
        headers=_sdk_headers(clerk_seeded),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["data_subject_id"] == "patient_secret_id_42"
    assert body["context"]["medication_orders"] == [
        "ondansetron IV PRN",
        "LR IV @ 100mL/hr",
    ]


# ── Decisions endpoint: dashboard + SDK both PHI-clean by schema ────────


@pytest.mark.asyncio
async def test_customer_decisions_dashboard_no_data_subject_id(
    async_client, db_session, clerk_seeded, keypair
):
    """Clerk dashboard GET /v1/customers/{tenant_id}/decisions — the
    response shape carries NO data_subject_id (the
    CustomerDecisionResponse schema never declared one)."""
    action = await _seed_action_and_customer(
        db_session, org_id=clerk_seeded["org_id"]
    )
    await _seed_approval(
        db_session,
        org_id=clerk_seeded["org_id"],
        request_record_id=action.id,
    )

    resp = await async_client.get(
        "/v1/customers/cleveland_clinic/decisions",
        headers=_clerk_headers(keypair, clerk_seeded),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    [decision] = body["decisions"]
    assert "data_subject_id" not in decision
    # Ruling exposes gate metadata only — no PHI passthrough from
    # Approval.context. The frontend uses these for the gate badge.
    ruling = decision["ruling"]
    assert ruling is not None
    assert ruling["gate_name"] == "new_diagnosis_gate"
    assert ruling["required_role"] == "attending_physician"
    # ``reason_detail`` is built from Approval.action_summary which the
    # gates commonly write with PHI baked in — must be nulled for
    # dashboard callers.
    assert ruling["reason_detail"] is None
    # And no PHI fields snuck into the ruling shape.
    ruling_str = str(ruling)
    assert "patient_mrn" not in ruling_str
    assert "MRN-" not in ruling_str
    assert "pancreatitis" not in ruling_str


@pytest.mark.asyncio
async def test_customer_decisions_sdk_full_shape_preserved(
    async_client, db_session, clerk_seeded
):
    """SDK key → same CustomerDecisionResponse shape (the schema is
    minimum-necessary by design; both callers get the same fields)."""
    action = await _seed_action_and_customer(
        db_session, org_id=clerk_seeded["org_id"]
    )
    await _seed_approval(
        db_session,
        org_id=clerk_seeded["org_id"],
        request_record_id=action.id,
    )

    resp = await async_client.get(
        "/v1/customers/cleveland_clinic/decisions",
        headers=_sdk_headers(clerk_seeded),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    [decision] = body["decisions"]
    assert decision["agent_name"] == "scribe-agent"
    assert decision["ruling"]["gate_name"] == "new_diagnosis_gate"
    # ``reason_detail`` (from Approval.action_summary) IS preserved for
    # SDK callers — the customer's in-band review surface uses it.
    assert decision["ruling"]["reason_detail"] is not None
    assert "MRN-31504806" in decision["ruling"]["reason_detail"]
    # The decisions feed never carried data_subject_id even for SDK
    # callers (Phase 1 contract); the SDK uses ``GET /v1/approvals/{id}``
    # when it needs the subject identifier.
    assert "data_subject_id" not in decision
