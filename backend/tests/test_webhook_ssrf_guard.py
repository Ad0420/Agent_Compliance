"""Tests for the SSRF guard (Wave 2D B3)."""
from __future__ import annotations

from unittest.mock import patch
import pytest
from app.services.webhook_url_validation import is_safe_outbound_url


# Unsafe URLs - each should be blocked.
@pytest.mark.parametrize("url,expected_reason_prefix", [
    ("http://127.0.0.1/hook", "loopback"),
    ("http://127.255.0.1/hook", "loopback"),
    ("http://10.0.0.1/hook", "private_network"),
    ("http://172.16.0.1/hook", "private_network"),
    ("http://192.168.1.1/hook", "private_network"),
    ("http://169.254.169.254/latest/meta-data/", "link_local"),
    ("http://169.254.1.1/hook", "link_local"),
    ("http://[::1]/hook", "loopback"),
    ("http://[fe80::1]/hook", "link_local"),
    ("http://100.100.100.200/hook", "cloud_metadata"),  # Alibaba metadata IP
    ("file:///etc/passwd", "scheme_not_allowed"),
    ("gopher://internal/", "scheme_not_allowed"),
    ("javascript:alert(1)", "scheme_not_allowed"),
    ("data:text/html,<script>", "scheme_not_allowed"),
    ("ftp://example.com/", "scheme_not_allowed"),
    ("not-a-url-at-all", "missing_scheme"),
    ("http://", "missing_hostname"),
])
def test_unsafe_url_blocked(url: str, expected_reason_prefix: str) -> None:
    safe, reason = is_safe_outbound_url(url)
    assert safe is False, f"expected {url!r} blocked"
    assert reason is not None
    assert reason.startswith(expected_reason_prefix), f"got reason={reason!r}"


def test_public_url_allowed_with_mocked_dns() -> None:
    """Public hostname resolving to a public IP is allowed."""
    with patch("app.services.webhook_url_validation.socket.getaddrinfo") as ga:
        ga.return_value = [(2, 1, 6, "", ("93.184.216.34", 0))]  # example.com
        safe, reason = is_safe_outbound_url("https://example.com/webhook")
        assert safe is True
        assert reason is None


def test_hostname_resolving_to_private_ip_blocked() -> None:
    """DNS rebinding mitigation - attacker-controlled DNS pointing at internal IP."""
    with patch("app.services.webhook_url_validation.socket.getaddrinfo") as ga:
        ga.return_value = [(2, 1, 6, "", ("10.0.0.50", 0))]
        safe, reason = is_safe_outbound_url("https://attacker.example/webhook")
        assert safe is False
        assert reason == "private_network"


def test_hostname_resolving_to_metadata_endpoint_blocked() -> None:
    with patch("app.services.webhook_url_validation.socket.getaddrinfo") as ga:
        ga.return_value = [(2, 1, 6, "", ("169.254.169.254", 0))]
        safe, reason = is_safe_outbound_url("https://meta.example/")
        assert safe is False
        assert reason == "link_local"


def test_dns_resolution_failure_blocked() -> None:
    """Cannot prove safety -> block."""
    import socket as _socket
    with patch("app.services.webhook_url_validation.socket.getaddrinfo") as ga:
        ga.side_effect = _socket.gaierror("nodename nor servname provided")
        safe, reason = is_safe_outbound_url("https://nonexistent.invalid/")
        assert safe is False
        assert reason == "dns_resolution_failed"


# ── Integration: delivery-time guard short-circuits HTTP + aborts ─────


@pytest.mark.asyncio
async def test_delivery_time_ssrf_blocks_http_and_aborts(db_session, org_and_key):
    """A subscription whose URL is unsafe at delivery time must:

    1. Skip the HTTP POST entirely (no httpx call).
    2. Mark the delivery as ``aborted`` (no retries — permanently unsafe).
    3. Record an attempt with ``error_message`` starting ``ssrf_blocked:``.
    """
    from unittest.mock import MagicMock
    from unittest.mock import patch as _patch
    from sqlalchemy import select

    from app.models import (
        WebhookDelivery,
        WebhookDeliveryAttempt,
        WebhookSubscription,
    )
    from app.services.webhooks import _attempt_delivery

    org, _, _ = org_and_key

    sub = WebhookSubscription(
        org_id=org.id,
        url="http://169.254.169.254/latest/meta-data/",  # AWS metadata
        secret="topsecret",
        event_types=["policy.violation"],
    )
    db_session.add(sub)
    await db_session.commit()
    await db_session.refresh(sub)

    delivery = WebhookDelivery(
        org_id=org.id,
        subscription_id=sub.id,
        event_type="policy.violation",
        payload={"x": 1},
        status="in_progress",
        attempt_count=0,
        idempotency_key="ssrf-test-k1",
    )
    db_session.add(delivery)
    await db_session.commit()
    await db_session.refresh(delivery)
    delivery_id = delivery.id

    # The httpx client MUST NOT be called — assert by failing if it is.
    httpx_mock = MagicMock()
    httpx_mock.AsyncClient = MagicMock(
        side_effect=AssertionError(
            "httpx must not be called for SSRF-blocked URL"
        )
    )
    with _patch("app.services.webhooks.httpx", httpx_mock):
        success = await _attempt_delivery(delivery_id)

    assert success is False

    refreshed = await db_session.get(WebhookDelivery, delivery_id)
    await db_session.refresh(refreshed)
    assert refreshed.status == "aborted", (
        f"expected aborted, got {refreshed.status}"
    )
    assert refreshed.attempt_count == 1

    attempts = (
        await db_session.execute(
            select(WebhookDeliveryAttempt).where(
                WebhookDeliveryAttempt.delivery_id == delivery_id
            )
        )
    ).scalars().all()
    assert len(attempts) == 1
    assert attempts[0].status_code is None
    assert attempts[0].error_message is not None
    assert attempts[0].error_message.startswith("ssrf_blocked:")
