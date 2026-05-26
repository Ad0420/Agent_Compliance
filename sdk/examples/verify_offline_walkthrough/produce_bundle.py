"""Build a small evidence bundle for the offline-verify walkthrough.

In production, `vera evidence-export --customer <tenant_id> --since <date>`
calls Vera, pulls the relevant ActionRecords + their Merkle proofs +
the signed checkpoints + the KMS key history, and writes a tar.gz to
`--out`. The bundle is self-contained: an auditor with the file plus
(for HMAC orgs) the shared secret can verify it offline.

This script produces a bundle in the same shape using local fixtures —
no real Vera credentials needed. It exists so a compliance engineer
reading the SDK docs for the first time can see what a bundle actually
looks like, run `verify_bundle.py` against it, and watch the verifier
exit 0.

Bundle shape this script produces (matches the production format):

    bundle/
      manifest.json                # bundle metadata + summary counts
      checkpoints/
        <checkpoint_id>.json       # one per sealed checkpoint
      records/
        <record_id>.json           # one Merkle proof payload per record
      kms_keys.json                # KMS key history (algorithm + PEM per key_id)

Fields inside each file mirror the production API exactly:

    checkpoints/<id>.json: GET /v1/checkpoints/{date} response body
    records/<id>.json:     GET /v1/records/{id}/merkle-proof response body
    kms_keys.json:         array of {key_id, algorithm, public_key_pem,
                                     first_seen_at}

The walkthrough deliberately uses HMAC-SHA256 because it has no PEM
indirection and the verifier can be read top-to-bottom. The verifier
also handles asymmetric signatures via cryptography>=42; see
verify_bundle.py for the branch.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import shutil
import sys
import tarfile
from pathlib import Path
from typing import Any


# ── Fixture data ────────────────────────────────────────────────────────


# Deterministic timestamps so the bundle hashes the same across runs.
BUNDLE_GENERATED_AT = "2026-05-25T10:00:00+00:00"
CUSTOMER_TENANT_ID = "cleveland_clinic"
KMS_KEY_ID = "vera-prod-2026q2"
HMAC_SECRET = b"walkthrough-demo-secret-do-not-use-in-production"

# Six toy action records spread across two checkpoint windows.
RECORDS: list[dict[str, Any]] = [
    {
        "id": "act_001",
        "sequence_number": 1,
        "agent_name": "intake-agent",
        "action_name": "screen_referral",
        "result": "success",
        "data_subject_id": "pat_001",
        "created_at": "2026-03-01T09:00:00+00:00",
    },
    {
        "id": "act_002",
        "sequence_number": 2,
        "agent_name": "intake-agent",
        "action_name": "schedule_appointment",
        "result": "success",
        "data_subject_id": "pat_001",
        "created_at": "2026-03-01T09:05:00+00:00",
    },
    {
        "id": "act_003",
        "sequence_number": 3,
        "agent_name": "scribe-agent",
        "action_name": "draft_chart_note",
        "result": "success",
        "data_subject_id": "pat_002",
        "created_at": "2026-03-01T11:30:00+00:00",
    },
    {
        "id": "act_004",
        "sequence_number": 4,
        "agent_name": "triage-agent",
        "action_name": "flag_for_review",
        "result": "require_hitl",
        "data_subject_id": "pat_003",
        "created_at": "2026-03-02T08:15:00+00:00",
    },
    {
        "id": "act_005",
        "sequence_number": 5,
        "agent_name": "billing-agent",
        "action_name": "submit_claim",
        "result": "success",
        "data_subject_id": "pat_002",
        "created_at": "2026-03-02T14:00:00+00:00",
    },
    {
        "id": "act_006",
        "sequence_number": 6,
        "agent_name": "scribe-agent",
        "action_name": "finalize_chart_note",
        "result": "success",
        "data_subject_id": "pat_003",
        "created_at": "2026-03-02T16:20:00+00:00",
    },
]

# Records 1-3 are sealed under checkpoint A, records 4-6 under checkpoint B.
CHECKPOINT_WINDOWS = [
    {
        "id": "cp_2026-03-01",
        "date": "2026-03-01",
        "signed_at": "2026-03-01T23:59:59+00:00",
        "sequence_at_checkpoint": 3,
        "record_ids": ["act_001", "act_002", "act_003"],
    },
    {
        "id": "cp_2026-03-02",
        "date": "2026-03-02",
        "signed_at": "2026-03-02T23:59:59+00:00",
        "sequence_at_checkpoint": 6,
        "record_ids": ["act_004", "act_005", "act_006"],
    },
]


# ── Canonical-bytes + chain hash helpers ────────────────────────────────


def _canonicalize(record: dict[str, Any]) -> str:
    """Stable, deterministic JSON serialisation of a record.

    Production canonicalisation lives in
    `backend/app/services/hashing.canonicalize`; this is the same
    sorted-keys + no-whitespace UTF-8 form.
    """
    return json.dumps(record, sort_keys=True, separators=(",", ":"))


def _record_hash(canonical: str, previous_hash: str) -> str:
    """Chain hash: SHA-256(previous_hash + canonical).

    Production rule in `backend/app/services/hashing.compute_record_hash`.
    """
    return hashlib.sha256((previous_hash + canonical).encode("utf-8")).hexdigest()


# ── Merkle tree (mirrors backend/app/services/merkle.py) ────────────────


def _hash_pair(left: str, right: str) -> str:
    return hashlib.sha256((left + right).encode("utf-8")).hexdigest()


def _build_merkle(leaves: list[str]) -> list[list[str]]:
    """Build a binary Merkle tree bottom-up; return the level list.

    Pads to next power of two with duplicates of the last leaf — same
    convention as the backend's Merkle builder.
    """
    if not leaves:
        return [[]]
    n = len(leaves)
    next_pow2 = 1 << (n - 1).bit_length() if n > 1 else 1
    padded = list(leaves) + [leaves[-1]] * (next_pow2 - n)
    levels: list[list[str]] = [padded]
    while len(levels[-1]) > 1:
        current = levels[-1]
        next_level = [_hash_pair(current[i], current[i + 1]) for i in range(0, len(current), 2)]
        levels.append(next_level)
    return levels


def _merkle_root(levels: list[list[str]]) -> str:
    return levels[-1][0] if levels and levels[-1] else hashlib.sha256(b"EMPTY_TREE").hexdigest()


def _merkle_proof_path(levels: list[list[str]], leaf_index: int) -> list[dict[str, str]]:
    """Sibling path from `leaf_index` up to (but not including) the root."""
    path: list[dict[str, str]] = []
    idx = leaf_index
    for level in levels[:-1]:
        if idx % 2 == 0:
            sibling_idx = idx + 1
            direction = "right"
        else:
            sibling_idx = idx - 1
            direction = "left"
        sibling = level[sibling_idx] if sibling_idx < len(level) else level[idx]
        path.append({"sibling_hash": sibling, "direction": direction})
        idx //= 2
    return path


# ── Bundle assembly ─────────────────────────────────────────────────────


def _checkpoint_message(checkpoint: dict[str, Any]) -> bytes:
    """Bytes that get signed by the KMS — same format as production.

    Backend builder: `services.checkpoint._checkpoint_message`. Format:
    `{org_id}:{sequence}:{hash_at_checkpoint}:{signed_at_isoformat}`.
    """
    return (
        f"{checkpoint['org_id']}:{checkpoint['sequence_at_checkpoint']}:"
        f"{checkpoint['hash_at_checkpoint']}:{checkpoint['signed_at']}"
    ).encode("utf-8")


def _sign_hmac(message: bytes, secret: bytes) -> str:
    return hmac.new(secret, message, hashlib.sha256).hexdigest()


def _record_canonical(record: dict[str, Any]) -> str:
    """Subset of fields that participate in the hash — matches the
    backend's `extract_hashable_fields` set we care about for the demo.
    """
    hashable = {
        "id": record["id"],
        "sequence_number": record["sequence_number"],
        "agent_name": record["agent_name"],
        "action_name": record["action_name"],
        "result": record["result"],
        "data_subject_id": record["data_subject_id"],
        "created_at": record["created_at"],
    }
    return _canonicalize(hashable)


def build_bundle(out_path: Path) -> Path:
    """Materialise the full bundle tree at `out_path` and tar.gz it.

    Returns the path to the tar.gz file.
    """
    work = out_path.parent / (out_path.stem.replace(".tar", "") + "_workdir")
    if work.exists():
        shutil.rmtree(work)
    (work / "checkpoints").mkdir(parents=True)
    (work / "records").mkdir(parents=True)

    org_id = "org_walkthrough_demo"
    record_by_id = {r["id"]: r for r in RECORDS}

    # Walk records in sequence order so previous_hash chains correctly.
    previous_hash = "0" * 64
    record_hashes: dict[str, str] = {}
    record_canonicals: dict[str, str] = {}
    for r in sorted(RECORDS, key=lambda x: x["sequence_number"]):
        canonical = _record_canonical(r)
        leaf = _record_hash(canonical, previous_hash)
        record_canonicals[r["id"]] = canonical
        record_hashes[r["id"]] = leaf
        previous_hash = leaf

    # Per checkpoint: build the Merkle tree, sign the head, emit
    # checkpoint JSON + per-record proof JSON.
    written_records = 0
    checkpoint_summaries: list[dict[str, Any]] = []
    head_hash_at_checkpoint = "0" * 64

    for window in CHECKPOINT_WINDOWS:
        leaves = [record_hashes[rid] for rid in window["record_ids"]]
        levels = _build_merkle(leaves)
        root = _merkle_root(levels)
        head_hash_at_checkpoint = record_hashes[window["record_ids"][-1]]

        checkpoint = {
            "id": window["id"],
            "org_id": org_id,
            "date": window["date"],
            "sequence_at_checkpoint": window["sequence_at_checkpoint"],
            "hash_at_checkpoint": head_hash_at_checkpoint,
            "merkle_root": root,
            "signed_at": window["signed_at"],
            "key_id": KMS_KEY_ID,
            "algorithm": "hmac-sha256",
            "record_count": len(leaves),
        }
        checkpoint["signature"] = _sign_hmac(_checkpoint_message(checkpoint), HMAC_SECRET)

        cp_path = work / "checkpoints" / f"{checkpoint['id']}.json"
        cp_path.write_text(json.dumps(checkpoint, indent=2, sort_keys=True))

        for idx, rid in enumerate(window["record_ids"]):
            record = record_by_id[rid]
            proof_payload = {
                "action_record_id": rid,
                "action_record_canonical": record_canonicals[rid],
                "leaf_hash": record_hashes[rid],
                "merkle_path": _merkle_proof_path(levels, idx),
                "merkle_root": root,
                "checkpoint_id": checkpoint["id"],
                "checkpoint_signed_at": checkpoint["signed_at"],
                "kms_key_id": KMS_KEY_ID,
                "kms_signature": checkpoint["signature"],
                "kms_algorithm": "hmac-sha256",
                "kms_public_key_pem": None,
                "tenant_id": CUSTOMER_TENANT_ID,
                "agent_name": record["agent_name"],
                "action_name": record["action_name"],
                "result": record["result"],
                "created_at": record["created_at"],
            }
            (work / "records" / f"{rid}.json").write_text(
                json.dumps(proof_payload, indent=2, sort_keys=True)
            )
            written_records += 1

        checkpoint_summaries.append(
            {
                "id": checkpoint["id"],
                "date": checkpoint["date"],
                "record_count": checkpoint["record_count"],
                "merkle_root": root,
            }
        )

    # KMS key history — algorithm + (for asymmetric) public_key_pem per
    # key_id ever used in this bundle. HMAC orgs have public_key_pem null
    # and an auditor needs the secret out-of-band.
    kms_keys = [
        {
            "key_id": KMS_KEY_ID,
            "algorithm": "hmac-sha256",
            "public_key_pem": None,
            "first_seen_at": "2026-04-01T00:00:00+00:00",
            "retired_at": None,
        }
    ]
    (work / "kms_keys.json").write_text(json.dumps(kms_keys, indent=2, sort_keys=True))

    manifest = {
        "schema_version": 1,
        "tenant_id": CUSTOMER_TENANT_ID,
        "org_id": org_id,
        "since": "2026-03-01",
        "until": "2026-03-02",
        "generated_at": BUNDLE_GENERATED_AT,
        "record_count": written_records,
        "checkpoints": checkpoint_summaries,
        "kms_algorithm": "hmac-sha256",
        "hmac_secret_required": True,
        "notes": (
            "HMAC-signed bundle. The verifier needs VERA_HMAC_SECRET set "
            "out-of-band to validate the checkpoint signatures. For "
            "asymmetric KMS, the bundle is fully self-contained."
        ),
    }
    (work / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True))

    if out_path.exists():
        out_path.unlink()
    with tarfile.open(out_path, "w:gz") as tar:
        for entry in sorted(work.rglob("*")):
            tar.add(entry, arcname=entry.relative_to(work))

    shutil.rmtree(work)
    return out_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build a small evidence bundle for the offline-verify walkthrough.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("bundle.tar.gz"),
        help="Output path for the tar.gz bundle (default: ./bundle.tar.gz).",
    )
    args = parser.parse_args(argv)
    bundle_path = build_bundle(args.out.resolve())
    print(f"wrote bundle: {bundle_path}")
    print(f"  records:     {len(RECORDS)}")
    print(f"  checkpoints: {len(CHECKPOINT_WINDOWS)}")
    print(f"  kms_key_id:  {KMS_KEY_ID}")
    print("  hmac_secret: set out-of-band — see verify_bundle.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
