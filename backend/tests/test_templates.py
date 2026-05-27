"""Tests for the Phase 5 PR A templates surface.

Coverage matrix (mirrors the PR brief):

  * Migration round-trip
  * POST /generate requires wizard_completed_at
  * POST /generate first run produces 5 keys
  * POST /generate idempotent — second run still 5 generated, 0 skipped
  * POST /generate skips attested rows
  * GET / returns 5 rows; status = not_started when no rows
  * Status transitions (not_started → in_progress → counsel_attested)
  * PUT /{key} clears attestation fields atomically
  * POST /{key}/attest with counsel_attested=False → 400
  * POST /{key}/attest happy path persists hash/name/timestamp
  * Cross-org isolation
  * CA AB 489 conditional clause included only when ``california`` (or
    legacy ``us_ca``) is in jurisdictions
  * TX TRAIGA conditional clause
  * UT AIPA conditional clause
  * Deselecting jurisdictions on regen removes clauses from un-attested rows
  * Regenerate does NOT remove clauses from attested rows
  * Unknown template_key → 422
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import select

from app.models import GeneratedTemplate, Organization


# ── Seed helpers ─────────────────────────────────────────────────────


async def _seed_org_with_chain(db_session, name: str) -> Organization:
    from app.models import ChainState

    org = Organization(name=name)
    db_session.add(org)
    await db_session.flush()
    db_session.add(ChainState(org_id=org.id))
    await db_session.commit()
    await db_session.refresh(org)
    return org


def _complete_wizard_answers(jurisdictions=None) -> dict:
    """Return a valid wizard_answers blob for ``Organization.wizard_answers``."""
    return {
        "agent_type": "scribe",
        "agent_type_other": None,
        "jurisdictions": list(jurisdictions or ["us_federal"]),
        "decision_volume": "10k_100k",
        "channel": "in_app_webhook",
        "privacy_officer": {
            "name": "Alice Privacy",
            "email": "privacy@example.com",
        },
    }


async def _complete_wizard(db_session, org: Organization, *, jurisdictions=None) -> None:
    org.wizard_answers = _complete_wizard_answers(jurisdictions)
    org.wizard_completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    await db_session.commit()
    await db_session.refresh(org)


# ── 1. POST /generate — wizard incomplete → 400 ──────────────────────


@pytest.mark.asyncio
async def test_generate_requires_wizard_completed(async_client, org_and_key):
    org, raw_key, _ = org_and_key
    resp = await async_client.post(
        "/v1/templates/generate",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 400, resp.text
    body = resp.json()
    assert body["code"] == "wizard_incomplete"


# ── 2. POST /generate — first run produces 5 keys ────────────────────


@pytest.mark.asyncio
async def test_generate_first_run_returns_all_five(
    async_client, org_and_key, db_session
):
    org, raw_key, _ = org_and_key
    await _complete_wizard(db_session, org)

    resp = await async_client.post(
        "/v1/templates/generate",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["generated"]) == 5
    assert set(body["generated"]) == {
        "hipaa_risk_analysis",
        "section_1557_ndp",
        "ai_tool_inventory",
        "workforce_training_outline",
        "ai_care_disclosure",
    }
    assert body["skipped_attested"] == []

    rows = (
        (
            await db_session.execute(
                select(GeneratedTemplate).where(GeneratedTemplate.org_id == org.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 5
    for row in rows:
        assert row.markdown_body.startswith("# ")
        assert row.attested_at is None


# ── 3. POST /generate — second run still refreshes ───────────────────


@pytest.mark.asyncio
async def test_generate_second_run_refreshes_unattested(
    async_client, org_and_key, db_session
):
    org, raw_key, _ = org_and_key
    await _complete_wizard(db_session, org)

    first = await async_client.post(
        "/v1/templates/generate",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert first.status_code == 200

    second = await async_client.post(
        "/v1/templates/generate",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert second.status_code == 200, second.text
    body = second.json()
    assert len(body["generated"]) == 5
    assert body["skipped_attested"] == []


# ── 4. POST /generate — skips attested rows ──────────────────────────


@pytest.mark.asyncio
async def test_generate_skips_attested_rows(
    async_client, org_and_key, db_session
):
    org, raw_key, _ = org_and_key
    await _complete_wizard(db_session, org)

    # Initial generation.
    await async_client.post(
        "/v1/templates/generate",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    # Attest one row.
    attest_resp = await async_client.post(
        "/v1/templates/hipaa_risk_analysis/attest",
        headers={"Authorization": f"Bearer {raw_key}"},
        json={"counsel_attested": True, "reviewer_name": "Jane Doe"},
    )
    assert attest_resp.status_code == 200, attest_resp.text

    # Regenerate — that one should be skipped.
    regen = await async_client.post(
        "/v1/templates/generate",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    body = regen.json()
    assert "hipaa_risk_analysis" in body["skipped_attested"]
    assert "hipaa_risk_analysis" not in body["generated"]
    assert len(body["generated"]) == 4
    assert len(body["skipped_attested"]) == 1


# ── 5. GET / — list always 5 rows ────────────────────────────────────


@pytest.mark.asyncio
async def test_list_returns_five_rows_even_when_empty(
    async_client, org_and_key, db_session
):
    org, raw_key, _ = org_and_key
    resp = await async_client.get(
        "/v1/templates/",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200, resp.text
    items = resp.json()
    assert len(items) == 5
    keys = [it["template_key"] for it in items]
    assert keys == [
        "hipaa_risk_analysis",
        "section_1557_ndp",
        "ai_tool_inventory",
        "workforce_training_outline",
        "ai_care_disclosure",
    ]
    for it in items:
        assert it["status"] == "not_started"
        assert it["attested_at"] is None
        assert it["attested_by_name"] is None
        assert it["updated_at"] is None


# ── 6. Status transitions ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_status_transitions_through_lifecycle(
    async_client, org_and_key, db_session
):
    org, raw_key, _ = org_and_key
    await _complete_wizard(db_session, org)

    # not_started → list says not_started for all keys.
    resp = await async_client.get(
        "/v1/templates/",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    for it in resp.json():
        assert it["status"] == "not_started"

    # Generate → in_progress.
    await async_client.post(
        "/v1/templates/generate",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    resp = await async_client.get(
        "/v1/templates/",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    for it in resp.json():
        assert it["status"] == "in_progress"

    # Attest one → that one flips to counsel_attested; others stay in_progress.
    await async_client.post(
        "/v1/templates/section_1557_ndp/attest",
        headers={"Authorization": f"Bearer {raw_key}"},
        json={"counsel_attested": True, "reviewer_name": "Bob Counsel"},
    )
    resp = await async_client.get(
        "/v1/templates/",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    by_key = {it["template_key"]: it for it in resp.json()}
    assert by_key["section_1557_ndp"]["status"] == "counsel_attested"
    assert by_key["section_1557_ndp"]["attested_by_name"] == "Bob Counsel"
    assert by_key["hipaa_risk_analysis"]["status"] == "in_progress"


# ── 7. PUT clears attestation atomically ─────────────────────────────


@pytest.mark.asyncio
async def test_put_clears_attestation_fields_atomically(
    async_client, org_and_key, db_session
):
    org, raw_key, _ = org_and_key
    await _complete_wizard(db_session, org)
    await async_client.post(
        "/v1/templates/generate",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    attest = await async_client.post(
        "/v1/templates/hipaa_risk_analysis/attest",
        headers={"Authorization": f"Bearer {raw_key}"},
        json={"counsel_attested": True, "reviewer_name": "Jane Doe"},
    )
    assert attest.status_code == 200
    assert attest.json()["status"] == "counsel_attested"

    put = await async_client.put(
        "/v1/templates/hipaa_risk_analysis",
        headers={"Authorization": f"Bearer {raw_key}"},
        json={"markdown_body": "# Edited body\n\nNew content."},
    )
    assert put.status_code == 200, put.text
    body = put.json()
    assert body["status"] == "in_progress"
    assert body["attested_at"] is None
    assert body["attested_by_user_id"] is None
    assert body["attested_by_name"] is None
    assert body["content_hash_at_attestation"] is None
    assert body["markdown_body"].startswith("# Edited body")


# ── 8. Attest without counsel_attested=True → 400 ────────────────────


@pytest.mark.asyncio
async def test_attest_requires_counsel_attested_true(
    async_client, org_and_key, db_session
):
    org, raw_key, _ = org_and_key
    await _complete_wizard(db_session, org)
    await async_client.post(
        "/v1/templates/generate",
        headers={"Authorization": f"Bearer {raw_key}"},
    )

    resp = await async_client.post(
        "/v1/templates/hipaa_risk_analysis/attest",
        headers={"Authorization": f"Bearer {raw_key}"},
        json={"counsel_attested": False, "reviewer_name": "Jane Doe"},
    )
    assert resp.status_code == 400, resp.text
    body = resp.json()
    assert body["code"] == "counsel_attestation_required"


# ── 9. Attest happy path persists hash + name + timestamp ────────────


@pytest.mark.asyncio
async def test_attest_persists_hash_name_timestamp(
    async_client, org_and_key, db_session
):
    org, raw_key, api_key = org_and_key
    await _complete_wizard(db_session, org)
    await async_client.post(
        "/v1/templates/generate",
        headers={"Authorization": f"Bearer {raw_key}"},
    )

    resp = await async_client.post(
        "/v1/templates/hipaa_risk_analysis/attest",
        headers={"Authorization": f"Bearer {raw_key}"},
        json={"counsel_attested": True, "reviewer_name": "Jane Doe"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["attested_by_name"] == "Jane Doe"
    assert body["attested_at"] is not None
    assert body["content_hash_at_attestation"] is not None
    assert len(body["content_hash_at_attestation"]) == 64
    # The hash matches SHA-256 of the body.
    expected = hashlib.sha256(body["markdown_body"].encode("utf-8")).hexdigest()
    assert body["content_hash_at_attestation"] == expected
    # API-key attestation records the API key id as the user id.
    assert body["attested_by_user_id"] == api_key.id


# ── 10. Cross-org isolation ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_cross_org_isolation(async_client, org_and_key, db_session):
    org_a, raw_key_a, _ = org_and_key
    await _complete_wizard(db_session, org_a)
    await async_client.post(
        "/v1/templates/generate",
        headers={"Authorization": f"Bearer {raw_key_a}"},
    )

    # Org B with its own templates.
    from app.services.auth import generate_api_key
    org_b = await _seed_org_with_chain(db_session, "other-org-templates")
    raw_key_b, _ = await generate_api_key(
        db_session, org_b.id, "key-b", ["read", "write", "admin"]
    )
    await _complete_wizard(db_session, org_b)
    await async_client.post(
        "/v1/templates/generate",
        headers={"Authorization": f"Bearer {raw_key_b}"},
    )

    # Org B attests one row.
    await async_client.post(
        "/v1/templates/hipaa_risk_analysis/attest",
        headers={"Authorization": f"Bearer {raw_key_b}"},
        json={"counsel_attested": True, "reviewer_name": "Org B Counsel"},
    )

    # Org A's list must not see org B's data.
    resp_a = await async_client.get(
        "/v1/templates/",
        headers={"Authorization": f"Bearer {raw_key_a}"},
    )
    by_key = {it["template_key"]: it for it in resp_a.json()}
    assert by_key["hipaa_risk_analysis"]["attested_by_name"] is None
    assert by_key["hipaa_risk_analysis"]["status"] == "in_progress"


# ── 11. CA AB 489 conditional ────────────────────────────────────────


@pytest.mark.asyncio
async def test_ca_clause_present_when_california_selected(
    async_client, org_and_key, db_session
):
    org, raw_key, _ = org_and_key
    await _complete_wizard(
        db_session, org, jurisdictions=["us_federal", "california"]
    )
    await async_client.post(
        "/v1/templates/generate",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    resp = await async_client.get(
        "/v1/templates/ai_care_disclosure",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200
    body_md = resp.json()["markdown_body"]
    assert "California (AB 489)" in body_md


@pytest.mark.asyncio
async def test_ca_clause_absent_when_california_not_selected(
    async_client, org_and_key, db_session
):
    org, raw_key, _ = org_and_key
    await _complete_wizard(db_session, org, jurisdictions=["us_federal"])
    await async_client.post(
        "/v1/templates/generate",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    resp = await async_client.get(
        "/v1/templates/ai_care_disclosure",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    body_md = resp.json()["markdown_body"]
    assert "California (AB 489)" not in body_md


# ── 12. TX TRAIGA conditional ────────────────────────────────────────


@pytest.mark.asyncio
async def test_tx_clause_present_when_texas_selected(
    async_client, org_and_key, db_session
):
    org, raw_key, _ = org_and_key
    await _complete_wizard(
        db_session, org, jurisdictions=["us_federal", "texas"]
    )
    await async_client.post(
        "/v1/templates/generate",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    resp = await async_client.get(
        "/v1/templates/ai_care_disclosure",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    body_md = resp.json()["markdown_body"]
    assert "Texas (TRAIGA)" in body_md
    assert "California (AB 489)" not in body_md


# ── 13. UT AIPA conditional ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_ut_clause_present_when_utah_selected(
    async_client, org_and_key, db_session
):
    org, raw_key, _ = org_and_key
    await _complete_wizard(
        db_session, org, jurisdictions=["us_federal", "utah"]
    )
    await async_client.post(
        "/v1/templates/generate",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    resp = await async_client.get(
        "/v1/templates/ai_care_disclosure",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    body_md = resp.json()["markdown_body"]
    assert "Utah (AIPA)" in body_md


# ── 14. Deselect jurisdiction removes clause on un-attested row ──────


@pytest.mark.asyncio
async def test_deselecting_jurisdiction_removes_clause_on_unattested(
    async_client, org_and_key, db_session
):
    org, raw_key, _ = org_and_key
    await _complete_wizard(
        db_session, org, jurisdictions=["us_federal", "california", "texas"]
    )
    await async_client.post(
        "/v1/templates/generate",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    resp = await async_client.get(
        "/v1/templates/ai_care_disclosure",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert "California (AB 489)" in resp.json()["markdown_body"]
    assert "Texas (TRAIGA)" in resp.json()["markdown_body"]

    # Reduce jurisdictions to just federal.
    await _complete_wizard(db_session, org, jurisdictions=["us_federal"])
    await async_client.post(
        "/v1/templates/generate",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    resp = await async_client.get(
        "/v1/templates/ai_care_disclosure",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    md = resp.json()["markdown_body"]
    assert "California (AB 489)" not in md
    assert "Texas (TRAIGA)" not in md


# ── 15. Attested rows survive jurisdiction deselect ──────────────────


@pytest.mark.asyncio
async def test_regenerate_preserves_attested_clauses(
    async_client, org_and_key, db_session
):
    org, raw_key, _ = org_and_key
    await _complete_wizard(
        db_session, org, jurisdictions=["us_federal", "california"]
    )
    await async_client.post(
        "/v1/templates/generate",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    # Attest the disclosure with the CA clause baked in.
    await async_client.post(
        "/v1/templates/ai_care_disclosure/attest",
        headers={"Authorization": f"Bearer {raw_key}"},
        json={"counsel_attested": True, "reviewer_name": "Counsel A"},
    )

    # Reduce jurisdictions, regenerate. Attested row stays intact.
    await _complete_wizard(db_session, org, jurisdictions=["us_federal"])
    regen = await async_client.post(
        "/v1/templates/generate",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert "ai_care_disclosure" in regen.json()["skipped_attested"]

    resp = await async_client.get(
        "/v1/templates/ai_care_disclosure",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    md = resp.json()["markdown_body"]
    assert "California (AB 489)" in md  # untouched because attested


# ── 16. Unknown template_key → 422 ───────────────────────────────────


@pytest.mark.asyncio
async def test_unknown_template_key_returns_422(
    async_client, org_and_key, db_session
):
    org, raw_key, _ = org_and_key
    await _complete_wizard(db_session, org)

    resp = await async_client.get(
        "/v1/templates/bogus_key",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 422, resp.text
    body = resp.json()
    assert body["code"] == "unknown_template_key"


# ── 17. GET /{key} 404 when row missing ──────────────────────────────


@pytest.mark.asyncio
async def test_get_returns_404_when_row_missing(
    async_client, org_and_key, db_session
):
    org, raw_key, _ = org_and_key
    # Wizard not completed; valid key, but no row.
    resp = await async_client.get(
        "/v1/templates/hipaa_risk_analysis",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 404, resp.text


# ── 18. Migration round-trip ─────────────────────────────────────────


def test_templates_migration_reversible(monkeypatch):
    """Alembic stamp parent → upgrade → downgrade → upgrade succeeds."""
    import logging.config as _logging_config
    import tempfile

    from alembic import command
    from alembic.config import Config

    monkeypatch.setattr(_logging_config, "fileConfig", lambda *a, **k: None)

    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "alembic_test.db"
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")

        cfg = Config(str(_here_root() / "alembic.ini"))
        cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")

        command.stamp(cfg, "w4a7b8c9d0e1")
        command.upgrade(cfg, "w5b8c9d0e1f2")
        command.downgrade(cfg, "w4a7b8c9d0e1")
        command.upgrade(cfg, "w5b8c9d0e1f2")


def _here_root() -> Path:
    return Path(__file__).resolve().parent.parent
