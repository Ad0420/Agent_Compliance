"""Per-resource asyncio locks for serialising state mutations.

* ``get_org_lock`` — used by chain.py (action inserts) and
  checkpoint.py (checkpoint creation) so the two can never interleave
  for the same org.
* ``get_review_lock`` — used by services.reviews.complete_review
  (Wave 2D PR A6) so two concurrent callbacks on the same review_id
  serialise within a single process. The DB-level ``SELECT … FOR
  UPDATE`` covers the cross-process case on Postgres; this in-process
  lock covers single-process deployments (and the SQLite test suite,
  where FOR UPDATE is a no-op).

NOTE: These are in-process only. For multi-instance deployments, the
SELECT FOR UPDATE on chain_state in chain.py and on approvals in
services/reviews.py provides the cross-process guarantee. SQLite has
no row-level locking — so SQLite deployments are single-instance only
(this is already documented in the README).
"""

import asyncio

_chain_locks: dict[str, asyncio.Lock] = {}
_review_locks: dict[str, asyncio.Lock] = {}
_locks_lock = asyncio.Lock()


async def get_org_lock(org_id: str) -> asyncio.Lock:
    """Get or create a per-org lock. Lazily allocated; never freed
    (the cardinality is bounded by org count, which is fine).
    """
    async with _locks_lock:
        if org_id not in _chain_locks:
            _chain_locks[org_id] = asyncio.Lock()
        return _chain_locks[org_id]


async def get_review_lock(review_id: str) -> asyncio.Lock:
    """Get or create a per-review lock for callback serialisation.

    Lazily allocated. Cardinality scales with the number of reviews
    that have ever received a callback in this process's lifetime;
    practical worst case is bounded by the active-org review volume,
    same shape as ``_chain_locks``. Never freed — the per-review state
    is tiny and freeing would require a watcher to avoid races between
    "is this lock still needed" and "is someone holding it".
    """
    async with _locks_lock:
        if review_id not in _review_locks:
            _review_locks[review_id] = asyncio.Lock()
        return _review_locks[review_id]
