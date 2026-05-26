"""Unit tests for ``vera.verify.signature``.

Covers the test-plan rows:

* "``vera verify --merkle-proof`` — bad KMS signature" (asymmetric +
  HMAC paths).
* "KMS rotation between checkpoints — proof still verifies" (the
  asymmetric retired-key verify path, which is the rotation case
  from Phase 3 Wave 3A.a's history table).
"""

from __future__ import annotations

import hashlib
import hmac

import pytest

from vera.verify.signature import (
    ALGO_ECDSA_P256_SHA256,
    ALGO_HMAC_SHA256,
    ALGO_RSA_PSS_SHA256,
    build_checkpoint_message,
    verify_signature,
)


# ── Cryptography availability gate ────────────────────────────────────


cryptography = pytest.importorskip(
    "cryptography",
    reason="Asymmetric verify requires the optional `cryptography` package.",
)


def _rsa_keypair():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = priv.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    return priv, pem


def _ec_keypair():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    priv = ec.generate_private_key(ec.SECP256R1())
    pem = priv.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    return priv, pem


def _sign_rsa_pss(priv, message: bytes) -> str:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding

    sig = priv.sign(
        message,
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.MAX_LENGTH,
        ),
        hashes.SHA256(),
    )
    return sig.hex()


def _sign_ecdsa(priv, message: bytes) -> str:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec

    sig = priv.sign(message, ec.ECDSA(hashes.SHA256()))
    return sig.hex()


# ── RSA-PSS path ──────────────────────────────────────────────────────


def test_rsa_pss_good_signature_verifies():
    priv, pem = _rsa_keypair()
    msg = b"orgA:42:abc:2026-01-01T00:00:00"
    sig = _sign_rsa_pss(priv, msg)
    res = verify_signature(
        algorithm=ALGO_RSA_PSS_SHA256,
        public_key_pem=pem,
        message=msg,
        signature_hex=sig,
    )
    assert res.ok, res.detail
    assert res.reason == "ok"


def test_rsa_pss_tampered_signature_fails_with_typed_reason():
    """Flip a byte → ``signature_invalid``, not a crash."""
    priv, pem = _rsa_keypair()
    msg = b"orgA:42:abc:2026-01-01T00:00:00"
    sig = _sign_rsa_pss(priv, msg)
    # Flip the last hex char in a deterministic way.
    tampered = sig[:-1] + ("0" if sig[-1] != "0" else "1")
    res = verify_signature(
        algorithm=ALGO_RSA_PSS_SHA256,
        public_key_pem=pem,
        message=msg,
        signature_hex=tampered,
    )
    assert res.ok is False
    assert res.reason == "signature_invalid"


def test_rsa_pss_tampered_message_fails():
    priv, pem = _rsa_keypair()
    msg = b"orgA:42:abc:2026-01-01T00:00:00"
    sig = _sign_rsa_pss(priv, msg)
    res = verify_signature(
        algorithm=ALGO_RSA_PSS_SHA256,
        public_key_pem=pem,
        message=msg + b":TAMPER",
        signature_hex=sig,
    )
    assert res.ok is False
    assert res.reason == "signature_invalid"


def test_rsa_pss_wrong_public_key_fails():
    """Verify with a freshly generated key the signer never used."""
    signer_priv, _ = _rsa_keypair()
    _, other_pem = _rsa_keypair()
    msg = b"hello"
    sig = _sign_rsa_pss(signer_priv, msg)
    res = verify_signature(
        algorithm=ALGO_RSA_PSS_SHA256,
        public_key_pem=other_pem,
        message=msg,
        signature_hex=sig,
    )
    assert res.ok is False
    assert res.reason == "signature_invalid"


# ── ECDSA path ────────────────────────────────────────────────────────


def test_ecdsa_good_signature_verifies():
    priv, pem = _ec_keypair()
    msg = b"hello world"
    sig = _sign_ecdsa(priv, msg)
    res = verify_signature(
        algorithm=ALGO_ECDSA_P256_SHA256,
        public_key_pem=pem,
        message=msg,
        signature_hex=sig,
    )
    assert res.ok, res.detail


def test_ecdsa_tampered_signature_fails():
    priv, pem = _ec_keypair()
    msg = b"hello world"
    sig = _sign_ecdsa(priv, msg)
    tampered = sig[:-1] + ("0" if sig[-1] != "0" else "1")
    res = verify_signature(
        algorithm=ALGO_ECDSA_P256_SHA256,
        public_key_pem=pem,
        message=msg,
        signature_hex=tampered,
    )
    assert res.ok is False
    # ECDSA tampering may surface as either signature_invalid or a
    # decode error (some byte flips break DER); both are typed reasons.
    assert res.reason in {"signature_invalid", "signature_verify_error"}


# ── HMAC path ─────────────────────────────────────────────────────────


def test_hmac_good_signature_verifies(monkeypatch):
    secret = "super-secret"
    msg = b"orgA:42:abc:2026-01-01T00:00:00"
    sig = hmac.new(
        secret.encode("utf-8"), msg, hashlib.sha256
    ).hexdigest()
    monkeypatch.setenv("VERA_HMAC_SECRET", secret)
    res = verify_signature(
        algorithm=ALGO_HMAC_SHA256,
        public_key_pem=None,
        message=msg,
        signature_hex=sig,
    )
    assert res.ok, res.detail


def test_hmac_wrong_secret_fails(monkeypatch):
    msg = b"orgA:42:abc:2026-01-01T00:00:00"
    sig = hmac.new(b"correct", msg, hashlib.sha256).hexdigest()
    monkeypatch.setenv("VERA_HMAC_SECRET", "wrong")
    res = verify_signature(
        algorithm=ALGO_HMAC_SHA256,
        public_key_pem=None,
        message=msg,
        signature_hex=sig,
    )
    assert res.ok is False
    assert res.reason == "hmac_mismatch"


def test_hmac_secret_missing_returns_soft_fail(monkeypatch):
    """No ``VERA_HMAC_SECRET`` → soft-fail reason, not hard-fail."""
    monkeypatch.delenv("VERA_HMAC_SECRET", raising=False)
    res = verify_signature(
        algorithm=ALGO_HMAC_SHA256,
        public_key_pem=None,
        message=b"any",
        signature_hex="deadbeef",
    )
    assert res.ok is False
    assert res.reason == "hmac_secret_missing"
    # Detail must mention that the record will be marked unverified
    # (caller relies on this distinction).
    assert "unverified" in res.detail


def test_hmac_empty_secret_treated_as_missing(monkeypatch):
    monkeypatch.setenv("VERA_HMAC_SECRET", "")
    res = verify_signature(
        algorithm=ALGO_HMAC_SHA256,
        public_key_pem=None,
        message=b"any",
        signature_hex="deadbeef",
    )
    assert res.ok is False
    assert res.reason == "hmac_secret_missing"


# ── Algorithm dispatch ────────────────────────────────────────────────


def test_unsupported_algorithm_returns_typed_reason():
    res = verify_signature(
        algorithm="md5-please-no",
        public_key_pem=None,
        message=b"x",
        signature_hex="00",
    )
    assert res.ok is False
    assert res.reason == "unsupported_algorithm"


def test_empty_algorithm_returns_typed_reason():
    res = verify_signature(
        algorithm="",
        public_key_pem=None,
        message=b"x",
        signature_hex="00",
    )
    assert res.ok is False
    assert res.reason == "unsupported_algorithm"


def test_asymmetric_missing_pem_returns_typed_reason():
    res = verify_signature(
        algorithm=ALGO_RSA_PSS_SHA256,
        public_key_pem=None,
        message=b"x",
        signature_hex="00",
    )
    assert res.ok is False
    assert res.reason == "public_key_missing"


# ── Backend-parity message builder ────────────────────────────────────


def test_build_checkpoint_message_matches_backend():
    """Mirrors ``backend.app.services.checkpoint._checkpoint_message``."""
    msg = build_checkpoint_message(
        org_id="org-abc",
        sequence=99,
        hash_at_checkpoint="deadbeef",
        signed_at_isoformat="2026-05-25T12:00:00",
    )
    assert msg == b"org-abc:99:deadbeef:2026-05-25T12:00:00"
