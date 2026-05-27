"""Tests for ``POST /v1/compliance/insights`` (Phase 4 Wave 2 PR B2).

AI Insights endpoint — OpenAI-backed 3-5 recommendation cards over the
live compliance posture snapshot.

Covers:

  * Happy path → mocked OpenAI returns 3 valid cards; endpoint returns
    them + disclaimer + posture_snapshot.
  * Clamp (low): 2 cards → 3 returned (1 fallback).
  * Clamp (high): 7 cards → 5 returned (first 5).
  * Hallucinated quoted_source → fallback card.
  * Whitespace-tolerant + case-insensitive quoted_source validation.
  * Severity clamp on unknown value.
  * Disclaimer is server-hard-coded, never trust model output.
  * Timeout → 504 with error.code == "insights_timeout".
  * Invalid JSON retries once then fallback.
  * Rate limit: 11th call in <1min gets 429 + Retry-After: 60.
  * Cross-org isolation: org A admin only sees org A's posture.
  * Staff audit row written on STAFF_READ_ONLY call.
  * IAM regression: no ctx.tier == IamTier.X in new code.
  * posture_snapshot byte-equals GET /v1/compliance/posture.

The OpenAI client is mocked at the SDK level via monkeypatching the
``_openai_client`` helper — no real network calls.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.models import (
    Approval,
    ChainState,
    Customer,
    Organization,
    StaffAuditLog,
)
from app.schemas.insights import INSIGHTS_DISCLAIMER
from app.services.insights import generator as insights_generator
from app.services.insights import rate_limit as insights_rate_limit


# ── Helpers / fixtures ─────────────────────────────────────────────


def _utc_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def _seed_org(db_session, name: str) -> Organization:
    org = Organization(name=name, checkpoint_cadence="daily")
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


async def _seed_approval(
    db_session,
    org_id: str,
    *,
    requested_at: datetime,
    decided_at: datetime | None,
    required_role: str = "physician",
    reviewer_role: str = "physician",
    decision: str = "approve",
):
    context: dict = {"gate_name": "g", "required_role": required_role}
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
    )
    db_session.add(approval)
    await db_session.commit()
    await db_session.refresh(approval)
    return approval


class _FakeResponse:
    """Stand-in for an OpenAI Responses-API response object.

    Exposes the ``output_text`` convenience accessor that
    :func:`_call_openai` reads in its fast path. The text mirrors the
    raw JSON the model would have emitted; the validator + parser take
    it from there.
    """

    def __init__(self, output_text: str):
        self.output_text = output_text
        # Keep ``output`` empty so the generator's fast-path
        # (``output_text``) is the one exercised — matches the real
        # SDK's behaviour when the convenience accessor is populated.
        self.output: list = []


class _FakeResponses:
    """Mock the ``client.responses`` namespace.

    Each call to :meth:`create` returns the next queued response (in
    insertion order) or raises if a pre-seeded exception is at the
    head of the queue. ``_call_log`` captures every kwargs payload so
    tests can assert what was sent to the model.
    """

    def __init__(self, *items, call_log: list[dict]):
        self._items = list(items)
        self._call_log = call_log

    async def create(self, **kwargs):
        self._call_log.append(kwargs)
        idx = len(self._call_log) - 1
        if idx >= len(self._items):
            # Default fallback: empty output → forces fallback path.
            return _FakeResponse("")
        item = self._items[idx]
        if isinstance(item, BaseException):
            raise item
        if isinstance(item, str):
            return _FakeResponse(item)
        # Pre-built response object — return as-is.
        return item


class _FakeOpenAI:
    """Minimal stand-in for :class:`openai.AsyncOpenAI`.

    Exposes only the ``responses.create`` surface the generator uses.
    Tests inspect :attr:`_call_log` to assert what was sent to the
    model (e.g. cross-org isolation).
    """

    def __init__(self, *items):
        self._call_log: list[dict] = []
        self.responses = _FakeResponses(*items, call_log=self._call_log)


def _install_fake_openai(monkeypatch, *responses):
    """Install a mock OpenAI client whose ``responses.create`` returns
    ``responses[i]`` on the (i+1)th call. Responses can be either:

    * a string  → wrapped via :class:`_FakeResponse` and surfaced as
      ``output_text``.
    * an Exception → raised on that call.
    * a pre-built response object → returned as-is.

    Returns the mock client so callers can inspect ``_call_log``.
    """
    fake = _FakeOpenAI(*responses)
    monkeypatch.setattr(insights_generator, "_openai_client", lambda: fake)
    return fake


@pytest.fixture(autouse=True)
def _reset_insights_state():
    """Drop the rate-limit buckets + cached OpenAI client between tests.

    The rate limiter is process-global by design (multi-instance v1 is
    out of scope); we have to scrub it manually per test so a test
    that hits the limit doesn't poison the next test's counter.
    """
    insights_rate_limit._reset_for_tests()
    insights_generator._reset_client_cache()
    yield
    insights_rate_limit._reset_for_tests()
    insights_generator._reset_client_cache()


@pytest_asyncio.fixture
async def staff_headers(monkeypatch):
    """Stub Clerk JWT verification for staff."""
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


# A canonical card the model "produces" — its quoted_source is a
# literal substring of the posture payload returned in the happy
# path, so the validator accepts it.
def _good_card(
    *,
    title: str = "Reviewer role coverage is low this window",
    severity: str = "HIGH",
    # The string "hitl_completion" appears in the posture payload as
    # the dimension name → always a valid substring.
    quoted_source: str = "hitl_completion",
    description: str = "The hitl_completion dimension is below threshold.",
    suggested_action: str = (
        "Consider auditing reviewer assignments over the past week."
    ),
) -> dict:
    return {
        "id": "ignored",  # server overwrites
        "title": title,
        "severity": severity,
        "quoted_source": quoted_source,
        "description": description,
        "suggested_action": suggested_action,
    }


def _good_payload(n: int = 3) -> str:
    """JSON-encoded ``{"insights": [...]}`` with ``n`` good cards."""
    return json.dumps({"insights": [_good_card() for _ in range(n)]})


# ── Happy path ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_insights_happy_path(
    async_client, db_session, org_and_key, monkeypatch
):
    """Mock OpenAI returns 3 valid cards → endpoint returns 3 cards +
    disclaimer + posture_snapshot."""
    org, raw_key, _ = org_and_key

    _install_fake_openai(monkeypatch, _good_payload(3))

    resp = await async_client.post(
        "/v1/compliance/insights",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["insights"]) == 3
    for card in body["insights"]:
        assert card["severity"] in {"HIGH", "MEDIUM", "LOW"}
        assert card["id"]  # server-generated UUID
        assert card["title"]
        assert card["quoted_source"]
        assert card["description"]
        assert card["suggested_action"]
    assert body["disclaimer"] == INSIGHTS_DISCLAIMER
    assert body["window_days"] == 30
    assert "posture_snapshot" in body
    snapshot = body["posture_snapshot"]
    assert "composite_headline" in snapshot
    assert "measured" in snapshot
    assert "not_yet_eligible" in snapshot


# ── Clamp count: too few ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_insights_clamps_to_3_when_llm_returns_2(
    async_client, db_session, org_and_key, monkeypatch
):
    """Mock 2 cards → response carries 3 (1 fallback padded)."""
    org, raw_key, _ = org_and_key

    _install_fake_openai(monkeypatch, _good_payload(2))

    resp = await async_client.post(
        "/v1/compliance/insights",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["insights"]) == 3
    # One of the cards is the fallback ("Insufficient signal" / etc).
    # Detected via the canonical fallback title.
    titles = [c["title"] for c in body["insights"]]
    assert any("Insufficient" in t or "specific recommendation" in t for t in titles)


# ── Clamp count: too many ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_insights_clamps_to_5_when_llm_returns_7(
    async_client, db_session, org_and_key, monkeypatch
):
    """Mock 7 cards → response carries 5 (first 5)."""
    org, raw_key, _ = org_and_key

    _install_fake_openai(monkeypatch, _good_payload(7))

    resp = await async_client.post(
        "/v1/compliance/insights",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["insights"]) == 5


# ── Quoted-source validation: hallucination ────────────────────────


@pytest.mark.asyncio
async def test_insights_quoted_source_validation_rejects_hallucination(
    async_client, db_session, org_and_key, monkeypatch
):
    """Card with a quoted_source not in posture → replaced with
    fallback. Hallucinated quote: "The org has 999999 actions"."""
    org, raw_key, _ = org_and_key

    # 3 cards — one with a hallucinated quote, two valid. After
    # validation: 2 valid + 1 fallback = 3 cards.
    payload = json.dumps(
        {
            "insights": [
                _good_card(),
                _good_card(quoted_source="The org has 999999 actions"),
                _good_card(),
            ]
        }
    )
    _install_fake_openai(monkeypatch, payload)

    resp = await async_client.post(
        "/v1/compliance/insights",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["insights"]) == 3
    # Exactly one fallback card replaced the hallucination. Detected
    # by either the fallback title sentinel OR the fallback
    # quoted_source ("Insufficient signal").
    quoted_sources = [c["quoted_source"] for c in body["insights"]]
    assert "Insufficient signal" in quoted_sources
    # The original hallucinated quote is NOT present.
    assert "The org has 999999 actions" not in quoted_sources


# ── Quoted-source validation: whitespace-tolerant ──────────────────


@pytest.mark.asyncio
async def test_insights_quoted_source_validation_whitespace_tolerant(
    async_client, db_session, org_and_key, monkeypatch
):
    """Extra spaces in quoted_source → accepted, no fallback substitution."""
    org, raw_key, _ = org_and_key
    customer = await _seed_customer(db_session, org.id, "cust-w")
    now = _utc_naive()
    # Seed enough approvals to produce a "12 of 14" style fact line.
    for i in range(14):
        await _seed_approval(
            db_session,
            org.id,
            requested_at=now - timedelta(hours=i + 1),
            decided_at=(
                now - timedelta(hours=i + 1, minutes=-30)
                if i < 12
                else None  # 2 still pending → "12 of 14"
            ),
        )

    # The posture's HITL fact line reads
    # "14 HITL events requested · 12 decided before commit". We quote
    # part of it with extra whitespace + mixed case so the validator's
    # whitespace-tolerant, case-insensitive match kicks in. Note the
    # different capitalisation ("Hitl") and the double space.
    payload = json.dumps(
        {
            "insights": [
                _good_card(
                    quoted_source="14  Hitl events requested",
                    title="HITL completion is slipping",
                ),
                _good_card(),
                _good_card(),
            ]
        }
    )
    _install_fake_openai(monkeypatch, payload)

    resp = await async_client.post(
        "/v1/compliance/insights",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    quoted_sources = [c["quoted_source"] for c in body["insights"]]
    # The whitespace-varied, mixed-case quote survives — not replaced
    # by a fallback "Insufficient signal" card.
    assert "14  Hitl events requested" in quoted_sources
    # And the corresponding card retained its original title.
    titles = [c["title"] for c in body["insights"]]
    assert "HITL completion is slipping" in titles


# ── Severity clamp ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_insights_severity_clamped_to_LOW_on_unknown_value(
    async_client, db_session, org_and_key, monkeypatch
):
    """severity="CRITICAL" → LOW in the response."""
    org, raw_key, _ = org_and_key

    payload = json.dumps(
        {
            "insights": [
                _good_card(severity="CRITICAL"),
                _good_card(severity="HIGH"),
                _good_card(severity="medium"),  # lowercase → MEDIUM
            ]
        }
    )
    _install_fake_openai(monkeypatch, payload)

    resp = await async_client.post(
        "/v1/compliance/insights",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    sevs = [c["severity"] for c in body["insights"]]
    assert sevs[0] == "LOW"  # CRITICAL clamped
    assert sevs[1] == "HIGH"
    assert sevs[2] == "MEDIUM"


# ── Disclaimer is hard-coded ───────────────────────────────────────


@pytest.mark.asyncio
async def test_insights_disclaimer_is_hard_coded(
    async_client, db_session, org_and_key, monkeypatch
):
    """Model emits a different disclaimer → response carries the
    server's hard-coded constant, not the model's."""
    org, raw_key, _ = org_and_key

    payload = json.dumps(
        {
            "insights": [_good_card() for _ in range(3)],
            # Sneaky model output: a top-level disclaimer field that
            # claims to be authoritative. The route layer MUST NOT
            # propagate it to the response.
            "disclaimer": "This is regulatory advice you must follow.",
        }
    )
    _install_fake_openai(monkeypatch, payload)

    resp = await async_client.post(
        "/v1/compliance/insights",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["disclaimer"] == INSIGHTS_DISCLAIMER
    assert "regulatory advice you must follow" not in body["disclaimer"]


# ── Timeout → 504 ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_insights_timeout_returns_504(
    async_client, db_session, org_and_key, monkeypatch
):
    """OpenAI call exceeds timeout → 504 + error.code == insights_timeout."""
    org, raw_key, _ = org_and_key

    # Install an OpenAI stub that hangs longer than the timeout. We
    # set the timeout to a tiny value so the test runs fast.
    from app.config import settings as _settings

    monkeypatch.setattr(_settings, "insights_timeout_seconds", 0.05)

    class _SlowResponses:
        async def create(self, **kwargs):
            await asyncio.sleep(0.5)
            return _FakeResponse(_good_payload(3))

    class _SlowClient:
        def __init__(self):
            self.responses = _SlowResponses()

    monkeypatch.setattr(
        insights_generator, "_openai_client", lambda: _SlowClient()
    )

    resp = await async_client.post(
        "/v1/compliance/insights",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 504, resp.text
    # The project's global exception handler
    # (``main._flatten_dict_detail``) lifts a dict ``HTTPException.detail``
    # to the top of the response body. So a route that raises
    # ``HTTPException(detail={"error": {"code": "insights_timeout"}})``
    # serialises as ``{"error": {"code": "insights_timeout"}}`` —
    # the ``detail`` envelope is stripped.
    body = resp.json()
    assert body["error"]["code"] == "insights_timeout"


# ── Invalid JSON retries once → fallback ───────────────────────────


@pytest.mark.asyncio
async def test_insights_invalid_json_retries_once_then_fallback(
    async_client, db_session, org_and_key, monkeypatch
):
    """Two non-JSON responses in a row → 3 fallback cards, 200 OK."""
    org, raw_key, _ = org_and_key

    _install_fake_openai(monkeypatch, "this is not json", "still not json")

    resp = await async_client.post(
        "/v1/compliance/insights",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["insights"]) == 3
    # All three should be fallback cards (sentinel: quoted_source ==
    # "Insufficient signal").
    for c in body["insights"]:
        assert c["quoted_source"] == "Insufficient signal"


# ── Rate limit: 11th call gets 429 + Retry-After: 60 ───────────────


@pytest.mark.asyncio
async def test_insights_rate_limit_429(
    async_client, db_session, org_and_key, monkeypatch
):
    """11 calls in <1min from the same org → 11th gets 429 + Retry-After."""
    org, raw_key, _ = org_and_key

    _install_fake_openai(
        monkeypatch,
        *[_good_payload(3) for _ in range(20)],
    )

    headers = {"Authorization": f"Bearer {raw_key}"}
    # First 10 succeed.
    for i in range(10):
        resp = await async_client.post(
            "/v1/compliance/insights", headers=headers
        )
        assert resp.status_code == 200, f"call {i} failed: {resp.text}"

    # 11th gets 429.
    resp = await async_client.post(
        "/v1/compliance/insights", headers=headers
    )
    assert resp.status_code == 429, resp.text
    assert "Retry-After" in resp.headers
    # Retry-After should be roughly 60 seconds (the brief specifies 60).
    retry_after = int(resp.headers["Retry-After"])
    assert 1 <= retry_after <= 61
    body = resp.json()
    # Per ``main._flatten_dict_detail``: dict detail flattens to top level.
    assert body["error"]["code"] == "insights_rate_limited"


# ── Cross-org isolation ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_insights_cross_org_isolation(
    async_client, db_session, org_and_key, monkeypatch
):
    """Customer admin for org A → insights generated for org A only.

    Concretely: when we hand OpenAI the posture payload, that payload
    is computed for org A. We inspect the captured user message and
    assert org B's id does NOT appear in it.
    """
    org_a, raw_key_a, _ = org_and_key
    org_b = await _seed_org(db_session, "other-org-b")

    # Seed data on org B that, if scope leaked, would surface in the
    # posture payload.
    now = _utc_naive()
    for i in range(20):
        await _seed_approval(
            db_session,
            org_b.id,
            requested_at=now - timedelta(hours=i + 1),
            decided_at=now - timedelta(hours=i, minutes=30),
        )

    mock_client = _install_fake_openai(monkeypatch, _good_payload(3))

    resp = await async_client.post(
        "/v1/compliance/insights",
        headers={"Authorization": f"Bearer {raw_key_a}"},
    )
    assert resp.status_code == 200, resp.text

    # Inspect what was sent to OpenAI — org B's id should not appear.
    assert len(mock_client._call_log) >= 1
    # The Responses-API call shape: ``input`` is a list of
    # ``{role, content}`` dicts. The user message carries the posture
    # payload.
    input_arr = mock_client._call_log[0]["input"]
    user_msgs = [m for m in input_arr if m.get("role") == "user"]
    assert user_msgs, "expected at least one user message in input"
    user_msg = user_msgs[0]["content"]
    assert org_b.id not in user_msg, (
        f"cross-org leak: org B id {org_b.id!r} appeared in user message"
    )


# ── Staff audit row written ────────────────────────────────────────


@pytest.mark.asyncio
async def test_insights_staff_audit_row_written(
    async_client, db_session, staff_headers, monkeypatch
):
    """STAFF_READ_ONLY POST → audit row with resource_type=compliance_insights."""
    customer = await _seed_org(db_session, "customer-org-z")

    _install_fake_openai(monkeypatch, _good_payload(3))

    resp = await async_client.post(
        "/v1/compliance/insights",
        headers={**staff_headers, "X-Org-Id": customer.id},
    )
    assert resp.status_code == 200, resp.text

    rows = (
        await db_session.execute(
            select(StaffAuditLog).where(
                StaffAuditLog.org_id == customer.id,
                StaffAuditLog.resource_type == "compliance_insights",
            )
        )
    ).scalars().all()
    assert len(rows) == 1
    row = rows[0]
    assert row.staff_id == "staff-user-1"
    assert row.endpoint == "/v1/compliance/insights"
    assert row.redacted is False
    assert row.resource_count == 1


# ── IAM regression: no enum equality antipattern ───────────────────


def test_insights_iam_tier_uses_helpers_not_enum():
    """Regression: the new insights code branches via ``ctx.is_staff`` /
    ``ctx.is_customer`` helpers, never via a direct
    ``ctx.tier == IamTier.X`` comparison. Mirrors the posture test
    pattern; the project-wide CI lint
    (``scripts/check_iam_tier_usage.sh``) is the canonical gate, but
    asserting it locally catches regressions in unit time.
    """
    import re

    pattern = re.compile(
        r"(ctx\.tier\s*==\s*IamTier\.|IamTier\.[A-Z_]+\s*==\s*ctx\.tier)"
    )
    new_files = [
        Path(__file__).resolve().parent.parent / "app" / "routes" / "compliance.py",
        Path(__file__).resolve().parent.parent
        / "app"
        / "services"
        / "insights"
        / "generator.py",
        Path(__file__).resolve().parent.parent
        / "app"
        / "services"
        / "insights"
        / "validator.py",
        Path(__file__).resolve().parent.parent
        / "app"
        / "services"
        / "insights"
        / "rate_limit.py",
    ]
    for path in new_files:
        text = path.read_text()
        for lineno, line in enumerate(text.splitlines(), start=1):
            stripped = line.lstrip()
            if stripped.startswith("#"):
                continue
            assert not pattern.search(line), (
                f"{path}:{lineno}: forbidden ctx.tier == IamTier.X "
                f"comparison — use ctx.is_staff / ctx.is_customer "
                f"instead. Offending line: {line!r}"
            )

    # Belt-and-braces: invoke the project-wide script.
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


# ── posture_snapshot matches GET /v1/compliance/posture ────────────


@pytest.mark.asyncio
async def test_insights_posture_snapshot_matches_get_posture(
    async_client, db_session, org_and_key, monkeypatch
):
    """The ``posture_snapshot`` field is byte-equal (modulo
    ``computed_at`` clock drift) to what ``GET /v1/compliance/posture``
    returns for the same org + default window. Documents that the
    field is for transparency, not a parallel implementation.
    """
    org, raw_key, _ = org_and_key

    _install_fake_openai(monkeypatch, _good_payload(3))

    headers = {"Authorization": f"Bearer {raw_key}"}

    insights_resp = await async_client.post(
        "/v1/compliance/insights", headers=headers
    )
    assert insights_resp.status_code == 200, insights_resp.text
    snapshot = insights_resp.json()["posture_snapshot"]

    posture_resp = await async_client.get(
        "/v1/compliance/posture", headers=headers
    )
    assert posture_resp.status_code == 200, posture_resp.text
    posture = posture_resp.json()

    # Compare structural keys + values, excluding ``computed_at``
    # (each call regenerates the timestamp).
    snapshot_no_ts = {k: v for k, v in snapshot.items() if k != "computed_at"}
    posture_no_ts = {k: v for k, v in posture.items() if k != "computed_at"}
    assert snapshot_no_ts == posture_no_ts
