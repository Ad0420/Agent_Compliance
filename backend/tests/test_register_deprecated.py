"""POST /v1/register is gone — verify 410 Gone + migration message.

Workstream E3: the legacy self-serve register endpoint was removed because
org provisioning now happens via Clerk webhooks (see
``app/routes/clerk_webhooks.py``). The route still exists as a 410 stub so
in-flight legacy clients get a clear migration message instead of a 404.
"""

import pytest


@pytest.fixture(autouse=True)
def _clear_rate_limit():
    # The register endpoint is unauthenticated; multiple tests share the
    # same per-IP bucket and trip the burst limit without this reset.
    from app.main import app

    stack = getattr(app, "middleware_stack", None)
    visited = set()
    while stack is not None and id(stack) not in visited:
        visited.add(id(stack))
        if type(stack).__name__ == "RateLimitMiddleware":
            requests = getattr(stack, "_requests", None)
            if requests is not None:
                requests.clear()
        stack = getattr(stack, "app", None)
    yield


@pytest.mark.asyncio
async def test_register_returns_410(async_client):
    resp = await async_client.post(
        "/v1/register", json={"org_name": "Anything"}
    )
    assert resp.status_code == 410
    body = resp.json()
    assert body["detail"]["error"] == "endpoint_removed"
    assert "Clerk" in body["detail"]["message"]
    assert "/dashboard/api-keys" in body["detail"]["message"]
    assert body["detail"]["migration_url"].startswith("http")


@pytest.mark.asyncio
async def test_register_returns_410_even_with_no_body(async_client):
    # No body at all should still 410 (the route handler never gets to a
    # validator because it short-circuits to HTTPException).
    resp = await async_client.post("/v1/register")
    assert resp.status_code == 410


@pytest.mark.asyncio
async def test_register_returns_410_does_not_create_org(async_client, db_session):
    """Defensive: the deprecation stub must not have any side effects."""
    from sqlalchemy import select

    from app.models import Organization

    before = (await db_session.execute(select(Organization))).scalars().all()
    await async_client.post(
        "/v1/register", json={"org_name": "Side Effect"}
    )
    after = (await db_session.execute(select(Organization))).scalars().all()
    assert len(after) == len(before)
