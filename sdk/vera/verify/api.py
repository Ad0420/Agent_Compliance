"""HTTP client for ``vera verify`` (online path).

Thin wrapper over :class:`vera.client.VeraClient` so the verify
subpackage doesn't reach into the client's private retry / error
machinery. Two endpoints:

* ``GET /v1/checkpoints/{date}`` — Phase 3 Wave 3B.1.
* ``GET /v1/records/{action_record_id}/merkle-proof`` — Phase 3 Wave 3B.2.

For the offline pipeline (``vera verify --offline``) these are not
called — the bundle on disk is the only input. For the future online
``vera verify <record_id>`` path these are the fetch primitives.
"""

from __future__ import annotations

from typing import Any

from ..client import VeraClient


def fetch_checkpoint_by_date(client: VeraClient, *, date_iso: str) -> dict[str, Any]:
    """Fetch the checkpoint sealed on ``date_iso`` (UTC).

    ``date_iso`` is an ISO-8601 calendar date string (``YYYY-MM-DD``).
    Raises :class:`vera.errors.VeraError` subclasses on HTTP failures
    (already mapped by ``VeraClient._request_with_retry``).
    """
    resp = client._request_with_retry("get", f"/v1/checkpoints/{date_iso}")
    return resp.json()


def fetch_merkle_proof(
    client: VeraClient, *, action_record_id: str
) -> dict[str, Any]:
    """Fetch the Merkle inclusion proof for ``action_record_id``.

    Response shape matches
    ``backend.app.services.merkle_proof.MerkleProofPayload.to_dict``.
    """
    resp = client._request_with_retry(
        "get", f"/v1/records/{action_record_id}/merkle-proof"
    )
    return resp.json()
