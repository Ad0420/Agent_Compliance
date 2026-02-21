from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import ActionRecord
from ..schemas.verification import ChainVerificationResult, RecordVerificationResult
from .hashing import verify_record_hash

# Process records in chunks to avoid loading the entire chain into memory.
_VERIFY_CHUNK_SIZE = 500


async def verify_chain(
    session: AsyncSession,
    org_id: str,
    start_seq: int | None = None,
    end_seq: int | None = None,
) -> ChainVerificationResult:
    """Walk the chain in sequence order and verify each record's hash and chain link.

    Uses chunked streaming so we never hold more than _VERIFY_CHUNK_SIZE
    records in memory at a time.
    """
    # Determine the previous_hash to start from
    first_seq = start_seq or 1
    if first_seq > 1:
        prev_result = await session.execute(
            select(ActionRecord.record_hash).where(
                ActionRecord.org_id == org_id,
                ActionRecord.sequence_number == first_seq - 1,
            )
        )
        row = prev_result.scalar_one_or_none()
        previous_hash = row if row else None
    else:
        previous_hash = "GENESIS"

    records_checked = 0
    current_offset = 0

    while True:
        query = (
            select(ActionRecord)
            .where(ActionRecord.org_id == org_id)
            .where(ActionRecord.sequence_number >= first_seq)
            .order_by(ActionRecord.sequence_number)
            .limit(_VERIFY_CHUNK_SIZE)
            .offset(current_offset)
        )
        if end_seq is not None:
            query = query.where(ActionRecord.sequence_number <= end_seq)

        result = await session.execute(query)
        chunk = result.scalars().all()

        if not chunk:
            break

        for record in chunk:
            # Verify record hash matches content
            if not verify_record_hash(record):
                return ChainVerificationResult(
                    is_valid=False,
                    records_checked=records_checked,
                    first_invalid_sequence=record.sequence_number,
                    message=f"Record hash mismatch at sequence {record.sequence_number}",
                )

            # Verify chain link
            if previous_hash is not None and record.previous_hash != previous_hash:
                return ChainVerificationResult(
                    is_valid=False,
                    records_checked=records_checked,
                    first_invalid_sequence=record.sequence_number,
                    message=f"Chain link broken at sequence {record.sequence_number}",
                )

            previous_hash = record.record_hash
            records_checked += 1

        current_offset += len(chunk)

        # Expire loaded objects to free memory before next chunk
        for record in chunk:
            await session.refresh(record)  # ensure state is synced
        session.expire_all()

    if records_checked == 0:
        return ChainVerificationResult(
            is_valid=True,
            records_checked=0,
            message="No records to verify",
        )

    return ChainVerificationResult(
        is_valid=True,
        records_checked=records_checked,
        message=f"All {records_checked} records verified successfully",
    )


async def verify_single_record(
    session: AsyncSession, org_id: str, record_id: str
) -> RecordVerificationResult:
    """Verify a single record's hash and chain link."""
    result = await session.execute(
        select(ActionRecord).where(
            ActionRecord.id == record_id,
            ActionRecord.org_id == org_id,
        )
    )
    record = result.scalar_one_or_none()
    if record is None:
        return RecordVerificationResult(
            record_id=record_id,
            record_hash_valid=False,
            chain_link_valid=False,
            message="Record not found",
        )

    # Verify hash
    hash_valid = verify_record_hash(record)

    # Verify chain link — check previous record
    chain_valid = True
    if record.sequence_number == 1:
        chain_valid = record.previous_hash == "GENESIS"
    else:
        prev_result = await session.execute(
            select(ActionRecord.record_hash).where(
                ActionRecord.org_id == org_id,
                ActionRecord.sequence_number == record.sequence_number - 1,
            )
        )
        prev_hash = prev_result.scalar_one_or_none()
        if prev_hash:
            chain_valid = record.previous_hash == prev_hash
        else:
            chain_valid = False

    if hash_valid and chain_valid:
        msg = "Record is valid"
    elif not hash_valid:
        msg = "Record hash does not match content"
    else:
        msg = "Chain link is broken — previous_hash does not match prior record"

    return RecordVerificationResult(
        record_id=record_id,
        record_hash_valid=hash_valid,
        chain_link_valid=chain_valid,
        message=msg,
    )
