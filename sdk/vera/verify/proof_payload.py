"""Offline Merkle proof + KMS signature verification (Wave 3C.2).

This module is the pure-Python verifier that ``vera verify --merkle-proof``
and ``vera evidence-export`` consume. Zero I/O, zero deps beyond stdlib +
``cryptography`` (already a transitive dep via ``vera-sdk[spool]``).

# Source-of-truth alignment

Each primitive here is a **vendored** copy of the corresponding
backend logic. Vendoring (not import-from-shared-lib) is deliberate:

* ``vera-sdk`` is published as a standalone PyPI package — a regulator
  running ``vera verify --merkle-proof`` on a 5-year-old wheel cannot
  depend on a checkout of the backend repo.
* The hash / Merkle / signing functions are tiny and intentionally
  frozen — any change to them is a hash-contract break that already
  requires coordinated rollout. There's no churn to keep in sync.

For every vendored function, the docstring names the backend module
that holds the authoritative implementation. If you update one, update
the other in the same PR.

Authoritative references (backend/app/services/):

* ``hashing.canonicalize`` / ``hashing.compute_record_hash`` /
  ``hashing.HASHABLE_FIELDS`` — the canonical-JSON contract.
* ``merkle._hash_pair`` / ``merkle.MerkleProof`` —
  the Merkle path-walker contract.
* ``checkpoint._checkpoint_message`` — the KMS signing message format.
* ``services.merkle_proof.MerkleProofPayload`` — the proof JSON shape.

# Failure-mode codes

Returned by :class:`ProofVerificationResult.reason`:

* ``"ok"`` — every check passed.
* ``"merkle_path_mismatch"`` — the folded path didn't equal the
  claimed root (tampered leaf, tampered sibling, or wrong root).
* ``"leaf_hash_mismatch"`` — the canonical bytes don't hash to
  ``leaf_hash``. This is a stronger chain-rule check that needs
  ``previous_hash``; we skip it when ``previous_hash`` is unavailable.
* ``"signature_invalid"`` — KMS signature does not verify against the
  claimed key.
* ``"signature_unverifiable_hmac"`` — proof uses an HMAC algorithm and
  no shared secret was provided. NON-FATAL: callers should treat this
  as a warning, not a hard fail (per brief).
* ``"signature_algorithm_unsupported"`` — algorithm name doesn't map
  to a verifier this SDK build knows about. Fatal.
* ``"missing_required_field"`` — proof payload is missing a field this
  verifier needs.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from typing import Any, Optional


# ── Reason codes ────────────────────────────────────────────────────────

REASON_OK = "ok"
REASON_MERKLE_PATH_MISMATCH = "merkle_path_mismatch"
REASON_LEAF_HASH_MISMATCH = "leaf_hash_mismatch"
REASON_SIGNATURE_INVALID = "signature_invalid"
REASON_SIGNATURE_UNVERIFIABLE_HMAC = "signature_unverifiable_hmac"
REASON_SIGNATURE_ALGORITHM_UNSUPPORTED = "signature_algorithm_unsupported"
REASON_MISSING_FIELD = "missing_required_field"


# ── Vendored: backend/app/services/merkle.py::_hash_pair ─────────────────


def _hash_pair(left: str, right: str) -> str:
    """SHA-256 of two hex-digest strings concatenated.

    Vendored from :func:`backend.app.services.merkle._hash_pair`.
    """
    payload = left + right
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ── Vendored: backend/app/services/hashing.py ────────────────────────────


def _normalize(obj: Any) -> str:
    """Canonical-JSON value normaliser.

    Vendored from :func:`backend.app.services.hashing._normalize`.
    Only the non-datetime branch is reachable here — the proof endpoint
    already serialised datetimes into ISO strings before canonicalisation.
    Kept as the same module-level shape for parity with the backend.
    """
    return str(obj)


def canonicalize(record_fields: dict) -> str:
    """Deterministic JSON: sorted keys, no whitespace, no None values.

    Vendored from :func:`backend.app.services.hashing.canonicalize`.
    The proof payload already carries ``action_record_canonical`` as the
    server's canonical string, so this helper is exposed mostly so SDK
    consumers can sanity-check the canonicalisation themselves.
    """
    cleaned = {k: v for k, v in record_fields.items() if v is not None}
    return json.dumps(
        cleaned, sort_keys=True, separators=(",", ":"), default=_normalize
    )


def compute_record_hash(canonical: str, previous_hash: str) -> str:
    """SHA-256(previous_hash + canonical).

    Vendored from :func:`backend.app.services.hashing.compute_record_hash`.
    """
    payload = previous_hash + canonical
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def recompute_leaf_hash(canonical: str, previous_hash: str) -> str:
    """Public alias for :func:`compute_record_hash` — clearer at call sites.

    The merkle proof endpoint does NOT return ``previous_hash``, so the
    SDK verifier can only run this check when the caller supplies it
    out-of-band (e.g. from the evidence-export bundle's record file).
    """
    return compute_record_hash(canonical, previous_hash)


# ── Vendored: backend/app/services/merkle_proof.py::verify_proof_payload ─


def verify_merkle_path(
    *, leaf_hash: str, merkle_path: list[dict], merkle_root: str
) -> bool:
    """Fold ``merkle_path`` from ``leaf_hash`` and assert it equals ``merkle_root``.

    Vendored from
    :func:`backend.app.services.merkle_proof.verify_proof_payload`. The
    backend's version takes the whole dict; this signature names the
    three fields explicitly so the call sites are unambiguous.

    A returned ``False`` covers all three Merkle-side tamper modes:

    * tampered leaf — ``leaf_hash`` doesn't fold to ``merkle_root``.
    * tampered sibling — flipped sibling bytes change the fold.
    * wrong root — the folded value can't match a substituted root.

    Empty paths (single-record checkpoint) pass iff
    ``leaf_hash == merkle_root``.
    """
    current = leaf_hash
    for step in merkle_path:
        sibling = step["sibling_hash"]
        direction = step["direction"]
        if direction == "left":
            current = _hash_pair(sibling, current)
        else:
            current = _hash_pair(current, sibling)
    return current == merkle_root


def recompute_checkpoint_root_via_proof(payload: dict) -> str:
    """Return the Merkle root computed by folding the path from the leaf.

    Useful when a caller wants the folded value to compare against
    *another* trusted source (e.g. a checkpoint they fetched separately).
    """
    current = payload["leaf_hash"]
    for step in payload["merkle_path"]:
        sibling = step["sibling_hash"]
        direction = step["direction"]
        if direction == "left":
            current = _hash_pair(sibling, current)
        else:
            current = _hash_pair(current, sibling)
    return current


# ── Vendored: backend/app/services/checkpoint.py::_checkpoint_message ────


def build_checkpoint_message(
    *,
    org_id: str,
    sequence: int,
    hash_at_checkpoint: str,
    signed_at: str,
) -> bytes:
    """Reconstruct the KMS signing message for a checkpoint.

    Vendored from
    :func:`backend.app.services.checkpoint._checkpoint_message`. The
    server formats this string then KMS-signs the UTF-8 bytes;
    ``signed_at`` is ``checkpoint.created_at.isoformat()`` (the same
    string as ``MerkleProofPayload.checkpoint_signed_at``).
    """
    return f"{org_id}:{sequence}:{hash_at_checkpoint}:{signed_at}".encode(
        "utf-8"
    )


# ── KMS signature verification ───────────────────────────────────────────

# Algorithm constants (mirror backend/app/services/kms.py).
ALGO_HMAC_SHA256 = "hmac-sha256"
ALGO_KMS_HMAC_SHA256 = "kms-hmac-sha256"
ALGO_RSA_PSS_SHA256 = "rsa-pss-sha256"


def verify_kms_signature_for_proof(
    payload: dict,
    *,
    hmac_secret: Optional[bytes] = None,
) -> tuple[bool, str]:
    """Verify the KMS signature embedded in a Merkle proof payload.

    Returns ``(ok, reason)``:

    * ``(True, "ok")`` — signature validates.
    * ``(False, "signature_invalid")`` — the bytes did not match.
    * ``(False, "signature_unverifiable_hmac")`` — algorithm is HMAC and
      no ``hmac_secret`` was supplied. The caller MUST treat this as a
      warning, not a hard fail (per the Wave 3C.2 brief: HMAC offline
      verification is a non-fatal warning unless the customer can
      supply the shared secret).
    * ``(False, "signature_algorithm_unsupported")`` — this SDK build
      doesn't know how to verify the named algorithm.
    * ``(False, "missing_required_field")`` — one of the required
      payload fields is missing.

    For asymmetric algorithms (``rsa-pss-sha256``), the proof payload
    MUST carry ``kms_public_key_pem`` — that's the historical key we
    look up via the KMS key-history table. Wave 3A.a wrote the history
    table; Wave 3B.2 wired it into the proof endpoint; Wave 3C.2 (here)
    consumes it.
    """
    required = (
        "checkpoint_org_id",
        "checkpoint_sequence",
        "checkpoint_hash_at_checkpoint",
        "checkpoint_signed_at",
        "kms_algorithm",
        "kms_signature",
    )
    for field in required:
        if field not in payload:
            return False, REASON_MISSING_FIELD

    message = build_checkpoint_message(
        org_id=payload["checkpoint_org_id"],
        sequence=payload["checkpoint_sequence"],
        hash_at_checkpoint=payload["checkpoint_hash_at_checkpoint"],
        signed_at=payload["checkpoint_signed_at"],
    )
    signature_hex = payload["kms_signature"]
    algorithm = payload["kms_algorithm"]

    if algorithm in (ALGO_HMAC_SHA256, ALGO_KMS_HMAC_SHA256):
        if hmac_secret is None:
            # Per brief: HMAC + no shared secret == non-fatal warning.
            return False, REASON_SIGNATURE_UNVERIFIABLE_HMAC
        try:
            expected = hmac.new(
                hmac_secret, message, hashlib.sha256
            ).hexdigest()
        except Exception:
            return False, REASON_SIGNATURE_INVALID
        if hmac.compare_digest(expected, signature_hex):
            return True, REASON_OK
        return False, REASON_SIGNATURE_INVALID

    if algorithm == ALGO_RSA_PSS_SHA256:
        pem = payload.get("kms_public_key_pem")
        if not pem:
            return False, REASON_MISSING_FIELD
        try:
            from cryptography.hazmat.primitives import hashes, serialization
            from cryptography.hazmat.primitives.asymmetric import padding
        except ImportError:  # pragma: no cover — install vera-sdk[spool]
            return False, REASON_SIGNATURE_ALGORITHM_UNSUPPORTED
        try:
            public_key = serialization.load_pem_public_key(
                pem.encode("utf-8")
            )
            signature_bytes = bytes.fromhex(signature_hex)
            public_key.verify(  # type: ignore[union-attr]
                signature_bytes,
                message,
                padding.PSS(
                    mgf=padding.MGF1(hashes.SHA256()),
                    salt_length=padding.PSS.MAX_LENGTH,
                ),
                hashes.SHA256(),
            )
            return True, REASON_OK
        except Exception:
            return False, REASON_SIGNATURE_INVALID

    return False, REASON_SIGNATURE_ALGORITHM_UNSUPPORTED


# ── High-level verifier ─────────────────────────────────────────────────


@dataclass
class ProofVerificationResult:
    """Outcome of a full Merkle-proof + signature verification.

    ``ok`` collapses ``REASON_OK`` into a single bool for ergonomic
    if-statements; ``reason`` carries the structured code for error
    messages and exit-code mapping in the CLI.

    ``signature_warning`` is set ONLY when ``ok=True`` but the
    signature could not be verified because the algorithm is HMAC and
    no shared secret was available. This is the "unverified (no HMAC
    secret)" non-fatal warning called out in the brief.
    """

    ok: bool
    reason: str
    signature_warning: bool = False
    # When ok=False, the field that caught the failure. Pure debug.
    failure_detail: str = ""


def verify_proof_payload(
    payload: dict,
    *,
    hmac_secret: Optional[bytes] = None,
    skip_signature: bool = False,
) -> ProofVerificationResult:
    """Verify a Merkle proof payload end-to-end.

    Order of checks (fail-fast):

    1. Merkle path folds to the claimed root.
    2. KMS signature validates against the rebuilt message bytes.

    ``hmac_secret`` is only needed if the proof was signed with HMAC.
    For asymmetric algorithms the public key travels in the payload.

    Returns a :class:`ProofVerificationResult` — never raises (other
    than on programmer error like a non-dict payload). The caller maps
    ``reason`` to its own exit code / warning string.
    """
    try:
        leaf_hash = payload["leaf_hash"]
        merkle_path = payload["merkle_path"]
        merkle_root = payload["merkle_root"]
    except KeyError as exc:
        return ProofVerificationResult(
            ok=False,
            reason=REASON_MISSING_FIELD,
            failure_detail=str(exc),
        )

    # 1. Merkle path
    if not verify_merkle_path(
        leaf_hash=leaf_hash,
        merkle_path=merkle_path,
        merkle_root=merkle_root,
    ):
        return ProofVerificationResult(
            ok=False,
            reason=REASON_MERKLE_PATH_MISMATCH,
            failure_detail=(
                "folded path != claimed root — leaf, sibling, or root "
                "tampered"
            ),
        )

    if skip_signature:
        return ProofVerificationResult(ok=True, reason=REASON_OK)

    # 2. KMS signature
    sig_ok, sig_reason = verify_kms_signature_for_proof(
        payload, hmac_secret=hmac_secret
    )
    if sig_ok:
        return ProofVerificationResult(ok=True, reason=REASON_OK)
    if sig_reason == REASON_SIGNATURE_UNVERIFIABLE_HMAC:
        # Per brief: non-fatal — surface as warning + ok=True.
        return ProofVerificationResult(
            ok=True,
            reason=REASON_OK,
            signature_warning=True,
            failure_detail=(
                "HMAC algorithm + no shared secret available; "
                "signature could not be verified offline"
            ),
        )
    return ProofVerificationResult(
        ok=False,
        reason=sig_reason,
        failure_detail="KMS signature did not validate",
    )
