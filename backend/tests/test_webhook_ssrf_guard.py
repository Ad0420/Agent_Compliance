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
