import asyncio
import os

# Force synchronous webhook dispatch in tests so the in-memory SQLite
# connection isn't contended by background ``asyncio.create_task`` work
# mid-test. Set BEFORE importing ``app.*`` so ``services.webhooks``
# sees it at module load. Production never sets this.
os.environ.setdefault("VERA_WEBHOOK_SYNC_DISPATCH", "1")
# Phase 3 Wave 3A.b — disable the checkpoint cadence sweeper by default
# in tests. Individual tests that need to exercise the sweeper opt in
# explicitly via ``monkeypatch.setattr(settings, ...)`` or by calling
# ``sweep_due_checkpoints`` directly. Mirrors the webhook sweeper
# pattern; both default to enabled in production and disabled in tests.
os.environ.setdefault("VERA_CHECKPOINT_SWEEPER_ENABLED", "false")

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

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
        # StaticPool keeps a single shared in-memory DB connection
        # across ALL sessions. Without it, aiosqlite gives each session
        # its own (separate, empty) memory DB and tests see no fixture
        # data. With Wave 2B PR A3's fire-and-forget background tasks
        # this also serialises the savepoint usage so two concurrent
        # ``begin_nested()`` calls don't trip
        # "cannot release savepoint - SQL statements in progress".
        poolclass=StaticPool,
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


@pytest.fixture(autouse=True)
def _disable_checkpoint_export_by_default(monkeypatch):
    """Phase 3 Wave 3B.1 — disable the customer S3 mirror exporter by
    default in tests.

    ``services.checkpoint.create_checkpoint`` calls
    ``schedule_export`` which spawns a background task on a separate
    session; under the in-memory StaticPool DB this races the parent
    session in concurrent-action regression tests. Tests that exercise
    the exporter (e.g. test_checkpoint_export.py
    ``test_sealing_checkpoint_schedules_export``) re-enable it via
    ``monkeypatch.setattr(settings, "checkpoint_export_enabled", True)``.
    The unit tests that call ``export_checkpoint_to_customer_mirror``
    directly don't go through ``create_checkpoint`` so the flag is
    irrelevant for them.
    """
    from app.config import settings as _settings
    monkeypatch.setattr(_settings, "checkpoint_export_enabled", False)


@pytest.fixture(autouse=True)
def _patch_ssrf_dns_for_tests(monkeypatch):
    """Wave 2D B3 — make synthetic test URLs resolve to a benign public IP.

    The SSRF guard in ``services/webhook_url_validation.py`` rejects
    hostnames whose DNS resolution fails (fail-closed). Most tests use
    ``hooks.example.com`` / ``x.example.com`` / ``attacker.example``
    style sentinel URLs that don't resolve, which would otherwise turn
    every webhook test into ``400 ssrf_blocked``.

    For tests, point all hostname lookups at a known public IP
    (``93.184.216.34`` — example.com). Tests that need to assert the
    SSRF guard itself patch ``socket.getaddrinfo`` directly inside the
    test body, which takes precedence over this fixture's monkeypatch.
    """
    import socket as _socket
    import app.services.webhook_url_validation as _v

    def _fake_getaddrinfo(host, *args, **kwargs):
        # If a test points at a literal IP it'll never hit this branch
        # (the validator's literal-IP fast path runs first). For
        # hostnames, return one synthetic public A record.
        return [(_socket.AF_INET, _socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]

    monkeypatch.setattr(_v.socket, "getaddrinfo", _fake_getaddrinfo)


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

    Also drains any leftover background tasks at teardown so a
    fire-and-forget task from the prior test doesn't race the next
    test's transaction (which trips ``cannot release savepoint - SQL
    statements in progress`` on CI's slower Python 3.12 runner).
    """
    import asyncio as _asyncio

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
    # Wave 3A.c — staff_audit_log writer uses its own ``AsyncSessionLocal``
    # binding so the audit row persists across a rolled-back request
    # transaction. Point it at the test engine the same way.
    try:
        import app.services.iam as _iam_module

        monkeypatch.setattr(
            _iam_module, "AsyncSessionLocal", session_factory
        )
    except Exception:
        pass
    # Wave 3B.1 — checkpoint S3 mirror exporter uses ``AsyncSessionLocal``
    # the same way (fire-and-forget background task on its own session).
    try:
        import app.services.checkpoint_export as _export_module

        monkeypatch.setattr(
            _export_module, "AsyncSessionLocal", session_factory
        )
    except Exception:
        pass
    # Phase 4 Wave 2 C4 — the audits route persists a
    # ``generated_audit_pdfs`` history row on a separate session
    # (defense-in-depth: a history write that constraint-violates must
    # not poison the request session). Same redirect.
    try:
        import app.routes.audits as _audits_route_module

        monkeypatch.setattr(
            _audits_route_module, "AsyncSessionLocal", session_factory
        )
    except Exception:
        pass
    yield
    # Drain any in-flight webhook delivery tasks BEFORE the next test
    # opens a session. Lingering background tasks holding the same
    # in-memory engine connection can collide with the next test's
    # ``begin_nested()`` SAVEPOINT (see chain._get_or_create_agent),
    # producing ``cannot release savepoint - SQL statements in
    # progress`` on CI's Python 3.12 runner where the scheduler is
    # different enough from 3.11 that the prior test's tasks are still
    # mid-flight when the next test starts.
    try:
        inflight = list(
            getattr(_webhooks_module, "_inflight_tasks", set())
        )
        if inflight:
            await _asyncio.wait(
                inflight, timeout=5.0,
                return_when=_asyncio.ALL_COMPLETED,
            )
        # Also drain any non-_track_task ``create_task`` (e.g.
        # auto-discovery's pending_events loop in chain.py).
        for _ in range(50):
            other = [
                t
                for t in _asyncio.all_tasks()
                if t is not _asyncio.current_task() and not t.done()
            ]
            if not other:
                break
            await _asyncio.wait(
                other, timeout=0.1,
                return_when=_asyncio.FIRST_COMPLETED,
            )
    except Exception:
        pass


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
