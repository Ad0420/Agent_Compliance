"""
Tests for the Policy Enforcement Engine.

Covers:
1. Unit: each of the 5 condition evaluators
2. Integration: action record triggers policy → policies_applied contains result
3. Integration: violation row created in DB after triggering action
4. API: create/list/update/delete policies
5. API: list violations with filters (severity, resolved, policy_id)
6. API: resolve violation
7. Email: policy with action="email" triggers send_policy_violation_alert
8. Edge: inactive policy does not fire
9. Edge: org with no policies — record writes normally
10. Batch: batch inserts skip policy evaluation, policies_applied = []
"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio

from app.models import Organization, ChainState, Policy, PolicyViolation
from app.schemas.action import ActionRecordCreate
from app.services.auth import generate_api_key
from app.services.chain import build_and_insert_record, build_and_insert_batch
from app.services.policy_engine import evaluate_policies


# ── Helpers ─────────────────────────────────────────────────────────────────


def _make_action(**kwargs) -> ActionRecordCreate:
    defaults = dict(
        action_name="test_action",
        agent_name="test-agent",
        result="success",
    )
    defaults.update(kwargs)
    return ActionRecordCreate(**defaults)


async def _create_policy(session, org_id, **kwargs):
    """Helper to create a Policy in the DB."""
    defaults = dict(
        org_id=org_id,
        name="Test Policy",
        condition_type="unknown_agent",
        condition_params={},
        action="flag",
        severity="medium",
        is_active=True,
    )
    defaults.update(kwargs)
    policy = Policy(**defaults)
    session.add(policy)
    await session.commit()
    await session.refresh(policy)
    return policy


# ── 1. Unit: condition evaluators ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_unknown_agent_triggers_for_unregistered(db_session, org_and_key):
    """unknown_agent fires when agent is not in agents table."""
    org, _, _ = org_and_key
    policy = await _create_policy(db_session, org.id, condition_type="unknown_agent")

    data = _make_action(agent_name="ghost-agent")
    results = await evaluate_policies(db_session, org.id, data)

    assert len(results) == 1
    assert results[0]["triggered"] is True
    assert results[0]["condition_type"] == "unknown_agent"


@pytest.mark.asyncio
async def test_unknown_agent_does_not_trigger_for_registered(db_session, org_and_key):
    """unknown_agent does NOT fire when agent is already in agents table."""
    org, raw_key, _ = org_and_key
    policy = await _create_policy(db_session, org.id, condition_type="unknown_agent")

    # First record auto-registers the agent
    data = _make_action(agent_name="known-agent")
    await build_and_insert_record(db_session, org.id, data)

    # Evaluate again — agent is now registered
    results = await evaluate_policies(db_session, org.id, data)
    assert results[0]["triggered"] is False


@pytest.mark.asyncio
async def test_missing_reasoning_triggers(db_session, org_and_key):
    """missing_reasoning fires when data_subject_id is set but reasoning is empty."""
    org, _, _ = org_and_key
    await _create_policy(db_session, org.id, condition_type="missing_reasoning")

    data = _make_action(data_subject_id="user-123", reasoning={})
    results = await evaluate_policies(db_session, org.id, data)
    assert results[0]["triggered"] is True


@pytest.mark.asyncio
async def test_missing_reasoning_does_not_trigger_when_reasoning_present(db_session, org_and_key):
    """missing_reasoning does NOT fire when reasoning is provided."""
    org, _, _ = org_and_key
    await _create_policy(db_session, org.id, condition_type="missing_reasoning")

    data = _make_action(data_subject_id="user-123", reasoning={"why": "user consent"})
    results = await evaluate_policies(db_session, org.id, data)
    assert results[0]["triggered"] is False


@pytest.mark.asyncio
async def test_missing_reasoning_does_not_trigger_without_subject(db_session, org_and_key):
    """missing_reasoning does NOT fire when data_subject_id is absent."""
    org, _, _ = org_and_key
    await _create_policy(db_session, org.id, condition_type="missing_reasoning")

    data = _make_action(reasoning={})
    results = await evaluate_policies(db_session, org.id, data)
    assert results[0]["triggered"] is False


@pytest.mark.asyncio
async def test_failure_rate_triggers(db_session, org_and_key):
    """failure_rate fires when >50% of last N actions are failures."""
    org, _, _ = org_and_key
    await _create_policy(
        db_session, org.id,
        condition_type="failure_rate",
        condition_params={"threshold": 0.5, "window": 4},
    )

    # Write 3 failures + 1 success = 75% failure rate > 50%
    for _ in range(3):
        await build_and_insert_record(db_session, org.id, _make_action(result="failure"))
    await build_and_insert_record(db_session, org.id, _make_action(result="success"))

    data = _make_action(result="success")
    results = await evaluate_policies(db_session, org.id, data)
    assert results[0]["triggered"] is True
    assert results[0]["context"]["failure_rate"] > 0.5


@pytest.mark.asyncio
async def test_failure_rate_does_not_trigger_below_threshold(db_session, org_and_key):
    """failure_rate does NOT fire when failure rate is below threshold."""
    org, _, _ = org_and_key
    await _create_policy(
        db_session, org.id,
        condition_type="failure_rate",
        condition_params={"threshold": 0.5, "window": 4},
    )

    # Write 1 failure + 3 successes = 25% failure rate
    await build_and_insert_record(db_session, org.id, _make_action(result="failure"))
    for _ in range(3):
        await build_and_insert_record(db_session, org.id, _make_action(result="success"))

    data = _make_action(result="success")
    results = await evaluate_policies(db_session, org.id, data)
    assert results[0]["triggered"] is False


@pytest.mark.asyncio
async def test_high_failure_burst_triggers(db_session, org_and_key):
    """high_failure_burst fires when >= threshold failures in last 60s."""
    org, _, _ = org_and_key
    await _create_policy(
        db_session, org.id,
        condition_type="high_failure_burst",
        condition_params={"threshold": 3},
    )

    for _ in range(3):
        await build_and_insert_record(db_session, org.id, _make_action(result="failure"))

    data = _make_action(result="success")
    results = await evaluate_policies(db_session, org.id, data)
    assert results[0]["triggered"] is True


@pytest.mark.asyncio
async def test_consecutive_failures_triggers(db_session, org_and_key):
    """consecutive_failures fires when last N records from same agent are all failures."""
    org, _, _ = org_and_key
    await _create_policy(
        db_session, org.id,
        condition_type="consecutive_failures",
        condition_params={"threshold": 3},
    )

    for _ in range(3):
        await build_and_insert_record(
            db_session, org.id, _make_action(agent_name="bad-agent", result="failure")
        )

    data = _make_action(agent_name="bad-agent", result="failure")
    results = await evaluate_policies(db_session, org.id, data)
    assert results[0]["triggered"] is True


@pytest.mark.asyncio
async def test_consecutive_failures_does_not_trigger_with_success_in_between(db_session, org_and_key):
    """consecutive_failures does NOT fire when there is a success in recent history."""
    org, _, _ = org_and_key
    await _create_policy(
        db_session, org.id,
        condition_type="consecutive_failures",
        condition_params={"threshold": 3},
    )

    await build_and_insert_record(db_session, org.id, _make_action(agent_name="agent-x", result="failure"))
    await build_and_insert_record(db_session, org.id, _make_action(agent_name="agent-x", result="success"))
    await build_and_insert_record(db_session, org.id, _make_action(agent_name="agent-x", result="failure"))

    data = _make_action(agent_name="agent-x", result="failure")
    results = await evaluate_policies(db_session, org.id, data)
    assert results[0]["triggered"] is False


# ── 2. Integration: policies_applied in record ──────────────────────────────

@pytest.mark.asyncio
async def test_unknown_agent_triggers_via_build_and_insert(db_session, org_and_key):
    """unknown_agent fires correctly when called through build_and_insert_record.

    This is the integration-path regression test for the ordering bug where
    _get_or_create_agent() was called before evaluate_policies(), causing the
    evaluator to always find the newly-flushed agent and report triggered=False.
    """
    from sqlalchemy import select as sa_select

    org, _, _ = org_and_key
    await _create_policy(db_session, org.id, condition_type="unknown_agent", severity="high")

    # First record — agent "new-rogue" does not exist yet in the DB
    data = _make_action(agent_name="new-rogue", result="success")
    record = await build_and_insert_record(db_session, org.id, data)

    # policies_applied must show triggered=True
    assert len(record.policies_applied) == 1
    result = record.policies_applied[0]
    assert result["triggered"] is True, (
        "unknown_agent policy should trigger for a brand-new agent. "
        "If False, evaluate_policies() is running after _get_or_create_agent()."
    )
    assert result["condition_type"] == "unknown_agent"
    assert result["context"]["agent_name"] == "new-rogue"
    assert result["context"]["registered"] is False

    # A violation row must also be created
    viol_result = await db_session.execute(
        sa_select(PolicyViolation).where(PolicyViolation.record_id == record.id)
    )
    violations = viol_result.scalars().all()
    assert len(violations) == 1
    assert violations[0].severity == "high"


@pytest.mark.asyncio
async def test_policies_applied_in_record_on_trigger(db_session, org_and_key):
    """policies_applied field in inserted record contains evaluation results."""
    org, _, _ = org_and_key
    await _create_policy(
        db_session, org.id,
        name="Missing Reasoning Check",
        condition_type="missing_reasoning",
        severity="high",
    )

    data = _make_action(data_subject_id="user-999", reasoning={})
    record = await build_and_insert_record(db_session, org.id, data)

    assert isinstance(record.policies_applied, list)
    assert len(record.policies_applied) == 1
    result = record.policies_applied[0]
    assert result["triggered"] is True
    assert result["condition_type"] == "missing_reasoning"
    assert result["severity"] == "high"
    assert result["policy_name"] == "Missing Reasoning Check"


@pytest.mark.asyncio
async def test_policies_applied_empty_when_no_trigger(db_session, org_and_key):
    """policies_applied is set but triggered=False when policy exists but doesn't fire."""
    org, _, _ = org_and_key
    await _create_policy(db_session, org.id, condition_type="missing_reasoning")

    # No data_subject_id → condition won't trigger
    data = _make_action()
    record = await build_and_insert_record(db_session, org.id, data)

    assert isinstance(record.policies_applied, list)
    assert len(record.policies_applied) == 1
    assert record.policies_applied[0]["triggered"] is False


# ── 3. Integration: violation row created ───────────────────────────────────


@pytest.mark.asyncio
async def test_violation_row_created_on_trigger(db_session, org_and_key):
    """A PolicyViolation row is inserted after a triggered policy."""
    from sqlalchemy import select as sa_select

    org, _, _ = org_and_key
    policy = await _create_policy(
        db_session, org.id,
        condition_type="missing_reasoning",
        severity="critical",
    )

    data = _make_action(data_subject_id="subj-1", reasoning={})
    record = await build_and_insert_record(db_session, org.id, data)

    result = await db_session.execute(
        sa_select(PolicyViolation).where(PolicyViolation.record_id == record.id)
    )
    violations = result.scalars().all()
    assert len(violations) == 1
    v = violations[0]
    assert v.org_id == org.id
    assert v.policy_id == policy.id
    assert v.severity == "critical"
    assert v.resolved_at is None


@pytest.mark.asyncio
async def test_no_violation_row_when_not_triggered(db_session, org_and_key):
    """No PolicyViolation row is created when policy doesn't fire."""
    from sqlalchemy import select as sa_select

    org, _, _ = org_and_key
    await _create_policy(db_session, org.id, condition_type="missing_reasoning")

    data = _make_action()  # no data_subject_id → no trigger
    record = await build_and_insert_record(db_session, org.id, data)

    result = await db_session.execute(
        sa_select(PolicyViolation).where(PolicyViolation.record_id == record.id)
    )
    violations = result.scalars().all()
    assert len(violations) == 0


# ── 4. API: create/list/update/delete policies ──────────────────────────────


@pytest.mark.asyncio
async def test_create_policy_api(async_client, org_and_key):
    """POST /v1/policies creates a policy."""
    _, raw_key, _ = org_and_key
    resp = await async_client.post(
        "/v1/policies",
        json={
            "name": "API Policy",
            "condition_type": "unknown_agent",
            "condition_params": {},
            "action": "flag",
            "severity": "high",
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "API Policy"
    assert data["condition_type"] == "unknown_agent"
    assert data["severity"] == "high"
    assert data["is_active"] is True


@pytest.mark.asyncio
async def test_create_policy_requires_admin(async_client, org_and_key, db_session):
    """POST /v1/policies requires admin key."""
    org, _, _ = org_and_key
    raw_key, _ = await generate_api_key(db_session, org.id, "readonly", ["read"])
    resp = await async_client.post(
        "/v1/policies",
        json={"name": "P", "condition_type": "unknown_agent", "condition_params": {}, "action": "flag", "severity": "low"},
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_list_policies_api(async_client, org_and_key):
    """GET /v1/policies returns list of policies."""
    _, raw_key, _ = org_and_key
    # Create 2 policies
    for name in ["P1", "P2"]:
        await async_client.post(
            "/v1/policies",
            json={"name": name, "condition_type": "missing_reasoning", "condition_params": {}, "action": "flag", "severity": "medium"},
            headers={"Authorization": f"Bearer {raw_key}"},
        )
    resp = await async_client.get("/v1/policies", headers={"Authorization": f"Bearer {raw_key}"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 2
    names = [p["name"] for p in data["policies"]]
    assert "P1" in names
    assert "P2" in names


@pytest.mark.asyncio
async def test_list_policies_filter_active(async_client, org_and_key):
    """GET /v1/policies?is_active=false returns only inactive policies."""
    _, raw_key, _ = org_and_key
    # Create and deactivate a policy
    create_resp = await async_client.post(
        "/v1/policies",
        json={"name": "ToDeactivate", "condition_type": "failure_rate", "condition_params": {"threshold": 0.5, "window": 10}, "action": "flag", "severity": "low"},
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    policy_id = create_resp.json()["id"]
    await async_client.patch(
        f"/v1/policies/{policy_id}",
        json={"is_active": False},
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    resp = await async_client.get(
        "/v1/policies?is_active=false",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200
    names = [p["name"] for p in resp.json()["policies"]]
    assert "ToDeactivate" in names


@pytest.mark.asyncio
async def test_update_policy_api(async_client, org_and_key):
    """PATCH /v1/policies/{id} updates policy fields."""
    _, raw_key, _ = org_and_key
    create_resp = await async_client.post(
        "/v1/policies",
        json={"name": "Original", "condition_type": "missing_reasoning", "condition_params": {}, "action": "flag", "severity": "low"},
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    policy_id = create_resp.json()["id"]

    resp = await async_client.patch(
        f"/v1/policies/{policy_id}",
        json={"name": "Updated", "severity": "critical", "is_active": False},
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Updated"
    assert data["severity"] == "critical"
    assert data["is_active"] is False


@pytest.mark.asyncio
async def test_delete_policy_api(async_client, org_and_key):
    """DELETE /v1/policies/{id} removes the policy."""
    _, raw_key, _ = org_and_key
    create_resp = await async_client.post(
        "/v1/policies",
        json={"name": "ToDelete", "condition_type": "unknown_agent", "condition_params": {}, "action": "flag", "severity": "low"},
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    policy_id = create_resp.json()["id"]

    del_resp = await async_client.delete(
        f"/v1/policies/{policy_id}",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert del_resp.status_code == 204

    # Verify it's gone
    list_resp = await async_client.get("/v1/policies", headers={"Authorization": f"Bearer {raw_key}"})
    ids = [p["id"] for p in list_resp.json()["policies"]]
    assert policy_id not in ids


@pytest.mark.asyncio
async def test_policy_not_found_returns_404(async_client, org_and_key):
    """PATCH/DELETE on non-existent policy returns 404."""
    _, raw_key, _ = org_and_key
    resp = await async_client.patch(
        "/v1/policies/nonexistent-id",
        json={"name": "X"},
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 404


# ── 5. API: list violations with filters ────────────────────────────────────


@pytest.mark.asyncio
async def test_list_violations_api(async_client, org_and_key, db_session):
    """GET /v1/policies/violations returns violations for the org."""
    org, raw_key, _ = org_and_key

    # Create a policy and trigger it
    policy = await _create_policy(db_session, org.id, condition_type="missing_reasoning", severity="high")
    data = _make_action(data_subject_id="s1", reasoning={})
    await build_and_insert_record(db_session, org.id, data)

    resp = await async_client.get(
        "/v1/policies/violations",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] >= 1
    assert any(v["severity"] == "high" for v in body["violations"])


@pytest.mark.asyncio
async def test_list_violations_filter_severity(async_client, org_and_key, db_session):
    """GET /v1/policies/violations?severity=high returns only high violations."""
    org, raw_key, _ = org_and_key

    await _create_policy(db_session, org.id, condition_type="missing_reasoning", severity="high")
    await _create_policy(db_session, org.id, name="Low Policy", condition_type="missing_reasoning", severity="low")

    data = _make_action(data_subject_id="s2", reasoning={})
    await build_and_insert_record(db_session, org.id, data)

    resp = await async_client.get(
        "/v1/policies/violations?severity=high",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200
    for v in resp.json()["violations"]:
        assert v["severity"] == "high"


@pytest.mark.asyncio
async def test_list_violations_filter_unresolved(async_client, org_and_key, db_session):
    """GET /v1/policies/violations?resolved=false returns unresolved violations."""
    org, raw_key, _ = org_and_key
    await _create_policy(db_session, org.id, condition_type="missing_reasoning")

    data = _make_action(data_subject_id="s3", reasoning={})
    await build_and_insert_record(db_session, org.id, data)

    resp = await async_client.get(
        "/v1/policies/violations?resolved=false",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200
    for v in resp.json()["violations"]:
        assert v["resolved_at"] is None


# ── 6. API: resolve violation ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_resolve_violation_api(async_client, org_and_key, db_session):
    """PATCH /v1/policies/violations/{id}/resolve marks violation as resolved."""
    org, raw_key, _ = org_and_key
    await _create_policy(db_session, org.id, condition_type="missing_reasoning")

    data = _make_action(data_subject_id="s4", reasoning={})
    await build_and_insert_record(db_session, org.id, data)

    # Get the violation ID
    list_resp = await async_client.get(
        "/v1/policies/violations",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    violation_id = list_resp.json()["violations"][0]["id"]

    resp = await async_client.patch(
        f"/v1/policies/violations/{violation_id}/resolve",
        json={"resolved_by": "security-team"},
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["resolved_at"] is not None
    assert data["resolved_by"] == "security-team"


@pytest.mark.asyncio
async def test_resolve_violation_twice_returns_409(async_client, org_and_key, db_session):
    """Resolving an already-resolved violation returns 409."""
    org, raw_key, _ = org_and_key
    await _create_policy(db_session, org.id, condition_type="missing_reasoning")

    data = _make_action(data_subject_id="s5", reasoning={})
    await build_and_insert_record(db_session, org.id, data)

    list_resp = await async_client.get(
        "/v1/policies/violations",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    violation_id = list_resp.json()["violations"][0]["id"]

    # First resolve
    await async_client.patch(
        f"/v1/policies/violations/{violation_id}/resolve",
        json={},
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    # Second resolve → 409
    resp = await async_client.patch(
        f"/v1/policies/violations/{violation_id}/resolve",
        json={},
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 409


# ── 7. Email: policy with action="email" triggers send_policy_violation_alert ──


@pytest.mark.asyncio
async def test_email_action_policy_fires_email(db_session, org_and_key):
    """A policy with action='email' triggers send_policy_violation_alert when fired."""
    org, _, _ = org_and_key
    # Set alert email on the org
    org.alert_email = "policy-alerts@test.com"
    await db_session.commit()

    await _create_policy(
        db_session, org.id,
        condition_type="missing_reasoning",
        action="email",
        severity="critical",
    )

    mock_email = AsyncMock()
    with patch("app.services.chain.send_policy_violation_alert", mock_email):
        data = _make_action(data_subject_id="user-email-test", reasoning={})
        record = await build_and_insert_record(db_session, org.id, data)
        # Flush tasks
        await asyncio.sleep(0)

    assert mock_email.called
    call_kwargs = mock_email.call_args.kwargs
    assert call_kwargs["alert_email"] == "policy-alerts@test.com"
    assert call_kwargs["condition_type"] == "missing_reasoning"
    assert call_kwargs["severity"] == "critical"
    assert call_kwargs["record_id"] == record.id


@pytest.mark.asyncio
async def test_flag_action_policy_does_not_fire_email(db_session, org_and_key):
    """A policy with action='flag' does NOT trigger an email."""
    org, _, _ = org_and_key
    org.alert_email = "policy-alerts@test.com"
    await db_session.commit()

    await _create_policy(
        db_session, org.id,
        condition_type="missing_reasoning",
        action="flag",
    )

    mock_email = AsyncMock()
    with patch("app.services.chain.send_policy_violation_alert", mock_email):
        data = _make_action(data_subject_id="user-flag-test", reasoning={})
        await build_and_insert_record(db_session, org.id, data)
        await asyncio.sleep(0)

    mock_email.assert_not_called()


# ── 8. Edge: inactive policy does not fire ───────────────────────────────────


@pytest.mark.asyncio
async def test_inactive_policy_does_not_evaluate(db_session, org_and_key):
    """An inactive policy is not evaluated — policies_applied is empty."""
    org, _, _ = org_and_key
    await _create_policy(
        db_session, org.id,
        condition_type="missing_reasoning",
        is_active=False,
    )

    data = _make_action(data_subject_id="user-inactive", reasoning={})
    record = await build_and_insert_record(db_session, org.id, data)

    assert record.policies_applied == []


# ── 9. Edge: org with no policies — record writes normally ───────────────────


@pytest.mark.asyncio
async def test_no_policies_record_writes_normally(db_session, org_and_key):
    """When org has no active policies, records write normally with empty policies_applied."""
    org, _, _ = org_and_key

    data = _make_action()
    record = await build_and_insert_record(db_session, org.id, data)

    assert record.id is not None
    assert record.record_hash != ""
    assert record.policies_applied == []


# ── 10. Batch: batch inserts skip policy evaluation ─────────────────────────


@pytest.mark.asyncio
async def test_batch_insert_skips_policy_evaluation(db_session, org_and_key):
    """Batch insert records have policies_applied = [] regardless of active policies."""
    org, _, _ = org_and_key
    await _create_policy(db_session, org.id, condition_type="missing_reasoning")

    records_data = [
        _make_action(data_subject_id="user-batch", reasoning={}),  # would trigger if evaluated
        _make_action(),
    ]
    records = await build_and_insert_batch(db_session, org.id, records_data)

    for r in records:
        assert r.policies_applied == []


# ── Bonus: invalid condition_type in API returns 422 ────────────────────────


@pytest.mark.asyncio
async def test_create_policy_invalid_condition_type(async_client, org_and_key):
    """POST /v1/policies with invalid condition_type returns 422."""
    _, raw_key, _ = org_and_key
    resp = await async_client.post(
        "/v1/policies",
        json={"name": "Bad", "condition_type": "invalid_type", "condition_params": {}, "action": "flag", "severity": "low"},
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_policy_invalid_action(async_client, org_and_key):
    """POST /v1/policies with invalid action returns 422.

    ``block`` was added as a valid action in PR-zeta — see
    ``test_policy_block.test_create_block_policy_via_api`` for that path.
    """
    _, raw_key, _ = org_and_key
    resp = await async_client.post(
        "/v1/policies",
        json={"name": "Bad", "condition_type": "unknown_agent", "condition_params": {}, "action": "ignore", "severity": "low"},
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 422
