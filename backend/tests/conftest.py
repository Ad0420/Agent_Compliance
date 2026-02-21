import asyncio

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models import Base, Organization, ChainState, APIKey
from app.services.auth import generate_api_key
from app.services.immutability import install_sqlite_triggers
from app.database import get_db
from app.main import app


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture
async def db_engine():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        echo=False,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(install_sqlite_triggers)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine):
    session_factory = async_sessionmaker(
        db_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with session_factory() as session:
        yield session


@pytest_asyncio.fixture
async def org_and_key(db_session):
    """Create a test org with chain state and an admin API key.
    Returns (org, raw_key, api_key).
    """
    org = Organization(name="test-org")
    db_session.add(org)
    await db_session.flush()

    chain_state = ChainState(org_id=org.id)
    db_session.add(chain_state)
    await db_session.commit()
    await db_session.refresh(org)

    raw_key, api_key = await generate_api_key(
        db_session, org.id, "test-admin-key", ["read", "write", "admin"]
    )
    return org, raw_key, api_key


@pytest_asyncio.fixture
async def async_client(db_engine, org_and_key):
    """httpx AsyncClient wired to the FastAPI app with test DB."""
    session_factory = async_sessionmaker(
        db_engine, class_=AsyncSession, expire_on_commit=False
    )

    async def override_get_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()
