"""Integration tests for ``vera verify --merkle-proof`` + ``vera evidence-export``
(Wave 3C.2).

Uses ``httpx.MockTransport`` rather than spinning up a real backend —
we're testing the SDK's wire-shape contract (URL paths, header
threading, exit-code mapping, bundle layout, determinism). The
backend's contract is exercised by the backend test suite.

For the end-to-end "vera evidence-export → vera verify --offline" loop,
see ``tests/test_evidence_export_offline_roundtrip.py`` — that one is
gated on Wave 3C.1 landing ``--offline``.
"""

from __future__ import annotations

import gzip
import hashlib
import hmac
import io
import json
import os
import tarfile
import uuid
from pathlib import Path
from typing import Any


def _new_uuid() -> str:
    """Generate a uuid4 string for use as an ActionRecord id in tests.

    The evidence-export CLI rejects record ids that don't match the
    canonical UUID regex (Wave 3C.2 path-traversal hardening — see
    ``vera._cli_verify._require_safe_record_id``). Tests that exercise
    the export flow MUST use uuid-shaped record ids; ad-hoc string IDs
    like ``"rec_001"`` are no longer accepted.
    """
    return str(uuid.uuid4())

import httpx
import pytest
from click.testing import CliRunner

from vera.cli import cli
from vera._cli_verify import verify_merkle_proof_for_record
from vera.verify.proof_payload import ALGO_HMAC_SHA256, build_checkpoint_message


# ── Helpers ─────────────────────────────────────────────────────────────

# Capture the real ``httpx.Client`` reference at import time so the test
# helpers can re-instantiate it after ``monkeypatch.setattr(cv.httpx,
# "Client", ...)`` has been applied to the module-attribute lookup chain.
# Without this, the patched ``httpx.Client`` symbol would recursively
# call our fake-client lambda.
_REAL_HTTPX_CLIENT = httpx.Client


def _install_transport(
    monkeypatch: pytest.MonkeyPatch, handler
) -> None:
    """Patch ``vera._cli_verify.httpx.Client`` to dispatch via ``handler``."""
    import vera._cli_verify as cv

    transport = httpx.MockTransport(handler)

    def fake_client(*args: Any, **kwargs: Any) -> httpx.Client:
        kwargs.pop("transport", None)
        return _REAL_HTTPX_CLIENT(transport=transport, **kwargs)

    monkeypatch.setattr(cv.httpx, "Client", fake_client)


def _sha256(left: str, right: str) -> str:
    return hashlib.sha256((left + right).encode("utf-8")).hexdigest()


def _build_proof_payload(
    *,
    record_id: str = "rec_001",
    org_id: str = "org_abc",
    sequence: int = 42,
    secret: bytes = b"shared-hmac-secret",
    signed_at: str = "2026-05-25T14:30:00",
) -> dict:
    """Produce a happy-path proof payload signed with HMAC."""
    leaves = ["a" * 64, "b" * 64, "c" * 64, "d" * 64]
    # Power-of-2 leaves so padding doesn't kick in.
    level0 = leaves
    level1 = [_sha256(level0[0], level0[1]), _sha256(level0[2], level0[3])]
    root = _sha256(level1[0], level1[1])
    leaf_index = 1
    # Path for leaf_index 1: sibling at idx 0 (left), then sibling at idx 1 (right).
    path = [
        {"sibling_hash": level0[0], "direction": "left"},
        {"sibling_hash": level1[1], "direction": "right"},
    ]
    hash_at_cp = "f" * 64
    message = build_checkpoint_message(
        org_id=org_id,
        sequence=sequence,
        hash_at_checkpoint=hash_at_cp,
        signed_at=signed_at,
    )
    sig = hmac.new(secret, message, hashlib.sha256).hexdigest()
    return {
        "action_record_id": record_id,
        "action_record_canonical": "{}",
        "leaf_hash": leaves[leaf_index],
        "merkle_path": path,
        "merkle_root": root,
        "checkpoint_id": "cp_001",
        "checkpoint_signed_at": signed_at,
        "checkpoint_org_id": org_id,
        "checkpoint_sequence": sequence,
        "checkpoint_hash_at_checkpoint": hash_at_cp,
        # Phase 3 follow-up: ``previous_hash`` is part of the proof
        # payload so an offline verifier can enforce
        # ``sha256(previous_hash + canonical) == leaf_hash``. The mock
        # proof here uses an empty-string previous_hash (first record
        # in a chain); real proofs return the predecessor's leaf hash.
        "previous_hash": "",
        "kms_key_id": "key-fingerprint",
        "kms_signature": sig,
        "kms_algorithm": ALGO_HMAC_SHA256,
        "kms_public_key_pem": None,
    }


def _build_checkpoint_body(
    *,
    date_iso: str,
    org_id: str = "org_abc",
    sequence: int = 42,
    prior_sequence: int = 0,
    record_count: int = 4,
    merkle_root: str = "deadbeef" * 8,
) -> dict:
    return {
        "checkpoint_id": f"cp_{date_iso}",
        "org_id": org_id,
        "merkle_root": merkle_root,
        "kms_key_id": "key-fingerprint",
        "signature": "00" * 32,
        "signed_at": f"{date_iso}T00:00:00.000",
        "head_action_id": "rec_004",
        "record_count": record_count,
        "prior_checkpoint_id": None,
        "sequence_at_checkpoint": sequence,
        "hash_at_checkpoint": "f" * 64,
        # Wave 3C.2 reads this if present; the byte-stable response
        # from the existing endpoint doesn't yet, so we leave it out
        # — the SDK falls back to its running prior_sequence.
    }


def _build_actions_body(record_ids: list[str], start_seq: int = 1) -> dict:
    """``GET /v1/actions`` response shape (records list)."""
    return {
        "records": [
            {"id": rid, "sequence_number": start_seq + idx}
            for idx, rid in enumerate(record_ids)
        ]
    }


# ── ``vera verify --merkle-proof`` via CliRunner + MockTransport ────────


def _make_runner_env() -> dict[str, str]:
    return {
        "VERA_API_KEY": "al_test_" + "x" * 32,
        "VERA_API_URL": "https://api.test.vera",
    }


def test_verify_merkle_proof_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub the httpx call inside ``verify_merkle_proof_for_record``.

    We patch ``httpx.Client`` to a MockTransport-backed instance so the
    full code path including error mapping runs without hitting the
    wire.
    """
    payload = _build_proof_payload()
    secret = b"shared-hmac-secret"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/records/rec_001/merkle-proof"
        assert request.headers["Authorization"].startswith("Bearer ")
        return httpx.Response(200, json=payload)

    _install_transport(monkeypatch, handler)
    monkeypatch.setenv("HMAC_SECRET", secret.decode("utf-8"))
    exit_code, message = verify_merkle_proof_for_record(
        "rec_001",
        api_url="https://api.test.vera",
        headers={"Authorization": "Bearer al_test_x"},
        hmac_secret=secret,
    )
    assert exit_code == 0, message
    assert "OK Record rec_001 verified" in message
    assert "Merkle root" in message
    assert "KMS key" in message


def test_verify_merkle_proof_tampered_leaf_returns_exit_1(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _build_proof_payload()
    payload["leaf_hash"] = "0" + payload["leaf_hash"][1:]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    _install_transport(monkeypatch, handler)
    exit_code, message = verify_merkle_proof_for_record(
        "rec_001",
        api_url="https://api.test.vera",
        headers={"Authorization": "Bearer al_test_x"},
        hmac_secret=b"shared-hmac-secret",
    )
    assert exit_code == 1
    assert "Merkle path verification failed" in message
    assert "merkle_path_mismatch" in message


def test_verify_merkle_proof_tampered_sibling_returns_exit_1(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _build_proof_payload()
    payload["merkle_path"][0]["sibling_hash"] = (
        "0" + payload["merkle_path"][0]["sibling_hash"][1:]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    _install_transport(monkeypatch, handler)
    exit_code, _ = verify_merkle_proof_for_record(
        "rec_001",
        api_url="https://api.test.vera",
        headers={"Authorization": "Bearer al_test_x"},
        hmac_secret=b"shared-hmac-secret",
    )
    assert exit_code == 1


def test_verify_merkle_proof_wrong_root_returns_exit_1(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _build_proof_payload()
    payload["merkle_root"] = "9" * 64

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    _install_transport(monkeypatch, handler)
    exit_code, _ = verify_merkle_proof_for_record(
        "rec_001",
        api_url="https://api.test.vera",
        headers={"Authorization": "Bearer al_test_x"},
        hmac_secret=b"shared-hmac-secret",
    )
    assert exit_code == 1


def test_verify_merkle_proof_bad_signature_returns_exit_1(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _build_proof_payload()
    payload["kms_signature"] = "00" * 32  # Merkle path intact; sig flipped.

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    _install_transport(monkeypatch, handler)
    exit_code, message = verify_merkle_proof_for_record(
        "rec_001",
        api_url="https://api.test.vera",
        headers={"Authorization": "Bearer al_test_x"},
        hmac_secret=b"shared-hmac-secret",
    )
    assert exit_code == 1
    assert "signature_invalid" in message


def test_verify_merkle_proof_hmac_no_secret_is_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Per brief: HMAC + no shared secret → exit 0 with warning line."""
    payload = _build_proof_payload()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    _install_transport(monkeypatch, handler)
    exit_code, message = verify_merkle_proof_for_record(
        "rec_001",
        api_url="https://api.test.vera",
        headers={"Authorization": "Bearer al_test_x"},
        hmac_secret=None,
    )
    assert exit_code == 0
    assert "unverified (no HMAC secret)" in message


def test_verify_merkle_proof_404_returns_exit_1(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            404, json={"code": "record_not_found", "detail": "nope"}
        )

    _install_transport(monkeypatch, handler)
    exit_code, message = verify_merkle_proof_for_record(
        "rec_001",
        api_url="https://api.test.vera",
        headers={"Authorization": "Bearer al_test_x"},
    )
    assert exit_code == 1
    assert "not found" in message


def test_verify_merkle_proof_409_returns_exit_1_tail_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(409, json={"code": "checkpoint_pending"})

    _install_transport(monkeypatch, handler)
    exit_code, message = verify_merkle_proof_for_record(
        "rec_001",
        api_url="https://api.test.vera",
        headers={"Authorization": "Bearer al_test_x"},
    )
    assert exit_code == 1
    assert "tail window" in message


def test_verify_merkle_proof_auth_failure_returns_exit_2(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="unauthorized")

    _install_transport(monkeypatch, handler)
    exit_code, _ = verify_merkle_proof_for_record(
        "rec_001",
        api_url="https://api.test.vera",
        headers={"Authorization": "Bearer al_test_x"},
    )
    assert exit_code == 2


# ── CLI surface via CliRunner ───────────────────────────────────────────


def test_cli_verify_no_flags_attempts_online_chain_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Post-3C.1/3C.2 merge: ``vera verify`` with no flags is no longer
    a usage error — it routes through ``_run_online_verify`` (3C.1's
    legacy chain-reachability check). In a test env with no Vera API
    reachable, that exits 1 (network failure), NOT 2 (usage).

    The test asserts the merged behavior so future changes that
    accidentally restore the "requires a flag" gate are caught.
    """
    for k, v in _make_runner_env().items():
        monkeypatch.setenv(k, v)
    runner = CliRunner()
    result = runner.invoke(cli, ["verify"])
    # Exit 1 = chain-check failed (no network in tests); exit 2 would
    # mean we regressed to the pre-merge usage-error gate.
    assert result.exit_code != 2, (
        f"Expected online chain check (exit 1 on no network); got "
        f"exit 2 (usage error). Output: {result.output!r}"
    )


def test_cli_verify_calls_endpoint_and_exits_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _build_proof_payload()
    secret = b"shared-hmac-secret"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    _install_transport(monkeypatch, handler)
    for k, v in _make_runner_env().items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("MY_HMAC", secret.decode("utf-8"))

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "verify",
            "--merkle-proof",
            "rec_001",
            "--hmac-secret-env",
            "MY_HMAC",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "OK Record rec_001" in result.output


# ── ``vera evidence-export`` ────────────────────────────────────────────


def _make_export_handler(
    checkpoint_dates: list[str],
    org_record_map: dict[str, list[tuple[str, int]]],
    proofs: dict[str, dict],
    *,
    customer_filter: str = None,
):
    """Build a MockTransport handler for an evidence-export run.

    ``checkpoint_dates`` is the ordered list of YYYY-MM-DD dates with
    a checkpoint sealed. ``org_record_map`` maps each date to the list
    of ``(record_id, sequence_number)`` rows in that checkpoint's
    window. ``proofs`` maps record_id → proof payload.
    """
    seq_for_date: dict[str, int] = {}
    for date_iso in checkpoint_dates:
        max_seq = max(s for _, s in org_record_map.get(date_iso, [])) if org_record_map.get(date_iso) else 0
        seq_for_date[date_iso] = max_seq

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.startswith("/v1/checkpoints/"):
            date_iso = path.split("/")[-1]
            if date_iso not in checkpoint_dates:
                return httpx.Response(
                    404, json={"code": "checkpoint_not_found"}
                )
            body = _build_checkpoint_body(
                date_iso=date_iso,
                sequence=seq_for_date[date_iso],
                record_count=len(org_record_map.get(date_iso, [])),
            )
            return httpx.Response(200, json=body)
        if path == "/v1/actions":
            tenant_filter = request.url.params.get("tenant_id")
            offset = int(request.url.params.get("offset", "0"))
            limit = int(request.url.params.get("limit", "200"))
            # Flatten all known records, then return ``DESC`` paginated
            # — matching the real route's ordering contract
            # (backend/app/routes/actions.py::list_actions).
            records: list[dict] = []
            for date_iso, lst in org_record_map.items():
                for rid, seq in lst:
                    proof = proofs.get(rid, {})
                    rec_tenant = proof.get("tenant_id")
                    if tenant_filter and rec_tenant != tenant_filter:
                        continue
                    records.append(
                        {
                            "id": rid,
                            "sequence_number": seq,
                            "tenant_id": rec_tenant,
                        }
                    )
            records.sort(
                key=lambda r: r["sequence_number"], reverse=True
            )
            page = records[offset : offset + limit]
            return httpx.Response(200, json={"records": page})
        if path.startswith("/v1/records/") and path.endswith(
            "/merkle-proof"
        ):
            rid = path.split("/")[3]
            if rid not in proofs:
                return httpx.Response(404, json={"code": "record_not_found"})
            return httpx.Response(200, json=proofs[rid])
        return httpx.Response(404, text=f"unknown path {path}")

    return handler


def test_evidence_export_directory_layout(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Happy path: export two days, get manifest + 2 checkpoints + N records."""
    date_a = "2026-05-20"
    date_b = "2026-05-21"
    rid_1 = _new_uuid()
    rid_2 = _new_uuid()
    p1 = _build_proof_payload(record_id=rid_1, sequence=2)
    p1["tenant_id"] = "cleveland_clinic"
    p2 = _build_proof_payload(record_id=rid_2, sequence=5)
    p2["tenant_id"] = "cleveland_clinic"
    org_records = {
        date_a: [(rid_1, 2)],
        date_b: [(rid_2, 5)],
    }
    handler = _make_export_handler(
        [date_a, date_b],
        org_records,
        {rid_1: p1, rid_2: p2},
    )
    _install_transport(monkeypatch, handler)
    for k, v in _make_runner_env().items():
        monkeypatch.setenv(k, v)

    out = tmp_path / "bundle"
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "evidence-export",
            "--since",
            date_a,
            "--until",
            date_b,
            "--out",
            str(out),
        ],
    )
    assert result.exit_code == 0, result.output

    # Verify the layout.
    assert (out / "manifest.json").exists()
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["checkpoint_count"] == 2
    assert manifest["record_count"] == 2
    assert (out / f"checkpoints/{date_a}.json").exists()
    assert (out / f"checkpoints/{date_b}.json").exists()
    assert (out / f"records/{rid_1}.json").exists()
    assert (out / f"records/{rid_2}.json").exists()

    # Phase 3 follow-up: every records/<id>.json must carry
    # ``previous_hash`` so the offline verifier can enforce the chain
    # rule ``sha256(previous_hash + canonical) == leaf_hash`` rather
    # than soft-failing with ``previous_hash_unavailable``.
    for record_file in (out / "records").iterdir():
        rec = json.loads(record_file.read_text())
        assert "previous_hash" in rec, (
            f"{record_file.name} is missing previous_hash — "
            "offline verifier cannot enforce the chain rule"
        )


def test_evidence_export_selective_disclosure_excludes_other_customer(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``--customer cleveland_clinic`` excludes other tenants' records.

    Building on the brief: the verifier with only this export must NOT
    be able to identify or count other customers' records. Their
    sibling hashes appear in Merkle paths (necessary for proof folding)
    but are bare SHA-256 hex — no PHI, no identity.
    """
    date_iso = "2026-05-20"
    # Two records: one for Cleveland Clinic, one for Memorial.
    rid_cc = _new_uuid()
    rid_mem = _new_uuid()
    cc_proof = _build_proof_payload(record_id=rid_cc, sequence=2)
    cc_proof["tenant_id"] = "cleveland_clinic"
    memorial_proof = _build_proof_payload(record_id=rid_mem, sequence=3)
    memorial_proof["tenant_id"] = "memorial"
    org_records = {
        date_iso: [(rid_cc, 2), (rid_mem, 3)],
    }
    handler = _make_export_handler(
        [date_iso],
        org_records,
        {rid_cc: cc_proof, rid_mem: memorial_proof},
    )
    _install_transport(monkeypatch, handler)
    for k, v in _make_runner_env().items():
        monkeypatch.setenv(k, v)

    out = tmp_path / "bundle"
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "evidence-export",
            "--customer",
            "cleveland_clinic",
            "--since",
            date_iso,
            "--until",
            date_iso,
            "--out",
            str(out),
        ],
    )
    assert result.exit_code == 0, result.output

    # Cleveland Clinic's record is present.
    assert (out / f"records/{rid_cc}.json").exists()
    # Memorial's record is NOT present.
    assert not (out / f"records/{rid_mem}.json").exists()

    # The bundle should not contain the foreign record id anywhere —
    # including in any sibling hashes (those are SHA-256 digests, not
    # record IDs, so this is automatic — we assert anyway to lock the
    # contract).
    for path in (out / "records").iterdir():
        text = path.read_text()
        assert rid_mem not in text

    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["customer_id"] == "cleveland_clinic"
    assert manifest["record_count"] == 1


def test_evidence_export_tarball_is_deterministic(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Two consecutive runs with the same input → byte-identical .tar.gz.

    Auditors will diff archives across exports; the brief explicitly
    requires byte-stability.
    """
    date_iso = "2026-05-20"
    rid_1 = _new_uuid()
    p1 = _build_proof_payload(record_id=rid_1, sequence=2)
    p1["tenant_id"] = "cleveland_clinic"
    org_records = {date_iso: [(rid_1, 2)]}
    handler = _make_export_handler(
        [date_iso], org_records, {rid_1: p1}
    )
    _install_transport(monkeypatch, handler)
    for k, v in _make_runner_env().items():
        monkeypatch.setenv(k, v)
    # Pin the manifest.exported_at so the comparison is meaningful.
    monkeypatch.setenv(
        "VERA_EVIDENCE_EXPORT_FAKE_NOW", "2026-05-25T00:00:00+00:00"
    )

    out_a = tmp_path / "a.tar.gz"
    out_b = tmp_path / "b.tar.gz"
    runner = CliRunner()
    for out in (out_a, out_b):
        result = runner.invoke(
            cli,
            [
                "evidence-export",
                "--since",
                date_iso,
                "--until",
                date_iso,
                "--out",
                str(out),
            ],
        )
        assert result.exit_code == 0, result.output

    bytes_a = out_a.read_bytes()
    bytes_b = out_b.read_bytes()
    assert bytes_a == bytes_b, (
        f"deterministic tarball broken: {len(bytes_a)} vs {len(bytes_b)} bytes; "
        f"hashes {hashlib.sha256(bytes_a).hexdigest()} vs "
        f"{hashlib.sha256(bytes_b).hexdigest()}"
    )

    # Sanity: the tarball actually contains manifest.json + the proof.
    with gzip.open(out_a, "rb") as gz:
        with tarfile.open(fileobj=io.BytesIO(gz.read()), mode="r") as tf:
            names = tf.getnames()
    assert "manifest.json" in names
    assert f"records/{rid_1}.json" in names
    assert "checkpoints/2026-05-20.json" in names


def test_evidence_export_dir_skips_missing_checkpoint_days(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Days without a sealed checkpoint are skipped silently — no error."""
    date_present = "2026-05-20"
    rid_x = _new_uuid()
    p1 = _build_proof_payload(record_id=rid_x, sequence=2)
    p1["tenant_id"] = "cleveland_clinic"
    org_records = {date_present: [(rid_x, 2)]}
    handler = _make_export_handler(
        [date_present], org_records, {rid_x: p1}
    )
    _install_transport(monkeypatch, handler)
    for k, v in _make_runner_env().items():
        monkeypatch.setenv(k, v)
    out = tmp_path / "bundle"
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "evidence-export",
            "--since",
            "2026-05-18",
            "--until",
            "2026-05-21",
            "--out",
            str(out),
        ],
    )
    assert result.exit_code == 0, result.output
    # Only the present day is in the bundle.
    assert (out / f"checkpoints/{date_present}.json").exists()
    assert not (out / "checkpoints/2026-05-19.json").exists()
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["checkpoint_count"] == 1
    assert manifest["record_count"] == 1


# ── Pagination: walks multiple pages and stops at prior_sequence ────────


def test_evidence_export_multipage_pagination(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """500 records in a single checkpoint window → multiple pages walked.

    The real ``/v1/actions`` route caps ``limit`` at 200 and orders
    ``sequence_number DESC``. Our enumerator MUST walk pages via
    ``offset`` until it sees a record at or below ``prior_sequence``.
    Building 500 records lets us assert at least 3 page-walks happened
    (200 + 200 + 100) without smearing into a slow integration test.
    """
    date_iso = "2026-05-20"
    org_records_full: list[tuple[str, int]] = []
    proofs: dict[str, dict] = {}
    for i in range(1, 501):
        rid = _new_uuid()
        proof = _build_proof_payload(record_id=rid, sequence=i)
        proof["tenant_id"] = "cleveland_clinic"
        org_records_full.append((rid, i))
        proofs[rid] = proof
    handler = _make_export_handler(
        [date_iso],
        {date_iso: org_records_full},
        proofs,
    )
    _install_transport(monkeypatch, handler)
    for k, v in _make_runner_env().items():
        monkeypatch.setenv(k, v)
    out = tmp_path / "bundle"
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "evidence-export",
            "--since",
            date_iso,
            "--until",
            date_iso,
            "--out",
            str(out),
        ],
    )
    assert result.exit_code == 0, result.output
    # All 500 records made it into the bundle — confirms pagination
    # walked the full window.
    record_files = list((out / "records").iterdir())
    assert len(record_files) == 500
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["record_count"] == 500


# ── End-to-end: export → verify proof against export ────────────────────


def test_export_bundle_proofs_verify_independently(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Each per-record proof in the bundle must verify standalone.

    This is the "verifier with only this export" property — the test
    asserts that we can take a record's proof.json from the export,
    feed it into ``verify_proof_payload``, and pass with only the
    HMAC secret (no further round-trip to Vera).
    """
    from vera.verify.proof_payload import verify_proof_payload

    date_iso = "2026-05-20"
    rid_1 = _new_uuid()
    p1 = _build_proof_payload(record_id=rid_1, sequence=2)
    p1["tenant_id"] = "cleveland_clinic"
    org_records = {date_iso: [(rid_1, 2)]}
    handler = _make_export_handler(
        [date_iso], org_records, {rid_1: p1}
    )
    _install_transport(monkeypatch, handler)
    for k, v in _make_runner_env().items():
        monkeypatch.setenv(k, v)
    out = tmp_path / "bundle"
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "evidence-export",
            "--since",
            date_iso,
            "--until",
            date_iso,
            "--out",
            str(out),
        ],
    )
    assert result.exit_code == 0, result.output

    proof = json.loads((out / f"records/{rid_1}.json").read_text())
    res = verify_proof_payload(
        proof, hmac_secret=b"shared-hmac-secret"
    )
    assert res.ok is True, res
    assert res.reason == "ok"


# ── Path-traversal guard on server-supplied filename components ─────────
#
# Threat model: a compromised Vera API (or a misbehaving local proxy)
# returns a record id like ``"../etc/passwd"`` in the ``/v1/actions``
# response. Without the regex guard added in the Phase 3 follow-up, the
# SDK would happily write ``bundle_root/records/../etc/passwd.json`` —
# escaping ``bundle_root``. The threat model is weak (authenticated
# customer-controlled flow + the .json suffix narrows reach), but the
# guard is free.


def test_evidence_export_rejects_traversal_record_id(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Server returning ``id="../etc/passwd"`` → CLI aborts with a clear
    error naming the offending value. Bundle write does NOT proceed.
    """
    date_iso = "2026-05-20"
    bad_id = "../etc/passwd"
    # Build a proof payload keyed by the bad id so the handler's
    # ``/v1/actions`` response surfaces it. The proof body's content
    # doesn't matter — the CLI aborts before fetching it.
    proof = _build_proof_payload(record_id=bad_id, sequence=2)
    proof["tenant_id"] = "cleveland_clinic"
    org_records = {date_iso: [(bad_id, 2)]}
    handler = _make_export_handler(
        [date_iso], org_records, {bad_id: proof}
    )
    _install_transport(monkeypatch, handler)
    for k, v in _make_runner_env().items():
        monkeypatch.setenv(k, v)

    out = tmp_path / "bundle"
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "evidence-export",
            "--since",
            date_iso,
            "--until",
            date_iso,
            "--out",
            str(out),
        ],
    )
    # Non-zero exit + clear error message naming the offending value.
    assert result.exit_code != 0, (
        f"Expected non-zero exit, got {result.exit_code}: {result.output!r}"
    )
    assert "UUID" in result.output
    # The offending value is surfaced via ``repr`` (escape-quoted) for
    # log-injection safety. Match on the substring; the surrounding
    # quotes are an implementation detail.
    assert "../etc/passwd" in result.output
    # And the bundle was NOT written outside bundle_root.
    assert not (tmp_path / "etc").exists()
    assert not (tmp_path.parent / "etc").exists()


def test_evidence_export_rejects_traversal_record_id_truncates_long_value(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A pathological 1KB record id is truncated to 80 chars in the
    error message — avoids log injection via super-long blobs."""
    date_iso = "2026-05-20"
    bad_id = "A" * 1000  # not a uuid; way over the 80-char truncation cap
    proof = _build_proof_payload(record_id=bad_id, sequence=2)
    proof["tenant_id"] = "cleveland_clinic"
    org_records = {date_iso: [(bad_id, 2)]}
    handler = _make_export_handler(
        [date_iso], org_records, {bad_id: proof}
    )
    _install_transport(monkeypatch, handler)
    for k, v in _make_runner_env().items():
        monkeypatch.setenv(k, v)

    out = tmp_path / "bundle"
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "evidence-export",
            "--since",
            date_iso,
            "--until",
            date_iso,
            "--out",
            str(out),
        ],
    )
    assert result.exit_code != 0
    assert "UUID" in result.output
    # Truncated — the full 1000-char blob must NOT appear.
    assert "A" * 1000 not in result.output
    # The ``...`` truncation marker indicates the value was clipped.
    assert "..." in result.output


def test_evidence_export_path_traversal_aborts_before_writing_other_records(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """If ANY record id fails the regex, the export aborts — the bundle
    is suspect, and partial success would silently drop rows in a way
    auditors couldn't see. Assert the export does NOT produce a bundle
    with the (presumably valid) leading records."""
    date_iso = "2026-05-20"
    good_id = _new_uuid()
    bad_id = "../../boom"
    good_proof = _build_proof_payload(record_id=good_id, sequence=1)
    good_proof["tenant_id"] = "cleveland_clinic"
    bad_proof = _build_proof_payload(record_id=bad_id, sequence=2)
    bad_proof["tenant_id"] = "cleveland_clinic"
    # The /v1/actions handler returns records sorted by sequence DESC,
    # so the bad id (seq=2) is processed first — the abort fires before
    # the good record's file is written.
    org_records = {date_iso: [(good_id, 1), (bad_id, 2)]}
    handler = _make_export_handler(
        [date_iso], org_records, {good_id: good_proof, bad_id: bad_proof}
    )
    _install_transport(monkeypatch, handler)
    for k, v in _make_runner_env().items():
        monkeypatch.setenv(k, v)

    out = tmp_path / "bundle"
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "evidence-export",
            "--since",
            date_iso,
            "--until",
            date_iso,
            "--out",
            str(out),
        ],
    )
    assert result.exit_code != 0, result.output
    # Bundle may have been partly created (checkpoint files land before
    # the per-record loop), but the records dir must NOT contain a
    # file for the good id either — the export aborted before producing
    # a "looks-complete" bundle that's actually missing rows.
    if (out / "records").exists():
        assert not (out / f"records/{good_id}.json").exists()


def test_require_safe_record_id_unit() -> None:
    """Unit-level test of the regex guard.

    The CLI surface tests above drive the full export flow; this test
    exercises the guard directly so a future refactor that moves the
    write site doesn't regress the guard's behaviour silently.
    """
    import click as _click
    from vera._cli_verify import _require_safe_record_id

    # Canonical UUID — accepted.
    _require_safe_record_id("ffffffff-ffff-4fff-bfff-ffffffffffff")
    # Real uuid4 — accepted.
    import uuid as _uuid
    _require_safe_record_id(str(_uuid.uuid4()))
    # Mixed case is fine (regex allows ``[0-9a-fA-F-]``).
    _require_safe_record_id("ABCDEFAB-CDEF-4abc-9DEF-ABCDEFABCDEF")

    # Traversal — rejected.
    for bad in [
        "../etc/passwd",
        "..",
        "/absolute",
        "name with spaces",
        "name/with/slashes",
        "name\nwith\nnewlines",
        "name\x00with\x00null",
        "",
        "x" * 50,  # too long
        "short",  # too short
        None,
        42,
        ["nope"],
    ]:
        with pytest.raises(_click.ClickException) as excinfo:
            _require_safe_record_id(bad)  # type: ignore[arg-type]
        assert "UUID" in excinfo.value.message


def test_require_safe_date_unit() -> None:
    """Same as above for the date guard."""
    import click as _click
    from vera._cli_verify import _require_safe_date

    _require_safe_date("2026-05-20")
    _require_safe_date("1999-12-31")

    for bad in [
        "../../bad",
        "2026/05/20",
        "26-05-20",
        "2026-5-20",
        "",
        None,
        "2026-05-20T00:00:00",
        "x" * 1000,
    ]:
        with pytest.raises(_click.ClickException) as excinfo:
            _require_safe_date(bad)  # type: ignore[arg-type]
        assert "YYYY-MM-DD" in excinfo.value.message


def test_truncate_for_error_caps_at_80_chars() -> None:
    """A pathological long value gets capped + escape-quoted via repr."""
    from vera._cli_verify import _truncate_for_error

    short = _truncate_for_error("hi")
    assert "hi" in short
    # repr adds quotes — assert the wrapping.
    assert short.startswith("'") and short.endswith("'")

    long = _truncate_for_error("A" * 1000)
    # ``"A" * 80 + "..."`` then repr → wrapped in quotes. The 1000-char
    # blob must NOT be in the output verbatim.
    assert "A" * 1000 not in long
    assert "..." in long


# ── Skipped-record surfacing (stderr + manifest) ────────────────────────
# Tail-window race: a record exists in the action list (200 from
# /v1/actions) but its individual proof fetch returns 409
# (checkpoint_pending) or 404 (record_not_found between enumeration and
# proof fetch). Phase 3 follow-up: surface these to stderr + manifest
# so the omission is auditable. Record IDs are real uuid4 strings to
# satisfy the path-traversal guard (Wave 3C.2 follow-up).


def _make_export_handler_with_proof_overrides(
    checkpoint_dates: list[str],
    org_record_map: dict[str, list[tuple[str, int]]],
    proofs: dict[str, dict],
    proof_status_overrides: dict[str, int],
):
    """Variant of ``_make_export_handler`` that lets a test force a
    specific HTTP status (409 / 404) for a given record_id's
    merkle-proof endpoint.
    """
    seq_for_date: dict[str, int] = {}
    for date_iso in checkpoint_dates:
        rows = org_record_map.get(date_iso, [])
        seq_for_date[date_iso] = max((s for _, s in rows), default=0)

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.startswith("/v1/checkpoints/"):
            date_iso = path.split("/")[-1]
            if date_iso not in checkpoint_dates:
                return httpx.Response(
                    404, json={"code": "checkpoint_not_found"}
                )
            body = _build_checkpoint_body(
                date_iso=date_iso,
                sequence=seq_for_date[date_iso],
                record_count=len(org_record_map.get(date_iso, [])),
            )
            return httpx.Response(200, json=body)
        if path == "/v1/actions":
            tenant_filter = request.url.params.get("tenant_id")
            offset = int(request.url.params.get("offset", "0"))
            limit = int(request.url.params.get("limit", "200"))
            records: list[dict] = []
            for date_iso, lst in org_record_map.items():
                for rid, seq in lst:
                    proof = proofs.get(rid, {})
                    rec_tenant = proof.get("tenant_id")
                    if tenant_filter and rec_tenant != tenant_filter:
                        continue
                    records.append(
                        {
                            "id": rid,
                            "sequence_number": seq,
                            "tenant_id": rec_tenant,
                        }
                    )
            records.sort(
                key=lambda r: r["sequence_number"], reverse=True
            )
            page = records[offset : offset + limit]
            return httpx.Response(200, json={"records": page})
        if path.startswith("/v1/records/") and path.endswith(
            "/merkle-proof"
        ):
            rid = path.split("/")[3]
            if rid in proof_status_overrides:
                forced = proof_status_overrides[rid]
                code = (
                    "checkpoint_pending"
                    if forced == 409
                    else "record_not_found"
                )
                return httpx.Response(forced, json={"code": code})
            if rid not in proofs:
                return httpx.Response(
                    404, json={"code": "record_not_found"}
                )
            return httpx.Response(200, json=proofs[rid])
        return httpx.Response(404, text=f"unknown path {path}")

    return handler


def test_evidence_export_409_skip_surfaces_in_stderr_and_manifest(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A 409 ``checkpoint_pending`` on one record-proof fetch:

    * Exporter exits 0 (skips are non-fatal — tail-window is routine).
    * ``manifest.json::skipped_records`` contains exactly the skipped
      record's ID + ``reason=checkpoint_pending``.
    * stderr contains ``"1 records skipped"`` + the record ID so an
      operator can't miss it.
    """
    date_iso = "2026-05-20"
    rid_ok_a = _new_uuid()
    rid_ok_b = _new_uuid()
    # rid_tail will return 409 from the merkle-proof endpoint even
    # though it's in the action list — the tail-window race.
    rid_tail = _new_uuid()
    p_ok_a = _build_proof_payload(record_id=rid_ok_a, sequence=2)
    p_ok_a["tenant_id"] = "cleveland_clinic"
    p_ok_b = _build_proof_payload(record_id=rid_ok_b, sequence=3)
    p_ok_b["tenant_id"] = "cleveland_clinic"
    p_tail = _build_proof_payload(record_id=rid_tail, sequence=4)
    p_tail["tenant_id"] = "cleveland_clinic"
    org_records = {
        date_iso: [
            (rid_ok_a, 2),
            (rid_ok_b, 3),
            (rid_tail, 4),
        ],
    }
    handler = _make_export_handler_with_proof_overrides(
        [date_iso],
        org_records,
        {
            rid_ok_a: p_ok_a,
            rid_ok_b: p_ok_b,
            rid_tail: p_tail,
        },
        proof_status_overrides={rid_tail: 409},
    )
    _install_transport(monkeypatch, handler)
    for k, v in _make_runner_env().items():
        monkeypatch.setenv(k, v)

    out = tmp_path / "bundle"
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "evidence-export",
            "--since",
            date_iso,
            "--until",
            date_iso,
            "--out",
            str(out),
        ],
    )
    assert result.exit_code == 0, (result.stdout, result.stderr)

    # Manifest: skipped_records carries exactly the one ID + reason.
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["skipped_records"] == [
        {"id": rid_tail, "reason": "checkpoint_pending"}
    ]
    # record_count counts only the successful fetches.
    assert manifest["record_count"] == 2

    # stderr: structured warning that an operator/CI log can spot.
    assert "1 records skipped" in result.stderr
    assert rid_tail in result.stderr
    assert "checkpoint_pending" in result.stderr

    # The skipped record's proof file is NOT written.
    assert not (out / f"records/{rid_tail}.json").exists()
    # The successful records' proofs ARE written.
    assert (out / f"records/{rid_ok_a}.json").exists()
    assert (out / f"records/{rid_ok_b}.json").exists()


def test_evidence_export_404_skip_surfaces_as_record_not_found(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Same shape as the 409 test, but the forced status is 404 →
    ``reason=record_not_found``. Models the "deleted server-side
    between enumeration and proof fetch" case.
    """
    date_iso = "2026-05-20"
    rid_ok = _new_uuid()
    rid_gone = _new_uuid()
    p_ok = _build_proof_payload(record_id=rid_ok, sequence=2)
    p_ok["tenant_id"] = "cleveland_clinic"
    p_gone = _build_proof_payload(record_id=rid_gone, sequence=3)
    p_gone["tenant_id"] = "cleveland_clinic"
    org_records = {
        date_iso: [(rid_ok, 2), (rid_gone, 3)],
    }
    handler = _make_export_handler_with_proof_overrides(
        [date_iso],
        org_records,
        {rid_ok: p_ok, rid_gone: p_gone},
        proof_status_overrides={rid_gone: 404},
    )
    _install_transport(monkeypatch, handler)
    for k, v in _make_runner_env().items():
        monkeypatch.setenv(k, v)

    out = tmp_path / "bundle"
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "evidence-export",
            "--since",
            date_iso,
            "--until",
            date_iso,
            "--out",
            str(out),
        ],
    )
    assert result.exit_code == 0, (result.stdout, result.stderr)

    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["skipped_records"] == [
        {"id": rid_gone, "reason": "record_not_found"}
    ]
    assert manifest["record_count"] == 1

    assert "1 records skipped" in result.stderr
    assert rid_gone in result.stderr
    assert "record_not_found" in result.stderr


def test_evidence_export_no_skips_emits_empty_array_and_no_warning(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Clean run (every proof fetch returns 200): no stderr warning,
    and ``manifest.json::skipped_records`` is an EMPTY ARRAY (not
    omitted).

    Choosing "always-present empty array" over "omit the field on a
    clean run" so downstream consumers can presence-check without
    branching on key existence — the schema stays stable across
    bundles regardless of whether any records were skipped.
    """
    date_iso = "2026-05-20"
    rid = _new_uuid()
    p1 = _build_proof_payload(record_id=rid, sequence=2)
    p1["tenant_id"] = "cleveland_clinic"
    org_records = {date_iso: [(rid, 2)]}
    handler = _make_export_handler(
        [date_iso], org_records, {rid: p1}
    )
    _install_transport(monkeypatch, handler)
    for k, v in _make_runner_env().items():
        monkeypatch.setenv(k, v)

    out = tmp_path / "bundle"
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "evidence-export",
            "--since",
            date_iso,
            "--until",
            date_iso,
            "--out",
            str(out),
        ],
    )
    assert result.exit_code == 0, (result.stdout, result.stderr)

    manifest = json.loads((out / "manifest.json").read_text())
    assert "skipped_records" in manifest
    assert manifest["skipped_records"] == []

    # No "records skipped" line on stderr when nothing was skipped.
    assert "records skipped" not in result.stderr
    # The success line still prints to stdout.
    assert "Exported 1 records" in result.stdout


def test_evidence_export_skip_list_caps_at_50_in_stderr(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """With > 50 skips, stderr prints the first 50 and an ``(and N more
    — see manifest.json::skipped_records)`` summary line. The manifest
    contains the FULL list — the cap is purely a stderr-readability
    knob, not a data drop.

    The actions endpoint returns ``sequence_number DESC``, so the
    highest-seq record is enumerated first and appears in stderr; the
    lowest-seq record is at position 55 and gets dropped by the 50-cap
    into the "and N more" pointer.
    """
    date_iso = "2026-05-20"
    rows: list[tuple[str, int]] = []
    proofs: dict[str, dict] = {}
    overrides: dict[str, int] = {}
    # Track the highest- and lowest-seq IDs explicitly so the
    # cap-behavior assertions don't depend on guessing UUIDs.
    rid_by_seq: dict[int, str] = {}
    for i in range(1, 56):  # 55 records, all return 409.
        rid = _new_uuid()
        p = _build_proof_payload(record_id=rid, sequence=i)
        p["tenant_id"] = "cleveland_clinic"
        rows.append((rid, i))
        proofs[rid] = p
        overrides[rid] = 409
        rid_by_seq[i] = rid
    org_records = {date_iso: rows}
    handler = _make_export_handler_with_proof_overrides(
        [date_iso], org_records, proofs, proof_status_overrides=overrides
    )
    _install_transport(monkeypatch, handler)
    for k, v in _make_runner_env().items():
        monkeypatch.setenv(k, v)

    out = tmp_path / "bundle"
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "evidence-export",
            "--since",
            date_iso,
            "--until",
            date_iso,
            "--out",
            str(out),
        ],
    )
    assert result.exit_code == 0, (result.stdout, result.stderr)

    # Stderr: opening line, first 50 IDs, "and 5 more" pointer.
    assert "55 records skipped" in result.stderr
    assert "(and 5 more" in result.stderr
    assert "manifest.json::skipped_records" in result.stderr
    # Highest seq (55) is at position 0 → in stderr;
    # lowest seq (1) is at position 54 → dropped by the 50-cap.
    assert rid_by_seq[55] in result.stderr
    assert rid_by_seq[1] not in result.stderr
    # Manifest still carries all 55 entries — the cap is a stderr
    # readability knob, not a data drop.
    manifest = json.loads((out / "manifest.json").read_text())
    assert len(manifest["skipped_records"]) == 55
