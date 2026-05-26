"""``vera verify`` — checkpoint + Merkle-proof verification for the SDK.

Phase 3 Wave 3C.1 extracts the verify pipeline from ``vera.cli`` into a
proper subpackage so the offline path can be tested in isolation and so
``vera verify --merkle-proof`` / ``vera verify --offline`` share the same
pure-Python verifiers.

Layering:

* :mod:`vera.verify.proof` — pure Merkle-path validation. No I/O.
  Mirrors :func:`backend.app.services.merkle_proof.verify_proof_payload`
  so a verifier built from this module reconstructs the same root the
  backend sealed.
* :mod:`vera.verify.signature` — pure KMS-signature verification.
  Asymmetric (RSA-PSS / ECDSA via PEM public key) and HMAC paths. No I/O.
* :mod:`vera.verify.api` — HTTP client that hits Vera's
  ``/v1/checkpoints/{date}`` and ``/v1/records/{id}/merkle-proof``.
  Uses the existing :class:`vera.client.VeraClient` for auth + base URL.
* :mod:`vera.verify.offline` — entire offline pipeline. Reads a bundle
  directory, calls into ``proof`` + ``signature``, returns a structured
  result. No network.
* :mod:`vera.verify.cli` — Click wiring. Thin layer over ``offline`` /
  ``api`` that turns a result into an exit code and printed table.

Public surface (re-exported here): ``run_verify``, ``VerifyResult``,
``RecordVerification``, ``verify_merkle_path``, ``verify_signature``.
``vera.verify.cli.register_verify_commands`` wires the ``verify`` Click
group onto an existing CLI group.

Why a subpackage and not more methods on :class:`VeraClient`: the
offline pipeline needs to be importable + callable WITHOUT a configured
``VeraClient`` (no API key, no base URL) — an OCR investigator running
``vera verify --offline /tmp/bundle/`` must not be required to set
``VERA_API_KEY``. Keeping the offline path file-system-only makes that
contract checkable.
"""

from __future__ import annotations

from .offline import (
    BundleManifest,
    RecordVerification,
    VerifyResult,
    run_offline_verify,
)
from .proof import (
    canonical_record_to_leaf_hash,
    verify_merkle_path,
)
from .signature import (
    SignatureResult,
    verify_signature,
)

# Convenience alias — the documented entry point is ``run_verify``;
# ``run_offline_verify`` is the long-form for clarity inside the module.
run_verify = run_offline_verify

__all__ = [
    "BundleManifest",
    "RecordVerification",
    "SignatureResult",
    "VerifyResult",
    "canonical_record_to_leaf_hash",
    "run_offline_verify",
    "run_verify",
    "verify_merkle_path",
    "verify_signature",
]
