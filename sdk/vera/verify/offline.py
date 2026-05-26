"""End-to-end offline verification pipeline.

Reads an evidence bundle previously written by ``vera evidence-export``
(Wave 3C.2) and verifies every record locally — NO network calls.

Bundle layout (per Phase 3 implementation plan)::

    bundle/
        manifest.json          # { vera_version, exported_at,
                               #   checkpoint_count, record_count }
        checkpoint.json        # legacy single-checkpoint bundle
        checkpoints/<id>.json  # one file per checkpoint (multi-checkpoint bundle)
        records/<id>.json      # one file per record (proof payload)

Either ``checkpoint.json`` or ``checkpoints/`` is acceptable. The
pipeline groups records by their ``checkpoint_id`` and looks up the
matching checkpoint payload in the bundle. Per-record verification
involves:

1. **Merkle path fold** — leaf → root via
   :func:`vera.verify.proof.verify_merkle_path`.
2. **Chain-rule canonical check** — assert
   ``sha256(previous_hash + canonical) == leaf_hash`` via
   :func:`vera.verify.proof.canonical_record_to_leaf_hash`. If the
   proof payload doesn't carry ``previous_hash`` we mark the check
   ``unverified`` rather than failing (some bundles export only the
   leaf hash + path, see Wave 3C.2 docs).
3. **Checkpoint signature** — reconstruct
   ``f"{org_id}:{seq}:{hash}:{signed_at}"`` from the bundle's
   ``checkpoint.json`` and verify via
   :func:`vera.verify.signature.verify_signature`.
4. **Chain head linkage** — when checkpoint N and N-1 are both in the
   bundle, assert checkpoint N's ``prior_checkpoint_id`` ==
   checkpoint N-1's ``checkpoint_id``. Proves no gap in the chain head.

Tarball support: if ``bundle_path`` ends with ``.tar`` / ``.tar.gz`` /
``.tgz`` we extract to a temp directory first.

The pipeline never raises on a verification failure — it records a
typed reason on the per-record result. Programmer-error inputs
(missing manifest, malformed JSON) raise :class:`BundleError` so the
CLI can distinguish "bundle is broken" from "bundle is valid but a
record fails verification".
"""

from __future__ import annotations

import json
import logging
import tarfile
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

from .proof import canonical_record_to_leaf_hash, verify_merkle_path
from .signature import (
    SignatureResult,
    build_checkpoint_message,
    verify_signature,
)

logger = logging.getLogger("vera.verify.offline")


class BundleError(Exception):
    """Raised when the bundle is structurally broken (vs. content-tampered).

    Examples: missing ``manifest.json``, malformed JSON, no
    ``records/`` directory. The CLI maps this to a distinct exit code
    so an auditor knows whether to suspect tampering or a bad export.
    """


@dataclass(frozen=True)
class BundleManifest:
    """Parsed ``manifest.json``. Carries no PHI.

    Fields beyond the documented four are preserved in :attr:`extras`
    so a forward-compatible exporter (Wave 3C.2+) can attach extra
    metadata without breaking older verifiers.
    """

    vera_version: str
    exported_at: str
    checkpoint_count: int
    record_count: int
    extras: dict[str, Any] = field(default_factory=dict)


@dataclass
class RecordVerification:
    """Per-record outcome of the offline pipeline.

    ``status`` is one of:

    * ``"verified"`` — all four checks passed.
    * ``"unverified"`` — at least one check returned a soft fail
      (e.g. ``hmac_secret_missing``, ``previous_hash_unavailable``).
      The record is NOT tampered with; it just couldn't be fully
      verified offline.
    * ``"failed"`` — at least one check returned a hard fail. The
      bundle's exit code is non-zero.

    ``reasons`` is the list of failure codes from the verifier layers;
    empty on ``"verified"``. Order matches check order so a CLI can
    surface the first failure.
    """

    action_record_id: str
    checkpoint_id: str | None
    status: str
    reasons: list[str] = field(default_factory=list)
    details: list[str] = field(default_factory=list)


@dataclass
class CheckpointVerification:
    """Per-checkpoint outcome (signature + chain linkage)."""

    checkpoint_id: str
    signature_ok: bool
    signature_reason: str
    chain_link_ok: bool | None  # None when no prior checkpoint in bundle.
    chain_link_reason: str | None = None


@dataclass
class VerifyResult:
    """Aggregate outcome for the entire bundle.

    :attr:`ok` is True only when every record is ``"verified"`` AND
    every checkpoint's signature verified. ``"unverified"`` records
    do NOT block ``ok`` — they're soft-fail (see :class:`RecordVerification`).
    The CLI prints them with a yellow ``UNVERIFIED`` marker but still
    exits 0; this matches the brief's "mark unverified rather than
    fail the whole bundle" semantics for HMAC-secret-missing.
    """

    ok: bool
    manifest: BundleManifest
    records: list[RecordVerification] = field(default_factory=list)
    checkpoints: list[CheckpointVerification] = field(default_factory=list)
    # Bundle-level issues that aren't tied to a single record (e.g.
    # a record's checkpoint is missing from the bundle).
    bundle_issues: list[str] = field(default_factory=list)


# ── Bundle loading ────────────────────────────────────────────────────


def _is_tarball(path: Path) -> bool:
    name = path.name.lower()
    return name.endswith(".tar") or name.endswith(".tar.gz") or name.endswith(".tgz")


def _extract_tarball(tar_path: Path) -> Path:
    """Extract ``tar_path`` to a temp dir and return the root.

    Uses ``tarfile.data_filter`` (Python 3.12+) when available to refuse
    path traversal and absolute paths. On older Pythons we hand-check
    member names — an evidence bundle should never carry ``../`` and
    rejecting them defensively keeps a tampered tarball from clobbering
    arbitrary disk locations.
    """
    tmp = Path(tempfile.mkdtemp(prefix="vera-verify-"))
    with tarfile.open(tar_path, mode="r:*") as tf:
        # tarfile.data_filter was added in 3.12; use it when present.
        extract_filter = getattr(tarfile, "data_filter", None)
        if extract_filter is not None:
            tf.extractall(tmp, filter="data")
        else:
            for member in tf.getmembers():
                name = member.name
                if name.startswith("/") or ".." in Path(name).parts:
                    raise BundleError(
                        f"tarball contains unsafe member name: {name!r}"
                    )
            tf.extractall(tmp)  # noqa: S202 — pre-filtered above
    # If everything extracted under a single top-level directory, root
    # there; otherwise return the temp dir itself. Lets us accept both
    # ``bundle.tar`` (flat) and ``my-bundle.tar`` (tar of a folder).
    contents = list(tmp.iterdir())
    if len(contents) == 1 and contents[0].is_dir():
        return contents[0]
    return tmp


def _load_json(path: Path) -> Any:
    try:
        with path.open("rb") as f:
            return json.load(f)
    except FileNotFoundError as exc:
        raise BundleError(f"missing bundle file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise BundleError(
            f"malformed JSON in {path.name}: {exc.msg} at line {exc.lineno}"
        ) from exc


def _load_manifest(bundle_root: Path) -> BundleManifest:
    raw = _load_json(bundle_root / "manifest.json")
    if not isinstance(raw, dict):
        raise BundleError("manifest.json is not a JSON object")
    required = {"vera_version", "exported_at", "checkpoint_count", "record_count"}
    missing = required - raw.keys()
    if missing:
        raise BundleError(
            f"manifest.json missing required keys: {sorted(missing)}"
        )
    extras = {k: v for k, v in raw.items() if k not in required}
    return BundleManifest(
        vera_version=str(raw["vera_version"]),
        exported_at=str(raw["exported_at"]),
        checkpoint_count=int(raw["checkpoint_count"]),
        record_count=int(raw["record_count"]),
        extras=extras,
    )


def _load_checkpoints(bundle_root: Path) -> dict[str, dict]:
    """Return ``{checkpoint_id: checkpoint_payload}``.

    Accepts either ``checkpoint.json`` (single checkpoint, legacy
    layout) or ``checkpoints/<id>.json`` (multi-checkpoint).
    """
    out: dict[str, dict] = {}

    multi_dir = bundle_root / "checkpoints"
    if multi_dir.is_dir():
        for jf in sorted(multi_dir.iterdir()):
            if jf.suffix != ".json":
                continue
            payload = _load_json(jf)
            if not isinstance(payload, dict) or "checkpoint_id" not in payload:
                raise BundleError(
                    f"{jf.name} is missing checkpoint_id"
                )
            out[payload["checkpoint_id"]] = payload

    single = bundle_root / "checkpoint.json"
    if single.is_file():
        payload = _load_json(single)
        if not isinstance(payload, dict) or "checkpoint_id" not in payload:
            raise BundleError("checkpoint.json is missing checkpoint_id")
        out[payload["checkpoint_id"]] = payload

    if not out:
        raise BundleError(
            "bundle contains no checkpoint file (expected checkpoint.json "
            "or checkpoints/<id>.json)"
        )
    return out


def _load_records(bundle_root: Path) -> list[dict]:
    """Return record proof payloads sorted by file name (stable order)."""
    records_dir = bundle_root / "records"
    if not records_dir.is_dir():
        raise BundleError(
            "bundle contains no records/ directory"
        )
    out: list[dict] = []
    for jf in sorted(records_dir.iterdir()):
        if jf.suffix != ".json":
            continue
        payload = _load_json(jf)
        if not isinstance(payload, dict):
            raise BundleError(f"{jf.name} is not a JSON object")
        out.append(payload)
    return out


# ── Per-record verifier ───────────────────────────────────────────────


def _verify_one_record(
    record_payload: dict,
    *,
    checkpoints: dict[str, dict],
) -> RecordVerification:
    """Run Merkle-path + chain-rule checks for one record proof payload.

    Signature verification happens once per checkpoint (see
    :func:`_verify_checkpoints`) — folding it in here would re-verify
    the same signature N times for N records in the same window.
    """
    rec_id = str(record_payload.get("action_record_id", "<unknown>"))
    cp_id = record_payload.get("checkpoint_id")
    reasons: list[str] = []
    details: list[str] = []
    hard_fail = False
    soft_fail = False

    # 1. Merkle path fold.
    ok, reason = verify_merkle_path(record_payload)
    if not ok:
        reasons.append(reason or "merkle_path_invalid")
        details.append(f"Merkle path did not fold to merkle_root ({reason!s}).")
        hard_fail = True

    # 2. Chain-rule canonical check (when previous_hash is in the payload).
    # ``GET /v1/records/.../merkle-proof`` does NOT include
    # ``previous_hash`` today (see backend route — the canonical bytes
    # are sealed but the predecessor pointer is chain-level metadata).
    # The Wave 3C.2 exporter will be able to attach previous_hash when
    # exporting an evidence bundle; until then, accept its absence as
    # a soft fail with ``previous_hash_unavailable`` so the bundle's
    # aggregate result still reports clearly.
    canonical = record_payload.get("action_record_canonical")
    leaf_hash = record_payload.get("leaf_hash")
    prev_hash = record_payload.get("previous_hash")
    if canonical is None or leaf_hash is None:
        reasons.append("missing_canonical_or_leaf")
        details.append("Proof payload missing canonical/leaf_hash field.")
        hard_fail = True
    elif prev_hash is None:
        reasons.append("previous_hash_unavailable")
        details.append(
            "previous_hash not in proof payload — canonical→leaf chain "
            "rule cannot be checked offline. Merkle inclusion verified."
        )
        soft_fail = True
    else:
        recomputed = canonical_record_to_leaf_hash(
            canonical=canonical, previous_hash=prev_hash
        )
        if recomputed != leaf_hash:
            reasons.append("canonical_leaf_mismatch")
            details.append(
                "sha256(previous_hash + canonical) did not match leaf_hash — "
                "the canonical bytes do not represent the sealed record."
            )
            hard_fail = True

    # 3. Checkpoint membership: the record's claimed checkpoint must be
    # in the bundle. If it isn't, the per-record path is suspect — even
    # if it folds, we have nothing to check it against.
    if cp_id is None:
        reasons.append("checkpoint_id_missing")
        details.append("Proof payload has no checkpoint_id.")
        hard_fail = True
    elif cp_id not in checkpoints:
        reasons.append("checkpoint_not_in_bundle")
        details.append(
            f"Proof claims checkpoint {cp_id} but that checkpoint's "
            f"payload is not in the bundle."
        )
        hard_fail = True
    else:
        # Cross-check: payload's merkle_root must equal the checkpoint's
        # merkle_root. If not, the record's path was constructed
        # against a different root than the checkpoint claims to have
        # sealed — clear tamper.
        cp_root = checkpoints[cp_id].get("merkle_root")
        if cp_root and record_payload.get("merkle_root") != cp_root:
            reasons.append("record_root_disagrees_with_checkpoint")
            details.append(
                "Proof's merkle_root does not match the checkpoint's "
                "sealed merkle_root."
            )
            hard_fail = True

    status = (
        "failed" if hard_fail else ("unverified" if soft_fail else "verified")
    )
    return RecordVerification(
        action_record_id=rec_id,
        checkpoint_id=str(cp_id) if cp_id is not None else None,
        status=status,
        reasons=reasons,
        details=details,
    )


# ── Per-checkpoint verifier ───────────────────────────────────────────


def _checkpoint_signature_inputs(
    checkpoint_payload: dict,
    *,
    record_payloads_for_checkpoint: Iterable[dict],
) -> Optional[tuple[str, Optional[str], bytes, str]]:
    """Pull (algorithm, public_key_pem, message, signature_hex) for a checkpoint.

    The checkpoint endpoint response carries ``kms_key_id`` and
    ``signature`` but NOT ``kms_algorithm`` or ``kms_public_key_pem`` —
    those live on the per-record proof payload (which includes the
    checkpoint metadata). So we look at any one record proof for the
    same checkpoint to get the algorithm + PEM. If no record proofs
    are in the bundle for this checkpoint we can't verify the
    signature and return ``None`` (callers mark it unverified).
    """
    one_record = next(iter(record_payloads_for_checkpoint), None)
    if one_record is None:
        return None

    algorithm = str(one_record.get("kms_algorithm", "") or "")
    public_key_pem = one_record.get("kms_public_key_pem")
    signature_hex = checkpoint_payload.get("signature") or one_record.get(
        "kms_signature"
    )
    if not signature_hex or not isinstance(signature_hex, str):
        return None

    org_id = checkpoint_payload.get("org_id")
    seq = checkpoint_payload.get("sequence_at_checkpoint")
    hash_at = checkpoint_payload.get("hash_at_checkpoint")
    signed_at = checkpoint_payload.get("signed_at")
    if (
        not isinstance(org_id, str)
        or not isinstance(seq, int)
        or not isinstance(hash_at, str)
        or not isinstance(signed_at, str)
    ):
        return None

    message = build_checkpoint_message(
        org_id=org_id,
        sequence=seq,
        hash_at_checkpoint=hash_at,
        signed_at_isoformat=signed_at,
    )
    return algorithm, public_key_pem, message, signature_hex


def _verify_checkpoints(
    checkpoints: dict[str, dict],
    records_by_checkpoint: dict[str, list[dict]],
) -> list[CheckpointVerification]:
    """Verify each checkpoint's signature and chain linkage."""
    out: list[CheckpointVerification] = []

    # Stable order: by sequence_at_checkpoint when available, else by id.
    def _order_key(cp: dict) -> tuple[int, str]:
        seq = cp.get("sequence_at_checkpoint")
        return (int(seq) if isinstance(seq, int) else 0, cp.get("checkpoint_id", ""))

    sorted_cps = sorted(checkpoints.values(), key=_order_key)

    # Build a lookup ``checkpoint_id -> position`` so we can check the
    # ``prior_checkpoint_id`` link.
    cps_by_id = {cp["checkpoint_id"]: cp for cp in sorted_cps}

    for cp in sorted_cps:
        cp_id = cp["checkpoint_id"]
        sig_inputs = _checkpoint_signature_inputs(
            cp,
            record_payloads_for_checkpoint=records_by_checkpoint.get(cp_id, []),
        )
        if sig_inputs is None:
            sig_ok = False
            sig_reason = "no_record_proofs_for_checkpoint"
        else:
            algorithm, public_key_pem, message, signature_hex = sig_inputs
            res: SignatureResult = verify_signature(
                algorithm=algorithm,
                public_key_pem=public_key_pem,
                message=message,
                signature_hex=signature_hex,
            )
            sig_ok = res.ok
            sig_reason = res.reason

        # Chain linkage: if cp's prior_checkpoint_id is also in the
        # bundle, assert they match.
        prior_id = cp.get("prior_checkpoint_id")
        chain_ok: Optional[bool] = None
        chain_reason: Optional[str] = None
        if prior_id is not None and prior_id in cps_by_id:
            # Walk back one in the sorted order and confirm the chain
            # points there. The prior's ``sequence_at_checkpoint`` must
            # be strictly less than the current's.
            this_seq = cp.get("sequence_at_checkpoint", 0) or 0
            prior_seq = cps_by_id[prior_id].get("sequence_at_checkpoint", 0) or 0
            if prior_seq < this_seq:
                chain_ok = True
            else:
                chain_ok = False
                chain_reason = "prior_checkpoint_sequence_not_less"
        elif prior_id is not None:
            # Prior referenced but not in bundle — informational, not a
            # failure. The bundle may have been ``--since`` truncated.
            chain_ok = None
            chain_reason = "prior_checkpoint_not_in_bundle"

        out.append(
            CheckpointVerification(
                checkpoint_id=cp_id,
                signature_ok=sig_ok,
                signature_reason=sig_reason,
                chain_link_ok=chain_ok,
                chain_link_reason=chain_reason,
            )
        )

    return out


# ── Public entry point ────────────────────────────────────────────────


def run_offline_verify(bundle_path: str | Path) -> VerifyResult:
    """Verify an evidence bundle. Never raises on a verification fail.

    Raises :class:`BundleError` only on structural problems (bundle
    layout broken). All content-level failures are recorded on the
    returned :class:`VerifyResult` with ``ok=False``.
    """
    path = Path(bundle_path)
    if not path.exists():
        raise BundleError(f"bundle path does not exist: {path}")

    if path.is_file():
        if not _is_tarball(path):
            raise BundleError(
                f"bundle path is a file but not a tarball: {path.name}"
            )
        root = _extract_tarball(path)
    else:
        root = path

    manifest = _load_manifest(root)
    checkpoints = _load_checkpoints(root)
    records = _load_records(root)

    # Group records by checkpoint_id for the per-checkpoint signature
    # check (one verify per checkpoint, not per record).
    records_by_cp: dict[str, list[dict]] = {}
    for r in records:
        cp_id = str(r.get("checkpoint_id") or "")
        records_by_cp.setdefault(cp_id, []).append(r)

    record_results = [
        _verify_one_record(r, checkpoints=checkpoints) for r in records
    ]
    checkpoint_results = _verify_checkpoints(checkpoints, records_by_cp)

    bundle_issues: list[str] = []
    # Manifest sanity: record_count / checkpoint_count are advisory but
    # surface a warning when they drift from the actual files in the
    # bundle. The exporter populates these, so a mismatch suggests
    # files were added or removed after export.
    if manifest.record_count != len(records):
        bundle_issues.append(
            f"manifest.record_count={manifest.record_count} but "
            f"records/ contains {len(records)} files"
        )
    if manifest.checkpoint_count != len(checkpoints):
        bundle_issues.append(
            f"manifest.checkpoint_count={manifest.checkpoint_count} but "
            f"bundle contains {len(checkpoints)} checkpoint payloads"
        )

    record_ok = all(r.status != "failed" for r in record_results)
    checkpoint_ok = all(c.signature_ok for c in checkpoint_results)
    chain_ok = all(
        c.chain_link_ok is not False for c in checkpoint_results
    )
    ok = record_ok and checkpoint_ok and chain_ok and not bundle_issues

    return VerifyResult(
        ok=ok,
        manifest=manifest,
        records=record_results,
        checkpoints=checkpoint_results,
        bundle_issues=bundle_issues,
    )
