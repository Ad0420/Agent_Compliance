"""W1.5 — Delivery-time SSRF re-check tests.

Companion to ``test_webhook_ssrf_guard.py`` (validator unit tests) and
``test_ssrf_registration_hardening.py`` (route-level tests). These cover
the third layer of the SSRF defense-in-depth chain: ``_attempt_delivery``
re-validates the subscription URL right before issuing the outbound HTTP
POST. This catches three classes of bug:

  1. Subscriptions that pre-date the registration-time guard (no
     validation was ever applied at insert).
  2. Subscriptions registered under a different validator version (e.g.
     a new metadata IP added to the block-list after the row existed).
  3. DNS rebinding — the hostname resolved to a public IP at
     registration time but resolves to an internal IP at delivery time.

Cross-reference: phase-2 acceptance finding
``ssrf-guard-non-deterministic-at-delivery-time``.
"""
from __future__ import annotations

import socket
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select

from app.models import (
    WebhookDelivery,
    WebhookDeliveryAttempt,
    WebhookSubscription,
)
from app.services.webhooks import _attempt_delivery


def _ok_mock_client():
    """Build an httpx.AsyncClient mock that returns 200 on every POST."""
    response = MagicMock()
    response.status_code = 200
    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.post = AsyncMock(return_value=response)
    return client


async def _insert_sub(db_session, org_id: str, url: str) -> WebhookSubscription:
    """Insert a subscription, bypassing the route-level guard.

    Mirrors the pre-W1.5 reality: rows may already exist in production
    whose URLs never passed registration-time validation. The
    delivery-time re-check is the only thing standing between those
    rows and the network.
    """
    sub = WebhookSubscription(
        org_id=org_id,
        url=url,
        secret="topsecret",
        event_types=["policy.violation"],
    )
    db_session.add(sub)
    await db_session.commit()
    await db_session.refresh(sub)
    return sub


async def _insert_pending_delivery(
    db_session, org_id: str, sub_id: str, idem: str
) -> str:
    delivery = WebhookDelivery(
        org_id=org_id,
        subscription_id=sub_id,
        event_type="policy.violation",
        payload={"x": 1},
        status="in_progress",
        attempt_count=0,
        idempotency_key=idem,
    )
    db_session.add(delivery)
    await db_session.commit()
    await db_session.refresh(delivery)
    return delivery.id


# ── Test 1: delivery against literal loopback → 1 attempt, aborted ─────


@pytest.mark.asyncio
async def test_delivery_against_loopback_aborts_after_one_attempt(
    db_session, org_and_key
):
    """Delivery against ``127.0.0.1`` must:

    * Skip the HTTP POST (httpx never called).
    * Record exactly ONE attempt whose ``error_message`` starts with
      ``ssrf_blocked:loopback``.
    * Transition delivery to ``status=aborted`` immediately — no
      ``MAX_ATTEMPTS=7`` retry burn on a permanently-bad URL.

    Directly closes the
    ``ssrf-guard-non-deterministic-at-delivery-time`` finding's symptom
    (11+ delivery attempts against the same unsafe URL).
    """
    org, _, _ = org_and_key
    sub = await _insert_sub(db_session, org.id, "http://127.0.0.1:9999/x")
    delivery_id = await _insert_pending_delivery(
        db_session, org.id, sub.id, "ssrf-recheck-loopback"
    )

    # Fail the test if httpx is invoked at all.
    httpx_mock = MagicMock()
    httpx_mock.AsyncClient = MagicMock(
        side_effect=AssertionError(
            "httpx must not be called for SSRF-blocked delivery"
        )
    )
    with patch("app.services.webhooks.httpx", httpx_mock):
        success = await _attempt_delivery(delivery_id)

    assert success is False

    refreshed = await db_session.get(WebhookDelivery, delivery_id)
    await db_session.refresh(refreshed)
    assert refreshed.status == "aborted", (
        f"expected aborted on first attempt, got {refreshed.status}"
    )
    assert refreshed.attempt_count == 1, (
        f"expected exactly 1 attempt (no retries on permanent-unsafe URL), "
        f"got {refreshed.attempt_count}"
    )
    assert refreshed.aborted_at is not None

    attempts = (
        await db_session.execute(
            select(WebhookDeliveryAttempt).where(
                WebhookDeliveryAttempt.delivery_id == delivery_id
            )
        )
    ).scalars().all()
    assert len(attempts) == 1
    assert attempts[0].status_code is None
    assert attempts[0].error_message == "ssrf_blocked:loopback"


# ── Test 2: safe URL → normal delivery path ────────────────────────────


@pytest.mark.asyncio
async def test_delivery_against_safe_url_proceeds_normally(
    db_session, org_and_key
):
    """Sanity check: a subscription with a safe URL is NOT short-
    circuited by the SSRF re-check. The hostname resolves to a public
    IP via the autouse conftest fixture; the delivery should go through
    the normal httpx path and succeed.
    """
    org, _, _ = org_and_key
    sub = await _insert_sub(db_session, org.id, "https://hooks.example.com/in")
    delivery_id = await _insert_pending_delivery(
        db_session, org.id, sub.id, "ssrf-recheck-safe"
    )

    with patch("app.services.webhooks.httpx") as httpx_mock:
        httpx_mock.AsyncClient = MagicMock(return_value=_ok_mock_client())
        success = await _attempt_delivery(delivery_id)

    assert success is True
    refreshed = await db_session.get(WebhookDelivery, delivery_id)
    await db_session.refresh(refreshed)
    assert refreshed.status == "succeeded"
    assert refreshed.attempt_count == 1

    attempts = (
        await db_session.execute(
            select(WebhookDeliveryAttempt).where(
                WebhookDeliveryAttempt.delivery_id == delivery_id
            )
        )
    ).scalars().all()
    assert len(attempts) == 1
    assert attempts[0].status_code == 200
    assert attempts[0].error_message is None


# ── Test 3: DNS rebinding mitigation ───────────────────────────────────


@pytest.mark.asyncio
async def test_delivery_time_dns_rebinding_caught(
    db_session, org_and_key
):
    """DNS rebinding scenario:

    * The subscription's hostname resolved to a benign public IP at
      registration time (the autouse fixture returns 93.184.216.34).
    * Between registration and delivery, the attacker flips DNS to
      point the hostname at 10.0.0.50.
    * The delivery-time re-check MUST catch the flip and abort.

    Without the delivery-time re-check, this is a free SSRF: register a
    hostname, swap the DNS record, drain our internal network.
    """
    org, _, _ = org_and_key
    # Registration uses the autouse fixture → resolves to 93.184.216.34
    # (public). No need to override here; the row gets inserted clean.
    sub = await _insert_sub(
        db_session, org.id, "https://rebind.attacker.example/hook"
    )
    delivery_id = await _insert_pending_delivery(
        db_session, org.id, sub.id, "ssrf-recheck-rebind"
    )

    # Now flip DNS so the delivery-time getaddrinfo returns a private IP.
    import app.services.webhook_url_validation as _v

    def _resolve_to_private(host, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.50", 0))]

    httpx_mock = MagicMock()
    httpx_mock.AsyncClient = MagicMock(
        side_effect=AssertionError(
            "httpx must not be called when delivery-time DNS resolves "
            "to a private IP (DNS rebinding mitigation)"
        )
    )

    with patch.object(_v.socket, "getaddrinfo", _resolve_to_private), \
         patch("app.services.webhooks.httpx", httpx_mock):
        success = await _attempt_delivery(delivery_id)

    assert success is False
    refreshed = await db_session.get(WebhookDelivery, delivery_id)
    await db_session.refresh(refreshed)
    assert refreshed.status == "aborted"
    assert refreshed.attempt_count == 1

    attempts = (
        await db_session.execute(
            select(WebhookDeliveryAttempt).where(
                WebhookDeliveryAttempt.delivery_id == delivery_id
            )
        )
    ).scalars().all()
    assert len(attempts) == 1
    assert attempts[0].error_message == "ssrf_blocked:private_network"
