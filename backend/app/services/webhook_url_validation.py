"""SSRF guard for outbound webhook URLs.

Blocks the canonical SSRF surface (RFC 1918 private ranges, loopback,
link-local including AWS instance-metadata 169.254.169.254, IPv6
equivalents, non-http(s) schemes, and cloud metadata IPs).

Used at two layers:
  1. Registration time (POST /v1/webhooks) - reject 400.
  2. Delivery time (services/webhooks._attempt_delivery) - defense in
     depth against DNS rebinding (the resolved IP at registration may
     differ from delivery-time IP).

Closes v1-test-plan.md Phase 2 row "SSRF on webhook URL".
"""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse


_ALLOWED_SCHEMES = frozenset({"http", "https"})

# Explicit cloud metadata IPs not always covered by link-local CIDR.
_BLOCKED_LITERAL_IPS = frozenset({
    "169.254.169.254",   # AWS, GCP, Azure
    "100.100.100.200",   # Alibaba Cloud
    "fd00:ec2::254",     # AWS IPv6 metadata
})


def _is_blocked_ip(ip: ipaddress._BaseAddress) -> tuple[bool, str | None]:
    """Return (blocked, reason) for an IP address."""
    if ip.is_loopback:
        return True, "loopback"
    if ip.is_link_local:
        return True, "link_local"
    if ip.is_private:
        return True, "private_network"
    if ip.is_multicast:
        return True, "multicast"
    if ip.is_reserved:
        return True, "reserved"
    if ip.is_unspecified:
        return True, "unspecified"
    if str(ip) in _BLOCKED_LITERAL_IPS:
        return True, "cloud_metadata"
    return False, None


def is_safe_outbound_url(url: str) -> tuple[bool, str | None]:
    """Return (safe, reason_if_unsafe) for a webhook URL.

    Resolves hostnames via socket.getaddrinfo so an attacker-controlled
    DNS record pointing at 169.254.169.254 is also caught. If DNS
    resolution fails entirely, reject (we cannot prove safety).
    """
    parsed = urlparse(url)
    if not parsed.scheme:
        return False, "missing_scheme"
    if parsed.scheme.lower() not in _ALLOWED_SCHEMES:
        return False, f"scheme_not_allowed:{parsed.scheme.lower()}"
    if not parsed.hostname:
        return False, "missing_hostname"

    host = parsed.hostname
    # Literal IP fast path
    try:
        ip = ipaddress.ip_address(host)
        blocked, reason = _is_blocked_ip(ip)
        if blocked:
            return False, reason
        return True, None
    except ValueError:
        pass  # host is a name, resolve below

    # Hostname -> resolve all A/AAAA records, block if ANY is unsafe
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False, "dns_resolution_failed"

    for _family, _, _, _, sockaddr in infos:
        addr = sockaddr[0]
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            continue
        blocked, reason = _is_blocked_ip(ip)
        if blocked:
            return False, reason

    return True, None
