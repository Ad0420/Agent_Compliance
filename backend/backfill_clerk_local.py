"""One-shot local dev helper: pull every Clerk org + membership for the
configured CLERK_SECRET_KEY and insert matching backend rows. Idempotent.

Use this when you don't have an inbound webhook on localhost (the normal
way the bridge populates) but you still want the dashboard to authenticate.
Production should rely on the webhook handler instead.
"""
import asyncio
import os
import sys

import httpx

sys.path.insert(0, os.path.dirname(__file__))

from app.config import settings  # noqa: E402
from app.database import AsyncSessionLocal, engine  # noqa: E402
from app.models import (  # noqa: E402
    Base,
    ChainState,
    Organization,
    OrgMembership,
)
from sqlalchemy import select  # noqa: E402

CLERK_API = "https://api.clerk.com/v1"

_ROLE_MAP = {
    "org:admin": "admin",
    "admin": "admin",
    "org:compliance_reviewer": "compliance_reviewer",
    "org:member": "developer",
    "member": "developer",
    "org:developer": "developer",
}


async def fetch(client: httpx.AsyncClient, path: str) -> list[dict]:
    resp = await client.get(f"{CLERK_API}{path}", params={"limit": 100})
    resp.raise_for_status()
    body = resp.json()
    return body.get("data", body) if isinstance(body, dict) else body


async def main() -> None:
    if not settings.clerk_secret_key:
        sys.exit("CLERK_SECRET_KEY missing in backend/.env")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with httpx.AsyncClient(
        headers={"Authorization": f"Bearer {settings.clerk_secret_key}"},
        timeout=10.0,
    ) as http:
        orgs = await fetch(http, "/organizations")
        print(f"Found {len(orgs)} org(s) in Clerk")

        async with AsyncSessionLocal() as db:
            for org_data in orgs:
                clerk_org_id = org_data["id"]
                name = org_data.get("name") or f"clerk:{clerk_org_id}"

                existing = (
                    await db.execute(
                        select(Organization).where(
                            Organization.clerk_org_id == clerk_org_id,
                            Organization.deleted_at.is_(None),
                        )
                    )
                ).scalar_one_or_none()

                if existing is None:
                    org = Organization(name=name, clerk_org_id=clerk_org_id)
                    db.add(org)
                    await db.flush()
                    db.add(ChainState(org_id=org.id))
                    await db.flush()
                    print(f"  + Org   {name} ({clerk_org_id}) -> {org.id}")
                else:
                    org = existing
                    print(f"  = Org   {name} ({clerk_org_id}) -> {org.id}")

                members = await fetch(
                    http, f"/organizations/{clerk_org_id}/memberships"
                )
                for m in members:
                    user = m.get("public_user_data") or {}
                    clerk_user_id = user.get("user_id")
                    if not clerk_user_id:
                        continue
                    role = _ROLE_MAP.get(m.get("role", ""), "developer")

                    mem = (
                        await db.execute(
                            select(OrgMembership).where(
                                OrgMembership.clerk_user_id == clerk_user_id,
                                OrgMembership.clerk_org_id == clerk_org_id,
                            )
                        )
                    ).scalar_one_or_none()
                    if mem is None:
                        db.add(
                            OrgMembership(
                                org_id=org.id,
                                clerk_user_id=clerk_user_id,
                                clerk_org_id=clerk_org_id,
                                role=role,
                            )
                        )
                        print(f"    + Member {clerk_user_id} ({role})")
                    else:
                        mem.role = role
                        print(f"    = Member {clerk_user_id} ({role})")

            await db.commit()

    await engine.dispose()
    print("\nDone. Reload http://localhost:3000/dashboard")


if __name__ == "__main__":
    asyncio.run(main())
