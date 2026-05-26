"""Pure-Python Merkle-path verification.

Mirrors :func:`backend.app.services.merkle_proof.verify_proof_payload`
so an offline verifier reconstructs the SAME root the backend sealed.
The wire format is the one the
``GET /v1/records/{action_record_id}/merkle-proof`` endpoint returns;
see ``MerkleProofPayload`` in
``backend/app/services/merkle_proof.py``.

Two layers:

* :func:`verify_merkle_path` — fold ``merkle_path`` from ``leaf_hash``
  toward the root and assert equality with ``merkle_root``.
* :func:`canonical_record_to_leaf_hash` — apply the *chain rule*
  (``sha256(previous_hash + canonical_bytes)``) to verify that the
  returned canonical bytes ARE the bytes that hashed to ``leaf_hash``.
  Requires the record's ``previous_hash`` — which is part of the
  ``action_record_canonical`` payload only when the chain rule's leaf
  representation matches what the backend sealed. Per the docstring on
  ``services/merkle_proof.canonicalize_action_record``, the Merkle
  *leaves* are ``record_hash`` = ``sha256(previous_hash + canonical)``.

The canonical-bytes assertion is what makes the proof regulator-ready:
it ties the human-readable record fields back to the cryptographic
leaf. The Merkle fold alone proves "the leaf was in this tree" but
nothing about what the leaf *says*.

Returns are uniformly ``(ok: bool, reason: str | None)`` so callers can
classify failures without re-running the verifier on a typed exception.
``reason`` is a stable machine-readable code (snake_case); the CLI
turns it into a human message.
"""

from __future__ import annotations

import hashlib
from typing import Tuple

_HASH_PAIR_ENC = "utf-8"


def _hash_pair(left: str, right: str) -> str:
    """Hash two hex digest strings together.

    Identical to ``backend.app.services.merkle._hash_pair`` — same
    encoding, same concatenation order. Vendored rather than imported
    because the SDK must not depend on backend imports.
    """
    return hashlib.sha256((left + right).encode(_HASH_PAIR_ENC)).hexdigest()


def verify_merkle_path(payload: dict) -> Tuple[bool, str | None]:
    """Fold a Merkle proof from ``leaf_hash`` to ``merkle_root``.

    Required fields in ``payload``:

    * ``leaf_hash`` (hex digest of the record's leaf)
    * ``merkle_path``  — list of ``{"sibling_hash", "direction"}`` dicts.
      ``direction`` is ``"left"`` if the sibling sits on the LEFT of the
      current node, ``"right"`` if it sits on the right. Matches the
      semantics in ``backend.app.services.merkle.MerkleProof``.
    * ``merkle_root`` (hex digest of the sealed checkpoint root)

    Returns ``(True, None)`` on success or ``(False, <reason>)`` on
    failure. Reasons:

    * ``"missing_field"`` — payload doesn't carry the required keys.
    * ``"invalid_path_step"`` — a step is missing
      ``sibling_hash`` / ``direction`` or has an unknown direction value.
    * ``"merkle_root_mismatch"`` — the folded result doesn't match
      ``merkle_root``. The most common failure mode in tampering tests.
    """
    try:
        leaf_hash = payload["leaf_hash"]
        merkle_path = payload["merkle_path"]
        merkle_root = payload["merkle_root"]
    except KeyError:
        return False, "missing_field"

    if not isinstance(leaf_hash, str) or not isinstance(merkle_root, str):
        return False, "missing_field"
    if not isinstance(merkle_path, list):
        return False, "missing_field"

    current = leaf_hash
    for step in merkle_path:
        if not isinstance(step, dict):
            return False, "invalid_path_step"
        sibling = step.get("sibling_hash")
        direction = step.get("direction")
        if not isinstance(sibling, str) or direction not in ("left", "right"):
            return False, "invalid_path_step"
        if direction == "left":
            current = _hash_pair(sibling, current)
        else:
            current = _hash_pair(current, sibling)

    if current != merkle_root:
        return False, "merkle_root_mismatch"
    return True, None


def canonical_record_to_leaf_hash(
    *,
    canonical: str,
    previous_hash: str | None,
) -> str:
    """Apply the chain rule: ``sha256(previous_hash + canonical)``.

    Mirrors :func:`backend.app.services.hashing.compute_record_hash`.
    ``previous_hash`` is the hex digest of the record's predecessor in
    the per-org hash chain. For the very first record in a chain the
    backend uses the empty string ``""``.

    Returns the hex digest of the leaf hash that the backend's Merkle
    tree was built over.

    Note: the verifier in :func:`verify_merkle_path` does NOT include
    this step — it accepts the ``leaf_hash`` from the payload as-is.
    The offline pipeline calls THIS function separately and asserts
    its output equals the payload's ``leaf_hash``. That ties the
    human-readable canonical bytes back to the cryptographic leaf.
    """
    prev = previous_hash if previous_hash is not None else ""
    return hashlib.sha256((prev + canonical).encode("utf-8")).hexdigest()
