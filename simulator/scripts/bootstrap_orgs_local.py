"""Local-only bootstrap that bypasses the deprecated POST /v1/register.

`POST /v1/register` returns 410 Gone now — orgs are provisioned via
Clerk webhooks in production. For local acceptance testing without
Clerk, this script seeds 3 customer orgs directly via the backend's
database session, mints an API key per org, and creates an active BAA
+ scope per org (so Gate 3 doesn't block every action).

Idempotent — re-running is safe; existing orgs are reused and only the
API keys are appended to .env.local (the script does NOT overwrite
an existing key for a given customer slug).

Usage:
    cd /Users/priyansh/code/Agent_Compliance
    conda activate vera
    # Backend must be RUNNING and pointed at the same DATABASE_URL
    # the script will use (Railway, local Docker Postgres, or SQLite).
    DATABASE_URL=$DATABASE_URL python -m simulator.scripts.bootstrap_orgs_local
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Ensure backend/ is on sys.path so we can import its models + helpers
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

# Load backend/.env BEFORE importing app.database — Pydantic Settings only
# reads .env files at module-import time (when the Settings class is
# instantiated), so any environment variables we want to influence the
# database engine MUST be in os.environ before that import fires.
#
# This also dodges the common foot-gun of shell sessions where
# DATABASE_URL is set to a stale placeholder (e.g. "user:password@host")
# from a copy-pasted example.
_BACKEND_ENV = REPO_ROOT / "backend" / ".env"
if _BACKEND_ENV.exists():
    for line in _BACKEND_ENV.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        # Only set keys that aren't already populated by a REAL value in
        # the shell. Treat the "host:5432" placeholder as not-real so we
        # override it.
        existing = os.environ.get(key, "")
        if not existing or ("host:5432" in existing and key == "DATABASE_URL"):
            os.environ[key] = value

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: F401

from app.database import AsyncSessionLocal, engine
from app.models import (  # type: ignore[attr-defined]
    APIKey,
    BAAAgreement,
    BAAScope,
    ChainState,
    Customer,
    Organization,
)
from app.services.auth import generate_api_key


CUSTOMERS = [
    {
        "slug": "scribemd",
        "org_name": "ScribeMD Health",
        "tenant_id": "scribemd_default",
        "env_var": "VERA_API_KEY_SCRIBEMD",
    },
    {
        "slug": "triageguard",
        "org_name": "TriageGuard",
        "tenant_id": "triageguard_default",
        "env_var": "VERA_API_KEY_TRIAGEGUARD",
    },
    {
        "slug": "authassist",
        "org_name": "AuthAssist RCM",
        "tenant_id": "authassist_default",
        "env_var": "VERA_API_KEY_AUTHASSIST",
    },
]


def _now_naive_utc() -> datetime:
    """Naive UTC — matches the project convention (see services/hashing.py)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def _ensure_customer_with_active_baa(
    session: AsyncSession, org_id: str, tenant_id: str
) -> None:
    """Idempotent: seed a Customer + active BAA + scope for this org if
    none exists. Required so Gate 3 (stale_baa) doesn't BLOCK every
    action this org tries to take.
    """
    existing = (
        await session.execute(
            select(Customer).where(Customer.org_id == org_id, Customer.tenant_id == tenant_id)
        )
    ).scalar_one_or_none()
    if existing:
        # Check if it already has an active BAA + scope
        active_baa = (
            await session.execute(
                select(BAAAgreement).where(
                    BAAAgreement.org_id == org_id,
                    BAAAgreement.customer_id == existing.id,
                    BAAAgreement.status == "active",
                )
            )
        ).scalar_one_or_none()
        if active_baa:
            return  # already seeded
        customer = existing
    else:
        customer = Customer(org_id=org_id, tenant_id=tenant_id, display_name=tenant_id)
        session.add(customer)
        await session.flush()

    now = _now_naive_utc()
    baa = BAAAgreement(
        org_id=org_id,
        customer_id=customer.id,
        status="active",
        effective_at=now - timedelta(days=1),
        expires_at=now + timedelta(days=365),
        signed_at=now - timedelta(days=1),
    )
    session.add(baa)
    await session.flush()

    scope = BAAScope(
        baa_agreement_id=baa.id,
        is_unrestricted=True,
        covered_services=["*"],
        covered_agent_types=["*"],
        granted_at=now,
    )
    session.add(scope)
    await session.commit()


async def _ensure_org(session: AsyncSession, org_name: str) -> Organization:
    """Idempotent: get or create org by name."""
    existing = (
        await session.execute(select(Organization).where(Organization.name == org_name))
    ).scalar_one_or_none()
    if existing:
        return existing
    org = Organization(name=org_name)
    session.add(org)
    await session.flush()
    chain_state = ChainState(org_id=org.id)
    session.add(chain_state)
    await session.commit()
    await session.refresh(org)
    return org


async def _ensure_api_key(
    session: AsyncSession, org_id: str, env_var: str, existing_env: dict[str, str]
) -> str | None:
    """If env_var already in existing_env, return None (skip). Otherwise
    mint a fresh test-tier key with read+write permissions and return
    the raw key string. Returns None on skip."""
    if existing_env.get(env_var):
        return None
    raw_key, _ = await generate_api_key(
        session,
        org_id=org_id,
        name=f"acceptance-test-{env_var.lower()}",
        permissions=["read", "write"],
        kind="test",
    )
    return raw_key


def _load_env_local(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        out[k.strip()] = v.strip()
    return out


def _append_to_env_local(path: Path, key: str, value: str) -> None:
    """Append KEY=VALUE to the file if KEY is not already present.
    Idempotent — won't duplicate."""
    existing = _load_env_local(path)
    if key in existing:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(f"\n{key}={value}\n")


async def main() -> int:
    env_local = REPO_ROOT / "simulator" / ".env.local"
    existing = _load_env_local(env_local)

    print(f"DATABASE_URL: {os.environ.get('DATABASE_URL', '(sqlite default)')[:60]}...")
    print(f"env file:     {env_local}")
    print(f"customers:    {[c['slug'] for c in CUSTOMERS]}")
    print()

    for cust in CUSTOMERS:
        slug = cust["slug"]
        print(f"[{slug}] {cust['org_name']}")

        async with AsyncSessionLocal() as session:
            org = await _ensure_org(session, cust["org_name"])
            print(f"  org_id: {org.id}")

            await _ensure_customer_with_active_baa(session, org.id, cust["tenant_id"])
            print(f"  customer + active BAA: OK")

            raw_key = await _ensure_api_key(session, org.id, cust["env_var"], existing)
            if raw_key:
                _append_to_env_local(env_local, cust["env_var"], raw_key)
                print(f"  API key minted: {raw_key[:20]}... → {env_local.name}")
            else:
                print(f"  API key already in {env_local.name} (skipped)")

        print()

    await engine.dispose()
    print("Done. Re-source simulator/.env.local in any open shells.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
