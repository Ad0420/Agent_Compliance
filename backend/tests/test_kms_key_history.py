"""Tests for the KMS key history table + history-aware sign/verify
(Phase 3 Wave 3A.a — eng review finding 1A).

Coverage map:
    1.  Migration up/down round-trip (via Base.metadata.create_all)
    2.  ``ensure_key_registered`` idempotent (call twice → 1 row)
    3.  LocalKMS registers with ``public_key_pem=None`` (HMAC)
    4.  Asymmetric KMS would register with PEM — mocked subclass
    5.  Rotate K1→K2: both rows exist; K1 stays ``is_active=True``
        unless manually retired
    6.  Manual retirement: ``retired_at`` set → ``is_active`` flips False
    7.  ``GET /v1/kms/keys`` returns history (200)
    8.  ``GET /v1/kms/keys`` 401/403 with no auth
    9.  ``GET /v1/kms/keys?active_only=true`` filters retired rows
    10. Verify checkpoint signed with current key passes via history
    11a. ``verify_with_history`` returns False for an unknown key_id
    11b. Verify checkpoint with ``key_id`` NOT in history → fails
    12. Verify HMAC retired key signature (key_id != current) → False
    13. Asymmetric retired-key path stubbed False in 3A.a
        (real verify lands in Wave 3C)
    14. Legacy checkpoint without ``key_id`` → falls back to current
        KMS (back-compat path)
    15. ``get_key_history`` ordering — newest first by ``created_at``
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ActionRecord, ChainState, Organization
from app.models.checkpoint import Checkpoint
from app.models.kms_key import KmsKey
from app.schemas.action import ActionRecordCreate
from app.services.chain import build_and_insert_record
from app.services.checkpoint import create_checkpoint, verify_checkpoint
from app.services.kms import (
    ALGO_HMAC_SHA256,
    KMSProvider,
    LocalKMS,
    ensure_key_registered,
    get_key_by_id,
    get_key_history,
    set_kms,
    verify_with_history,
)


# ── Helpers ────────────────────────────────────────────────


def _make_action(**kwargs) -> ActionRecordCreate:
    defaults = {
        "action_name": "test_action",
        "action_type": "function_call",
        "agent_name": "test-agent",
        "result": "success",
    }
    defaults.update(kwargs)
    return ActionRecordCreate(**defaults)


class _FakeAsymmetricKMS(KMSProvider):
    """Mock asymmetric KMS — algorithm + PEM but symmetric-style sign().

    Exists only to exercise the ``public_key_pem != None`` branch in
    :func:`ensure_key_registered`. The signing math is HMAC-shaped, but
    the registered row reports the asymmetric algorithm + PEM so the
    history-aware verifier exercises the retired-asymmetric path.
    """

    algorithm = "kms-rsa-pss-2048"

    def __init__(self, key_id: str, pem: str, secret: bytes):
        self._key_id = key_id
        self._pem = pem
        self._secret = secret

    def sign(self, message: bytes) -> str:
        import hashlib
        import hmac

        return hmac.new(self._secret, message, hashlib.sha256).hexdigest()

    def verify(self, message: bytes, signature: str) -> bool:
        import hmac

        return hmac.compare_digest(self.sign(message), signature)

    def get_key_id(self) -> str:
        return self._key_id

    def get_public_key_pem(self) -> Optional[str]:
        return self._pem


# ── 1. Round-trip (model + table) ──────────────────────────


@pytest.mark.asyncio
async def test_kms_keys_table_created(db_session: AsyncSession):
    """The ``kms_keys`` table exists with the expected columns after
    ``Base.metadata.create_all`` in conftest. Inserts a row and reads
    it back to confirm the schema."""
    row = KmsKey(
        key_id="round-trip",
        algorithm=ALGO_HMAC_SHA256,
        public_key_pem=None,
        is_active=True,
    )
    db_session.add(row)
    await db_session.commit()

    fetched = await db_session.get(KmsKey, "round-trip")
    assert fetched is not None
    assert fetched.algorithm == ALGO_HMAC_SHA256
    assert fetched.public_key_pem is None
    assert fetched.is_active is True
    assert fetched.retired_at is None
    assert fetched.created_at is not None


# ── 2. Idempotent registration ─────────────────────────────


@pytest.mark.asyncio
async def test_ensure_key_registered_idempotent(db_session: AsyncSession):
    """Calling ``ensure_key_registered`` twice on the same KMS produces
    exactly one row."""
    kms = LocalKMS(key="idempotent-secret")
    set_kms(kms)
    try:
        row1 = await ensure_key_registered(db_session, kms)
        await db_session.commit()
        row2 = await ensure_key_registered(db_session, kms)
        await db_session.commit()
        assert row1.key_id == row2.key_id

        count_stmt = select(KmsKey).where(KmsKey.key_id == kms.get_key_id())
        result = await db_session.execute(count_stmt)
        rows = list(result.scalars().all())
        assert len(rows) == 1
    finally:
        set_kms(LocalKMS())


# ── 3. LocalKMS registers with NULL pem ────────────────────


@pytest.mark.asyncio
async def test_local_kms_registers_with_null_pem(db_session: AsyncSession):
    """LocalKMS is HMAC — no public key exists; row's
    ``public_key_pem`` is NULL and algorithm is ``hmac-sha256``."""
    kms = LocalKMS(key="hmac-null-pem")
    set_kms(kms)
    try:
        row = await ensure_key_registered(db_session, kms)
        await db_session.commit()
        assert row.public_key_pem is None
        assert row.algorithm == ALGO_HMAC_SHA256
        assert row.is_active is True
    finally:
        set_kms(LocalKMS())


# ── 4. Asymmetric KMS registers with PEM ───────────────────


@pytest.mark.asyncio
async def test_asymmetric_kms_registers_with_pem(db_session: AsyncSession):
    """A KMSProvider whose ``get_public_key_pem`` returns a real PEM is
    recorded with that PEM, surfacing the offline-verify material."""
    pem = "-----BEGIN PUBLIC KEY-----\nMIIBIjA...\n-----END PUBLIC KEY-----\n"
    kms = _FakeAsymmetricKMS(
        key_id="asym-2026-q2", pem=pem, secret=b"asym-secret"
    )
    set_kms(kms)
    try:
        row = await ensure_key_registered(db_session, kms)
        await db_session.commit()
        assert row.public_key_pem == pem
        assert row.algorithm == "kms-rsa-pss-2048"
    finally:
        set_kms(LocalKMS())


# ── 5. Rotation: both rows exist, both active ──────────────


@pytest.mark.asyncio
async def test_rotation_keeps_both_rows_active(db_session: AsyncSession):
    """After rotating K1 → K2 without manual retirement, both rows
    exist in the history table and both report ``is_active=True``.
    Manual retirement is a separate step."""
    k1 = LocalKMS(key="rotation-k1")
    set_kms(k1)
    try:
        await ensure_key_registered(db_session, k1)
        await db_session.commit()

        k2 = LocalKMS(key="rotation-k2")
        set_kms(k2)
        await ensure_key_registered(db_session, k2)
        await db_session.commit()

        rows = await get_key_history(db_session)
        ids = {r.key_id for r in rows}
        assert k1.get_key_id() in ids
        assert k2.get_key_id() in ids
        for r in rows:
            assert r.is_active is True
            assert r.retired_at is None
    finally:
        set_kms(LocalKMS())


# ── 6. Manual retirement flips is_active ───────────────────


@pytest.mark.asyncio
async def test_manual_retirement(db_session: AsyncSession):
    """Setting ``retired_at`` AND flipping ``is_active`` is the manual
    retirement step. ``is_active`` is a column (not a computed field)
    so the application is responsible for the flip — the model docs
    spell this out."""
    kms = LocalKMS(key="retire-me")
    row = await ensure_key_registered(db_session, kms)
    await db_session.commit()

    row.retired_at = datetime.now(timezone.utc).replace(tzinfo=None)
    row.is_active = False
    await db_session.commit()

    refreshed = await db_session.get(KmsKey, kms.get_key_id())
    assert refreshed is not None
    assert refreshed.is_active is False
    assert refreshed.retired_at is not None


# ── 7. GET /v1/kms/keys 200 returns history ────────────────


@pytest.mark.asyncio
async def test_kms_keys_endpoint_returns_history(
    async_client, org_and_key, db_session
):
    """``GET /v1/kms/keys`` returns the history rows."""
    _, raw_key, _ = org_and_key
    db_session.add(
        KmsKey(
            key_id="endpoint-a",
            algorithm=ALGO_HMAC_SHA256,
            public_key_pem=None,
            is_active=True,
        )
    )
    db_session.add(
        KmsKey(
            key_id="endpoint-b",
            algorithm="kms-rsa-pss-2048",
            public_key_pem="-----BEGIN PUBLIC KEY-----\n...\n-----END PUBLIC KEY-----",
            is_active=True,
        )
    )
    await db_session.commit()

    resp = await async_client.get(
        "/v1/kms/keys", headers={"Authorization": f"Bearer {raw_key}"}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    ids = {k["key_id"] for k in body["keys"]}
    assert "endpoint-a" in ids
    assert "endpoint-b" in ids
    assert body["total"] >= 2


# ── 8. GET /v1/kms/keys 401/403 without auth ───────────────


@pytest.mark.asyncio
async def test_kms_keys_endpoint_unauthenticated(async_client):
    """No bearer → 401/403. Starlette's HTTPBearer returns 403 when the
    Authorization header is missing entirely; the gate would return
    401 for a present-but-invalid token. Accept either to keep the
    test stable across FastAPI's evolving default behaviour."""
    resp = await async_client.get("/v1/kms/keys")
    assert resp.status_code in (401, 403)


# ── 9. active_only=true filters retired keys ───────────────


@pytest.mark.asyncio
async def test_kms_keys_endpoint_active_only_filter(
    async_client, org_and_key, db_session
):
    """``?active_only=true`` excludes retired keys."""
    _, raw_key, _ = org_and_key
    db_session.add(
        KmsKey(
            key_id="active-only-active",
            algorithm=ALGO_HMAC_SHA256,
            public_key_pem=None,
            is_active=True,
        )
    )
    db_session.add(
        KmsKey(
            key_id="active-only-retired",
            algorithm=ALGO_HMAC_SHA256,
            public_key_pem=None,
            is_active=False,
            retired_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
    )
    await db_session.commit()

    resp = await async_client.get(
        "/v1/kms/keys?active_only=true",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200, resp.text
    ids = {k["key_id"] for k in resp.json()["keys"]}
    assert "active-only-active" in ids
    assert "active-only-retired" not in ids


# ── 10. Verify checkpoint via history (current key) ────────


@pytest.mark.asyncio
async def test_verify_checkpoint_via_history_current_key(
    db_session: AsyncSession, org_and_key
):
    """A checkpoint created with the current KMS verifies through the
    history-aware path. Implicitly tests that ``create_checkpoint``
    populates the history row."""
    org, _, _ = org_and_key
    await build_and_insert_record(
        db_session, org.id, _make_action(action_name="for_history_verify")
    )
    cp = await create_checkpoint(db_session, org.id)
    assert cp.key_id is not None

    history_row = await get_key_by_id(db_session, cp.key_id)
    assert history_row is not None, "create_checkpoint did not register the key"

    valid = await verify_checkpoint(db_session, cp)
    assert valid is True


# ── 11. Unknown key_id fails verification (no silent allow) ─


@pytest.mark.asyncio
async def test_verify_with_history_missing_key_id_fails(
    db_session: AsyncSession,
):
    """An unknown ``key_id`` must fail verification — silently
    accepting would defeat the history table's purpose."""
    ok = await verify_with_history(
        db_session,
        key_id="never-seen",
        message=b"anything",
        signature="00" * 32,
    )
    assert ok is False


@pytest.mark.asyncio
async def test_verify_checkpoint_with_unknown_key_id_fails(
    db_session: AsyncSession, org_and_key
):
    """A checkpoint whose ``key_id`` is not in the history table fails
    verification (route-level integration check)."""
    org, _, _ = org_and_key
    await build_and_insert_record(
        db_session, org.id, _make_action(action_name="orphan_key")
    )
    cp = await create_checkpoint(db_session, org.id)

    cp.key_id = "never-registered"
    valid = await verify_checkpoint(db_session, cp)
    assert valid is False


# ── 12. HMAC retired key cannot be verified offline ─────────


@pytest.mark.asyncio
async def test_hmac_retired_key_verify_returns_false(
    db_session: AsyncSession,
):
    """``verify_with_history`` returns False for an HMAC history row
    whose ``key_id`` differs from the current KMS — there is no way to
    verify a symmetric signature without the original secret. The
    HMAC-vs-asymmetric trade-off is documented in the model + migration
    docstrings; this test pins the safe-default behaviour."""
    retired = KmsKey(
        key_id="retired-hmac",
        algorithm=ALGO_HMAC_SHA256,
        public_key_pem=None,
        is_active=False,
        retired_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    db_session.add(retired)
    await db_session.commit()

    set_kms(LocalKMS(key="active-not-retired"))
    try:
        ok = await verify_with_history(
            db_session,
            key_id="retired-hmac",
            message=b"msg",
            signature="00" * 32,
        )
        assert ok is False
    finally:
        set_kms(LocalKMS())


# ── 13. Asymmetric retired key stubbed False in 3A.a ──────


@pytest.mark.asyncio
async def test_asymmetric_retired_key_stub_returns_false(
    db_session: AsyncSession,
):
    """Wave 3A.a returns False for asymmetric retired keys as a safe
    default — the real RSA-PSS / ECDSA verifier lands in Wave 3C.
    Pinning the stub keeps the contract explicit so the 3C agent
    sees a clear test to flip."""
    db_session.add(
        KmsKey(
            key_id="asym-stub",
            algorithm="kms-rsa-pss-2048",
            public_key_pem="-----BEGIN PUBLIC KEY-----\n...\n-----END PUBLIC KEY-----",
            is_active=False,
            retired_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
    )
    await db_session.commit()

    set_kms(LocalKMS(key="some-other-active-key"))
    try:
        ok = await verify_with_history(
            db_session,
            key_id="asym-stub",
            message=b"msg",
            signature="aa" * 32,
        )
        assert ok is False
    finally:
        set_kms(LocalKMS())


# ── 14. Legacy checkpoint (no key_id) falls back ───────────


@pytest.mark.asyncio
async def test_legacy_checkpoint_without_key_id_falls_back(
    db_session: AsyncSession, org_and_key
):
    """A checkpoint written before Wave 3A.a has no ``key_id`` set.
    ``verify_checkpoint`` falls back to the current KMS provider so
    existing checkpoints don't break across the migration boundary."""
    org, _, _ = org_and_key
    await build_and_insert_record(
        db_session, org.id, _make_action(action_name="legacy_path")
    )
    cp = await create_checkpoint(db_session, org.id)

    # Simulate a legacy row: clear key_id (the column didn't exist
    # before Wave 3A.a) and the external_receipt (the published
    # proof embeds key_id; tampering with one without the other
    # makes the external verifier reject — orthogonal to the
    # signature-fallback path we're exercising here).
    cp.key_id = None
    cp.external_receipt = None
    await db_session.commit()

    valid = await verify_checkpoint(db_session, cp)
    assert valid is True


# ── 15. History ordering — newest first ────────────────────


@pytest.mark.asyncio
async def test_get_key_history_orders_newest_first(
    db_session: AsyncSession,
):
    """``get_key_history`` returns rows in ``created_at DESC`` order so
    the dashboard / offline-verify CLI can render the newest key
    first."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    older = KmsKey(
        key_id="order-older",
        algorithm=ALGO_HMAC_SHA256,
        public_key_pem=None,
        is_active=True,
        created_at=now - timedelta(days=10),
    )
    newer = KmsKey(
        key_id="order-newer",
        algorithm=ALGO_HMAC_SHA256,
        public_key_pem=None,
        is_active=True,
        created_at=now - timedelta(days=1),
    )
    db_session.add_all([older, newer])
    await db_session.commit()

    rows = await get_key_history(db_session)
    ours = [r for r in rows if r.key_id in {"order-older", "order-newer"}]
    assert len(ours) == 2
    assert ours[0].key_id == "order-newer"
    assert ours[1].key_id == "order-older"
