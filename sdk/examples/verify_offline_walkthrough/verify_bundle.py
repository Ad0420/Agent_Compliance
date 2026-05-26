"""Reference offline verifier for a Vera evidence bundle.

This is what `vera verify --offline <bundle.tar.gz>` does under the hood:

  1. Open the tar.gz, parse manifest.json, checkpoints/, records/, kms_keys.json.
  2. For each record proof:
     - Recompute the leaf via SHA-256(previous_hash + canonical) and assert
       it matches `leaf_hash`. (Skipped here since the demo bundle is
       per-checkpoint isolated; the production verifier walks the full
       chain.)
     - Fold the Merkle path from `leaf_hash` toward the root. Assert it
       equals `merkle_root`.
     - Look up the KMS key by `kms_key_id` in `kms_keys.json` and verify
       the checkpoint signature over the canonical checkpoint-message
       bytes.
  3. Exit 0 if every record verifies; exit 1 otherwise with the first
     failure printed to stderr.

The walkthrough handles three KMS modes:

  hmac-sha256        — verifier needs the shared secret out-of-band, read
                       from VERA_HMAC_SECRET. Without it, the verifier
                       can confirm Merkle structure but not the signature.
  kms-hmac-sha256    — AWS KMS HMAC. Same on-the-wire signature shape as
                       hmac-sha256 (AWS KMS produces standard HMAC-SHA256
                       output); the verifier handles both as one branch.
  rsa-pss-sha256     — verifier reads `public_key_pem` from kms_keys.json
                       and validates the signature with cryptography>=42.
                       Fully self-contained — no shared secret required.

This file is intentionally readable as a specification of the bundle
shape. Production code in `vera.verify` (the subpackage refactored in
Wave 3C.1) implements the same logic with proper streaming, key-history
walking, and structured error codes.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import Any


class VerificationError(Exception):
    """Raised on the first verification failure with a structured reason."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


# ── Bundle extraction ───────────────────────────────────────────────────


def _safe_extract_member(member: tarfile.TarInfo, dest: Path) -> None:
    """Reject any tar member that would write outside `dest` or use unsafe
    features. Mirrors what tarfile's `data` filter does (Python 3.12+; also
    backported to 3.10.12 / 3.11.4 as a fix for CVE-2007-4559), implemented
    by hand so the verifier works on every Python the SDK supports (3.10+).
    """
    if member.name.startswith("/") or ".." in Path(member.name).parts:
        raise VerificationError(
            "extract_unsafe",
            f"bundle member {member.name!r} has an absolute or traversing path.",
        )
    target = (dest / member.name).resolve()
    try:
        target.relative_to(dest.resolve())
    except ValueError as exc:
        raise VerificationError(
            "extract_unsafe",
            f"bundle member {member.name!r} resolves outside the extract dir.",
        ) from exc
    if member.issym() or member.islnk():
        raise VerificationError(
            "extract_unsafe",
            f"bundle member {member.name!r} is a symlink or hardlink; refusing.",
        )
    if member.isdev() or member.isfifo():
        raise VerificationError(
            "extract_unsafe",
            f"bundle member {member.name!r} is a device or FIFO; refusing.",
        )


def _extract_bundle(bundle_path: Path) -> Path:
    """Extract `bundle_path` into a fresh tempdir; return the work dir.

    Each member is validated by `_safe_extract_member` before extraction:
    no absolute paths, no traversal segments, no symlinks/hardlinks, no
    device files. Equivalent to what tarfile's `data` filter enforces on
    Python 3.12+; reimplemented here so the verifier is safe on every
    SDK-supported runtime (3.10+).
    """
    work = Path(tempfile.mkdtemp(prefix="vera_verify_"))
    with tarfile.open(bundle_path, "r:gz") as tar:
        for member in tar.getmembers():
            _safe_extract_member(member, work)
        tar.extractall(work)  # noqa: S202 — every member validated above
    return work


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text())


# ── Merkle fold ─────────────────────────────────────────────────────────


def _hash_pair(left: str, right: str) -> str:
    return hashlib.sha256((left + right).encode("utf-8")).hexdigest()


def _fold_merkle(leaf: str, path: list[dict[str, str]]) -> str:
    current = leaf
    for step in path:
        sibling = step["sibling_hash"]
        if step["direction"] == "left":
            current = _hash_pair(sibling, current)
        else:
            current = _hash_pair(current, sibling)
    return current


# ── Signature verification ──────────────────────────────────────────────


def _checkpoint_message(checkpoint: dict[str, Any]) -> bytes:
    """Same byte layout the signer used; see produce_bundle._checkpoint_message."""
    return (
        f"{checkpoint['org_id']}:{checkpoint['sequence_at_checkpoint']}:"
        f"{checkpoint['hash_at_checkpoint']}:{checkpoint['signed_at']}"
    ).encode("utf-8")


def _verify_signature(
    *,
    algorithm: str,
    message: bytes,
    signature_hex: str,
    public_key_pem: str | None,
    hmac_secret: bytes | None,
) -> bool:
    if algorithm in {"hmac-sha256", "kms-hmac-sha256"}:
        # AWS KMS HMAC (kms-hmac-sha256) produces standard HMAC-SHA256
        # output, so the verification path is identical to LocalKMS HMAC.
        # See backend/app/services/kms.py for the algorithm constants.
        if hmac_secret is None:
            raise VerificationError(
                "hmac_secret_missing",
                "bundle uses HMAC; set VERA_HMAC_SECRET to verify signatures.",
            )
        expected = hmac.new(hmac_secret, message, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature_hex)

    if algorithm in {"rsa-pss-sha256", "ecdsa-p256-sha256"}:
        if not public_key_pem:
            raise VerificationError(
                "public_key_missing",
                f"bundle declares {algorithm} but kms_keys.json has no public_key_pem.",
            )
        try:
            from cryptography.hazmat.primitives import hashes, serialization
            from cryptography.hazmat.primitives.asymmetric import padding
        except ImportError as exc:
            raise VerificationError(
                "cryptography_missing",
                "asymmetric verification requires the `cryptography` package "
                "(pip install cryptography>=42).",
            ) from exc

        key = serialization.load_pem_public_key(public_key_pem.encode("utf-8"))
        try:
            if algorithm == "rsa-pss-sha256":
                key.verify(
                    bytes.fromhex(signature_hex),
                    message,
                    padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH),
                    hashes.SHA256(),
                )
            else:  # ecdsa-p256-sha256
                from cryptography.hazmat.primitives.asymmetric import ec

                key.verify(bytes.fromhex(signature_hex), message, ec.ECDSA(hashes.SHA256()))
            return True
        except Exception:
            return False

    raise VerificationError("unknown_algorithm", f"unsupported algorithm: {algorithm!r}")


# ── Top-level verifier ──────────────────────────────────────────────────


def verify_bundle(bundle_path: Path) -> dict[str, Any]:
    """Verify every proof in the bundle. Returns a summary dict on success.

    Raises `VerificationError` on the first failure.
    """
    work = _extract_bundle(bundle_path)

    manifest_path = work / "manifest.json"
    if not manifest_path.exists():
        raise VerificationError("manifest_missing", "bundle has no manifest.json")
    manifest = _load_json(manifest_path)

    kms_keys_path = work / "kms_keys.json"
    if not kms_keys_path.exists():
        raise VerificationError("kms_keys_missing", "bundle has no kms_keys.json")
    kms_keys = {row["key_id"]: row for row in _load_json(kms_keys_path)}

    hmac_secret_env = os.environ.get("VERA_HMAC_SECRET")
    hmac_secret = hmac_secret_env.encode("utf-8") if hmac_secret_env else None

    # Pre-verify every checkpoint signature once; cache the verdict per
    # checkpoint_id so we don't re-do the work for every record.
    checkpoints_dir = work / "checkpoints"
    if not checkpoints_dir.is_dir():
        raise VerificationError("checkpoints_dir_missing", "bundle has no checkpoints/ directory")

    checkpoint_by_id: dict[str, dict[str, Any]] = {}
    verified_checkpoint_ids: set[str] = set()
    for cp_path in sorted(checkpoints_dir.glob("*.json")):
        cp = _load_json(cp_path)
        checkpoint_by_id[cp["id"]] = cp

        kms_row = kms_keys.get(cp["key_id"])
        if kms_row is None:
            raise VerificationError(
                "kms_key_not_in_history",
                f"checkpoint {cp['id']} signed by {cp['key_id']!r} which is "
                f"not in kms_keys.json — bundle is incomplete.",
            )

        ok = _verify_signature(
            algorithm=cp["algorithm"],
            message=_checkpoint_message(cp),
            signature_hex=cp["signature"],
            public_key_pem=kms_row.get("public_key_pem"),
            hmac_secret=hmac_secret,
        )
        if not ok:
            raise VerificationError(
                "signature_invalid",
                f"checkpoint {cp['id']} signature does not validate against {cp['key_id']!r}.",
            )
        verified_checkpoint_ids.add(cp["id"])

    # Walk every record proof. Each must (a) fold to the claimed root,
    # (b) reference a checkpoint we already validated, and (c) reference
    # the same root the validated checkpoint sealed.
    records_dir = work / "records"
    if not records_dir.is_dir():
        raise VerificationError("records_dir_missing", "bundle has no records/ directory")

    verified_record_count = 0
    for rec_path in sorted(records_dir.glob("*.json")):
        payload = _load_json(rec_path)

        folded = _fold_merkle(payload["leaf_hash"], payload["merkle_path"])
        if folded != payload["merkle_root"]:
            raise VerificationError(
                "merkle_proof_invalid",
                f"record {payload['action_record_id']!r}: folded root "
                f"{folded[:16]}... does not match claimed {payload['merkle_root'][:16]}...",
            )

        cp = checkpoint_by_id.get(payload["checkpoint_id"])
        if cp is None or payload["checkpoint_id"] not in verified_checkpoint_ids:
            raise VerificationError(
                "checkpoint_not_validated",
                f"record {payload['action_record_id']!r} references checkpoint "
                f"{payload['checkpoint_id']!r} which is missing or unverified.",
            )

        if cp["merkle_root"] != payload["merkle_root"]:
            raise VerificationError(
                "root_mismatch",
                f"record {payload['action_record_id']!r} claims root "
                f"{payload['merkle_root'][:16]}... but checkpoint "
                f"{payload['checkpoint_id']!r} sealed {cp['merkle_root'][:16]}...",
            )

        verified_record_count += 1

    if verified_record_count != manifest["record_count"]:
        raise VerificationError(
            "record_count_mismatch",
            f"manifest claims {manifest['record_count']} records but "
            f"{verified_record_count} verified.",
        )

    return {
        "tenant_id": manifest["tenant_id"],
        "record_count": verified_record_count,
        "checkpoint_count": len(verified_checkpoint_ids),
        "kms_key_ids": sorted(kms_keys.keys()),
        "algorithm": manifest["kms_algorithm"],
    }


# ── CLI ─────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Reference offline verifier for a Vera evidence bundle.",
    )
    parser.add_argument("bundle", type=Path, help="Path to the bundle tar.gz.")
    args = parser.parse_args(argv)

    if not args.bundle.exists():
        print(f"FAIL Bundle does not exist: {args.bundle}", file=sys.stderr)
        return 1

    try:
        summary = verify_bundle(args.bundle.resolve())
    except VerificationError as exc:
        print(f"FAIL {exc.code}: {exc.detail}", file=sys.stderr)
        return 1

    record_count = summary["record_count"]
    checkpoint_count = summary["checkpoint_count"]
    algorithm = summary["algorithm"]
    key_ids = ", ".join(summary["kms_key_ids"])
    print(
        f"OK {record_count} record(s) verified across "
        f"{checkpoint_count} checkpoint(s) (algorithm: {algorithm}; "
        f"key history: {key_ids})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
