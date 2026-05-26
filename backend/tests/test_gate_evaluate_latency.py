"""W1.4 — Phase 2 acceptance: ``POST /v1/gates/evaluate`` is non-blocking
on webhook dispatch.

The Phase 2 acceptance regression (``gate-evaluate-blocks-on-webhook-dispatch``):
when an org has an active webhook subscription pointing at a slow/dead
receiver, calling ``@vera.gate`` against an action that resolves to
``REQUIRE_HITL`` must return in well under the SDK's 5s read-timeout.
Webhook delivery is fire-and-forget per A3 design — the delivery row is
persisted and a background task drives the HTTP POST, so the request
return path never waits on customer-side latency.

These tests assert:

1. ``POST /v1/gates/evaluate`` returns in <500ms even when the
   subscriber's HTTP receiver hangs for an order of magnitude longer.
2. The ``WebhookDelivery`` row is ``status='in_progress'`` at response
   time — proves dispatch happened but is still in flight, confirming
   the async path is exercised. A regression that re-awaits
   ``_attempt_delivery`` would flip the row to ``succeeded`` before the
   response returns and trip this assertion.
3. Both dual-emission events (``approval.requested`` + ``review.requested``)
   spawn delivery rows in parallel, not serialised — guards against a
   future change that accidentally awaits the second dispatch behind the
   first delivery's wire-time.

Test environment notes
----------------------
* The module-scoped autouse fixture unsets ``VERA_WEBHOOK_SYNC_DISPATCH``
  so the real ``asyncio.create_task`` code path runs. The rest of the
  suite forces sync dispatch (set in ``conftest.py``) to avoid
  background-task contention on the shared in-memory SQLite connection.
* The hanging stand-in for ``httpx.AsyncClient`` sleeps 1.5s — long
  enough that any inline await blows the 500ms budget by 3x, short
  enough that the spawned task completes cleanly before fixture
  teardown disposes the engine (avoids the StaticPool half-rollback
  ``no active connection`` artefact).
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.models import BAAAgreement, BAAScope, Customer, WebhookDelivery, WebhookSubscription
from app.services import baa as baa_service


@pytest.fixture(autouse=True)
def _reset_baa_cache():
    baa_service._reset_baa_freshness_cache_for_tests()
    yield
    baa_service._reset_baa_freshness_cache_for_tests()


@pytest.fixture(autouse=True)
def _disable_sync_dispatch(monkeypatch):
    """Force production-mode (fire-and-forget) dispatch for this module.

    ``conftest.py`` sets ``VERA_WEBHOOK_SYNC_DISPATCH=1`` so the rest of
    the suite awaits the first delivery attempt inline (avoids
    background-task races against the shared in-memory SQLite
    connection). For latency tests we explicitly want the async path —
    the whole point is to prove the request doesn't block on the wire-time.

    The ``_should_dispatch_sync`` helper reads this env var at call
    time, so patching it on the os.environ alone is enough — no module
    re-import needed. We also stub the helper to ``False`` directly so a
    future refactor that caches the env-read at import time still picks
    up the override.
    """
    monkeypatch.delenv("VERA_WEBHOOK_SYNC_DISPATCH", raising=False)
    import app.services.webhooks as webhooks_mod

    monkeypatch.setattr(webhooks_mod, "_should_dispatch_sync", lambda: False)
    yield


def _now_naive_utc() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def _seed_active_baa(db_session, org_id: str):
    customer = Customer(org_id=org_id, tenant_id="latency_customer")
    db_session.add(customer)
    await db_session.flush()
    now = _now_naive_utc()
    baa = BAAAgreement(
        org_id=org_id,
        customer_id=customer.id,
        status="active",
        effective_at=now - timedelta(days=1),
        expires_at=now + timedelta(days=365),
    )
    db_session.add(baa)
    await db_session.flush()
    db_session.add(
        BAAScope(
            baa_agreement_id=baa.id,
            covered_services=["chart_entry"],
            covered_agent_types=["scribe"],
            granted_at=now,
        )
    )
    await db_session.commit()


async def _make_slow_subscription(db_session, org_id: str) -> WebhookSubscription:
    """Register a webhook pointed at the simulated slow receiver."""
    sub = WebhookSubscription(
        org_id=org_id,
        url="https://slow.example.com/hook",
        secret="latency-test-secret",
        event_types=["approval.requested", "review.requested"],
        is_active=True,
    )
    db_session.add(sub)
    await db_session.commit()
    await db_session.refresh(sub)
    return sub


class _HangingClient:
    """Stand-in for ``httpx.AsyncClient`` that sleeps on POST.

    Matches the real client's async-context-manager + ``.post()`` shape.
    The sleep is awaited *inside* the spawned ``_attempt_delivery`` task —
    NOT on the request path. If the request awaits this anywhere, the
    test will detect it via the 500ms latency assertion.

    Sleep duration is calibrated to two competing constraints:
    * Long enough that ``response_time + 50ms`` is still mid-sleep (so the
      "delivery row is in_progress at response time" assertion is robust).
    * Short enough that the spawned task completes before pytest teardown
      so the in-memory SQLite connection isn't left in a half-rolled-back
      state (which surfaces as ``no active connection`` during
      ``StaticPool`` finalisation).

    1.5s satisfies both: the request returns in ~100ms, we sleep 50ms,
    we assert ``in_progress``, then the task wakes up ~1.4s later and
    cleanly commits a ``succeeded`` row before fixtures dispose the engine.
    """

    SLEEP_SECONDS = 1.5

    def __init__(self, *args, **kwargs):  # accept timeout=... etc.
        self._args = args
        self._kwargs = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, **kwargs):
        await asyncio.sleep(self.SLEEP_SECONDS)

        class _Resp:
            status_code = 200
            content = b""

        return _Resp()


@pytest.fixture
def _patch_hanging_httpx(monkeypatch):
    """Patch ``httpx.AsyncClient`` inside ``services.webhooks`` to hang.

    Scope is the test function — the patch must be in place when
    ``_attempt_delivery`` runs the HTTP POST, which is on the background
    task. We monkeypatch the symbol the module imported (``httpx``),
    not the global ``httpx`` package, so other modules are unaffected.
    """
    import app.services.webhooks as webhooks_mod

    monkeypatch.setattr(webhooks_mod.httpx, "AsyncClient", _HangingClient)
    yield


@pytest_asyncio.fixture
async def _await_inflight_after_test():
    """Await all spawned webhook tasks to completion at teardown.

    With ``_HangingClient.SLEEP_SECONDS = 1.5`` the tasks complete on
    their own well within the conftest drain's 5s budget. We additionally
    await ``_inflight_tasks`` here (before the conftest drain runs) so a
    cancellation isn't necessary — letting the tasks finish cleanly
    avoids the ``StaticPool`` half-rollback issue that bites when an
    in-memory SQLite engine is disposed mid-transaction.
    """
    yield
    import app.services.webhooks as webhooks_mod

    tracked = [
        t
        for t in list(getattr(webhooks_mod, "_inflight_tasks", set()))
        if not t.done()
    ]
    if tracked:
        await asyncio.gather(*tracked, return_exceptions=True)


@pytest.mark.asyncio
async def test_gate_evaluate_returns_under_500ms_with_slow_webhook(
    async_client,
    org_and_key,
    db_session,
    _patch_hanging_httpx,
    _await_inflight_after_test,
):
    """The ``REQUIRE_HITL`` response path must not await the webhook POST.

    Slow receiver simulates a 1.5s hang; request must return in <500ms.
    """
    org, raw_key, _ = org_and_key
    await _seed_active_baa(db_session, org.id)
    await _make_slow_subscription(db_session, org.id)

    payload = {
        "agent_name": "scribemd",
        "action_type": "diagnosis_create",
        "action_name": "add_diagnosis",
        "authorized_by": "dr_smith",
        "data_subject_id": "patient_99",
        "input_data": {"icd10": "E11.9"},
    }

    t0 = time.monotonic()
    response = await async_client.post(
        "/v1/gates/evaluate",
        json=payload,
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    elapsed_ms = (time.monotonic() - t0) * 1000

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["effect"] == "require_hitl"
    assert body["review_id"] is not None

    assert elapsed_ms < 500, (
        f"gate-evaluate took {elapsed_ms:.0f}ms with a 1.5s slow webhook; "
        "dispatch is not fire-and-forget (W1.4 regression)"
    )


@pytest.mark.asyncio
async def test_gate_evaluate_creates_delivery_row_in_flight(
    async_client,
    org_and_key,
    db_session,
    _patch_hanging_httpx,
    _await_inflight_after_test,
):
    """At response time, the delivery row exists with ``status='in_progress'``.

    Proves the dispatch happened (DB row is durable) but the HTTP attempt
    is genuinely still in flight (status not yet flipped to ``succeeded``
    / ``aborted``). If a future regression makes dispatch synchronous,
    the row would already be ``succeeded`` by the time the response
    returns and this assertion would catch it.
    """
    org, raw_key, _ = org_and_key
    await _seed_active_baa(db_session, org.id)
    sub = await _make_slow_subscription(db_session, org.id)

    payload = {
        "agent_name": "scribemd",
        "action_type": "diagnosis_create",
        "action_name": "add_diagnosis",
        "authorized_by": "dr_smith",
        "data_subject_id": "patient_100",
        "input_data": {"icd10": "E11.9"},
    }

    response = await async_client.post(
        "/v1/gates/evaluate",
        json=payload,
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert response.status_code == 200
    assert response.json()["effect"] == "require_hitl"

    # Give the event loop a tick so the create_task gets scheduled,
    # but don't await the hanging POST itself.
    await asyncio.sleep(0.05)

    result = await db_session.execute(
        select(WebhookDelivery).where(WebhookDelivery.subscription_id == sub.id)
    )
    deliveries = list(result.scalars().all())
    assert len(deliveries) >= 1, "no delivery row created — dispatch never ran"
    # All deliveries must still be in flight (the HTTP POST is hanging).
    # The producer inserts with ``status='in_progress'`` and the task
    # only flips terminal status after the HTTP returns or aborts.
    for d in deliveries:
        assert d.status == "in_progress", (
            f"delivery {d.id} reached terminal status {d.status!r} during "
            "the request — dispatch was synchronous"
        )


@pytest.mark.asyncio
async def test_gate_evaluate_dual_emission_both_rows_created(
    async_client,
    org_and_key,
    db_session,
    _patch_hanging_httpx,
    _await_inflight_after_test,
):
    """Both ``approval.requested`` and ``review.requested`` materialise rows.

    ``request_approval`` fires both legacy and new event names. Even with
    a slow receiver, both rows must exist at response time — neither
    emission may serialise behind the other's HTTP wire-time.
    """
    org, raw_key, _ = org_and_key
    await _seed_active_baa(db_session, org.id)
    sub = await _make_slow_subscription(db_session, org.id)

    payload = {
        "agent_name": "scribemd",
        "action_type": "diagnosis_create",
        "action_name": "add_diagnosis",
        "authorized_by": "dr_smith",
        "data_subject_id": "patient_101",
        "input_data": {"icd10": "E11.9"},
    }

    t0 = time.monotonic()
    response = await async_client.post(
        "/v1/gates/evaluate",
        json=payload,
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    elapsed_ms = (time.monotonic() - t0) * 1000
    assert response.status_code == 200
    assert elapsed_ms < 500, (
        f"dual emission took {elapsed_ms:.0f}ms — second event awaited the first"
    )

    await asyncio.sleep(0.05)

    result = await db_session.execute(
        select(WebhookDelivery).where(WebhookDelivery.subscription_id == sub.id)
    )
    deliveries = list(result.scalars().all())
    event_types = {d.event_type for d in deliveries}
    assert "approval.requested" in event_types, (
        "legacy approval.requested delivery row missing"
    )
    assert "review.requested" in event_types, (
        "new review.requested delivery row missing"
    )
