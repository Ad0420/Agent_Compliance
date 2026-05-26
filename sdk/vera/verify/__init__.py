"""``vera.verify`` — offline Merkle proof + checkpoint verification.

Wave 3C.2 (this PR) seeds the subpackage with the proof-validation
primitives needed by ``vera verify --merkle-proof`` and
``vera evidence-export``. Wave 3C.1 (in parallel) is refactoring the
existing ``verify`` CLI flow into this same subpackage and adding a
``--offline`` flag that consumes the evidence-export bundle.

Subpackage contract (Wave 3C.2 baseline — 3C.1 may extend on rebase):

* :mod:`vera.verify.proof` — pure-Python primitives (no httpx, no I/O):
    - :func:`verify_merkle_path`
    - :func:`recompute_leaf_hash`
    - :func:`recompute_checkpoint_root_via_proof`
    - :func:`verify_kms_signature_for_proof`
    - :func:`verify_proof_payload` — full verifier with structured result
    - :class:`ProofVerificationResult` — pass/fail + reason code

Touch points for 3C.1:
* If 3C.1 wants to share the ``MerkleProofPayload`` shape, the
  authoritative reference is :class:`backend.app.services.merkle_proof.MerkleProofPayload`.
* The bundle layout produced by ``vera evidence-export`` (see
  :mod:`vera.cli.evidence_export_cmd`) is the input shape 3C.1's
  ``--offline`` is expected to consume.
"""

from .proof import (
    ProofVerificationResult,
    recompute_checkpoint_root_via_proof,
    recompute_leaf_hash,
    verify_kms_signature_for_proof,
    verify_merkle_path,
    verify_proof_payload,
)

__all__ = [
    "ProofVerificationResult",
    "recompute_checkpoint_root_via_proof",
    "recompute_leaf_hash",
    "verify_kms_signature_for_proof",
    "verify_merkle_path",
    "verify_proof_payload",
]
