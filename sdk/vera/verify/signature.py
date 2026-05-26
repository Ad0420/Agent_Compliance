"""Pure-Python KMS-signature verification.

Verifies a checkpoint signature without contacting Vera. Three paths:

* **HMAC** (algorithm ``hmac-sha256`` or ``kms-hmac-sha256``) —
  symmetric. Needs the shared secret. Read from ``VERA_HMAC_SECRET``
  env var. If absent, returns ``("hmac_secret_missing", ...)`` so the
  offline pipeline can mark the record "unverified" rather than fail
  the whole bundle.
* **RSA-PSS** (algorithm ``rsa-pss-sha256`` / ``RSASSA_PSS_SHA_256``) —
  asymmetric. Public key comes in from the proof payload as a PEM. We
  use ``cryptography`` if available; if the user installed
  ``vera-sdk`` without the optional ``cryptography`` dep we return
  ``"cryptography_unavailable"`` so the CLI can print a helpful
  install hint.
* **ECDSA** (algorithm ``ecdsa-p256-sha256`` / ``ECDSA_SHA_256``) — same
  asymmetric path.

Failure mode constants (see :class:`SignatureResult.reason`):

* ``"ok"`` — signature verified.
* ``"unsupported_algorithm"`` — algorithm string isn't one we know.
* ``"hmac_secret_missing"`` — HMAC path but ``VERA_HMAC_SECRET`` unset.
* ``"hmac_mismatch"`` — HMAC computed but didn't match.
* ``"cryptography_unavailable"`` — asymmetric path but the
  ``cryptography`` library isn't installed.
* ``"public_key_missing"`` — asymmetric path but the proof carries no
  ``kms_public_key_pem``. Means the checkpoint was sealed by a
  retired HMAC key whose secret is gone — by design, that signature
  cannot be independently verified offline. Logged separately so the
  bundle can still mark records "unverified" instead of "failed".
* ``"signature_invalid"`` — asymmetric verify raised; the signature is
  not valid for the public key + message.
* ``"signature_decode_error"`` — the hex signature can't be decoded.

The functions never raise on a signature failure; they always return a
:class:`SignatureResult`. Programmer-error inputs (missing keys in the
payload dict) raise ``KeyError`` as usual.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger("vera.verify.signature")


# Algorithm string constants. Kept in sync with backend
# ``app.services.kms``. The asymmetric strings below are placeholders
# for Wave 3C+ algorithms; the verifier accepts a handful of common
# spellings (the backend doesn't normalise yet, and AWS KMS returns
# its enum literals like ``RSASSA_PSS_SHA_256``).
ALGO_HMAC_SHA256 = "hmac-sha256"
ALGO_KMS_HMAC_SHA256 = "kms-hmac-sha256"
ALGO_RSA_PSS_SHA256 = "rsa-pss-sha256"
ALGO_RSA_PSS_SHA256_AWS = "rsassa_pss_sha_256"  # AWS KMS literal
ALGO_ECDSA_P256_SHA256 = "ecdsa-p256-sha256"
ALGO_ECDSA_P256_SHA256_AWS = "ecdsa_sha_256"  # AWS KMS literal

_HMAC_ALGORITHMS = frozenset({ALGO_HMAC_SHA256, ALGO_KMS_HMAC_SHA256})
_RSA_PSS_ALGORITHMS = frozenset(
    {ALGO_RSA_PSS_SHA256, ALGO_RSA_PSS_SHA256_AWS}
)
_ECDSA_ALGORITHMS = frozenset(
    {ALGO_ECDSA_P256_SHA256, ALGO_ECDSA_P256_SHA256_AWS}
)


@dataclass(frozen=True)
class SignatureResult:
    """Outcome of a signature-verification attempt.

    ``ok`` is True only on a clean verification. ``reason`` is the
    machine-readable code from the module docstring; for ``ok=True``
    it's ``"ok"``. ``detail`` is a human-readable string for the CLI
    table; it carries no PHI.
    """

    ok: bool
    reason: str
    detail: str = ""

    # Convenience constructors that keep the call sites readable.
    @classmethod
    def success(cls) -> "SignatureResult":
        return cls(ok=True, reason="ok", detail="signature verified")

    @classmethod
    def fail(cls, reason: str, detail: str = "") -> "SignatureResult":
        return cls(ok=False, reason=reason, detail=detail)


def _hmac_secret_from_env() -> Optional[bytes]:
    """Read the HMAC secret from ``VERA_HMAC_SECRET``.

    Returns ``None`` if unset. Documented separately so tests can
    monkey-patch ``os.environ`` and so the offline pipeline can
    distinguish "secret missing" from "secret wrong".
    """
    raw = os.environ.get("VERA_HMAC_SECRET")
    if raw is None or raw == "":
        return None
    return raw.encode("utf-8")


def _verify_hmac(*, message: bytes, signature_hex: str) -> SignatureResult:
    secret = _hmac_secret_from_env()
    if secret is None:
        return SignatureResult.fail(
            "hmac_secret_missing",
            detail=(
                "HMAC algorithm but VERA_HMAC_SECRET not set. Offline "
                "HMAC verification requires the shared secret. Record "
                "marked unverified (not failed)."
            ),
        )
    expected = hmac.new(secret, message, hashlib.sha256).hexdigest()
    if hmac.compare_digest(expected, signature_hex):
        return SignatureResult.success()
    return SignatureResult.fail(
        "hmac_mismatch",
        detail="HMAC signature did not match the configured VERA_HMAC_SECRET.",
    )


def _verify_asymmetric(
    *,
    algorithm: str,
    public_key_pem: Optional[str],
    message: bytes,
    signature_hex: str,
) -> SignatureResult:
    if not public_key_pem:
        # By design, asymmetric checkpoints carry a PEM. If it's absent
        # AND the algorithm is asymmetric, the proof payload is broken
        # (or the backend sealed with a retired key that lost its PEM).
        # The pipeline treats this as "unverified" rather than failed.
        return SignatureResult.fail(
            "public_key_missing",
            detail=(
                "Asymmetric algorithm but proof payload carries no "
                "kms_public_key_pem. Cannot verify offline."
            ),
        )
    try:
        import cryptography  # noqa: F401 — probe
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa
    except ImportError:
        return SignatureResult.fail(
            "cryptography_unavailable",
            detail=(
                "Asymmetric verify requires the ``cryptography`` package. "
                "Install with: pip install vera-sdk[spool]"
            ),
        )

    try:
        signature_bytes = bytes.fromhex(signature_hex)
    except ValueError:
        return SignatureResult.fail(
            "signature_decode_error",
            detail="Signature hex string could not be decoded.",
        )

    try:
        public_key = serialization.load_pem_public_key(public_key_pem.encode("utf-8"))
    except Exception as exc:  # noqa: BLE001 — wrap to a typed reason
        return SignatureResult.fail(
            "public_key_invalid",
            detail=f"Could not load public key PEM: {exc}",
        )

    algo_norm = algorithm.lower()
    try:
        if algo_norm in _RSA_PSS_ALGORITHMS:
            if not isinstance(public_key, rsa.RSAPublicKey):
                return SignatureResult.fail(
                    "public_key_type_mismatch",
                    detail="Algorithm claims RSA-PSS but PEM is not an RSA key.",
                )
            public_key.verify(
                signature_bytes,
                message,
                padding.PSS(
                    mgf=padding.MGF1(hashes.SHA256()),
                    # MAX_LENGTH matches AWS KMS RSASSA_PSS_SHA_256 default.
                    salt_length=padding.PSS.MAX_LENGTH,
                ),
                hashes.SHA256(),
            )
        elif algo_norm in _ECDSA_ALGORITHMS:
            if not isinstance(public_key, ec.EllipticCurvePublicKey):
                return SignatureResult.fail(
                    "public_key_type_mismatch",
                    detail="Algorithm claims ECDSA but PEM is not an EC key.",
                )
            public_key.verify(
                signature_bytes,
                message,
                ec.ECDSA(hashes.SHA256()),
            )
        else:
            return SignatureResult.fail(
                "unsupported_algorithm",
                detail=f"Unrecognised algorithm: {algorithm!r}",
            )
    except InvalidSignature:
        return SignatureResult.fail(
            "signature_invalid",
            detail="Signature did not validate against the public key.",
        )
    except Exception as exc:  # noqa: BLE001 — wrap to a typed reason
        # Defensive: cryptography raises a small number of types here.
        # Wrap so the CLI doesn't barf an opaque exception.
        return SignatureResult.fail(
            "signature_verify_error",
            detail=f"Unexpected verify error: {exc}",
        )

    return SignatureResult.success()


def verify_signature(
    *,
    algorithm: str,
    public_key_pem: Optional[str],
    message: bytes,
    signature_hex: str,
) -> SignatureResult:
    """Verify ``signature_hex`` over ``message``.

    Single dispatch entry point. Routes to HMAC or asymmetric based on
    ``algorithm``. Empty / unknown algorithms return
    ``unsupported_algorithm``.

    See module docstring for the full list of reason codes.
    """
    if not algorithm:
        return SignatureResult.fail(
            "unsupported_algorithm",
            detail=(
                "Empty algorithm string — proof payload is missing the "
                "kms_algorithm field. Legacy checkpoint?"
            ),
        )
    algo_norm = algorithm.lower()
    if algo_norm in _HMAC_ALGORITHMS:
        return _verify_hmac(message=message, signature_hex=signature_hex)
    if algo_norm in _RSA_PSS_ALGORITHMS or algo_norm in _ECDSA_ALGORITHMS:
        return _verify_asymmetric(
            algorithm=algo_norm,
            public_key_pem=public_key_pem,
            message=message,
            signature_hex=signature_hex,
        )
    return SignatureResult.fail(
        "unsupported_algorithm",
        detail=f"Unrecognised algorithm: {algorithm!r}",
    )


def build_checkpoint_message(
    *,
    org_id: str,
    sequence: int,
    hash_at_checkpoint: str,
    signed_at_isoformat: str,
) -> bytes:
    """Build the canonical message bytes for a checkpoint signature.

    Mirrors :func:`backend.app.services.checkpoint._checkpoint_message`:
    ``f"{org_id}:{sequence}:{hash_at_checkpoint}:{signed_at_isoformat}"``.
    """
    return (
        f"{org_id}:{sequence}:{hash_at_checkpoint}:{signed_at_isoformat}"
    ).encode("utf-8")
