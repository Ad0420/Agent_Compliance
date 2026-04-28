"""Per-org asyncio locks for serialising chain mutations.

Used by both chain.py (action inserts) and checkpoint.py (checkpoint creation)
so the two can never interleave for the same org.

NOTE: These are in-process only. For multi-instance deployments, the
SELECT FOR UPDATE on chain_state in chain.py provides the cross-process
guarantee. SQLite has no row-level locking — so SQLite deployments are
single-instance only (this is already documented in the README).
"""

import asyncio

_chain_locks: dict[str, asyncio.Lock] = {}
_locks_lock = asyncio.Lock()


async def get_org_lock(org_id: str) -> asyncio.Lock:
    """Get or create a per-org lock. Lazily allocated; never freed
    (the cardinality is bounded by org count, which is fine).
    """
    async with _locks_lock:
        if org_id not in _chain_locks:
            _chain_locks[org_id] = asyncio.Lock()
        return _chain_locks[org_id]
