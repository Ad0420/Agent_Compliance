"""
Local setup script: creates SQLite database, tables, default org, and admin API key.
Run this before starting the server.
"""
import asyncio
import sys
import os

# Add the backend directory to the path
sys.path.insert(0, os.path.dirname(__file__))

from app.database import engine, AsyncSessionLocal
from app.models import Base, Organization, ChainState
from app.services.auth import generate_api_key


async def setup():
    # 1. Create all tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("[OK] Database tables created")

    async with AsyncSessionLocal() as session:
        # 2. Create default organization
        org = Organization(name="Local Dev Org")
        session.add(org)
        await session.flush()

        # 3. Initialize chain state
        chain_state = ChainState(org_id=org.id)
        session.add(chain_state)
        await session.commit()
        await session.refresh(org)
        print(f"[OK] Organization created: {org.name} (id: {org.id})")

        # 4. Create admin API key
        raw_key, api_key = await generate_api_key(
            session, org.id, "admin-key", ["read", "write", "admin"]
        )
        print(f"[OK] Admin API key created")
        print()
        print("=" * 60)
        print("  YOUR API KEY (save this — it won't be shown again):")
        print(f"  {raw_key}")
        print("=" * 60)
        print()
        print("Next steps:")
        print("  1. Start the server:  cd backend && uvicorn app.main:app --reload")
        print(f"  2. Use this API key in the SDK or demo script")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(setup())
