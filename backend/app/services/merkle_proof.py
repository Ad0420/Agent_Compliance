"""Merkle proof exposure — Phase 3 Wave 3B.2.

Generates an **independently-verifiable** Merkle inclusion proof for a single
``ActionRecord``: enough material for an offline verifier to reconstruct
the checkpoint's Merkle root from the leaf and then validate the
checkpoint's KMS signature over that root, without ever calling back into
Vera.

Decision: **recompute on demand** rather than persist per-leaf paths.

Rationale:

* Reads are rare (regulator-evidence queries / audit exports), not hot.
  An average customer might pull a handful of proofs per audit cycle.
* Compute is cheap. A SHA-256 binary Merkle tree over the records since
  the last checkpoint is O(N) hashes; for typical checkpoint windows of
  10²–10³ records this is a couple of ms.
* The build path is deterministic and **already shared** with the
  checkpoint-sealing code (``services.merkle.build_tree_from_records``),
  so recomputation matches the sealed root by construction. Persisting
  would introduce a second source of truth, with all the divergence
  risk that implies.
* Storing per-leaf paths would cost roughly ``log2(N) * 64`` bytes of
  hex per record, multiplied by every record we've ever sealed —
  pure write-amplification for paths that may never be read.
* Avoids new schema and keeps the surface area away from Wave 3B.1
  (checkpoint S3 mirror), which is touching ``checkpoint.py`` in
  parallel.

The single canonical reproduction path lives in :func:`build_proof` —
this is the function that ``GET /v1/records/{id}/merkle-proof`` calls
and the function tests verify against.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import ActionRecord
from ..models.checkpoint import Checkpoint
from .hashing import canonicalize, extract_hashable_fields
from .kms import get_key_by_id
from .merkle import MerkleProof, build_tree_from_records


# ── Error sentinels ────────────────────────────────────────────────────
# Returned by ``build_proof`` so the router can map to HTTP status without
# leaking the literal error string into the response unless we want to.


class ProofUnavailable(Exception):
    """Base for proof-build failures."""

    def __init__(self, code: str, *, retry_after: Optional[int] = None) -> None:
        super().__init__(code)
        self.code = code
        # Only set for ``checkpoint_pending`` so the route can echo it in
        # the Retry-After header. Cadence-driven (60s by default — same
        # as the original brief's value; the sweeper itself uses the
        # per-org cadence_threshold which is typically 1h or 24h, but
        # 60s is the polite "ask again soon" hint to clients).
        self.retry_after = retry_after


# ── Proof payload ──────────────────────────────────────────────────────


@dataclass
class MerkleProofPayload:
    """The full response payload for ``GET /v1/records/{id}/merkle-proof``.

    Field-for-field what the Wave 3B.2 brief specifies. The router turns
    this into a JSON body verbatim; tests check the same shape.

    Wave 3C.2 added three checkpoint-identity fields
    (``checkpoint_org_id``, ``checkpoint_sequence``,
    ``checkpoint_hash_at_checkpoint``) so the payload is fully
    self-contained for offline signature verification. The KMS signature
    is over ``f"{org_id}:{sequence}:{hash}:{timestamp}"`` (see
    ``services.checkpoint._checkpoint_message``); without these fields,
    an offline verifier would need a second round-trip to fetch the
    checkpoint row. Including them is additive — pre-3C.2 consumers
    that ignore unknown JSON keys keep working unchanged.
    """

    action_record_id: str
    action_record_canonical: str
    leaf_hash: str
    merkle_path: list[dict]  # [{sibling_hash, direction}, ...]
    merkle_root: str
    checkpoint_id: str
    checkpoint_signed_at: str
    # ── Wave 3C.2: signature-verification material ────────────────────
    checkpoint_org_id: str
    checkpoint_sequence: int
    checkpoint_hash_at_checkpoint: str
    # ── Phase 3 follow-up: chain-rule material ────────────────────────
    # ``previous_hash`` is the predecessor leaf in the per-org chain
    # — required so the offline verifier can recompute
    # ``sha256(previous_hash + canonical_bytes) == leaf_hash``. Without
    # this, an offline verifier can only prove Merkle path inclusion
    # (i.e. "some leaf was sealed at this position") and NOT that the
    # canonical bytes shown are the bytes that hashed to the sealed
    # leaf. For the first record in a chain this is the literal string
    # ``"GENESIS"`` (the default value of ``ChainState.latest_hash``),
    # NOT an empty string — the backend seeds every org's chain with
    # that sentinel so the SHA-256 input is never empty.
    previous_hash: str
    # ── KMS fields ────────────────────────────────────────────────────
    kms_key_id: str
    kms_signature: str
    kms_algorithm: str
    kms_public_key_pem: Optional[str]

    def to_dict(self) -> dict:
        return {
            "action_record_id": self.action_record_id,
            "action_record_canonical": self.action_record_canonical,
            "leaf_hash": self.leaf_hash,
            "merkle_path": list(self.merkle_path),
            "merkle_root": self.merkle_root,
            "checkpoint_id": self.checkpoint_id,
            "checkpoint_signed_at": self.checkpoint_signed_at,
            "checkpoint_org_id": self.checkpoint_org_id,
            "checkpoint_sequence": self.checkpoint_sequence,
            "checkpoint_hash_at_checkpoint": self.checkpoint_hash_at_checkpoint,
            "previous_hash": self.previous_hash,
            "kms_key_id": self.kms_key_id,
            "kms_signature": self.kms_signature,
            "kms_algorithm": self.kms_algorithm,
            "kms_public_key_pem": self.kms_public_key_pem,
        }


# ── Helpers ────────────────────────────────────────────────────────────


def canonicalize_action_record(record: ActionRecord) -> str:
    """Re-derive the canonical JSON for an ``ActionRecord``.

    Uses the SAME ``extract_hashable_fields`` + ``canonicalize`` pair that
    ``services.chain._create_record`` runs when computing ``record_hash``
    at insert time. The verifier hashes ``previous_hash + canonical`` →
    SHA-256 and asserts equality with ``record_hash``; mismatching this
    function with the chain-side function would silently corrupt every
    proof returned by this endpoint.
    """
    fields = extract_hashable_fields(record)
    return canonicalize(fields)


# Note on leaf representation: ``services.checkpoint.create_checkpoint``
# builds the Merkle tree directly over ``ActionRecord.record_hash``
# values (not over canonical bytes), and ``build_proof`` below pulls
# those same hashes via SELECT. If the seal-time tree ever changes its
# leaf representation, ``build_proof``'s SELECT must change with it.


# ── Lookup: which checkpoint sealed this record? ───────────────────────


async def _find_sealing_checkpoint(
    session: AsyncSession, record: ActionRecord
) -> Optional[Checkpoint]:
    """Return the checkpoint whose sealed window includes this record.

    The seal-time window is ``(prev_checkpoint_seq, this_checkpoint_seq]``
    where ``this_checkpoint_seq = checkpoint.sequence_at_checkpoint``.
    A record at sequence ``N`` is sealed by the checkpoint with the
    smallest ``sequence_at_checkpoint >= N`` for the same org.

    Returns ``None`` if no checkpoint has been sealed yet at-or-above
    this record's sequence — i.e. the record is in the "tail" window
    between the last checkpoint and now. The router maps that to 409
    ``checkpoint_pending``.
    """
    result = await session.execute(
        select(Checkpoint)
        .where(
            Checkpoint.org_id == record.org_id,
            Checkpoint.sequence_at_checkpoint >= record.sequence_number,
        )
        .order_by(Checkpoint.sequence_at_checkpoint.asc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _previous_checkpoint_sequence(
    session: AsyncSession, org_id: str, this_seq: int
) -> int:
    """Sequence-at-checkpoint of the checkpoint immediately before this one.

    Used to compute the half-open window ``(prev_seq, this_seq]`` of
    records sealed under ``this_seq``. Returns 0 if this is the first
    checkpoint for the org.
    """
    result = await session.execute(
        select(Checkpoint.sequence_at_checkpoint)
        .where(
            Checkpoint.org_id == org_id,
            Checkpoint.sequence_at_checkpoint < this_seq,
        )
        .order_by(Checkpoint.sequence_at_checkpoint.desc())
        .limit(1)
    )
    val = result.scalar_one_or_none()
    return val or 0


# ── Main entry point ───────────────────────────────────────────────────


async def build_proof(
    session: AsyncSession,
    *,
    record: ActionRecord,
) -> MerkleProofPayload:
    """Build a :class:`MerkleProofPayload` for ``record``.

    Raises ``ProofUnavailable("checkpoint_pending", retry_after=60)`` if
    the record exists but its sealing checkpoint hasn't been created yet.

    Other failure modes raise ``ProofUnavailable`` with a descriptive
    code; the router maps each to the right HTTP status. We deliberately
    never raise ``HTTPException`` here so the service stays testable
    without a running app.
    """
    sealing = await _find_sealing_checkpoint(session, record)
    if sealing is None:
        # Record is past the last checkpoint — the "tail". A client
        # should retry after the next checkpoint cadence tick. 60s is
        # the polite default; ``hourly`` orgs will see a fresh checkpoint
        # within an hour, ``daily`` orgs within 24h. We do NOT echo the
        # cadence_threshold here because (a) it leaks operator
        # configuration and (b) a client should never be polling that
        # often anyway.
        raise ProofUnavailable("checkpoint_pending", retry_after=60)

    prev_seq = await _previous_checkpoint_sequence(
        session, record.org_id, sealing.sequence_at_checkpoint
    )

    # Pull the exact same set of record hashes the seal-time code used:
    # ``(prev_seq, this_seq]``, ordered by sequence_number ASC. The
    # ordering is load-bearing — Merkle leaf positions depend on it.
    leaves_result = await session.execute(
        select(ActionRecord.record_hash, ActionRecord.id)
        .where(
            ActionRecord.org_id == record.org_id,
            ActionRecord.sequence_number > prev_seq,
            ActionRecord.sequence_number <= sealing.sequence_at_checkpoint,
        )
        .order_by(ActionRecord.sequence_number)
    )
    rows = leaves_result.all()
    leaf_hashes = [row[0] for row in rows]
    leaf_ids = [row[1] for row in rows]

    if not leaf_hashes:
        # Should be unreachable: we found a sealing checkpoint with
        # ``sequence_at_checkpoint >= record.sequence_number``, so the
        # window must contain at least our own record. Treat as a
        # data-integrity bug rather than a 200 with empty path.
        raise ProofUnavailable("proof_window_empty")

    try:
        leaf_index = leaf_ids.index(record.id)
    except ValueError:
        # Same logic — our record's id is supposed to be in this window.
        raise ProofUnavailable("proof_record_not_in_window")

    tree = build_tree_from_records(leaf_hashes)
    proof: MerkleProof = tree.get_proof(leaf_index)

    # Defensive: the recomputed root MUST equal the sealed root. If it
    # doesn't, the chain or the checkpoint has been tampered with; we
    # refuse to return a "proof" that wouldn't actually verify offline.
    # Note ``checkpoint.merkle_root`` may be NULL only for the
    # zero-record case (which we already rejected above).
    if sealing.merkle_root and proof.root != sealing.merkle_root:
        raise ProofUnavailable("proof_root_mismatch")

    # Look up the historical KMS key. Older checkpoints (pre-3A.a)
    # may have ``key_id IS NULL`` — in that case we can't carry an
    # algorithm/public key into the proof, but we can still return
    # the checkpoint signature; the verifier should treat that as a
    # legacy-checkpoint case (logged on the offline-verify side).
    kms_algorithm = ""
    kms_public_key_pem: Optional[str] = None
    if sealing.key_id:
        history_row = await get_key_by_id(session, sealing.key_id)
        if history_row is not None:
            kms_algorithm = history_row.algorithm
            kms_public_key_pem = history_row.public_key_pem

    canonical = canonicalize_action_record(record)

    return MerkleProofPayload(
        action_record_id=record.id,
        action_record_canonical=canonical,
        leaf_hash=proof.leaf_hash,
        merkle_path=[
            {"sibling_hash": h, "direction": d}
            for h, d in zip(proof.proof_hashes, proof.proof_directions)
        ],
        merkle_root=proof.root,
        checkpoint_id=sealing.id,
        checkpoint_signed_at=sealing.created_at.isoformat(),
        checkpoint_org_id=sealing.org_id,
        checkpoint_sequence=sealing.sequence_at_checkpoint,
        checkpoint_hash_at_checkpoint=sealing.hash_at_checkpoint,
        # ``previous_hash`` is stored on every ActionRecord
        # (``models/action_record.py``: ``Text, nullable=False``).
        # The first record in any org's chain receives the sentinel
        # ``"GENESIS"`` from ``ChainState.latest_hash`` — never an
        # empty string. Pre-Phase-3-followup consumers ignore unknown
        # JSON keys, so adding this field is additive and
        # backwards-compatible.
        previous_hash=record.previous_hash,
        kms_key_id=sealing.key_id or "",
        kms_signature=sealing.signature,
        kms_algorithm=kms_algorithm,
        kms_public_key_pem=kms_public_key_pem,
    )


# ── Offline verification helper (for tests, SDK, and the future CLI) ───


def verify_proof_payload(payload: dict) -> bool:
    """Re-derive ``merkle_root`` from a returned proof payload.

    This function is the **independent verifier** referenced in the test
    plan ("verifier reconstructs root"). It performs:

      1. ``sha256(action_record_canonical) ?= leaf_hash`` —
         **No.** The Merkle leaves are ``record_hash`` (i.e.
         ``sha256(previous_hash + canonical)``), not
         ``sha256(canonical)``. So the verifier must know the chain's
         ``previous_hash`` to recompute the leaf — that's a chain-level
         claim, not a Merkle-level one. We therefore only assert leaf
         hash → root reconstruction here, and leave the
         canonical→leaf-hash claim to a chain-level verifier that walks
         the record's previous_hash.

      2. Fold ``merkle_path`` from ``leaf_hash`` toward the root.
      3. Assert the folded result equals ``merkle_root``.

    Returns True only if all checks pass. Signature verification over
    ``merkle_root`` is intentionally out of scope here — that lives in
    the offline ``vera verify`` CLI which has the KMS public key and the
    algorithm. Tests assert signature validity separately using the
    same KMS singleton that signed the checkpoint.
    """
    current = payload["leaf_hash"]
    for step in payload["merkle_path"]:
        sibling = step["sibling_hash"]
        direction = step["direction"]
        if direction == "left":
            combined = sibling + current
        else:
            combined = current + sibling
        current = hashlib.sha256(combined.encode("utf-8")).hexdigest()
    return current == payload["merkle_root"]
