"""Tests for the Phase 4 Wave 2 PR A3 white-label PDF cover.

Two surfaces under test:

  1. ``PUT /v1/organizations/me/branding`` — multipart upload endpoint
     (logo file + accent-colour hex). Validation: MIME (PNG / SVG),
     size cap (1 MB), accent regex (``#RRGGBB``), SVG sanitisation,
     admin-only auth.
  2. ``POST /v1/audits/{customer_id}`` — extended cover renderer
     branches on ``branding`` (``customer`` vs ``vera-neutral``) and on
     whether ``Organization.logo_bytes`` is populated.

Parsing strategy
----------------
Same as ``test_audit_pdf.py`` — pypdf text extraction for sentinel
strings, plus ``page.images`` for the "logo is on page 1" assertion.
ReportLab non-determinism (creation timestamp, font subset hashes)
makes byte-equality assertions flaky; substring + image-count checks
are stable.

Migration reversibility
-----------------------
``test_pdf_branding_migration_reversible`` exercises the new alembic
revision against a temp SQLite file, asserting upgrade → downgrade →
upgrade leaves the column set in the expected state at each step.
Mirrors the pattern in ``test_checkpoint_cadence.py``.
"""
from __future__ import annotations

import importlib.util
import io
import os
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
import sqlalchemy as sa
from PIL import Image as PILImage
from pypdf import PdfReader
from sqlalchemy import select
from sqlalchemy.orm import undefer

from app.models import (
    BAAAgreement,
    BAAScope,
    ChainState,
    Customer,
    Organization,
)
from app.services.auth import generate_api_key


async def _refetch_org_with_logo(db_session, org_id: str) -> Organization:
    """Fetch an Organization with the deferred ``logo_bytes`` column
    materialised so test assertions can read the blob without tripping
    SQLAlchemy's sync lazy-load (which raises ``MissingGreenlet`` inside
    an async session).

    ``Organization.logo_bytes`` is ``deferred=True`` so generic
    ``session.get(Organization, ...)`` / ``session.refresh(org)`` does
    NOT pull the blob. We mirror the same pattern as
    :func:`app.services.pdf.context.build_context` here.

    Crucially: ``async_client`` overrides ``get_db`` with its own
    session factory so writes from the test's HTTP call land on a
    *different* SQLAlchemy session than the one the ``db_session``
    fixture yields. Those sessions share the same StaticPool engine
    so the data IS persisted, but ``db_session``'s identity map still
    holds the pre-PUT instance. ``expire_all()`` forces SQLAlchemy to
    re-issue a SELECT instead of handing back the cached, stale row.
    """
    db_session.expire_all()
    result = await db_session.execute(
        select(Organization)
        .where(Organization.id == org_id)
        .options(undefer(Organization.logo_bytes))
    )
    return result.scalar_one()


BACKEND_ROOT = Path(__file__).resolve().parents[1]

# Revision IDs for the new migration. Kept as constants so a future
# rename of the migration file fails the test loudly rather than
# silently skipping the reversibility assertion.
REV_PREV = "t0o2p3q4r5s6"
REV_NEW = "w4t7u8v9w0x1"
MIGRATION_FILE = "w4t7u8v9w0x1_add_org_logo_and_accent_color.py"

# Default SVG body used by ``_make_svg_bytes`` when the caller passes no
# explicit body. Held at module scope (rather than inline in the
# f-string) because Python 3.11 disallows backslashes inside f-string
# expression parts: embedding the escaped ``\"`` quotes directly in the
# ``{body or "..."}`` expression triggers ``SyntaxError`` at import time
# on 3.11, even though 3.12+ accepts it. See PEP 701.
_DEFAULT_SVG_BODY = '<rect x="10" y="10" width="80" height="80" fill="#3366cc"/>'


# ── Fixture helpers ─────────────────────────────────────────


def _make_png_bytes(size: tuple[int, int] = (64, 64)) -> bytes:
    """Build a real (header-valid) PNG that Pillow can parse.

    The branding endpoint validates PNG via ``Image.verify()``, so the
    test fixture must produce a file whose header survives that pass.
    A solid-colour buffer is the smallest valid input.
    """
    img = PILImage.new("RGB", size, color=(120, 80, 200))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _make_jpeg_bytes(size: tuple[int, int] = (64, 64)) -> bytes:
    """Build a JPEG so we can test the format-rejection path."""
    img = PILImage.new("RGB", size, color=(120, 80, 200))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def _make_svg_bytes(extra_attrs: str = "", body: str = "") -> bytes:
    """Build a minimal but parseable SVG."""
    svg = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 100 100" width="100" height="100" {extra_attrs}>\n'
        f'  {body or _DEFAULT_SVG_BODY}\n'
        f"</svg>\n"
    )
    return svg.encode("utf-8")


async def _seed_org_with_chain(db_session, name: str) -> Organization:
    org = Organization(name=name)
    db_session.add(org)
    await db_session.flush()
    db_session.add(ChainState(org_id=org.id))
    await db_session.commit()
    await db_session.refresh(org)
    return org


async def _seed_customer(
    db_session, *, org_id: str, tenant_id: str, display_name: str | None = None
) -> Customer:
    c = Customer(
        org_id=org_id,
        tenant_id=tenant_id,
        display_name=display_name or tenant_id,
    )
    db_session.add(c)
    await db_session.commit()
    await db_session.refresh(c)
    return c


async def _seed_active_baa(db_session, *, org_id: str, customer_id: str) -> None:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    agreement = BAAAgreement(
        org_id=org_id,
        customer_id=customer_id,
        document_uri="s3://baa/test.pdf",
        signed_at=now - timedelta(days=30),
        effective_at=now - timedelta(days=29),
        expires_at=now + timedelta(days=300),
        status="active",
    )
    db_session.add(agreement)
    await db_session.flush()
    scope = BAAScope(
        baa_agreement_id=agreement.id,
        covered_services=["chart_entry"],
        covered_agent_types=["scribe"],
        is_unrestricted=True,
        granted_at=now - timedelta(days=29),
    )
    db_session.add(scope)
    await db_session.commit()


def _page1_image_count(pdf_bytes: bytes) -> int:
    """Count XObject images on page 1.

    pypdf's ``Page.images`` returns the list of embedded image
    XObjects on the page. SVG drawings rendered via svglib do NOT
    register as images (they become vector paths), so this test
    function is only meaningful for the PNG-logo branch — SVG-logo
    tests assert against the vector paths via a different sentinel.
    """
    reader = PdfReader(io.BytesIO(pdf_bytes))
    return len(reader.pages[0].images)


def _extract_text(pdf_bytes: bytes) -> str:
    reader = PdfReader(io.BytesIO(pdf_bytes))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


# ── 1. PUT /v1/organizations/me/branding — happy paths ─────────────


@pytest.mark.asyncio
async def test_put_branding_uploads_png_logo(async_client, org_and_key):
    """PUT with a valid PNG + hex colour → 200 and persisted values."""
    _, raw_key, _ = org_and_key
    png = _make_png_bytes()
    resp = await async_client.put(
        "/v1/organizations/me/branding",
        files={"logo": ("logo.png", png, "image/png")},
        data={"accent_color": "#1A73E8"},
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["logo_mime"] == "image/png"
    # Colour normalised to lowercase before storage.
    assert body["accent_color_hex"] == "#1a73e8"


@pytest.mark.asyncio
async def test_put_branding_uploads_svg_logo(async_client, org_and_key, db_session):
    """PUT with a valid SVG → 200; row reflects sanitised bytes + mime."""
    org, raw_key, _ = org_and_key
    svg = _make_svg_bytes()
    resp = await async_client.put(
        "/v1/organizations/me/branding",
        files={"logo": ("logo.svg", svg, "image/svg+xml")},
        data={"accent_color": "#aabbcc"},
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["logo_mime"] == "image/svg+xml"
    fresh = await _refetch_org_with_logo(db_session, org.id)
    assert fresh.logo_mime == "image/svg+xml"
    assert fresh.accent_color_hex == "#aabbcc"
    assert fresh.logo_bytes is not None
    # Sanitised SVG should still parse as an SVG root.
    assert b"<svg" in fresh.logo_bytes.lower()


# ── 2. PUT — validation errors ─────────────────────────────────────


@pytest.mark.asyncio
async def test_put_branding_rejects_oversized_logo(async_client, org_and_key):
    """1.5 MB upload → 400 logo_too_large."""
    _, raw_key, _ = org_and_key
    # 1.5 MB of zero bytes — content is irrelevant, the size cap fires
    # before MIME sniffing.
    oversized = b"\x00" * int(1.5 * 1024 * 1024)
    resp = await async_client.put(
        "/v1/organizations/me/branding",
        files={"logo": ("big.png", oversized, "image/png")},
        data={"accent_color": "#112233"},
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 400, resp.text
    body = resp.json()
    # FastAPI's exception handler flattens dict details to the top
    # level (see ``main._flatten_dict_detail``).
    assert body["code"] == "logo_too_large"


@pytest.mark.asyncio
async def test_put_branding_rejects_invalid_format(async_client, org_and_key):
    """JPEG upload → 400 invalid_logo_format."""
    _, raw_key, _ = org_and_key
    jpeg = _make_jpeg_bytes()
    resp = await async_client.put(
        "/v1/organizations/me/branding",
        files={"logo": ("logo.jpg", jpeg, "image/jpeg")},
        data={"accent_color": "#112233"},
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["code"] == "invalid_logo_format"


@pytest.mark.asyncio
async def test_put_branding_rejects_invalid_color(async_client, org_and_key):
    """Non-hex accent_color → 400 invalid_accent_color."""
    _, raw_key, _ = org_and_key
    png = _make_png_bytes()
    resp = await async_client.put(
        "/v1/organizations/me/branding",
        files={"logo": ("logo.png", png, "image/png")},
        data={"accent_color": "#zzzzzz"},
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["code"] == "invalid_accent_color"


@pytest.mark.asyncio
async def test_put_branding_sanitizes_svg_scripts(
    async_client, org_and_key, db_session
):
    """SVG with ``<script>`` → stored bytes must NOT contain ``<script``."""
    org, raw_key, _ = org_and_key
    malicious = _make_svg_bytes(
        extra_attrs='onload="alert(1)"',
        body=(
            '<script>alert("xss")</script>'
            '<rect x="10" y="10" width="80" height="80" fill="#3366cc" '
            'onclick="evil()"/>'
            '<image href="https://attacker.example/leak.png"/>'
        ),
    )
    resp = await async_client.put(
        "/v1/organizations/me/branding",
        files={"logo": ("logo.svg", malicious, "image/svg+xml")},
        data={"accent_color": "#112233"},
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200, resp.text
    fresh = await _refetch_org_with_logo(db_session, org.id)
    stored_lower = fresh.logo_bytes.lower()
    assert b"<script" not in stored_lower
    assert b"onload" not in stored_lower
    assert b"onclick" not in stored_lower
    # External href stripped — the attacker.example URL must not
    # survive into the stored asset.
    assert b"attacker.example" not in stored_lower


# ── 3. PUT — auth ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_put_branding_rejects_non_admin_session(async_client, db_session):
    """API key with only ``write`` scope → 403 (admin-only endpoint)."""
    org = Organization(name="non-admin-org")
    db_session.add(org)
    await db_session.flush()
    db_session.add(ChainState(org_id=org.id))
    await db_session.commit()

    # Non-admin key (read + write only).
    raw_key, _ = await generate_api_key(
        db_session, org.id, "non-admin", ["read", "write"]
    )
    png = _make_png_bytes()
    resp = await async_client.put(
        "/v1/organizations/me/branding",
        files={"logo": ("logo.png", png, "image/png")},
        data={"accent_color": "#112233"},
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 403, resp.text


# ── 4. PDF cover — customer-branded with logo ─────────────────────


@pytest.mark.asyncio
async def test_pdf_cover_renders_with_customer_logo(
    async_client, org_and_key, db_session
):
    """Configure logo + accent, render PDF with branding=customer → image
    embedded on page 1; Customer name + title still in text stream."""
    org, raw_key, _ = org_and_key
    customer = await _seed_customer(
        db_session,
        org_id=org.id,
        tenant_id="cleveland_clinic",
        display_name="Cleveland Clinic",
    )
    await _seed_active_baa(db_session, org_id=org.id, customer_id=customer.id)

    # Upload the logo via the real endpoint so we exercise the full
    # write path (not just the model column).
    png = _make_png_bytes(size=(200, 100))
    resp = await async_client.put(
        "/v1/organizations/me/branding",
        files={"logo": ("logo.png", png, "image/png")},
        data={"accent_color": "#1a73e8"},
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200, resp.text

    today = date.today()
    resp = await async_client.post(
        f"/v1/audits/{customer.id}",
        json={
            "date_from": (today - timedelta(days=30)).isoformat(),
            "date_to": today.isoformat(),
            "branding": "customer",
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200, resp.text
    pdf_bytes = resp.content

    # Logo embedded as a PDF XObject → at least one image on page 1.
    assert _page1_image_count(pdf_bytes) >= 1

    text = _extract_text(pdf_bytes)
    assert "Cleveland Clinic" in text
    assert "HIPAA AI Audit Trail" in text


# ── 5. PDF cover — customer-branded, no logo configured ────────────


@pytest.mark.asyncio
async def test_pdf_cover_renders_neutral_when_no_logo(
    async_client, org_and_key, db_session
):
    """branding=customer + ``logo_bytes IS NULL`` → no image on page 1, but
    Customer name still appears in text stream as a wordmark."""
    org, raw_key, _ = org_and_key
    customer = await _seed_customer(
        db_session,
        org_id=org.id,
        tenant_id="branded_no_logo",
        display_name="Branded Without Logo",
    )
    await _seed_active_baa(db_session, org_id=org.id, customer_id=customer.id)
    # NB: no PUT /branding call — logo_bytes stays NULL.

    today = date.today()
    resp = await async_client.post(
        f"/v1/audits/{customer.id}",
        json={
            "date_from": (today - timedelta(days=30)).isoformat(),
            "date_to": today.isoformat(),
            "branding": "customer",
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200, resp.text
    pdf_bytes = resp.content
    assert _page1_image_count(pdf_bytes) == 0
    text = _extract_text(pdf_bytes)
    assert "Branded Without Logo" in text


# ── 6. PDF cover — vera-neutral branding ──────────────────────────


@pytest.mark.asyncio
async def test_pdf_cover_vera_neutral_branding(
    async_client, org_and_key, db_session
):
    """branding=vera-neutral → cover text contains 'Vera', no customer
    logo image, Customer name still in body."""
    org, raw_key, _ = org_and_key
    customer = await _seed_customer(
        db_session,
        org_id=org.id,
        tenant_id="vera_neutral_clinic",
        display_name="Vera Neutral Clinic",
    )
    await _seed_active_baa(db_session, org_id=org.id, customer_id=customer.id)

    # Even if a logo is configured, vera-neutral must NOT render it.
    png = _make_png_bytes(size=(200, 100))
    resp = await async_client.put(
        "/v1/organizations/me/branding",
        files={"logo": ("logo.png", png, "image/png")},
        data={"accent_color": "#1a73e8"},
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200, resp.text

    today = date.today()
    resp = await async_client.post(
        f"/v1/audits/{customer.id}",
        json={
            "date_from": (today - timedelta(days=30)).isoformat(),
            "date_to": today.isoformat(),
            "branding": "vera-neutral",
        },
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200, resp.text
    pdf_bytes = resp.content
    # Vera-neutral path MUST NOT embed the Customer's logo on page 1.
    assert _page1_image_count(pdf_bytes) == 0
    text = _extract_text(pdf_bytes)
    assert "Vera" in text
    assert "Vera Neutral Clinic" in text


# ── 7. Migration reversibility ────────────────────────────────────


@pytest.fixture
def temp_db_url(monkeypatch):
    """Temp SQLite file backed by ``DATABASE_URL`` for alembic.

    Mirrors the pattern from ``test_checkpoint_cadence.py``. Each test
    gets a fresh file so upgrade / downgrade ordering is deterministic.
    """
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    url = f"sqlite:///{path}"
    monkeypatch.setenv("DATABASE_URL", url)
    try:
        yield url, path
    finally:
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass


def _inspector(db_url: str):
    engine = sa.create_engine(db_url)
    return engine, sa.inspect(engine)


def _columns(db_url: str, table: str) -> set[str]:
    engine, insp = _inspector(db_url)
    try:
        return {c["name"] for c in insp.get_columns(table)}
    finally:
        engine.dispose()


def _load_migration_module(filename: str):
    """Load an alembic migration as a standalone Python module.

    We isolate just this migration's ``upgrade`` / ``downgrade`` so the
    test can verify reversibility without dragging in the rest of the
    revision chain — relevant here because the project's
    ``s9n1o2p3q4r5`` revision contains a Postgres-only ALTER COLUMN
    that doesn't run on SQLite, and running the full chain to ``head``
    in a SQLite-backed test would fail on that pre-existing migration
    rather than on anything this PR added.
    """
    path = BACKEND_ROOT / "alembic" / "versions" / filename
    spec = importlib.util.spec_from_file_location(filename[:-3], path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _rerun_migration(db_url: str, filename: str, direction: str) -> None:
    """Apply this migration's ``upgrade`` or ``downgrade`` directly.

    ``direction`` is ``"upgrade"`` or ``"downgrade"``. Uses alembic's
    ``MigrationContext`` + ``Operations`` so the migration module's
    ``op.add_column`` / ``op.drop_column`` calls bind to a live DB
    connection.
    """
    assert direction in ("upgrade", "downgrade")
    mod = _load_migration_module(filename)
    engine = sa.create_engine(db_url)
    try:
        with engine.connect() as conn:
            with conn.begin():
                from alembic.runtime.migration import MigrationContext
                from alembic.operations import Operations

                ctx = MigrationContext.configure(conn)
                with Operations.context(ctx):
                    getattr(mod, direction)()
    finally:
        engine.dispose()


def test_pdf_branding_migration_reversible(temp_db_url):
    """upgrade → downgrade → upgrade leaves columns in the expected
    presence/absence state at each step.

    Runs the migration in isolation against a DB pre-populated with
    just the ``organizations`` table (via SQLAlchemy ``create_all``)
    rather than walking the full alembic chain to ``head``. The
    sibling ``s9n1o2p3q4r5`` revision contains a Postgres-only
    ``ALTER COLUMN`` that doesn't execute on SQLite, so a chain-walk
    test would fail on that pre-existing migration rather than on
    anything this PR introduced. Isolating to a single migration
    matches the ``_rerun_upgrade`` pattern used in
    ``test_checkpoint_cadence.py``.

    The post-upgrade ``Base.metadata`` here will have the new columns
    pre-declared (the model already carries them), so we set up a
    stripped table that mimics the *pre-migration* shape.
    """
    db_url, _ = temp_db_url
    engine = sa.create_engine(db_url)
    try:
        # Stripped pre-migration shape — only the columns the migration
        # operates on are absent. Other columns are irrelevant to the
        # reversibility check, so the minimal schema keeps the test
        # focused.
        with engine.begin() as conn:
            conn.execute(
                sa.text(
                    "CREATE TABLE organizations ("
                    "  id VARCHAR(36) PRIMARY KEY,"
                    "  name VARCHAR NOT NULL"
                    ")"
                )
            )
    finally:
        engine.dispose()

    def cols() -> set[str]:
        return _columns(db_url, "organizations")

    # 1) upgrade adds all three columns.
    _rerun_migration(db_url, MIGRATION_FILE, "upgrade")
    after_up = cols()
    assert "logo_bytes" in after_up
    assert "logo_mime" in after_up
    assert "accent_color_hex" in after_up

    # 2) downgrade removes them.
    _rerun_migration(db_url, MIGRATION_FILE, "downgrade")
    after_down = cols()
    assert "logo_bytes" not in after_down
    assert "logo_mime" not in after_down
    assert "accent_color_hex" not in after_down

    # 3) upgrade again — idempotent re-application.
    _rerun_migration(db_url, MIGRATION_FILE, "upgrade")
    after_up_again = cols()
    assert "logo_bytes" in after_up_again
    assert "logo_mime" in after_up_again
    assert "accent_color_hex" in after_up_again


def test_pdf_branding_migration_file_present():
    """Sanity: the migration file exists at the expected path so
    ``MIGRATION_FILE`` doesn't silently drift if the file is renamed.
    """
    path = BACKEND_ROOT / "alembic" / "versions" / MIGRATION_FILE
    assert path.exists(), f"missing migration file: {path}"
    # And the module loads as a valid Python file.
    spec = importlib.util.spec_from_file_location(MIGRATION_FILE[:-3], path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.revision == REV_NEW
    assert mod.down_revision == REV_PREV
