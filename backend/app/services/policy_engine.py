"""
Policy Enforcement Engine.

Evaluates active policies for an org against an incoming action record
at write time. Called by chain.py before _create_record() so that
evaluation results are included in the tamper-proof hash.

Each evaluator returns a dict with at minimum:
  {
    "policy_id": str,
    "policy_name": str,
    "condition_type": str,
    "triggered": bool,
    "severity": str,
    "action": str,
    "context": dict,   # metric values, window, threshold — for violation row
  }
"""
import logging
from datetime import datetime, timezone, timedelta

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Policy, Agent, ActionRecord
from ..schemas.action import ActionRecordCreate

logger = logging.getLogger(__name__)


# ── Individual condition evaluators ────────────────────────────────────────


async def _eval_unknown_agent(
    policy: Policy,
    data: ActionRecordCreate,
    session: AsyncSession,
    org_id: str,
) -> dict:
    """Trigger if agent_name is not in org's registered agents table."""
    result = await session.execute(
        select(Agent).where(Agent.org_id == org_id, Agent.name == data.agent_name)
    )
    agent = result.scalar_one_or_none()
    triggered = agent is None
    return {
        "policy_id": policy.id,
        "policy_name": policy.name,
        "condition_type": "unknown_agent",
        "triggered": triggered,
        "severity": policy.severity,
        "action": policy.action,
        "context": {
            "agent_name": data.agent_name,
            "registered": not triggered,
        },
    }


async def _eval_missing_reasoning(
    policy: Policy,
    data: ActionRecordCreate,
    session: AsyncSession,
    org_id: str,
) -> dict:
    """Trigger if data_subject_id is set but reasoning is empty."""
    has_subject = bool(data.data_subject_id)
    has_reasoning = bool(data.reasoning)
    triggered = has_subject and not has_reasoning
    return {
        "policy_id": policy.id,
        "policy_name": policy.name,
        "condition_type": "missing_reasoning",
        "triggered": triggered,
        "severity": policy.severity,
        "action": policy.action,
        "context": {
            "data_subject_id_present": has_subject,
            "reasoning_empty": not has_reasoning,
        },
    }


async def _eval_failure_rate(
    policy: Policy,
    data: ActionRecordCreate,
    session: AsyncSession,
    org_id: str,
) -> dict:
    """Trigger if >threshold fraction of last N actions are failures.

    condition_params: {"threshold": 0.5, "window": 50}
    """
    params = policy.condition_params
    threshold = float(params.get("threshold", 0.5))
    window = int(params.get("window", 50))

    # Fetch the last N records for this org
    result = await session.execute(
        select(ActionRecord.result)
        .where(ActionRecord.org_id == org_id)
        .order_by(ActionRecord.recorded_at.desc())
        .limit(window)
    )
    recent_results = [row[0] for row in result.fetchall()]

    if not recent_results:
        rate = 0.0
        triggered = False
    else:
        failure_count = sum(1 for r in recent_results if r == "failure")
        rate = failure_count / len(recent_results)
        triggered = rate > threshold

    return {
        "policy_id": policy.id,
        "policy_name": policy.name,
        "condition_type": "failure_rate",
        "triggered": triggered,
        "severity": policy.severity,
        "action": policy.action,
        "context": {
            "failure_rate": round(rate, 4),
            "threshold": threshold,
            "window": window,
            "records_sampled": len(recent_results),
        },
    }


async def _eval_high_failure_burst(
    policy: Policy,
    data: ActionRecordCreate,
    session: AsyncSession,
    org_id: str,
) -> dict:
    """Trigger if >N failures in the last 60 seconds.

    condition_params: {"threshold": 5}
    """
    params = policy.condition_params
    threshold = int(params.get("threshold", 5))

    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=60)
    result = await session.execute(
        select(func.count())
        .select_from(ActionRecord)
        .where(
            ActionRecord.org_id == org_id,
            ActionRecord.result == "failure",
            ActionRecord.recorded_at >= cutoff,
        )
    )
    count = result.scalar() or 0
    triggered = count >= threshold

    return {
        "policy_id": policy.id,
        "policy_name": policy.name,
        "condition_type": "high_failure_burst",
        "triggered": triggered,
        "severity": policy.severity,
        "action": policy.action,
        "context": {
            "failures_in_last_60s": count,
            "threshold": threshold,
        },
    }


async def _eval_consecutive_failures(
    policy: Policy,
    data: ActionRecordCreate,
    session: AsyncSession,
    org_id: str,
) -> dict:
    """Trigger if the last N records from the same agent are all failures.

    condition_params: {"threshold": 3}
    """
    params = policy.condition_params
    threshold = int(params.get("threshold", 3))

    result = await session.execute(
        select(ActionRecord.result)
        .where(ActionRecord.org_id == org_id, ActionRecord.agent_name == data.agent_name)
        .order_by(ActionRecord.recorded_at.desc())
        .limit(threshold)
    )
    recent = [row[0] for row in result.fetchall()]

    if len(recent) < threshold:
        triggered = False
    else:
        triggered = all(r == "failure" for r in recent)

    return {
        "policy_id": policy.id,
        "policy_name": policy.name,
        "condition_type": "consecutive_failures",
        "triggered": triggered,
        "severity": policy.severity,
        "action": policy.action,
        "context": {
            "agent_name": data.agent_name,
            "consecutive_failures_required": threshold,
            "recent_results": recent,
        },
    }


_EVALUATORS = {
    "unknown_agent": _eval_unknown_agent,
    "missing_reasoning": _eval_missing_reasoning,
    "failure_rate": _eval_failure_rate,
    "high_failure_burst": _eval_high_failure_burst,
    "consecutive_failures": _eval_consecutive_failures,
}


# ── Main entry point ────────────────────────────────────────────────────────


async def evaluate_policies(
    session: AsyncSession,
    org_id: str,
    data: ActionRecordCreate,
) -> list[dict]:
    """Evaluate all active policies for the org against an incoming action record.

    Returns a list of evaluation result dicts (one per active policy).
    Results for non-triggered policies are included with triggered=False so
    the full evaluation is auditable via policies_applied.
    """
    result = await session.execute(
        select(Policy)
        .where(Policy.org_id == org_id, Policy.is_active == True)  # noqa: E712
        .order_by(Policy.created_at)
    )
    policies = result.scalars().all()

    if not policies:
        return []

    results = []
    for policy in policies:
        evaluator = _EVALUATORS.get(policy.condition_type)
        if evaluator is None:
            logger.warning("Unknown condition_type %r for policy %s — skipping", policy.condition_type, policy.id)
            continue
        try:
            eval_result = await evaluator(policy, data, session, org_id)
            results.append(eval_result)
        except Exception:
            logger.exception("Policy evaluation failed for policy %s (org %s)", policy.id, org_id)

    return results
