"""Checkpoint service — periodic signed snapshots of chain state.

Checkpoints are signed using the configured KMS provider (LocalKMS or AWSKMS),
NOT the app secret_key. This ensures checkpoint signatures can be verified
independently and that key management is centralized.

Each checkpoint also:
  - Computes a Merkle root over all records since the last checkpoint
  - Publishes proof to the configured external store (S3 WORM, local file, etc.)
  - Stores the external receipt for independent verification
"""

import logging
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import ActionRecord, ChainState
from ..models.checkpoint import Checkpoint
from .kms import get_kms
from .merkle import build_tree_from_records
from .external_store import get_external_store, ExternalProof

logger = logging.getLogger("actionledger.checkpoint")


def _checkpoint_message(org_id: str, sequence: int, hash_value: str, timestamp: str) -> bytes:
    """Build the canonical message bytes for checkpoint signing."""
    return f"{org_id}:{sequence}:{hash_value}:{timestamp}".encode("utf-8")


async def _get_last_checkpoint_sequence(session: AsyncSession, org_id: str) -> int:
    """Get the sequence number of the most recent checkpoint, or 0 if none."""
    result = await session.execute(
        select(func.max(Checkpoint.sequence_at_checkpoint))
        .where(Checkpoint.org_id == org_id)
    )
    val = result.scalar_one_or_none()
    return val or 0


async def create_checkpoint(session: AsyncSession, org_id: str) -> Checkpoint:
    """Create a signed checkpoint from current chain state.

    Steps:
      1. Read current chain_state (latest sequence + hash)
      2. Compute Merkle root over records since last checkpoint
      3. Sign the checkpoint with KMS
      4. Save to database
      5. Publish proof to external store (best-effort)
    """
    result = await session.execute(
        select(ChainState).where(ChainState.org_id == org_id)
    )
    chain_state = result.scalar_one_or_none()
    if chain_state is None:
        raise HTTPException(
            status_code=404,
            detail=f"Chain state not found for organization {org_id}. Was the org initialized correctly?",
        )

    now = datetime.now(timezone.utc)
    timestamp = now.isoformat()

    # Build Merkle root over records since last checkpoint
    last_cp_seq = await _get_last_checkpoint_sequence(session, org_id)
    records_result = await session.execute(
        select(ActionRecord.record_hash)
        .where(
            ActionRecord.org_id == org_id,
            ActionRecord.sequence_number > last_cp_seq,
            ActionRecord.sequence_number <= chain_state.latest_sequence,
        )
        .order_by(ActionRecord.sequence_number)
    )
    record_hashes = [row for row in records_result.scalars().all()]

    merkle_root = None
    if record_hashes:
        tree = build_tree_from_records(record_hashes)
        merkle_root = tree.root

    # Sign with KMS
    kms = get_kms()
    message = _checkpoint_message(
        org_id, chain_state.latest_sequence, chain_state.latest_hash, timestamp
    )
    signature = kms.sign(message)

    checkpoint = Checkpoint(
        org_id=org_id,
        sequence_at_checkpoint=chain_state.latest_sequence,
        hash_at_checkpoint=chain_state.latest_hash,
        merkle_root=merkle_root,
        key_id=kms.get_key_id(),
        created_at=now,
        signature=signature,
    )
    session.add(checkpoint)
    await session.commit()
    await session.refresh(checkpoint)

    # Publish to external store (best-effort — failure doesn't roll back checkpoint)
    try:
        proof = ExternalProof(
            checkpoint_id=checkpoint.id,
            org_id=org_id,
            sequence=chain_state.latest_sequence,
            merkle_root=merkle_root or "",
            chain_hash=chain_state.latest_hash,
            timestamp=timestamp,
            signature=signature,
            key_id=kms.get_key_id(),
        )
        store = get_external_store()
        receipt = await store.publish(proof)

        # Save receipt back to checkpoint
        checkpoint.external_receipt = receipt.to_dict()
        await session.commit()
        await session.refresh(checkpoint)

        logger.info(
            f"Checkpoint {checkpoint.id} published to {receipt.store_type} "
            f"at {receipt.location}"
        )
    except Exception as e:
        logger.warning(
            f"Failed to publish checkpoint {checkpoint.id} to external store: {e}. "
            f"The checkpoint was saved locally but the external proof was NOT published. "
            f"Re-create the checkpoint or manually publish when the store is available.",
            exc_info=True,
        )

    return checkpoint


async def verify_checkpoint(session: AsyncSession, checkpoint: Checkpoint) -> bool:
    """Verify a single checkpoint's signature, chain state, and external proof."""
    timestamp = checkpoint.created_at.isoformat()

    # 1. Verify KMS signature
    kms = get_kms()
    message = _checkpoint_message(
        checkpoint.org_id,
        checkpoint.sequence_at_checkpoint,
        checkpoint.hash_at_checkpoint,
        timestamp,
    )
    if not kms.verify(message, checkpoint.signature):
        return False

    # 2. Verify the record at that sequence actually has that hash
    result = await session.execute(
        select(ActionRecord).where(
            ActionRecord.org_id == checkpoint.org_id,
            ActionRecord.sequence_number == checkpoint.sequence_at_checkpoint,
        )
    )
    record = result.scalar_one_or_none()
    if record is None:
        return False

    if record.record_hash != checkpoint.hash_at_checkpoint:
        return False

    # 3. Verify external receipt if present (best-effort)
    if checkpoint.external_receipt:
        try:
            from .external_store import PublishReceipt
            receipt = PublishReceipt(**checkpoint.external_receipt)
            proof = ExternalProof(
                checkpoint_id=checkpoint.id,
                org_id=checkpoint.org_id,
                sequence=checkpoint.sequence_at_checkpoint,
                merkle_root=checkpoint.merkle_root or "",
                chain_hash=checkpoint.hash_at_checkpoint,
                timestamp=timestamp,
                signature=checkpoint.signature,
                key_id=checkpoint.key_id or "",
            )
            store = get_external_store()
            if not await store.verify(proof, receipt):
                logger.warning(f"External proof verification failed for checkpoint {checkpoint.id}")
                return False
        except Exception:
            logger.warning(
                f"Could not verify external proof for checkpoint {checkpoint.id}",
                exc_info=True,
            )

    return True


async def verify_all_checkpoints(
    session: AsyncSession, org_id: str
) -> list[dict]:
    """Verify all checkpoints for an org, updating their verification status."""
    result = await session.execute(
        select(Checkpoint)
        .where(Checkpoint.org_id == org_id)
        .order_by(Checkpoint.created_at.desc())
    )
    checkpoints = list(result.scalars().all())

    results = []
    now = datetime.now(timezone.utc)

    for cp in checkpoints:
        is_valid = await verify_checkpoint(session, cp)
        cp.verified_at = now
        cp.is_valid = is_valid
        results.append({
            "checkpoint_id": cp.id,
            "sequence": cp.sequence_at_checkpoint,
            "hash": cp.hash_at_checkpoint,
            "merkle_root": cp.merkle_root,
            "is_valid": is_valid,
            "verified_at": now.isoformat(),
        })

    await session.commit()
    return results


async def list_checkpoints(
    session: AsyncSession, org_id: str
) -> list[Checkpoint]:
    """List all checkpoints for an org, newest first."""
    result = await session.execute(
        select(Checkpoint)
        .where(Checkpoint.org_id == org_id)
        .order_by(Checkpoint.created_at.desc())
    )
    return list(result.scalars().all())
