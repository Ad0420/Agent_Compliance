"""End-to-end tests for ``vera verify --offline``.

Synthesizes a complete evidence bundle in pure Python — same Merkle
tree shape the backend builds, same checkpoint message format, real
RSA-PSS signature — then runs the offline pipeline + CLI against it.

Why no backend imports: SDK tests must be importable without the
backend on PYTHONPATH (the SDK ships standalone via ``pip install
vera-sdk``). Mirroring the backend's tree + canonical-bytes rule in
the test helper keeps the contract checkable.

Coverage:

* "``vera verify --offline`` passes with Vera's API firewalled" —
  ``test_offline_verify_succeeds_with_http_client_firewalled``
  monkey-patches the HTTP client to raise on any call and asserts the
  pipeline still exits 0.
* "Offline verify with tampered ActionRecord" —
  ``test_tampered_record_fails_with_nonzero_exit``.
* Bundle structural errors → exit 2 (BundleError path).
"""

from __future__ import annotations

import hashlib
import json
import tarfile
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

from vera.cli import cli
from vera.verify.offline import (
    BundleError,
    run_offline_verify,
)


# ── Bundle synthesis helpers ──────────────────────────────────────────


def _hash_pair(left: str, right: str) -> str:
    return hashlib.sha256((left + right).encode("utf-8")).hexdigest()


def _build_merkle(leaves: list[str]) -> tuple[str, list[list[str]]]:
    """Return ``(root, levels)`` for ``leaves``.

    Mirrors ``backend.app.services.merkle.MerkleTree`` — pad to next
    power-of-two with the last leaf, hash pairs level by level.
    """
    n = len(leaves)
    if n == 0:
        return hashlib.sha256(b"EMPTY_TREE").hexdigest(), [[]]
    next_pow2 = 1 << (n - 1).bit_length() if n > 1 else 1
    padded = list(leaves) + [leaves[-1]] * (next_pow2 - n)
    levels = [padded]
    current = padded
    while len(current) > 1:
        next_level = []
        for i in range(0, len(current), 2):
            next_level.append(_hash_pair(current[i], current[i + 1]))
        levels.append(next_level)
        current = next_level
    return current[0], levels


def _build_path(levels: list[list[str]], leaf_index: int) -> list[dict]:
    proof_hashes: list[str] = []
    proof_directions: list[str] = []
    idx = leaf_index
    for level in levels[:-1]:
        if idx % 2 == 0:
            sibling_idx = idx + 1
            proof_directions.append("right")
        else:
            sibling_idx = idx - 1
            proof_directions.append("left")
        if sibling_idx < len(level):
            proof_hashes.append(level[sibling_idx])
        else:
            proof_hashes.append(level[idx])
        idx //= 2
    return [
        {"sibling_hash": h, "direction": d}
        for h, d in zip(proof_hashes, proof_directions)
    ]


def _canonicalize(record_fields: dict) -> str:
    """Same canonicalization the backend uses (sorted keys, no whitespace,
    None-excluded)."""
    cleaned = {k: v for k, v in record_fields.items() if v is not None}
    return json.dumps(cleaned, sort_keys=True, separators=(",", ":"))


def _generate_rsa_keypair():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = priv.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    return priv, pem


def _sign_rsa_pss(priv, message: bytes) -> str:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding

    sig = priv.sign(
        message,
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.MAX_LENGTH,
        ),
        hashes.SHA256(),
    )
    return sig.hex()


def _build_bundle(
    tmp_path: Path,
    *,
    org_id: str = "org-test",
    n_records: int = 5,
    sequence_at_checkpoint: int = 5,
    signed_at: str = "2026-05-25T12:00:00",
    prior_checkpoint_id: str | None = None,
    nonce: str = "",
) -> dict[str, Any]:
    """Build a synthetic bundle on disk; return metadata for assertions.

    Returns ``{root_dir, record_ids, checkpoint_id, priv, pem,
    record_payloads}`` so tests can tamper or assert.
    """
    pytest.importorskip("cryptography")
    priv, pem = _generate_rsa_keypair()

    # Build chain of N records with realistic canonical bytes + chained
    # previous_hash. Mirrors how ``services.chain._create_record`` would
    # build them: leaf = sha256(previous_hash + canonical).
    record_payloads: list[dict] = []
    leaves: list[str] = []
    canonicals: list[str] = []
    previous_hashes: list[str] = []
    record_ids: list[str] = []

    prev = ""
    seq_offset = sequence_at_checkpoint - n_records  # so last record's
                                                       # seq == sequence_at_checkpoint
    for i in range(n_records):
        rid = f"rec-{nonce}-{i:04d}" if nonce else f"rec-{i:04d}"
        record_ids.append(rid)
        fields = {
            "action_name": f"a_{nonce}_{i}",
            "agent_name": "scribe",
            "result": "success",
            "sequence_number": seq_offset + i + 1,
            "org_id": org_id,
        }
        canonical = _canonicalize(fields)
        leaf = hashlib.sha256((prev + canonical).encode("utf-8")).hexdigest()
        canonicals.append(canonical)
        leaves.append(leaf)
        previous_hashes.append(prev)
        prev = leaf

    root, levels = _build_merkle(leaves)
    checkpoint_id = "cp-" + hashlib.sha256(root.encode()).hexdigest()[:16]
    hash_at_checkpoint = leaves[-1]
    message = (
        f"{org_id}:{sequence_at_checkpoint}:{hash_at_checkpoint}:{signed_at}"
    ).encode("utf-8")
    signature = _sign_rsa_pss(priv, message)

    # Per-record proof payloads (the shape returned by GET
    # /v1/records/<id>/merkle-proof).
    for i, rid in enumerate(record_ids):
        path = _build_path(levels, leaf_index=i)
        record_payloads.append(
            {
                "action_record_id": rid,
                "action_record_canonical": canonicals[i],
                "leaf_hash": leaves[i],
                "previous_hash": previous_hashes[i],  # Wave 3C.2 extension
                "merkle_path": path,
                "merkle_root": root,
                "checkpoint_id": checkpoint_id,
                "checkpoint_signed_at": signed_at,
                "kms_key_id": "key-test",
                "kms_signature": signature,
                "kms_algorithm": "rsa-pss-sha256",
                "kms_public_key_pem": pem,
            }
        )

    checkpoint_payload = {
        "checkpoint_id": checkpoint_id,
        "org_id": org_id,
        "merkle_root": root,
        "kms_key_id": "key-test",
        "signature": signature,
        "signed_at": signed_at,
        "head_action_id": record_ids[-1],
        "record_count": n_records,
        "prior_checkpoint_id": prior_checkpoint_id,
        "sequence_at_checkpoint": sequence_at_checkpoint,
        "hash_at_checkpoint": hash_at_checkpoint,
    }

    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir(parents=True)
    (bundle_dir / "records").mkdir()
    (bundle_dir / "checkpoint.json").write_text(
        json.dumps(checkpoint_payload, sort_keys=True), encoding="utf-8"
    )
    for r in record_payloads:
        (bundle_dir / "records" / f"{r['action_record_id']}.json").write_text(
            json.dumps(r, sort_keys=True), encoding="utf-8"
        )
    (bundle_dir / "manifest.json").write_text(
        json.dumps(
            {
                "vera_version": "1.1.0",
                "exported_at": signed_at,
                "checkpoint_count": 1,
                "record_count": n_records,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    return {
        "root_dir": bundle_dir,
        "record_ids": record_ids,
        "checkpoint_id": checkpoint_id,
        "checkpoint_payload": checkpoint_payload,
        "record_payloads": record_payloads,
        "priv": priv,
        "pem": pem,
    }


# ── Happy path + firewalled-HTTP gate ─────────────────────────────────


def test_offline_verify_happy_path(tmp_path):
    """Bundle with valid Merkle + RSA-PSS signature verifies cleanly."""
    bundle = _build_bundle(tmp_path)
    result = run_offline_verify(bundle["root_dir"])
    assert result.ok, [
        (r.action_record_id, r.status, r.reasons) for r in result.records
    ]
    assert all(r.status == "verified" for r in result.records)
    assert len(result.records) == 5
    assert len(result.checkpoints) == 1
    assert result.checkpoints[0].signature_ok
    assert not result.bundle_issues


def test_offline_verify_succeeds_with_http_client_firewalled(
    tmp_path, monkeypatch
):
    """Phase 3 acceptance gate: HTTP client raises on ANY call → still passes.

    Monkey-patches ``httpx.Client.request`` and ``send`` to raise so any
    accidental network call surfaces as a failure. The offline path
    must not touch the network — this test would fail loudly if
    someone wired ``offline.run_offline_verify`` to call back into the
    online API.
    """
    bundle = _build_bundle(tmp_path)

    import httpx

    def _raise_on_call(*args, **kwargs):
        raise RuntimeError(
            "vera verify --offline made an HTTP call — firewall gate failed!"
        )

    # Cover both sync and async client codepaths just in case.
    monkeypatch.setattr(httpx.Client, "request", _raise_on_call)
    monkeypatch.setattr(httpx.Client, "send", _raise_on_call)
    monkeypatch.setattr(httpx.AsyncClient, "request", _raise_on_call)
    monkeypatch.setattr(httpx.AsyncClient, "send", _raise_on_call)

    # Library entry point.
    result = run_offline_verify(bundle["root_dir"])
    assert result.ok

    # CLI entry point — exit 0 even with the firewall in place.
    runner = CliRunner()
    cli_result = runner.invoke(
        cli, ["verify", "--offline", str(bundle["root_dir"])]
    )
    assert cli_result.exit_code == 0, cli_result.output
    assert "OK" in cli_result.output
    assert "FAIL" not in cli_result.output.replace("--offline", "")


# ── Tamper tests (exit non-zero) ──────────────────────────────────────


def test_tampered_record_fails_with_nonzero_exit(tmp_path):
    """Flip a byte in one record's canonical → exit 1.

    Matches the test-plan row "Offline verify with tampered
    ActionRecord". The chain rule
    ``sha256(previous_hash + canonical) == leaf_hash`` breaks
    immediately on canonical tampering.
    """
    bundle = _build_bundle(tmp_path)
    # Tamper: rewrite one record's canonical bytes.
    target = bundle["root_dir"] / "records" / f"{bundle['record_ids'][2]}.json"
    payload = json.loads(target.read_text())
    payload["action_record_canonical"] = (
        payload["action_record_canonical"][:-1] + "!"
    )
    target.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")

    result = run_offline_verify(bundle["root_dir"])
    assert result.ok is False
    failed = [r for r in result.records if r.status == "failed"]
    assert len(failed) == 1
    assert failed[0].action_record_id == bundle["record_ids"][2]
    # The tampered canonical breaks the chain-rule check first.
    assert "canonical_leaf_mismatch" in failed[0].reasons

    runner = CliRunner()
    cli_result = runner.invoke(
        cli, ["verify", "--offline", str(bundle["root_dir"])]
    )
    assert cli_result.exit_code == 1, cli_result.output
    assert "FAIL" in cli_result.output


def test_tampered_leaf_hash_fails(tmp_path):
    """Flip a byte in ``leaf_hash`` → Merkle path mismatch."""
    bundle = _build_bundle(tmp_path)
    target = bundle["root_dir"] / "records" / f"{bundle['record_ids'][0]}.json"
    payload = json.loads(target.read_text())
    # Replace with a valid-but-different hex digest.
    payload["leaf_hash"] = hashlib.sha256(b"tampered").hexdigest()
    target.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")

    result = run_offline_verify(bundle["root_dir"])
    assert result.ok is False
    failed = [r for r in result.records if r.status == "failed"]
    assert len(failed) == 1
    # Either merkle_root_mismatch OR canonical_leaf_mismatch fires
    # first depending on check order; both are typed reasons.
    assert failed[0].reasons


def test_tampered_signature_fails_checkpoint(tmp_path):
    """Flip a byte in the checkpoint signature → checkpoint not ok."""
    bundle = _build_bundle(tmp_path)
    target = bundle["root_dir"] / "checkpoint.json"
    payload = json.loads(target.read_text())
    sig = payload["signature"]
    payload["signature"] = sig[:-1] + ("0" if sig[-1] != "0" else "1")
    target.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    # Mirror tamper into all per-record payloads (they carry the same
    # signature field).
    for rp in (bundle["root_dir"] / "records").iterdir():
        p = json.loads(rp.read_text())
        p["kms_signature"] = payload["signature"]
        rp.write_text(json.dumps(p, sort_keys=True), encoding="utf-8")

    result = run_offline_verify(bundle["root_dir"])
    assert result.ok is False
    assert not result.checkpoints[0].signature_ok
    assert result.checkpoints[0].signature_reason == "signature_invalid"


# ── Bundle structural errors → exit 2 ─────────────────────────────────


def test_missing_manifest_raises_bundle_error(tmp_path):
    bundle = _build_bundle(tmp_path)
    (bundle["root_dir"] / "manifest.json").unlink()
    with pytest.raises(BundleError) as exc:
        run_offline_verify(bundle["root_dir"])
    assert "manifest" in str(exc.value)


def test_malformed_json_raises_bundle_error(tmp_path):
    bundle = _build_bundle(tmp_path)
    (bundle["root_dir"] / "manifest.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(BundleError) as exc:
        run_offline_verify(bundle["root_dir"])
    assert "malformed" in str(exc.value).lower() or "json" in str(exc.value).lower()


def test_missing_records_dir_raises_bundle_error(tmp_path):
    bundle = _build_bundle(tmp_path)
    # Wipe the records dir.
    import shutil

    shutil.rmtree(bundle["root_dir"] / "records")
    with pytest.raises(BundleError) as exc:
        run_offline_verify(bundle["root_dir"])
    assert "records" in str(exc.value)


def test_cli_returns_exit_2_on_bundle_error(tmp_path):
    """Bundle structural failures map to a distinct exit code (2)."""
    bundle = _build_bundle(tmp_path)
    (bundle["root_dir"] / "manifest.json").unlink()
    runner = CliRunner()
    res = runner.invoke(cli, ["verify", "--offline", str(bundle["root_dir"])])
    assert res.exit_code == 2, res.output
    assert "Bundle error" in res.output


def test_cli_returns_exit_2_for_nonexistent_path(tmp_path):
    res = CliRunner().invoke(
        cli, ["verify", "--offline", str(tmp_path / "does-not-exist")]
    )
    assert res.exit_code == 2


# ── Tarball support ──────────────────────────────────────────────────


def test_offline_verify_accepts_tarball(tmp_path):
    """Pass a ``.tar.gz`` instead of a directory → works."""
    bundle = _build_bundle(tmp_path)
    tar_path = tmp_path / "bundle.tar.gz"
    with tarfile.open(tar_path, "w:gz") as tf:
        tf.add(bundle["root_dir"], arcname="bundle")
    result = run_offline_verify(tar_path)
    assert result.ok


def test_offline_verify_rejects_path_traversal_in_tarball(tmp_path):
    """Tarball with ``../`` member → BundleError, not arbitrary writes."""
    tar_path = tmp_path / "evil.tar"
    with tarfile.open(tar_path, "w") as tf:
        info = tarfile.TarInfo(name="../escape.txt")
        info.size = 4
        import io

        tf.addfile(info, io.BytesIO(b"oops"))
    with pytest.raises((BundleError, tarfile.TarError, Exception)):
        # Either our pre-filter rejects, or tarfile's data_filter does.
        run_offline_verify(tar_path)


# ── HMAC soft-fail behaviour ─────────────────────────────────────────


def test_hmac_secret_missing_marks_unverified_not_failed(
    tmp_path, monkeypatch
):
    """HMAC bundle without VERA_HMAC_SECRET → checkpoint.signature_reason
    is ``hmac_secret_missing``; the pipeline still reports a clear
    result rather than crashing.
    """
    pytest.importorskip("cryptography")

    # Build an HMAC bundle (different from the default RSA one).
    org_id = "org-hmac"
    n_records = 3
    sequence_at_checkpoint = 3
    signed_at = "2026-05-25T12:00:00"
    secret = b"shared-secret-bytes"

    leaves: list[str] = []
    canonicals: list[str] = []
    previous_hashes: list[str] = []
    record_ids: list[str] = []
    prev = ""
    for i in range(n_records):
        rid = f"rec-{i}"
        record_ids.append(rid)
        fields = {"a": i, "org_id": org_id}
        canonical = _canonicalize(fields)
        leaf = hashlib.sha256((prev + canonical).encode("utf-8")).hexdigest()
        leaves.append(leaf)
        canonicals.append(canonical)
        previous_hashes.append(prev)
        prev = leaf

    root, levels = _build_merkle(leaves)
    cp_id = "cp-hmac-1"
    hash_at = leaves[-1]
    import hmac as _hmac

    message = f"{org_id}:{sequence_at_checkpoint}:{hash_at}:{signed_at}".encode()
    sig = _hmac.new(secret, message, hashlib.sha256).hexdigest()

    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir(parents=True)
    (bundle_dir / "records").mkdir()
    for i, rid in enumerate(record_ids):
        payload = {
            "action_record_id": rid,
            "action_record_canonical": canonicals[i],
            "leaf_hash": leaves[i],
            "previous_hash": previous_hashes[i],
            "merkle_path": _build_path(levels, i),
            "merkle_root": root,
            "checkpoint_id": cp_id,
            "checkpoint_signed_at": signed_at,
            "kms_key_id": "hmac-key",
            "kms_signature": sig,
            "kms_algorithm": "hmac-sha256",
            "kms_public_key_pem": None,
        }
        (bundle_dir / "records" / f"{rid}.json").write_text(
            json.dumps(payload, sort_keys=True), encoding="utf-8"
        )
    (bundle_dir / "checkpoint.json").write_text(
        json.dumps(
            {
                "checkpoint_id": cp_id,
                "org_id": org_id,
                "merkle_root": root,
                "kms_key_id": "hmac-key",
                "signature": sig,
                "signed_at": signed_at,
                "head_action_id": record_ids[-1],
                "record_count": n_records,
                "prior_checkpoint_id": None,
                "sequence_at_checkpoint": sequence_at_checkpoint,
                "hash_at_checkpoint": hash_at,
            }
        ),
        encoding="utf-8",
    )
    (bundle_dir / "manifest.json").write_text(
        json.dumps(
            {
                "vera_version": "1.1.0",
                "exported_at": signed_at,
                "checkpoint_count": 1,
                "record_count": n_records,
            }
        ),
        encoding="utf-8",
    )

    # No VERA_HMAC_SECRET — checkpoint signature can't be verified.
    monkeypatch.delenv("VERA_HMAC_SECRET", raising=False)
    result = run_offline_verify(bundle_dir)
    assert result.ok is False  # checkpoint sig is unverified → overall fail
    assert result.checkpoints[0].signature_reason == "hmac_secret_missing"
    # All RECORDS still verify (Merkle + chain rule don't need the secret).
    assert all(r.status == "verified" for r in result.records)

    # Provide the secret → full pass.
    monkeypatch.setenv("VERA_HMAC_SECRET", secret.decode("utf-8"))
    result_with_secret = run_offline_verify(bundle_dir)
    assert result_with_secret.ok
    assert result_with_secret.checkpoints[0].signature_ok


# ── Cross-checkpoint chain head ──────────────────────────────────────


def test_chain_head_link_between_checkpoints(tmp_path):
    """Two checkpoints, N+1 points at N: chain_link_ok=True."""
    cp1 = _build_bundle(
        tmp_path / "a",
        org_id="org-link",
        n_records=2,
        sequence_at_checkpoint=2,
        signed_at="2026-05-25T12:00:00",
        nonce="A",
    )
    cp1_id = cp1["checkpoint_id"]

    # Build a second checkpoint that references the first.
    cp2 = _build_bundle(
        tmp_path / "b",
        org_id="org-link",
        n_records=2,
        sequence_at_checkpoint=4,
        signed_at="2026-05-26T12:00:00",
        prior_checkpoint_id=cp1_id,
        nonce="B",
    )

    # Merge into one bundle directory under ``checkpoints/`` layout.
    merged = tmp_path / "merged"
    merged.mkdir()
    (merged / "records").mkdir()
    (merged / "checkpoints").mkdir()
    (merged / "checkpoints" / f"{cp1_id}.json").write_text(
        json.dumps(cp1["checkpoint_payload"]), encoding="utf-8"
    )
    (merged / "checkpoints" / f"{cp2['checkpoint_id']}.json").write_text(
        json.dumps(cp2["checkpoint_payload"]), encoding="utf-8"
    )
    for p in (cp1["root_dir"] / "records").iterdir():
        (merged / "records" / p.name).write_text(
            p.read_text(), encoding="utf-8"
        )
    for p in (cp2["root_dir"] / "records").iterdir():
        (merged / "records" / p.name).write_text(
            p.read_text(), encoding="utf-8"
        )
    (merged / "manifest.json").write_text(
        json.dumps(
            {
                "vera_version": "1.1.0",
                "exported_at": "2026-05-26T12:00:00",
                "checkpoint_count": 2,
                "record_count": 4,
            }
        ),
        encoding="utf-8",
    )

    result = run_offline_verify(merged)
    assert result.ok, [c.signature_reason for c in result.checkpoints]
    # Newer checkpoint (cp2) should have chain_link_ok=True since cp1
    # is in the bundle.
    cp2_result = next(
        c for c in result.checkpoints if c.checkpoint_id == cp2["checkpoint_id"]
    )
    assert cp2_result.chain_link_ok is True


def test_chain_head_link_broken_fails(tmp_path):
    """If the prior_checkpoint_id points to one with a HIGHER sequence
    (impossible in a real chain) we flag chain_link_ok=False."""
    # Build two checkpoints and deliberately swap their sequences so
    # cp2 claims to follow cp1 but actually has a lower sequence.
    cp1 = _build_bundle(
        tmp_path / "a",
        org_id="org-broken",
        n_records=2,
        sequence_at_checkpoint=10,
        nonce="A",
    )
    cp2 = _build_bundle(
        tmp_path / "b",
        org_id="org-broken",
        n_records=2,
        sequence_at_checkpoint=5,
        prior_checkpoint_id=cp1["checkpoint_id"],
        nonce="B",
    )

    merged = tmp_path / "merged"
    merged.mkdir()
    (merged / "records").mkdir()
    (merged / "checkpoints").mkdir()
    (merged / "checkpoints" / f"{cp1['checkpoint_id']}.json").write_text(
        json.dumps(cp1["checkpoint_payload"]), encoding="utf-8"
    )
    (merged / "checkpoints" / f"{cp2['checkpoint_id']}.json").write_text(
        json.dumps(cp2["checkpoint_payload"]), encoding="utf-8"
    )
    for p in (cp1["root_dir"] / "records").iterdir():
        (merged / "records" / p.name).write_text(p.read_text(), encoding="utf-8")
    for p in (cp2["root_dir"] / "records").iterdir():
        target = merged / "records" / ("b-" + p.name)
        payload = json.loads(p.read_text())
        payload["action_record_id"] = "b-" + payload["action_record_id"]
        target.write_text(json.dumps(payload), encoding="utf-8")
    (merged / "manifest.json").write_text(
        json.dumps(
            {
                "vera_version": "1.1.0",
                "exported_at": "x",
                "checkpoint_count": 2,
                "record_count": 4,
            }
        ),
        encoding="utf-8",
    )

    result = run_offline_verify(merged)
    # At least one checkpoint should have a broken chain link.
    broken = [c for c in result.checkpoints if c.chain_link_ok is False]
    assert broken, [
        (c.checkpoint_id, c.chain_link_ok, c.chain_link_reason)
        for c in result.checkpoints
    ]
    assert result.ok is False


# ── Manifest drift surfaces as bundle issue ──────────────────────────


def test_manifest_record_count_drift_surfaces(tmp_path):
    bundle = _build_bundle(tmp_path)
    manifest = json.loads((bundle["root_dir"] / "manifest.json").read_text())
    manifest["record_count"] = 999
    (bundle["root_dir"] / "manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    result = run_offline_verify(bundle["root_dir"])
    assert result.ok is False
    assert any("record_count" in iss for iss in result.bundle_issues)
