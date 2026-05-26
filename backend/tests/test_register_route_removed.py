"""W2.3 — POST /v1/register is deleted, not 410.

The 410-Gone stub from Workstream E3 was retired in W2.3 (housekeeping
trio). The Clerk org bridge has been the production provisioning path
for long enough that any remaining legacy clients pointing at
``/v1/register`` are either ours (covered) or noise — keeping a stub
around indefinitely is dead code. Local-dev provisioning lives at
``POST /v1/dev/orgs`` (W1.6).

This regression test locks the deletion: the path must not exist
(``404 Not Found``), not return ``410 Gone``. If a future change
re-mounts a /register router by accident this fails loudly.
"""

import pytest


@pytest.mark.asyncio
async def test_register_path_returns_404(async_client):
    resp = await async_client.post(
        "/v1/register", json={"org_name": "Anything"}
    )
    # 404 means the path doesn't exist. 410 would mean the deprecation
    # stub is still wired up — which is exactly what W2.3 removes.
    assert resp.status_code == 404, (
        f"Expected 404 (path removed) but got {resp.status_code}. "
        "If a /register router was re-introduced, either delete it or "
        "rewrite this test with a clear rationale."
    )


@pytest.mark.asyncio
async def test_register_path_returns_404_with_no_body(async_client):
    resp = await async_client.post("/v1/register")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_register_get_also_404(async_client):
    # Belt-and-braces: a GET should likewise 404, not 405.
    resp = await async_client.get("/v1/register")
    assert resp.status_code == 404
