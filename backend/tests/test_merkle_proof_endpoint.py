"""Merkle proof exposure tests — Phase 3 Wave 3B.2.

Covers the test-plan rows:

  * "Merkle proof generation — happy path" — independent verifier
    reconstructs the root from the returned payload.
  * "Merkle proof — record in pending checkpoint window" — 409
    ``checkpoint_pending`` + ``Retry-After`` header.
  * "Merkle proof — power-of-2 padding edge case" — proofs verify for
    1 / 2 / 3 / 5 / 7 / 9 leaves.
  * "Merkle proof — single-record checkpoint" — single-leaf proof has
    empty path and root == leaf.
  * "Hash chain still independently valid" — regression: canonical
    bytes still hash to ``record.record_hash`` via the chain rule.
  * Plus per-error-code coverage (404 nonexistent, 404 cross-org, 403
    staff PHI-block, 409 tail-window) and HMAC algorithm surfacing.

The tests use the in-memory SQLite engine + ``async_client`` /
``org_and_key`` fixtures from ``conftest.py``. Where staff-tier
assertions are needed we copy the Clerk-test-helpers pattern from
``test_iam_staff_tier.py`` rather than re-fixturing it.
"""

from __future__ import annotations

import hashlib

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.config import settings
from app.main import app
from app.models import (
    APIKey,
    ActionRecord,
    ChainState,
    Organization,
    OrgMembership,
    StaffAuditLog,
)
from app.models.kms_key import KmsKey
from app.services import auth as auth_service
from app.services.auth import generate_api_key
from app.services.checkpoint import create_checkpoint
from app.services.hashing import compute_record_hash
from app.services.kms import get_kms, set_kms
from app.services.merkle_proof import (
    ProofUnavailable,
    build_proof,
    canonicalize_action_record,
    verify_proof_payload,
)

from tests._clerk_test_helpers import (
    TEST_ISSUER,
    make_keypair,
    reset_rate_limit,
    sign_token,
)


# ── Test plumbing ────────────────────────────────────────────────────────


_STAFF_CLERK_ORG_ID = "org_vera_staff_internal"


@pytest.fixture(scope="module")
def keypair():
    return make_keypair()


@pytest.fixture(autouse=True)
def _configure_clerk(monkeypatch, keypair):
    """Wire test JWKS + designate a staff Clerk org for IamTier resolution."""
    monkeypatch.setattr(settings, "clerk_jwks_url", "https://fixture/jwks.json")
    monkeypatch.setattr(settings, "clerk_issuer", TEST_ISSUER)
    monkeypatch.setattr(settings, "clerk_audience", None)
    monkeypatch.setattr(settings, "clerk_staff_org_id", _STAFF_CLERK_ORG_ID)
    auth_service._reset_jwks_cache_for_tests()

    async def _fake_fetch(_url: str) -> dict:
        return {"keys": [keypair["jwk"]]}

    monkeypatch.setattr(auth_service, "_fetch_jwks", _fake_fetch)
    reset_rate_limit(app)
    yield
    auth_service._reset_jwks_cache_for_tests()


def _staff_token(keypair) -> str:
    return sign_token(
        keypair["priv"],
        sub="user_vera_engineer",
        org_id=_STAFF_CLERK_ORG_ID,
    )


# ── Helpers ──────────────────────────────────────────────────────────────


async def _create_actions(async_client, raw_key, count: int) -> list[str]:
    """Create ``count`` ActionRecords via the public API; return their ids."""
    ids: list[str] = []
    for i in range(count):
        resp = await async_client.post(
            "/v1/actions",
            json={
                "action_name": f"a_{i}",
                "action_type": "function_call",
                "agent_name": "scribe-agent",
                "data_subject_id": f"patient_{i}",
                "input_data": {"note": f"PHI note {i}"},
                "metadata": {"chart_id": f"chart_{i}"},
                "result": "success",
            },
            headers={"Authorization": f"Bearer {raw_key}"},
        )
        assert resp.status_code == 200, resp.text
        ids.append(resp.json()["id"])
    return ids


async def _seal_checkpoint(db_session, org_id: str):
    """Convenience: create a checkpoint for the org via the service.

    Bypasses HTTP so we don't have to mint an admin-key request when the
    test only needs the sealing side-effect.
    """
    return await create_checkpoint(db_session, org_id)


# ── 1. Happy-path proof + independent verifier ───────────────────────────


@pytest.mark.asyncio
async def test_proof_happy_path_reconstructs_root_and_validates_signature(
    async_client, org_and_key, db_session
):
    """Pick a record in the middle of a sealed window. The returned proof
    must (a) reconstruct the Merkle root from the leaf via the path,
    (b) match the sealed checkpoint's signature when verified against the
    KMS provider, and (c) preserve the canonical bytes that hashed to
    ``leaf_hash`` via the chain rule.
    """
    org, raw_key, _ = org_and_key
    ids = await _create_actions(async_client, raw_key, count=7)
    await _seal_checkpoint(db_session, org.id)

    middle_id = ids[3]
    resp = await async_client.get(
        f"/v1/records/{middle_id}/merkle-proof",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    # Shape: every field documented in the brief is present.
    for field in (
        "action_record_id",
        "action_record_canonical",
        "leaf_hash",
        "merkle_path",
        "merkle_root",
        "checkpoint_id",
        "checkpoint_signed_at",
        # Wave 3C.2 — checkpoint-identity fields for offline signature verify.
        "checkpoint_org_id",
        "checkpoint_sequence",
        "checkpoint_hash_at_checkpoint",
        # Phase 3 follow-up — previous_hash so offline verifiers can
        # enforce ``sha256(previous_hash + canonical) == leaf_hash``.
        "previous_hash",
        "kms_key_id",
        "kms_signature",
        "kms_algorithm",
        "kms_public_key_pem",
    ):
        assert field in body, f"missing field {field!r} in proof payload"

    # Phase 3 follow-up: ``previous_hash`` in the payload must match
    # the value persisted on the record. An offline verifier feeds it
    # into the chain rule below; drift here would silently fail every
    # bundle export's chain-rule check.
    record_for_prev = await db_session.get(ActionRecord, middle_id)
    assert body["previous_hash"] == (record_for_prev.previous_hash or "")

    # Wave 3C.2 — the identity fields must match the checkpoint row so a
    # downstream offline verifier can rebuild the signing message.
    assert body["checkpoint_org_id"] == org.id
    assert body["checkpoint_sequence"] > 0
    assert isinstance(body["checkpoint_hash_at_checkpoint"], str)
    assert len(body["checkpoint_hash_at_checkpoint"]) == 64  # sha256 hex

    # (a) Reconstruct the root via the path — pure-Python verifier in
    # the service module; this is what an offline auditor will do.
    assert verify_proof_payload(body) is True

    # (b) The signature validates against the KMS that signed the
    # checkpoint. We assemble the same message bytes that
    # services.checkpoint._checkpoint_message builds.
    from app.models.checkpoint import Checkpoint
    cp = await db_session.get(Checkpoint, body["checkpoint_id"])
    assert cp is not None
    message = (
        f"{cp.org_id}:{cp.sequence_at_checkpoint}:"
        f"{cp.hash_at_checkpoint}:{cp.created_at.isoformat()}"
    ).encode("utf-8")
    assert get_kms().verify(message, body["kms_signature"]) is True

    # (c) Chain rule: SHA256(previous_hash + canonical) ?= leaf_hash.
    # The endpoint returns canonical bytes, not the previous_hash, so
    # the verifier needs both for a full chain replay. We pull
    # previous_hash from the DB to make the assertion explicit.
    record = await db_session.get(ActionRecord, middle_id)
    recomputed_leaf = compute_record_hash(
        body["action_record_canonical"], record.previous_hash
    )
    assert recomputed_leaf == body["leaf_hash"] == record.record_hash


# ── 2. 404: nonexistent record ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_nonexistent_record_404(async_client, org_and_key):
    _, raw_key, _ = org_and_key
    resp = await async_client.get(
        "/v1/records/00000000-0000-0000-0000-000000000000/merkle-proof",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 404, resp.text
    body = resp.json()
    # The app's ``_flatten_dict_detail`` exception handler lifts
    # dict-typed ``HTTPException.detail`` payloads to the top level so
    # the SDK's ``code``-aware error mapping works. Assert via the
    # flat key.
    assert body["code"] == "record_not_found"


# ── 3. 404: cross-org isolation (presence side-channel closed) ───────────


@pytest.mark.asyncio
async def test_cross_org_record_404(async_client, org_and_key, db_session):
    """Customer in org A reads a record that exists ONLY in org B → 404.
    NOT 403 — 403 would confirm "this id exists, just not for you",
    which leaks presence."""
    _, raw_key_a, _ = org_and_key  # org A's key

    # Spin up a second org B with its own record.
    org_b = Organization(name="org-b")
    db_session.add(org_b)
    await db_session.flush()
    db_session.add(ChainState(org_id=org_b.id))
    await db_session.commit()
    raw_key_b, _ = await generate_api_key(
        db_session, org_b.id, "b-key", ["read", "write", "admin"]
    )

    # Create a record under org B via the public API.
    create = await async_client.post(
        "/v1/actions",
        json={
            "action_name": "b_action",
            "action_type": "function_call",
            "agent_name": "b-agent",
            "result": "success",
        },
        headers={"Authorization": f"Bearer {raw_key_b}"},
    )
    assert create.status_code == 200
    b_record_id = create.json()["id"]

    # Org A asks for org B's record — must 404, not 403.
    resp = await async_client.get(
        f"/v1/records/{b_record_id}/merkle-proof",
        headers={"Authorization": f"Bearer {raw_key_a}"},
    )
    assert resp.status_code == 404


# ── 4. 409: tail window (checkpoint_pending) ─────────────────────────────


@pytest.mark.asyncio
async def test_tail_record_returns_409_checkpoint_pending(
    async_client, org_and_key, db_session
):
    """Record exists but no checkpoint has been sealed at-or-above its
    sequence yet → 409 ``checkpoint_pending`` + ``Retry-After`` header.
    """
    org, raw_key, _ = org_and_key
    ids = await _create_actions(async_client, raw_key, count=3)
    # No checkpoint created — every record is in the tail window.
    resp = await async_client.get(
        f"/v1/records/{ids[0]}/merkle-proof",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 409
    assert resp.headers.get("Retry-After") == "60"
    body = resp.json()
    assert body.get("code") == "checkpoint_pending"


@pytest.mark.asyncio
async def test_post_checkpoint_new_record_is_in_tail(
    async_client, org_and_key, db_session
):
    """Seal a checkpoint, then add a new record. The pre-checkpoint
    records resolve; the new record returns 409."""
    org, raw_key, _ = org_and_key
    sealed_ids = await _create_actions(async_client, raw_key, count=2)
    await _seal_checkpoint(db_session, org.id)

    new_ids = await _create_actions(async_client, raw_key, count=1)

    # Sealed record: 200.
    ok = await async_client.get(
        f"/v1/records/{sealed_ids[0]}/merkle-proof",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert ok.status_code == 200

    # Tail record: 409.
    pending = await async_client.get(
        f"/v1/records/{new_ids[0]}/merkle-proof",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert pending.status_code == 409


# ── 5. 403: staff PHI restriction ────────────────────────────────────────


@pytest.mark.asyncio
async def test_staff_blocked_with_audit_row(
    async_client, org_and_key, db_session, keypair
):
    """Staff session (STAFF_READ_ONLY) cannot pull a proof — the
    canonical bytes carry PHI that can't be redacted without breaking
    verification. Refusal is audited (so the customer can later see
    that Vera staff tried to read this)."""
    org, raw_key, _ = org_and_key
    ids = await _create_actions(async_client, raw_key, count=2)
    await _seal_checkpoint(db_session, org.id)

    token = _staff_token(keypair)
    resp = await async_client.get(
        f"/v1/records/{ids[0]}/merkle-proof",
        headers={
            "Authorization": f"Bearer {token}",
            "X-Org-Id": org.id,
        },
    )
    assert resp.status_code == 403, resp.text
    body = resp.json()
    # Flat shape via ``_flatten_dict_detail`` — top-level ``code`` key.
    assert body["code"] == "merkle_proof_phi_restricted"

    # Audit row written.
    rows = (
        await db_session.execute(
            select(StaffAuditLog).where(
                StaffAuditLog.resource_type == "action_record_merkle_proof"
            )
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].endpoint == "/v1/records/{record_id}/merkle-proof"
    assert rows[0].resource_id == ids[0]
    assert rows[0].org_id == org.id
    assert rows[0].staff_id == "user_vera_engineer"
    # ``redacted=False`` here — the response was REFUSED, not redacted.
    # If a future tier ever returns a partial-redaction proof, this
    # should flip — until then the audit-log column accurately reports
    # "no payload was returned at all."
    assert rows[0].redacted is False


# ── 6. HMAC org: algorithm surfaced, public_key_pem null ─────────────────


@pytest.mark.asyncio
async def test_hmac_org_proof_carries_algorithm_no_pem(
    async_client, org_and_key, db_session
):
    """For the default LocalKMS (HMAC) deployment, the proof carries the
    algorithm string + a null ``kms_public_key_pem`` + the signature.
    Independent verification still requires the symmetric secret out-of-
    band; the response makes that legible."""
    org, raw_key, _ = org_and_key
    ids = await _create_actions(async_client, raw_key, count=3)
    await _seal_checkpoint(db_session, org.id)

    resp = await async_client.get(
        f"/v1/records/{ids[1]}/merkle-proof",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["kms_algorithm"] == "hmac-sha256"
    assert body["kms_public_key_pem"] is None
    assert body["kms_signature"]  # present


# ── 7. Asymmetric KMS: PEM is surfaced ──────────────────────────────────


class _FakeAsymmetricKMS:
    """Minimal asymmetric-shaped KMS mock — returns a real-looking PEM
    so the proof carries it."""

    algorithm = "kms-rsa-pss-2048"

    def __init__(self, key_id: str, pem: str, secret: bytes):
        self._key_id = key_id
        self._pem = pem
        self._secret = secret

    def sign(self, message: bytes) -> str:
        import hashlib as _h
        import hmac as _hm

        return _hm.new(self._secret, message, _h.sha256).hexdigest()

    def verify(self, message: bytes, signature: str) -> bool:
        import hmac as _hm

        return _hm.compare_digest(self.sign(message), signature)

    def get_key_id(self) -> str:
        return self._key_id

    def get_public_key_pem(self):
        return self._pem


@pytest.mark.asyncio
async def test_asymmetric_kms_proof_includes_pem(
    async_client, org_and_key, db_session
):
    """An asymmetric KMS registers a row with ``public_key_pem`` set;
    the proof endpoint surfaces that PEM so an offline verifier has the
    material to validate the signature."""
    pem = "-----BEGIN PUBLIC KEY-----\nMIIBIjA...\n-----END PUBLIC KEY-----\n"
    fake = _FakeAsymmetricKMS(
        key_id="asym-test-key", pem=pem, secret=b"asym-secret-for-test"
    )
    prior = get_kms()
    set_kms(fake)
    try:
        org, raw_key, _ = org_and_key
        ids = await _create_actions(async_client, raw_key, count=2)
        await _seal_checkpoint(db_session, org.id)

        resp = await async_client.get(
            f"/v1/records/{ids[0]}/merkle-proof",
            headers={"Authorization": f"Bearer {raw_key}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["kms_algorithm"] == "kms-rsa-pss-2048"
        assert body["kms_public_key_pem"] == pem
        assert body["kms_key_id"] == "asym-test-key"
        # Reconstruction still succeeds — the Merkle path is unaffected
        # by the KMS algorithm.
        assert verify_proof_payload(body) is True
    finally:
        set_kms(prior)


# ── 8. Power-of-2 padding edge cases ────────────────────────────────────


@pytest.mark.parametrize("n_records", [1, 2, 3, 5, 7, 9])
@pytest.mark.asyncio
async def test_padding_edge_cases_proofs_verify(
    async_client, org_and_key, db_session, n_records
):
    """For every leaf in checkpoints of size 1 / 2 / 3 / 5 / 7 / 9, the
    returned proof reconstructs the sealed root.

    Covers the test-plan row "Merkle proof — power-of-2 padding edge
    case" plus the single-record special case (n=1 → empty path, root
    == leaf hash).
    """
    org, raw_key, _ = org_and_key
    ids = await _create_actions(async_client, raw_key, count=n_records)
    await _seal_checkpoint(db_session, org.id)

    for rec_id in ids:
        resp = await async_client.get(
            f"/v1/records/{rec_id}/merkle-proof",
            headers={"Authorization": f"Bearer {raw_key}"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert verify_proof_payload(body) is True

        if n_records == 1:
            # Single-record checkpoint: root equals leaf, empty path.
            assert body["merkle_path"] == []
            assert body["merkle_root"] == body["leaf_hash"]


# ── 9. Canonical bytes still chain-hash to the leaf ─────────────────────


@pytest.mark.asyncio
async def test_returned_canonical_chain_hashes_to_leaf(
    async_client, org_and_key, db_session
):
    """Regression test for the test-plan row "Hash chain still
    independently valid". The endpoint must return canonical bytes that
    the verifier can ``sha256(previous_hash || canonical)`` and get
    ``leaf_hash`` back. Any drift in ``extract_hashable_fields`` or
    ``canonicalize`` between insert-time and proof-time would break
    this immediately."""
    org, raw_key, _ = org_and_key
    ids = await _create_actions(async_client, raw_key, count=4)
    await _seal_checkpoint(db_session, org.id)

    for rec_id in ids:
        resp = await async_client.get(
            f"/v1/records/{rec_id}/merkle-proof",
            headers={"Authorization": f"Bearer {raw_key}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        record = await db_session.get(ActionRecord, rec_id)
        recomputed = compute_record_hash(
            body["action_record_canonical"], record.previous_hash
        )
        assert recomputed == body["leaf_hash"] == record.record_hash


# ── 10. Service-layer unit tests on build_proof / canonicalize ──────────


@pytest.mark.asyncio
async def test_build_proof_raises_checkpoint_pending_for_tail_record(
    async_client, org_and_key, db_session
):
    """Direct service-layer call: no sealed checkpoint → raises
    ``ProofUnavailable('checkpoint_pending', retry_after=60)``."""
    org, raw_key, _ = org_and_key
    ids = await _create_actions(async_client, raw_key, count=1)
    record = await db_session.get(ActionRecord, ids[0])

    with pytest.raises(ProofUnavailable) as exc_info:
        await build_proof(db_session, record=record)
    assert exc_info.value.code == "checkpoint_pending"
    assert exc_info.value.retry_after == 60


@pytest.mark.asyncio
async def test_canonicalize_matches_chain_canonicalize(
    async_client, org_and_key, db_session
):
    """``canonicalize_action_record`` must produce the SAME bytes the
    chain insert-time path produced. We pull a fresh record back from
    the DB and re-run the canonicalizer; the result must match
    ``compute_record_hash(canonical, previous_hash) == record.record_hash``.
    A drift here is exactly the bug the proof endpoint exists to make
    impossible — if the assertion ever fails, every proof returned by
    the endpoint would be unverifiable offline.
    """
    _, raw_key, _ = org_and_key
    ids = await _create_actions(async_client, raw_key, count=1)
    record = await db_session.get(ActionRecord, ids[0])
    canonical = canonicalize_action_record(record)
    assert compute_record_hash(canonical, record.previous_hash) == record.record_hash


# ── 11. Selective-disclosure side-channel closed ────────────────────────


@pytest.mark.asyncio
async def test_proof_does_not_leak_other_records_payloads(
    async_client, org_and_key, db_session
):
    """The proof carries only sibling HASHES, never sibling canonical
    bytes. The test-plan row "verifier can't infer other customers"
    requires this: handing a proof to a third party MUST NOT let them
    reconstruct any other record's payload, only the cryptographic path
    to the root."""
    org, raw_key, _ = org_and_key
    ids = await _create_actions(async_client, raw_key, count=5)
    await _seal_checkpoint(db_session, org.id)

    resp = await async_client.get(
        f"/v1/records/{ids[2]}/merkle-proof",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200
    body = resp.json()

    # Every step's ``sibling_hash`` must be hex (64 chars) — no JSON
    # payload, no patient identifier, no action_name leaks.
    for step in body["merkle_path"]:
        sib = step["sibling_hash"]
        assert isinstance(sib, str) and len(sib) == 64
        int(sib, 16)  # raises ValueError if not pure hex
        assert step["direction"] in {"left", "right"}

    # And the canonical bytes are only for the asked-for record — they
    # don't reference any other record id.
    other_ids = [i for i in ids if i != ids[2]]
    for other in other_ids:
        assert other not in body["action_record_canonical"]


# ── 12. Tamper detection (offline verifier rejects mutations) ───────────


@pytest.mark.asyncio
async def test_tampered_leaf_hash_fails_verification(
    async_client, org_and_key, db_session
):
    """Flip a bit in ``leaf_hash`` → ``verify_proof_payload`` returns
    False. Maps to the "tampered leaf" CLI test plan row."""
    org, raw_key, _ = org_and_key
    ids = await _create_actions(async_client, raw_key, count=4)
    await _seal_checkpoint(db_session, org.id)
    resp = await async_client.get(
        f"/v1/records/{ids[1]}/merkle-proof",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    body = resp.json()

    # Flip the first hex char of leaf_hash.
    body["leaf_hash"] = ("0" if body["leaf_hash"][0] != "0" else "1") + body["leaf_hash"][1:]
    assert verify_proof_payload(body) is False


@pytest.mark.asyncio
async def test_tampered_sibling_hash_fails_verification(
    async_client, org_and_key, db_session
):
    """Flip a bit in ``merkle_path[0].sibling_hash`` → verification
    fails. Maps to the "tampered sibling" CLI test plan row."""
    org, raw_key, _ = org_and_key
    # Need at least 2 leaves for a non-empty path.
    ids = await _create_actions(async_client, raw_key, count=4)
    await _seal_checkpoint(db_session, org.id)
    resp = await async_client.get(
        f"/v1/records/{ids[1]}/merkle-proof",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    body = resp.json()
    assert body["merkle_path"], "expected non-empty path for 4-leaf tree"

    sib = body["merkle_path"][0]["sibling_hash"]
    body["merkle_path"][0]["sibling_hash"] = (
        ("0" if sib[0] != "0" else "1") + sib[1:]
    )
    assert verify_proof_payload(body) is False


@pytest.mark.asyncio
async def test_wrong_root_fails_verification(
    async_client, org_and_key, db_session
):
    """Replace ``merkle_root`` with a different valid-looking hex
    string → verification fails."""
    org, raw_key, _ = org_and_key
    ids = await _create_actions(async_client, raw_key, count=4)
    await _seal_checkpoint(db_session, org.id)
    resp = await async_client.get(
        f"/v1/records/{ids[1]}/merkle-proof",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    body = resp.json()
    body["merkle_root"] = hashlib.sha256(b"not-the-real-root").hexdigest()
    assert verify_proof_payload(body) is False
