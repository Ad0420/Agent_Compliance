import asyncio

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models import Base, Customer, Organization, ChainState, APIKey
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

    # SQLite has FK enforcement OFF by default. Per-test PRAGMA may not
    # stick across aiosqlite's connection pool, so we wire it onto the
    # underlying sync engine's connect event — every fresh DBAPI connection
    # picks it up automatically. Required for accurate CASCADE / SET NULL
    # behaviour in model tests.
    @event.listens_for(engine.sync_engine, "connect")
    def _enable_sqlite_fk(dbapi_conn, _connection_record):
        cursor = dbapi_conn.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()

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


@pytest_asyncio.fixture(autouse=True)
async def _patch_async_session_local_for_webhooks(db_engine, monkeypatch):
    """Wave 2B PR A3 — point ``AsyncSessionLocal`` at the test engine.

    The webhook delivery pipeline (``services.webhooks._attempt_delivery``
    + ``services.webhook_sweeper``) opens its own sessions via
    ``AsyncSessionLocal`` so a fire-and-forget ``asyncio.create_task``
    doesn't hold the caller's request session. Tests run against an
    in-memory engine, so unless we patch the module-level binding the
    background task lands on the dev ``vera.db`` (or worse, a Postgres
    that doesn't have the test fixtures).

    Autouse so every test gets the redirect without explicit setup —
    matches the spirit of the in-memory ``db_engine`` fixture itself.
    Individual tests can still ``patch(...)`` to override.
    """
    session_factory = async_sessionmaker(
        db_engine, class_=AsyncSession, expire_on_commit=False
    )
    import app.services.webhooks as _webhooks_module

    monkeypatch.setattr(
        _webhooks_module, "AsyncSessionLocal", session_factory
    )
    # Sweeper uses its own import binding.
    try:
        import app.services.webhook_sweeper as _sweeper_module

        monkeypatch.setattr(
            _sweeper_module, "AsyncSessionLocal", session_factory
        )
    except Exception:
        pass
    yield


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
async def make_org_and_customer(db_session):
    """Factory fixture returning ``async def make(name) -> (Organization, Customer)``.

    Centralised here so the Customer/CustomerAgent/BAA test modules don't
    each maintain their own (drift-prone) helper.
    """

    async def _make(name: str) -> tuple[Organization, Customer]:
        org = Organization(name=name)
        db_session.add(org)
        await db_session.flush()
        customer = Customer(org_id=org.id, tenant_id=f"{name}_tenant")
        db_session.add(customer)
        await db_session.commit()
        await db_session.refresh(customer)
        return org, customer

    return _make


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
