"""W1.5 — Registration-time SSRF hardening tests.

Companion to ``test_webhook_ssrf_guard.py`` (which unit-tests the
``is_safe_outbound_url`` validator). These tests exercise the FULL
``POST /v1/webhooks`` HTTP path so a regression that silently un-wires
the validator from the route handler is caught immediately. PR #227
wired the guard at registration time; W1.5 locks that contract in with
explicit route-level assertions and adds the DNS-rebinding scenario.

Cross-reference: phase-2 acceptance findings
``ssrf-guard-not-blocking-loopback-on-webhook-registration``.
"""
from __future__ import annotations

import socket
from unittest.mock import patch

import pytest


# ── Literal-IP SSRF payloads (route layer) ─────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url,expected_reason",
    [
        ("http://127.0.0.1/x", "loopback"),
        ("http://127.0.0.1:9999/x", "loopback"),
        ("http://10.0.0.1/x", "private_network"),
        ("http://172.16.0.1/x", "private_network"),
        ("http://192.168.1.1/x", "private_network"),
        ("http://169.254.169.254/latest/meta-data/", "link_local"),
        ("http://[::1]/x", "loopback"),
        ("http://[fe80::1]/x", "link_local"),
        ("http://100.100.100.200/x", "cloud_metadata"),
        # 0.0.0.0/8 is matched by ``is_private`` in the stdlib before
        # ``is_unspecified``, so the guard reports ``private_network``.
        # Either label is correct — what matters is that 0.0.0.0 is
        # blocked.
        ("http://0.0.0.0/x", "private_network"),
    ],
)
async def test_post_webhook_blocks_literal_ssrf(
    async_client, org_and_key, url, expected_reason
):
    """POST /v1/webhooks with a literal SSRF IP → 400 ssrf_blocked.

    Replays the exact reproduction from the Scenario 4 finding. If this
    test regresses, the registration-time guard has been unwired from
    the route handler.
    """
    _, raw_key, _ = org_and_key
    resp = await async_client.post(
        "/v1/webhooks",
        json={"url": url, "event_types": ["review.requested"]},
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 400, (
        f"expected 400 for {url!r}, got {resp.status_code}: {resp.text}"
    )
    # ``main.py::_flatten_dict_detail`` lifts dict-typed ``HTTPException.detail``
    # to the top level — wire shape is ``{"code": ..., "reason": ...}``.
    body = resp.json()
    assert body.get("code") == "ssrf_blocked", f"got body {body!r}"
    assert body.get("reason") == expected_reason


@pytest.mark.asyncio
async def test_post_webhook_file_scheme_rejected_by_schema_layer(
    async_client, org_and_key
):
    """``file:///etc/passwd`` is rejected by the Pydantic schema (422)
    BEFORE the SSRF guard runs. Either rejection class is acceptable —
    the contract is "never persisted". Documents the two-layer defense.
    """
    _, raw_key, _ = org_and_key
    resp = await async_client.post(
        "/v1/webhooks",
        json={
            "url": "file:///etc/passwd",
            "event_types": ["review.requested"],
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    # 422: Pydantic schema rejects non-http(s) prefix.
    # 400: Would mean the schema accepted it and SSRF guard caught it.
    # Either is "blocked"; we just need NOT 200.
    assert resp.status_code in (400, 422), (
        f"file:// must not register, got {resp.status_code}: {resp.text}"
    )


# ── Hostname → public IP: allowed ──────────────────────────────────────


@pytest.mark.asyncio
async def test_post_webhook_public_hostname_allowed(
    async_client, org_and_key
):
    """Hostname resolving to a public IP → 200 created.

    The autouse ``_patch_ssrf_dns_for_tests`` fixture already points
    hostnames at ``93.184.216.34`` (example.com). This is the happy
    path baseline — proves the guard isn't over-blocking legitimate URLs.
    """
    _, raw_key, _ = org_and_key
    resp = await async_client.post(
        "/v1/webhooks",
        json={
            "url": "https://api.example.com/webhooks/vera",
            "event_types": ["review.requested"],
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["url"] == "https://api.example.com/webhooks/vera"


# ── Hostname → private IP: blocked (DNS rebinding) ─────────────────────


@pytest.mark.asyncio
async def test_post_webhook_dns_rebinding_blocked(
    async_client, org_and_key
):
    """Attacker-controlled DNS pointing a hostname at an RFC 1918 IP →
    400 ssrf_blocked. This is the classic DNS-rebinding precursor — if
    we accept the URL at registration just because it's a hostname, the
    attacker flips DNS at delivery time and we leak internal traffic.
    """
    _, raw_key, _ = org_and_key
    import app.services.webhook_url_validation as _v

    def _resolve_to_private(host, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.50", 0))]

    with patch.object(_v.socket, "getaddrinfo", _resolve_to_private):
        resp = await async_client.post(
            "/v1/webhooks",
            json={
                "url": "https://attacker.example/webhook",
                "event_types": ["review.requested"],
            },
            headers={"Authorization": f"Bearer {raw_key}"},
        )
    assert resp.status_code == 400, resp.text
    assert resp.json()["code"] == "ssrf_blocked"
    assert resp.json()["reason"] == "private_network"


@pytest.mark.asyncio
async def test_post_webhook_dns_resolution_failure_blocked(
    async_client, org_and_key
):
    """Unresolvable hostname → 400. Fail-closed: if we can't prove the
    URL is safe, we don't persist it. Without this, an attacker can
    register a sentinel hostname and flip DNS later.
    """
    _, raw_key, _ = org_and_key
    import app.services.webhook_url_validation as _v

    def _fail(host, *args, **kwargs):
        raise socket.gaierror("nodename nor servname provided")

    with patch.object(_v.socket, "getaddrinfo", _fail):
        resp = await async_client.post(
            "/v1/webhooks",
            json={
                "url": "https://nonexistent.invalid/x",
                "event_types": ["review.requested"],
            },
            headers={"Authorization": f"Bearer {raw_key}"},
        )
    assert resp.status_code == 400, resp.text
    assert resp.json()["code"] == "ssrf_blocked"
    assert resp.json()["reason"] == "dns_resolution_failed"


# ── PATCH path: same guard must apply when URL is updated ──────────────


@pytest.mark.asyncio
async def test_patch_webhook_blocks_ssrf_url_update(
    async_client, org_and_key
):
    """PATCH /v1/webhooks/{id} swapping in an SSRF URL → 400 ssrf_blocked.

    An attacker who compromises an API key could otherwise re-target an
    existing subscription at ``169.254.169.254`` without re-creating it.
    The guard MUST run on update too.
    """
    _, raw_key, _ = org_and_key
    # Create a benign subscription first.
    create = await async_client.post(
        "/v1/webhooks",
        json={
            "url": "https://api.example.com/hook",
            "event_types": ["review.requested"],
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert create.status_code == 200, create.text
    sub_id = create.json()["id"]

    patch_resp = await async_client.patch(
        f"/v1/webhooks/{sub_id}",
        json={"url": "http://169.254.169.254/latest/meta-data/"},
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert patch_resp.status_code == 400, patch_resp.text
    assert patch_resp.json()["code"] == "ssrf_blocked"
    assert patch_resp.json()["reason"] == "link_local"


# ── No subscription row persisted when SSRF blocks ─────────────────────


@pytest.mark.asyncio
async def test_blocked_registration_does_not_persist_subscription(
    async_client, org_and_key, db_session
):
    """The blocked POST must NOT create a ``WebhookSubscription`` row.

    A naive implementation might persist first and validate later. This
    test catches that: list-after-block returns zero subscriptions.
    """
    _, raw_key, _ = org_and_key
    resp = await async_client.post(
        "/v1/webhooks",
        json={
            "url": "http://127.0.0.1:9999/x",
            "event_types": ["review.requested"],
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 400, resp.text

    list_resp = await async_client.get(
        "/v1/webhooks",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert list_resp.status_code == 200
    assert list_resp.json()["webhooks"] == [], (
        "SSRF-blocked POST must not persist a subscription row"
    )
