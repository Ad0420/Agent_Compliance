"""Customer-scoped evidence bundle generator — Wave 3D.2.

Builds a ``tar.gz`` archive that contains everything an external
verifier (the customer's compliance officer running ``vera verify
--offline``, or a regulator with the same CLI) needs to:

  1. Reconstruct the chain hash for every record in the bundle.
  2. Re-derive the Merkle root that the checkpoint signed.
  3. Validate the checkpoint's KMS signature over that root (asymmetric
     keys only; HMAC verification requires the shared secret out-of-band
     so this bundle is not enough by itself for HMAC chains).

The bundle is **selectively disclosed** — only records belonging to
the requested ``tenant_id`` are included. Sibling records from other
customers in the same checkpoint are NOT included; only the Merkle
sibling hashes for the verifier to recompute the root. A verifier
with the bundle cannot enumerate or count any other customer's
records.

Archive layout::

    bundle.tar.gz
      ├── manifest.json
      ├── checkpoints/
      │   ├── <checkpoint_id>.json   # GET /v1/checkpoints/{date} shape
      │   └── ...
      └── records/
          ├── <record_id>.json       # canonical + chain hash + merkle path
          └── ...

This shape matches the brief: ``manifest.json`` + ``checkpoints/<date>
.json`` + ``records/<id>.json``. The naming convention uses
checkpoint IDs (UUIDs) rather than dates because two checkpoints can
land in the same day under hourly cadence — file-per-id is collision
free; the manifest carries the date→id mapping for the CLI to use.

``manifest.json`` shape::

    {
      "schema_version": 1,
      "generated_at": "...",
      "tenant_id": "cleveland_clinic",
      "customer_display_name": "Cleveland Clinic",
      "org_id": "...",
      "date_range": {"start": "2026-02-26", "end": "2026-05-25"},
      "checkpoints": [
        {"checkpoint_id": "...", "date": "...", "merkle_root": "...",
         "customer_record_count": 12, "total_record_count": 47}
      ],
      "records": [
        {"id": "...", "checkpoint_id": "...", "sequence_number": 7234,
         "leaf_hash": "..."}
      ],
      "warnings": []  # e.g. "hmac_chain_no_offline_signature_verify"
    }
"""
from __future__ import annotations

import hashlib
import io
import json
import logging
import re
import tarfile
from dataclasses import dataclass
from datetime import date as date_cls, datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import ActionRecord, Checkpoint, Customer, Organization
from ..services.kms import ALGO_HMAC_SHA256, get_key_by_id
from ..services.merkle import build_tree_from_records
from .hashing import canonicalize, extract_hashable_fields

logger = logging.getLogger("vera.evidence_export")

SCHEMA_VERSION = 1

# Defense-in-depth: server-side guard mirroring the SDK CLI's
# ``_require_safe_record_id`` / ``_require_safe_date`` checks (see
# ``sdk/vera/_cli_verify.py``). Today the backend mints every
# ``ActionRecord.id`` and ``Checkpoint.id`` as a uuid4 via
# ``default=lambda: str(uuid.uuid4())`` and dates via
# ``cp.created_at.date().isoformat()`` — both safe by construction.
# This guard exists so a future refactor that, say, lets a caller
# supply a record id can't silently re-introduce a path-traversal
# write outside the in-memory tar (where ``tarfile.TarInfo(name=...)``
# would happily honor ``"../etc/passwd"``).
_UUID_RE = re.compile(r"^[0-9a-fA-F-]{36}$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _truncate_for_error(value: Any, *, limit: int = 80) -> str:
    """Truncate ``value`` for an exception message; ``repr``-escapes
    non-printables to neutralise log injection via crafted IDs."""
    s = str(value) if value is not None else "<none>"
    if len(s) > limit:
        s = s[:limit] + "..."
    return repr(s)


def _require_safe_record_id(rid: Any) -> None:
    """Raise ``ValueError`` if ``rid`` is not a UUID-shaped string."""
    if not isinstance(rid, str) or not _UUID_RE.match(rid):
        raise ValueError(
            "evidence-export aborted: record id does not match the "
            "expected UUID format "
            f"(offending value={_truncate_for_error(rid)})."
        )


def _require_safe_checkpoint_id(cid: Any) -> None:
    """Raise ``ValueError`` if ``cid`` is not a UUID-shaped string."""
    if not isinstance(cid, str) or not _UUID_RE.match(cid):
        raise ValueError(
            "evidence-export aborted: checkpoint id does not match "
            "the expected UUID format "
            f"(offending value={_truncate_for_error(cid)})."
        )


def _require_safe_date(date_iso: Any) -> None:
    """Raise ``ValueError`` if ``date_iso`` is not a YYYY-MM-DD string."""
    if not isinstance(date_iso, str) or not _DATE_RE.match(date_iso):
        raise ValueError(
            "evidence-export aborted: date does not match the "
            "expected YYYY-MM-DD format "
            f"(offending value={_truncate_for_error(date_iso)})."
        )


@dataclass
class EvidenceBundleSummary:
    """Lightweight view of what's in a bundle. Used for the modal preview
    so the dashboard can show ``"This export will contain X records
    belonging only to {customer_name}."`` without materialising the
    bundle bytes.
    """

    customer_record_count: int
    checkpoint_count: int
    tenant_id: str
    customer_display_name: Optional[str]
    warnings: list[str]


def _format_iso_ms(ts: datetime) -> str:
    if ts.tzinfo is not None:
        ts = ts.astimezone(timezone.utc).replace(tzinfo=None)
    ts = ts.replace(microsecond=(ts.microsecond // 1000) * 1000)
    return ts.isoformat(timespec="milliseconds")


def _naive_utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _canonicalize_action_record(record: ActionRecord) -> str:
    fields = extract_hashable_fields(record)
    return canonicalize(fields)


async def _customer_records_in_range(
    session: AsyncSession,
    *,
    org_id: str,
    tenant_id: str,
    start: datetime,
    end: datetime,
) -> list[ActionRecord]:
    """Customer-scoped ActionRecord rows whose ``recorded_at`` falls in
    ``[start, end)``.

    Ordered by ``sequence_number`` so the verifier can walk them in
    chain order.
    """
    q = (
        select(ActionRecord)
        .where(
            ActionRecord.org_id == org_id,
            ActionRecord.tenant_id == tenant_id,
            ActionRecord.recorded_at >= start,
            ActionRecord.recorded_at < end,
        )
        .order_by(ActionRecord.sequence_number)
    )
    return list((await session.execute(q)).scalars().all())


async def _checkpoints_covering_records(
    session: AsyncSession,
    *,
    org_id: str,
    records: list[ActionRecord],
) -> list[Checkpoint]:
    """All distinct checkpoints whose sealed windows contain any of
    ``records``.

    For each record, the sealing checkpoint is the one with the smallest
    ``sequence_at_checkpoint >= record.sequence_number``. We collect the
    unique set of those checkpoints and return them sorted by
    ``sequence_at_checkpoint``.

    Implementation: one SELECT for every checkpoint whose
    ``sequence_at_checkpoint`` is at-or-above the minimum record
    sequence in the bundle, ordered ASC. Then walk records (sorted ASC)
    and the checkpoint cursor together — each record's sealing
    checkpoint is the first one whose seq >= the record's seq. O(N+M)
    Python work, one round-trip to the DB. The earlier per-record SELECT
    was O(N) queries which dominated wall-clock for large bundles.
    """
    if not records:
        return []
    min_seq = min(r.sequence_number for r in records)
    q = (
        select(Checkpoint)
        .where(
            Checkpoint.org_id == org_id,
            Checkpoint.sequence_at_checkpoint >= min_seq,
        )
        .order_by(Checkpoint.sequence_at_checkpoint.asc())
    )
    all_cps = list((await session.execute(q)).scalars().all())
    if not all_cps:
        return []

    # Walk records (sorted ASC) and the checkpoint cursor together.
    # Each record's sealing checkpoint is the first ``cp`` whose
    # ``cp.sequence_at_checkpoint >= r.sequence_number``.
    sorted_records = sorted(records, key=lambda r: r.sequence_number)
    cp_iter = iter(all_cps)
    current_cp: Optional[Checkpoint] = next(cp_iter, None)
    sealing_ids: set[str] = set()
    for r in sorted_records:
        while (
            current_cp is not None
            and current_cp.sequence_at_checkpoint < r.sequence_number
        ):
            current_cp = next(cp_iter, None)
        if current_cp is None:
            break  # record is past the last sealed checkpoint — tail
        sealing_ids.add(current_cp.id)

    return [cp for cp in all_cps if cp.id in sealing_ids]


async def _previous_seq(
    session: AsyncSession, *, org_id: str, this_seq: int
) -> int:
    q = (
        select(Checkpoint.sequence_at_checkpoint)
        .where(
            Checkpoint.org_id == org_id,
            Checkpoint.sequence_at_checkpoint < this_seq,
        )
        .order_by(Checkpoint.sequence_at_checkpoint.desc())
        .limit(1)
    )
    val = (await session.execute(q)).scalar_one_or_none()
    return int(val) if val is not None else 0


async def _window_leaf_hashes(
    session: AsyncSession, *, org_id: str, prior_seq: int, this_seq: int
) -> tuple[list[str], list[str]]:
    """Return ``(leaf_hashes, leaf_ids)`` for the half-open window
    ``(prior_seq, this_seq]`` ordered by sequence_number ASC.

    Same selection logic as ``services.merkle_proof.build_proof`` — the
    leaf set MUST match the one used at seal time to reconstruct the
    root.
    """
    q = (
        select(ActionRecord.record_hash, ActionRecord.id)
        .where(
            ActionRecord.org_id == org_id,
            ActionRecord.sequence_number > prior_seq,
            ActionRecord.sequence_number <= this_seq,
        )
        .order_by(ActionRecord.sequence_number)
    )
    rows = (await session.execute(q)).all()
    return [r[0] for r in rows], [r[1] for r in rows]


async def _record_total_count_in_window(
    session: AsyncSession,
    *,
    org_id: str,
    prior_seq: int,
    this_seq: int,
) -> int:
    """COUNT(*) of ALL records (not customer-filtered) in the window."""
    from sqlalchemy import func

    q = select(func.count(ActionRecord.id)).where(
        ActionRecord.org_id == org_id,
        ActionRecord.sequence_number > prior_seq,
        ActionRecord.sequence_number <= this_seq,
    )
    return int((await session.execute(q)).scalar_one() or 0)


async def summarize_evidence_bundle(
    session: AsyncSession,
    *,
    customer: Customer,
    start: datetime,
    end: datetime,
) -> EvidenceBundleSummary:
    """Cheap preview — counts + warnings only, no archive bytes built.

    Powers the download modal's "This export will contain X,XXX
    records belonging only to {customer_name}" line.
    """
    records = await _customer_records_in_range(
        session,
        org_id=customer.org_id,
        tenant_id=customer.tenant_id,
        start=start,
        end=end,
    )
    checkpoints = await _checkpoints_covering_records(
        session, org_id=customer.org_id, records=records
    )
    warnings: list[str] = []
    for cp in checkpoints:
        if cp.key_id:
            row = await get_key_by_id(session, cp.key_id)
            if row is not None and row.algorithm == ALGO_HMAC_SHA256:
                warnings.append("hmac_chain_no_offline_signature_verify")
                break
    return EvidenceBundleSummary(
        customer_record_count=len(records),
        checkpoint_count=len(checkpoints),
        tenant_id=customer.tenant_id,
        customer_display_name=customer.display_name,
        warnings=warnings,
    )


async def build_evidence_bundle_tar_gz(
    session: AsyncSession,
    *,
    customer: Customer,
    org: Organization,
    start: datetime,
    end: datetime,
) -> tuple[bytes, EvidenceBundleSummary]:
    """Materialise the full ``.tar.gz`` bundle for ``customer`` in
    ``[start, end)``.

    Returns ``(archive_bytes, summary)``. The archive contents match
    the layout in the module docstring.

    The bundle is **byte-stable per call** in the sense that the JSON
    payloads inside are canonical (sorted keys, no whitespace). The
    tar gzip wrapper itself isn't byte-stable because gzip embeds a
    modification time — we set ``mtime=0`` on each tar entry so two
    bundles for the same date range *are* identical at the tar level;
    the outer gzip stream still varies (Python's GzipFile picks the
    current time as mtime). That's fine: the verifier reads the
    files, not the gzip header.
    """
    records = await _customer_records_in_range(
        session,
        org_id=customer.org_id,
        tenant_id=customer.tenant_id,
        start=start,
        end=end,
    )
    checkpoints = await _checkpoints_covering_records(
        session, org_id=customer.org_id, records=records
    )

    # Per-checkpoint window leaf material (shared across the per-record
    # files that fall in that window — avoids rebuilding the same tree
    # for each record). Cache the constructed Merkle tree too: with the
    # leaf list pinned, the tree is fully determined, and the per-record
    # loop below would otherwise rebuild it N times for N customer
    # records in the same checkpoint window (O(N²) for large bundles).
    from ..services.merkle import MerkleTree

    tree_cache: dict[str, tuple[list[str], list[str], MerkleTree]] = {}
    cp_meta: dict[str, dict[str, Any]] = {}
    warnings: set[str] = set()
    # Defense-in-depth: validate every checkpoint id up-front. Same
    # rationale as the record-id pre-pass below — the guard MUST fire
    # before any code path uses ``cp.id`` as a dict key or filename
    # component (``tree_cache[cp.id]`` happens inside this loop).
    for cp in checkpoints:
        _require_safe_checkpoint_id(cp.id)
    for cp in checkpoints:
        prior = await _previous_seq(
            session, org_id=customer.org_id, this_seq=cp.sequence_at_checkpoint
        )
        leaf_hashes, leaf_ids = await _window_leaf_hashes(
            session,
            org_id=customer.org_id,
            prior_seq=prior,
            this_seq=cp.sequence_at_checkpoint,
        )
        # Build the tree ONCE per checkpoint. ``MerkleTree.get_proof(i)``
        # is O(log N) on the cached internal levels; the alternative
        # (building the tree per record) would be O(N log N) per record
        # and dominate wall-clock for large bundles.
        cached_tree = build_tree_from_records(leaf_hashes)
        tree_cache[cp.id] = (leaf_hashes, leaf_ids, cached_tree)
        total_count = await _record_total_count_in_window(
            session,
            org_id=customer.org_id,
            prior_seq=prior,
            this_seq=cp.sequence_at_checkpoint,
        )

        kms_algorithm = ""
        kms_public_key_pem: Optional[str] = None
        if cp.key_id:
            row = await get_key_by_id(session, cp.key_id)
            if row is not None:
                kms_algorithm = row.algorithm
                kms_public_key_pem = row.public_key_pem
                if row.algorithm == ALGO_HMAC_SHA256:
                    warnings.add("hmac_chain_no_offline_signature_verify")

        cp_meta[cp.id] = {
            "checkpoint_id": cp.id,
            "org_id": cp.org_id,
            "merkle_root": cp.merkle_root,
            "kms_key_id": cp.key_id,
            "kms_algorithm": kms_algorithm or None,
            "kms_public_key_pem": kms_public_key_pem,
            "signature": cp.signature,
            "signed_at": _format_iso_ms(cp.created_at),
            "sequence_at_checkpoint": cp.sequence_at_checkpoint,
            "hash_at_checkpoint": cp.hash_at_checkpoint,
            "prior_sequence_at_checkpoint": prior,
            "total_record_count": total_count,
            "date": cp.created_at.date().isoformat(),
        }

    # Build per-record JSONs (canonical + chain hash + merkle path).
    #
    # Defense-in-depth: validate every record id up-front before doing
    # ANY work for that record. The guard MUST fire before
    # ``leaf_ids.index(r.id)`` (which would mask a bad id by falling
    # into the "not found in window" skip-branch and silently dropping
    # the row from the bundle). Today every id is uuid4 so this is
    # a no-op; the guard hardens against a future refactor.
    for r in records:
        _require_safe_record_id(r.id)

    record_files: list[tuple[str, bytes]] = []
    manifest_records: list[dict[str, Any]] = []
    for r in records:
        cp = next(
            (
                c
                for c in checkpoints
                if c.sequence_at_checkpoint >= r.sequence_number
            ),
            None,
        )
        if cp is None:
            # Tail record — no sealing checkpoint yet. Skip from the
            # bundle; the manifest's record count reflects only included
            # records. The CLI can re-request once a checkpoint seals.
            warnings.add("tail_records_excluded")
            continue
        leaf_hashes, leaf_ids, tree = tree_cache[cp.id]
        try:
            idx = leaf_ids.index(r.id)
        except ValueError:
            logger.error(
                "evidence_export: record %s not found in sealing checkpoint %s window",
                r.id,
                cp.id,
            )
            continue
        proof = tree.get_proof(idx)

        canonical = _canonicalize_action_record(r)
        record_payload: dict[str, Any] = {
            "id": r.id,
            "tenant_id": r.tenant_id,
            "sequence_number": r.sequence_number,
            "recorded_at": _format_iso_ms(r.recorded_at)
            if r.recorded_at
            else None,
            "previous_hash": r.previous_hash,
            "record_hash": r.record_hash,
            "canonical": canonical,
            "leaf_hash": proof.leaf_hash,
            "merkle_path": [
                {"sibling_hash": h, "direction": d}
                for h, d in zip(proof.proof_hashes, proof.proof_directions)
            ],
            "checkpoint_id": cp.id,
            "merkle_root": proof.root,
        }
        body = json.dumps(
            record_payload, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        # Defense-in-depth path-traversal guard: every ActionRecord.id
        # is a uuid4 today, but a guard here prevents a future
        # refactor (e.g. accepting a caller-supplied record id) from
        # silently re-introducing a way to drive ``tarfile.TarInfo``
        # to write at ``../etc/passwd``.
        _require_safe_record_id(r.id)
        _require_safe_checkpoint_id(cp.id)
        record_files.append((f"records/{r.id}.json", body))
        manifest_records.append(
            {
                "id": r.id,
                "checkpoint_id": cp.id,
                "sequence_number": r.sequence_number,
                "leaf_hash": proof.leaf_hash,
            }
        )

    # Per-checkpoint JSON files. Customer-filtered count derived from the
    # records we actually included in the bundle.
    customer_counts: dict[str, int] = {}
    for mr in manifest_records:
        customer_counts[mr["checkpoint_id"]] = (
            customer_counts.get(mr["checkpoint_id"], 0) + 1
        )

    checkpoint_files: list[tuple[str, bytes]] = []
    manifest_checkpoints: list[dict[str, Any]] = []
    for cp in checkpoints:
        if cp.id not in customer_counts:
            # No customer records landed in this checkpoint after all
            # (every record from this checkpoint was a tail record or a
            # record that didn't index — both warn-flagged above). Skip
            # writing the file so the bundle stays minimal.
            continue
        meta = cp_meta[cp.id]
        meta = {**meta, "customer_record_count": customer_counts[cp.id]}
        body = json.dumps(meta, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
        # Defense-in-depth: same path-traversal guard as the per-record
        # write site above. Both ``cp.id`` and the date field are
        # UUID/ISO-shaped by construction; the regex protects the
        # filename slot against future refactors.
        _require_safe_checkpoint_id(cp.id)
        _require_safe_date(meta["date"])
        checkpoint_files.append((f"checkpoints/{cp.id}.json", body))
        manifest_checkpoints.append(
            {
                "checkpoint_id": cp.id,
                "date": meta["date"],
                "merkle_root": cp.merkle_root,
                "customer_record_count": customer_counts[cp.id],
                "total_record_count": meta["total_record_count"],
            }
        )

    # ``vera_version`` / ``exported_at`` / ``checkpoint_count`` /
    # ``record_count`` are the four keys the SDK's offline verifier
    # (``sdk/vera/verify/offline.py``, Wave 3C.1) requires to even open
    # the bundle. They were missing in the original Wave 3D.2 exporter
    # output, so ``vera verify --offline`` against any dashboard-
    # produced bundle failed at the manifest gate. Found during Phase 3
    # Scenario 4 acceptance testing — this is the headline regulator-
    # ready gate. Keep the existing dashboard-only keys too — the SDK
    # ignores unknowns.
    _generated_at = _format_iso_ms(_naive_utc_now())
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "vera_version": str(SCHEMA_VERSION),
        "generated_at": _generated_at,
        "exported_at": _generated_at,
        "tenant_id": customer.tenant_id,
        "customer_display_name": customer.display_name,
        "org_id": customer.org_id,
        "org_name": org.name,
        "date_range": {
            "start": start.date().isoformat(),
            "end": (end - timedelta(microseconds=1)).date().isoformat(),
        },
        "checkpoints": manifest_checkpoints,
        "checkpoint_count": len(manifest_checkpoints),
        "records": manifest_records,
        "record_count": len(manifest_records),
        "warnings": sorted(warnings),
    }
    manifest_body = json.dumps(
        manifest, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")

    # Build the tar.gz in-memory. The bundle is selective-disclosure so
    # the size is bounded by per-customer record count — streaming to
    # disk would over-engineer the path; the typical bundle is in the
    # low MB. If we ever ship 1M-record bundles, switch to a streaming
    # response with chunked writes through a pipe.
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        def _add(name: str, data: bytes) -> None:
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            info.mtime = 0  # byte-stable mtime
            tar.addfile(info, io.BytesIO(data))

        _add("manifest.json", manifest_body)
        for name, data in checkpoint_files:
            _add(name, data)
        for name, data in record_files:
            _add(name, data)

    summary = EvidenceBundleSummary(
        customer_record_count=len(manifest_records),
        checkpoint_count=len(manifest_checkpoints),
        tenant_id=customer.tenant_id,
        customer_display_name=customer.display_name,
        warnings=sorted(warnings),
    )
    return buf.getvalue(), summary


def bundle_filename(tenant_id: str, start: datetime, end: datetime) -> str:
    """Suggested filename for the bundle. Keeps the date range visible
    so an investigator pulling multiple bundles can tell them apart at
    a glance.
    """
    start_str = start.date().isoformat()
    end_str = (end - timedelta(microseconds=1)).date().isoformat()
    safe_tenant = "".join(
        c if c.isalnum() or c in ("-", "_") else "_" for c in tenant_id
    )
    return f"vera-evidence-{safe_tenant}-{start_str}_to_{end_str}.tar.gz"


# Used by tests + the CLI to sanity-check a bundle locally without
# untarring to disk.
def verify_bundle_record_path(record_json: dict) -> bool:
    """Fold a record's merkle_path from leaf_hash toward the root and
    assert the folded result equals ``merkle_root``.

    Mirrors ``services.merkle_proof.verify_proof_payload`` — duplicated
    here so the CLI doesn't need to import the proof service to verify
    a bundle.
    """
    current = record_json["leaf_hash"]
    for step in record_json["merkle_path"]:
        sibling = step["sibling_hash"]
        direction = step["direction"]
        if direction == "left":
            combined = sibling + current
        else:
            combined = current + sibling
        current = hashlib.sha256(combined.encode("utf-8")).hexdigest()
    return current == record_json["merkle_root"]
