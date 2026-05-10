"""Tests for the default HTTP timeout on VeraClient and AsyncVeraClient.

Audit operations should fail fast (5s) so customer-facing code never blocks on
Vera availability. See mvp-hardening-plan.md item A3.
"""

from vera import AsyncVeraClient, VeraClient


def test_sync_default_timeout():
    c = VeraClient()
    # httpx.Timeout exposes .connect/.read/.write/.pool. When constructed from
    # a single float, all four are set equal to that float.
    assert c._client.timeout.connect == 5.0
    assert c._client.timeout.read == 5.0
    assert c._client.timeout.write == 5.0
    assert c._client.timeout.pool == 5.0


def test_async_default_timeout():
    c = AsyncVeraClient()
    assert c._client.timeout.connect == 5.0
    assert c._client.timeout.read == 5.0
    assert c._client.timeout.write == 5.0
    assert c._client.timeout.pool == 5.0
