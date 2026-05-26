"""Unit tests for ``vera.verify.proof`` (Wave 3C.2).

These cover the four tamper modes called out in the brief —
tampered-leaf, tampered-sibling, wrong-root, signature-invalid — plus
the HMAC-no-secret non-fatal warning path. Each test builds a tiny
Merkle tree locally so the assertions don't depend on a running
backend.
"""

from __future__ import annotations

import hashlib
import hmac

import pytest

from vera.verify.proof import (
    ALGO_HMAC_SHA256,
    ALGO_RSA_PSS_SHA256,
    REASON_MERKLE_PATH_MISMATCH,
    REASON_OK,
    REASON_SIGNATURE_ALGORITHM_UNSUPPORTED,
    REASON_SIGNATURE_INVALID,
    REASON_SIGNATURE_UNVERIFIABLE_HMAC,
    build_checkpoint_message,
    verify_merkle_path,
    verify_proof_payload,
)


def _hash_pair(left: str, right: str) -> str:
    return hashlib.sha256((left + right).encode("utf-8")).hexdigest()


def _build_tree(leaves: list[str]) -> dict:
    """Build a tiny power-of-2 padded tree and return level lists."""
    n = len(leaves)
    next_pow2 = 1 << (n - 1).bit_length() if n > 1 else 1
    padded = list(leaves) + [leaves[-1]] * (next_pow2 - n)
    levels = [padded]
    current = padded
    while len(current) > 1:
        nxt = [
            _hash_pair(current[i], current[i + 1])
            for i in range(0, len(current), 2)
        ]
        levels.append(nxt)
        current = nxt
    return {"levels": levels, "root": current[0]}


def _proof_for(levels: list[list[str]], leaf_index: int) -> list[dict]:
    """Generate a proof path for ``leaf_index`` in ``levels``."""
    path: list[dict] = []
    idx = leaf_index
    for level in levels[:-1]:
        if idx % 2 == 0:
            sibling_idx = idx + 1
            direction = "right"
        else:
            sibling_idx = idx - 1
            direction = "left"
        sibling = (
            level[sibling_idx] if sibling_idx < len(level) else level[idx]
        )
        path.append({"sibling_hash": sibling, "direction": direction})
        idx //= 2
    return path


def _good_payload(*, signed_at: str = "2026-05-25T14:30:00") -> dict:
    """Return a happy-path payload with HMAC signature already computed."""
    leaves = ["a" * 64, "b" * 64, "c" * 64, "d" * 64]
    tree = _build_tree(leaves)
    target = 1  # leaf at index 1
    path = _proof_for(tree["levels"], target)
    org_id = "org_abc"
    sequence = 42
    hash_at_cp = "f" * 64
    secret = b"shared-hmac-secret"
    message = build_checkpoint_message(
        org_id=org_id,
        sequence=sequence,
        hash_at_checkpoint=hash_at_cp,
        signed_at=signed_at,
    )
    sig = hmac.new(secret, message, hashlib.sha256).hexdigest()
    return {
        "action_record_id": "rec_001",
        "action_record_canonical": "{}",
        "leaf_hash": leaves[target],
        "merkle_path": path,
        "merkle_root": tree["root"],
        "checkpoint_id": "cp_001",
        "checkpoint_signed_at": signed_at,
        "checkpoint_org_id": org_id,
        "checkpoint_sequence": sequence,
        "checkpoint_hash_at_checkpoint": hash_at_cp,
        "kms_key_id": "key-fingerprint",
        "kms_signature": sig,
        "kms_algorithm": ALGO_HMAC_SHA256,
        "kms_public_key_pem": None,
    }, secret


# ── Merkle path verification (no signature) ─────────────────────────────


def test_happy_path_verify_merkle_path() -> None:
    payload, _ = _good_payload()
    assert verify_merkle_path(
        leaf_hash=payload["leaf_hash"],
        merkle_path=payload["merkle_path"],
        merkle_root=payload["merkle_root"],
    ) is True


def test_single_leaf_empty_path_root_equals_leaf() -> None:
    leaves = ["e" * 64]
    tree = _build_tree(leaves)
    assert tree["root"] == leaves[0]
    assert verify_merkle_path(
        leaf_hash=leaves[0],
        merkle_path=[],
        merkle_root=tree["root"],
    ) is True


def test_tampered_leaf_fails() -> None:
    payload, _ = _good_payload()
    # Flip one nibble in the leaf hash → fold mismatches root.
    payload["leaf_hash"] = "0" + payload["leaf_hash"][1:]
    assert verify_merkle_path(
        leaf_hash=payload["leaf_hash"],
        merkle_path=payload["merkle_path"],
        merkle_root=payload["merkle_root"],
    ) is False


def test_tampered_sibling_fails() -> None:
    payload, _ = _good_payload()
    # Flip one bit in the first sibling hash.
    sibling = payload["merkle_path"][0]["sibling_hash"]
    payload["merkle_path"][0]["sibling_hash"] = (
        "0" + sibling[1:]
    )
    assert verify_merkle_path(
        leaf_hash=payload["leaf_hash"],
        merkle_path=payload["merkle_path"],
        merkle_root=payload["merkle_root"],
    ) is False


def test_wrong_root_fails() -> None:
    payload, _ = _good_payload()
    # Replace root with a valid-looking but wrong hex string.
    payload["merkle_root"] = "9" * 64
    assert verify_merkle_path(
        leaf_hash=payload["leaf_hash"],
        merkle_path=payload["merkle_path"],
        merkle_root=payload["merkle_root"],
    ) is False


# ── verify_proof_payload — end-to-end (path + signature) ────────────────


def test_full_verify_happy_path_with_hmac_secret() -> None:
    payload, secret = _good_payload()
    result = verify_proof_payload(payload, hmac_secret=secret)
    assert result.ok is True
    assert result.reason == REASON_OK
    assert result.signature_warning is False


def test_full_verify_tampered_leaf_fails_with_path_mismatch_reason() -> None:
    payload, secret = _good_payload()
    payload["leaf_hash"] = "0" + payload["leaf_hash"][1:]
    result = verify_proof_payload(payload, hmac_secret=secret)
    assert result.ok is False
    assert result.reason == REASON_MERKLE_PATH_MISMATCH


def test_full_verify_tampered_sibling_fails() -> None:
    payload, secret = _good_payload()
    payload["merkle_path"][0]["sibling_hash"] = (
        "0" + payload["merkle_path"][0]["sibling_hash"][1:]
    )
    result = verify_proof_payload(payload, hmac_secret=secret)
    assert result.ok is False
    assert result.reason == REASON_MERKLE_PATH_MISMATCH


def test_full_verify_wrong_root_fails() -> None:
    payload, secret = _good_payload()
    payload["merkle_root"] = "9" * 64
    result = verify_proof_payload(payload, hmac_secret=secret)
    assert result.ok is False
    assert result.reason == REASON_MERKLE_PATH_MISMATCH


def test_full_verify_bad_signature_fails() -> None:
    payload, secret = _good_payload()
    # Tamper the signature bytes — Merkle path still validates so
    # the failure reason must be the signature mismatch, not the path.
    payload["kms_signature"] = "00" * 32
    result = verify_proof_payload(payload, hmac_secret=secret)
    assert result.ok is False
    assert result.reason == REASON_SIGNATURE_INVALID


def test_full_verify_hmac_without_secret_is_non_fatal_warning() -> None:
    """Per brief: HMAC + no shared secret → ok=True with warning flag."""
    payload, _ = _good_payload()
    result = verify_proof_payload(payload, hmac_secret=None)
    assert result.ok is True
    assert result.signature_warning is True
    assert "HMAC" in result.failure_detail


def test_full_verify_unsupported_algorithm_fails() -> None:
    payload, _ = _good_payload()
    payload["kms_algorithm"] = "ecdsa-p256-sha256"  # not implemented
    result = verify_proof_payload(payload, hmac_secret=b"x")
    assert result.ok is False
    assert result.reason == REASON_SIGNATURE_ALGORITHM_UNSUPPORTED


def test_full_verify_missing_field_fails_cleanly() -> None:
    payload, _ = _good_payload()
    del payload["merkle_path"]
    result = verify_proof_payload(payload)
    assert result.ok is False
    assert "merkle_path" in result.failure_detail


# ── Tampered checkpoint identity (signature must rebuild from fields) ────


def test_tampered_checkpoint_sequence_fails_signature() -> None:
    """If someone swaps ``checkpoint_sequence`` in the payload after
    signing, the rebuilt message bytes differ → signature fails. This
    is the load-bearing property that makes the new identity fields
    safe to expose (Wave 3C.2 added them so the payload is self-
    contained for offline verify)."""
    payload, secret = _good_payload()
    payload["checkpoint_sequence"] = payload["checkpoint_sequence"] + 1
    result = verify_proof_payload(payload, hmac_secret=secret)
    assert result.ok is False
    assert result.reason == REASON_SIGNATURE_INVALID


def test_tampered_checkpoint_org_id_fails_signature() -> None:
    payload, secret = _good_payload()
    payload["checkpoint_org_id"] = "org_evil"
    result = verify_proof_payload(payload, hmac_secret=secret)
    assert result.ok is False
    assert result.reason == REASON_SIGNATURE_INVALID


def test_tampered_checkpoint_hash_at_checkpoint_fails_signature() -> None:
    payload, secret = _good_payload()
    payload["checkpoint_hash_at_checkpoint"] = "0" * 64
    result = verify_proof_payload(payload, hmac_secret=secret)
    assert result.ok is False
    assert result.reason == REASON_SIGNATURE_INVALID


# ── skip_signature mode ─────────────────────────────────────────────────


def test_skip_signature_returns_ok_when_path_valid() -> None:
    payload, _ = _good_payload()
    # Even with no secret + intact path, skip_signature short-circuits.
    result = verify_proof_payload(payload, skip_signature=True)
    assert result.ok is True


def test_skip_signature_still_catches_path_tampering() -> None:
    payload, _ = _good_payload()
    payload["merkle_root"] = "9" * 64
    result = verify_proof_payload(payload, skip_signature=True)
    assert result.ok is False
    assert result.reason == REASON_MERKLE_PATH_MISMATCH


# ── RSA-PSS path (smoke test using a real keypair) ───────────────────────


def test_rsa_pss_happy_and_tampered() -> None:
    """Sanity-check the asymmetric verifier path using cryptography.

    Generates an in-process RSA keypair, signs the rebuilt checkpoint
    message with RSA-PSS-SHA256 + MGF1-MAX_LENGTH salt (matching the
    backend's expected algorithm wiring), and asserts the verifier
    accepts the good signature and rejects a flipped one.
    """
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding, rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_pem = (
        key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("utf-8")
    )
    payload, _ = _good_payload()
    payload["kms_algorithm"] = ALGO_RSA_PSS_SHA256
    payload["kms_public_key_pem"] = public_pem
    message = build_checkpoint_message(
        org_id=payload["checkpoint_org_id"],
        sequence=payload["checkpoint_sequence"],
        hash_at_checkpoint=payload["checkpoint_hash_at_checkpoint"],
        signed_at=payload["checkpoint_signed_at"],
    )
    sig = key.sign(
        message,
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.MAX_LENGTH,
        ),
        hashes.SHA256(),
    )
    payload["kms_signature"] = sig.hex()

    good = verify_proof_payload(payload)
    assert good.ok is True
    assert good.signature_warning is False

    # Tamper signature.
    bad = dict(payload)
    bad["kms_signature"] = "00" * len(sig)
    bad_result = verify_proof_payload(bad)
    assert bad_result.ok is False
    assert bad_result.reason == REASON_SIGNATURE_INVALID
