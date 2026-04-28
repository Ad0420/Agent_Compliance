"""Tests for the BLOCK policy action (PR-zeta).

A policy with ``action="block"`` is pre-action enforcement: the audit
record is still inserted (with ``result="blocked"``) so the regulator /
dashboard can see what was attempted, but the API response is HTTP 409
Conflict so the SDK caller's wrapped function aborts.

Coverage:
1.  Block policy on unknown_agent fires → 409, record persisted with result='blocked'.
2.  Same policy with a registered agent → no 409, normal flow.
3.  Two policies on same condition (one email, one block) → block wins, both violations recorded.
4.  Block policy on missing_reasoning → triggers when data_subject_id but no reasoning.
5.  Inactive block policy → does NOT block.
6.  Block fires → webhook ``policy.violation`` is dispatched.
7.  Chain integrity: post-block, the next action's previous_hash references the blocked record's hash.
8.  Batch endpoint: block policies are NOT enforced on /v1/actions/batch (documented v1 limitation).
9.  Schema: POST /v1/policies with action='block' is accepted; bogus action → 422.
10. Schema: POST /v1/actions with result='blocked' from client → 422 (engine-set only).
11. Idempotency: replaying an Idempotency-Key on a blocked action returns the cached 409.
12. Block policy does NOT fire an email (block surfaces via 409, not via mail).
"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.models import (
    ActionRecord,
    Organization,
    Policy,
    PolicyViolation,
    WebhookSubscription,
)
from app.schemas.action import ActionRecordCreate
from app.services.chain import build_and_insert_record


# ── helpers ─────────────────────────────────────────────────────────────────


def _action_payload(name: str = "test_action", **overrides) -> dict:
    payload = {
        "action_name": name,
        "action_type": "function_call",
        "agent_name": "ghost-agent",
        "result": "success",
    }
    payload.update(overrides)
    return payload


async def _create_policy(session, org_id: str, **kwargs) -> Policy:
    defaults = dict(
        org_id=org_id,
        name="Test Block Policy",
        condition_type="unknown_agent",
        condition_params={},
        action="block",
        severity="high",
        is_active=True,
    )
    defaults.update(kwargs)
    policy = Policy(**defaults)
    session.add(policy)
    await session.commit()
    await session.refresh(policy)
    return policy


# ── 1. Block fires → 409 + audit record with result='blocked' ───────────────


@pytest.mark.asyncio
async def test_block_unknown_agent_returns_409_and_persists_record(
    async_client, org_and_key, db_session
):
    """Unknown-agent block: HTTP 409, record persisted with result='blocked'."""
    org, raw_key, _ = org_and_key
    policy = await _create_policy(
        db_session,
        org.id,
        name="No Unknown Agents",
        condition_type="unknown_agent",
        action="block",
        severity="critical",
    )

    resp = await async_client.post(
        "/v1/actions",
        json=_action_payload(agent_name="rogue-agent"),
        headers={"Authorization": f"Bearer {raw_key}"},
    )

    assert resp.status_code == 409, resp.text
    body = resp.json()
    # FastAPI wraps detail under "detail" by default
    detail = body.get("detail", body)
    assert detail["error"] == "policy_block"
    assert detail["message"] == "Action blocked by policy"
    assert detail["record_id"]
    assert len(detail["blocking_policies"]) == 1
    bp = detail["blocking_policies"][0]
    assert bp["policy_id"] == policy.id
    assert bp["policy_name"] == "No Unknown Agents"
    assert bp["condition_type"] == "unknown_agent"
    assert bp["severity"] == "critical"
    assert bp["context"]["agent_name"] == "rogue-agent"
    assert bp["context"]["registered"] is False

    # Record was still inserted with result='blocked'.
    result = await db_session.execute(
        select(ActionRecord).where(ActionRecord.id == detail["record_id"])
    )
    record = result.scalar_one()
    assert record.result == "blocked"
    assert record.agent_name == "rogue-agent"
    assert record.policies_applied
    assert record.policies_applied[0]["triggered"] is True
    assert record.policies_applied[0]["action"] == "block"


# ── 2. Registered agent: no 409, normal flow ────────────────────────────────


@pytest.mark.asyncio
async def test_block_does_not_fire_for_registered_agent(
    async_client, org_and_key, db_session
):
    """Block policy on unknown_agent does nothing once the agent is known.

    The first request blocks (agent unknown) but the audit insert auto-
    registers the agent. The second request with the same agent name now
    sees a registered agent and proceeds normally.
    """
    org, raw_key, _ = org_and_key
    await _create_policy(
        db_session, org.id, condition_type="unknown_agent", action="block"
    )

    # First call with this agent — blocked (unknown). Side effect: the
    # ``agents`` row is auto-created during the same insert.
    resp1 = await async_client.post(
        "/v1/actions",
        json=_action_payload(agent_name="will-be-known"),
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp1.status_code == 409

    # Second call: agent is now registered, no 409.
    resp2 = await async_client.post(
        "/v1/actions",
        json=_action_payload(agent_name="will-be-known"),
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp2.status_code == 200
    body = resp2.json()
    assert body["result"] == "success"


# ── 3. Mixed actions on same condition: block wins ──────────────────────────


@pytest.mark.asyncio
async def test_block_and_email_on_same_condition_records_both_violations(
    async_client, org_and_key, db_session
):
    """An email-action policy AND a block-action policy on the same condition.

    The action is blocked, BOTH violations are recorded, the email-policy
    still gets its own violation row.
    """
    org, raw_key, _ = org_and_key
    org.alert_email = "alerts@test.com"
    await db_session.commit()

    p_email = await _create_policy(
        db_session,
        org.id,
        name="Email Notify",
        condition_type="missing_reasoning",
        action="email",
        severity="medium",
    )
    p_block = await _create_policy(
        db_session,
        org.id,
        name="Block Hard",
        condition_type="missing_reasoning",
        action="block",
        severity="high",
    )

    mock_email = AsyncMock()
    with patch("app.services.chain.send_policy_violation_alert", mock_email):
        resp = await async_client.post(
            "/v1/actions",
            json=_action_payload(
                agent_name="known-agent", data_subject_id="user-1", reasoning={}
            ),
            headers={"Authorization": f"Bearer {raw_key}"},
        )
        await asyncio.sleep(0)

    assert resp.status_code == 409
    detail = resp.json().get("detail", resp.json())
    # Only the block policy is reported in blocking_policies.
    assert len(detail["blocking_policies"]) == 1
    assert detail["blocking_policies"][0]["policy_id"] == p_block.id

    # Both violation rows are stored.
    result = await db_session.execute(
        select(PolicyViolation).where(PolicyViolation.record_id == detail["record_id"])
    )
    violations = result.scalars().all()
    assert len(violations) == 2
    policy_ids = {v.policy_id for v in violations}
    assert policy_ids == {p_email.id, p_block.id}

    # The email-action policy still triggers an email.
    assert mock_email.called


# ── 4. Block on missing_reasoning ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_block_missing_reasoning(async_client, org_and_key, db_session):
    """Block policy on missing_reasoning: data_subject_id + empty reasoning → 409."""
    org, raw_key, _ = org_and_key
    await _create_policy(
        db_session, org.id, condition_type="missing_reasoning", action="block"
    )

    resp = await async_client.post(
        "/v1/actions",
        json=_action_payload(data_subject_id="subject-x", reasoning={}),
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 409

    # Same shape but with reasoning provided — passes.
    resp_ok = await async_client.post(
        "/v1/actions",
        json=_action_payload(
            data_subject_id="subject-y", reasoning={"why": "consent"}
        ),
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp_ok.status_code == 200


# ── 5. Inactive block policy is a no-op ─────────────────────────────────────


@pytest.mark.asyncio
async def test_inactive_block_policy_does_not_block(
    async_client, org_and_key, db_session
):
    """A block-action policy that is_active=False does NOT enforce."""
    org, raw_key, _ = org_and_key
    await _create_policy(
        db_session,
        org.id,
        condition_type="unknown_agent",
        action="block",
        is_active=False,
    )

    resp = await async_client.post(
        "/v1/actions",
        json=_action_payload(agent_name="any-rogue"),
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["result"] == "success"


# ── 6. Block fires → webhook dispatched ─────────────────────────────────────


@pytest.mark.asyncio
async def test_block_policy_dispatches_webhook(
    async_client, org_and_key, db_session
):
    """A block-action policy still fires the policy.violation webhook event."""
    org, raw_key, _ = org_and_key
    await _create_policy(
        db_session, org.id, condition_type="unknown_agent", action="block"
    )

    mock_dispatch = AsyncMock()
    with patch("app.services.chain.dispatch_event", mock_dispatch):
        resp = await async_client.post(
            "/v1/actions",
            json=_action_payload(agent_name="webhook-rogue"),
            headers={"Authorization": f"Bearer {raw_key}"},
        )
        await asyncio.sleep(0)

    assert resp.status_code == 409
    assert mock_dispatch.called
    # First positional or kwargs: dispatch_event(session, org_id, event_type, payload)
    call_args = mock_dispatch.call_args
    args = call_args.args
    # event_type is the third positional arg.
    assert args[2] == "policy.violation"
    payload = args[3]
    assert payload["condition_type"] == "unknown_agent"


# ── 7. Chain integrity preserved across a blocked record ────────────────────


@pytest.mark.asyncio
async def test_blocked_record_chain_integrity(
    async_client, org_and_key, db_session
):
    """After a blocked record, the next action's previous_hash chains correctly."""
    org, raw_key, _ = org_and_key
    await _create_policy(
        db_session, org.id, condition_type="unknown_agent", action="block"
    )

    blocked_resp = await async_client.post(
        "/v1/actions",
        json=_action_payload(agent_name="block-then-chain-rogue"),
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert blocked_resp.status_code == 409
    blocked_id = blocked_resp.json().get("detail", blocked_resp.json())["record_id"]

    # The blocked agent is now registered (the unknown_agent eval ran before
    # _get_or_create_agent, but the agent row is still flushed before commit).
    # So the next call will NOT trigger again.
    next_resp = await async_client.post(
        "/v1/actions",
        json=_action_payload(agent_name="block-then-chain-rogue"),
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert next_resp.status_code == 200
    next_body = next_resp.json()

    # Fetch both records and verify chain.
    blocked = (
        await db_session.execute(
            select(ActionRecord).where(ActionRecord.id == blocked_id)
        )
    ).scalar_one()
    next_record = (
        await db_session.execute(
            select(ActionRecord).where(ActionRecord.id == next_body["id"])
        )
    ).scalar_one()

    assert next_record.previous_hash == blocked.record_hash
    assert next_record.sequence_number == blocked.sequence_number + 1


# ── 8. Batch endpoint does NOT enforce block (v1 limitation) ────────────────


@pytest.mark.asyncio
async def test_batch_endpoint_does_not_enforce_block(
    async_client, org_and_key, db_session
):
    """``/v1/actions/batch`` skips policy evaluation in v1; block is not enforced.

    Documented as a follow-up — see chain.py build_and_insert_batch TODO and
    test_policy_engine.test_batch_insert_skips_policy_evaluation.
    """
    org, raw_key, _ = org_and_key
    await _create_policy(
        db_session, org.id, condition_type="unknown_agent", action="block"
    )

    resp = await async_client.post(
        "/v1/actions/batch",
        json={"records": [_action_payload(agent_name="batch-rogue")]},
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    # No 409 on batch in v1. Records are inserted normally.
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    assert body[0]["result"] == "success"
    assert body[0]["policies_applied"] == []


# ── 9. Schema validation: action='block' allowed, bogus rejected ────────────


@pytest.mark.asyncio
async def test_create_block_policy_via_api(async_client, org_and_key):
    """POST /v1/policies with action='block' is accepted (was 422 before PR-zeta)."""
    _, raw_key, _ = org_and_key
    resp = await async_client.post(
        "/v1/policies",
        json={
            "name": "Block Unknown",
            "condition_type": "unknown_agent",
            "condition_params": {},
            "action": "block",
            "severity": "critical",
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["action"] == "block"
    assert body["severity"] == "critical"


# ── 10. Schema validation: client-supplied result='blocked' is rejected ─────


@pytest.mark.asyncio
async def test_client_cannot_submit_result_blocked(async_client, org_and_key):
    """Direct POST with result='blocked' fails 422 — engine-set only."""
    _, raw_key, _ = org_and_key
    resp = await async_client.post(
        "/v1/actions",
        json=_action_payload(result="blocked"),
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 422
    detail_text = resp.text
    assert "blocked" in detail_text or "result" in detail_text


# ── 11. Idempotency replays return the cached 409 ───────────────────────────


@pytest.mark.asyncio
async def test_idempotency_replays_blocked_response(
    async_client, org_and_key, db_session
):
    """Re-sending the same Idempotency-Key on a blocked action returns the cached 409.

    Also asserts that a single blocked action_record exists — replays do
    not insert a second row.
    """
    import uuid
    from sqlalchemy import func as sa_func

    org, raw_key, _ = org_and_key
    await _create_policy(
        db_session, org.id, condition_type="unknown_agent", action="block"
    )

    idem_key = uuid.uuid4().hex
    payload = _action_payload(agent_name="idem-rogue")

    resp1 = await async_client.post(
        "/v1/actions",
        json=payload,
        headers={
            "Authorization": f"Bearer {raw_key}",
            "Idempotency-Key": idem_key,
        },
    )
    assert resp1.status_code == 409
    record_id_1 = resp1.json().get("detail", resp1.json())["record_id"]

    resp2 = await async_client.post(
        "/v1/actions",
        json=payload,
        headers={
            "Authorization": f"Bearer {raw_key}",
            "Idempotency-Key": idem_key,
        },
    )
    assert resp2.status_code == 409
    record_id_2 = resp2.json().get("detail", resp2.json())["record_id"]
    assert record_id_1 == record_id_2

    # Only ONE action record was actually inserted.
    count_result = await db_session.execute(
        select(sa_func.count(ActionRecord.id)).where(
            ActionRecord.org_id == org.id,
            ActionRecord.agent_name == "idem-rogue",
        )
    )
    assert count_result.scalar_one() == 1


# ── 12. Block does NOT fire an email ───────────────────────────────────────


@pytest.mark.asyncio
async def test_block_policy_does_not_fire_email(
    async_client, org_and_key, db_session
):
    """A standalone block-action policy does not auto-send an email.

    The 409 already surfaces the issue to the SDK caller. Customers who
    want both can configure two policies on the same condition (one
    action='email', one action='block').
    """
    org, raw_key, _ = org_and_key
    org.alert_email = "alerts@test.com"
    await db_session.commit()

    await _create_policy(
        db_session, org.id, condition_type="unknown_agent", action="block"
    )

    mock_email = AsyncMock()
    with patch("app.services.chain.send_policy_violation_alert", mock_email):
        resp = await async_client.post(
            "/v1/actions",
            json=_action_payload(agent_name="silent-rogue"),
            headers={"Authorization": f"Bearer {raw_key}"},
        )
        await asyncio.sleep(0)

    assert resp.status_code == 409
    mock_email.assert_not_called()


# ── 13. Direct service call also raises HTTPException for block ─────────────


@pytest.mark.asyncio
async def test_build_and_insert_record_raises_on_block(db_session, org_and_key):
    """Calling the chain service directly with a block-triggering policy raises 409."""
    from fastapi import HTTPException

    org, _, _ = org_and_key
    await _create_policy(
        db_session, org.id, condition_type="unknown_agent", action="block"
    )

    data = ActionRecordCreate(
        action_name="direct_call",
        agent_name="direct-rogue",
        result="success",
    )

    with pytest.raises(HTTPException) as exc_info:
        await build_and_insert_record(db_session, org.id, data)

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["error"] == "policy_block"
    assert exc_info.value.detail["record_id"]

    # Despite the raise, the record exists with result='blocked'.
    record_id = exc_info.value.detail["record_id"]
    result = await db_session.execute(
        select(ActionRecord).where(ActionRecord.id == record_id)
    )
    record = result.scalar_one()
    assert record.result == "blocked"
