"""Unit tests for ``vera.verify.proof``.

Covers the test-plan rows that previously deferred their CLI surface
to Wave 3C:

* "``vera verify --merkle-proof`` — happy path"
* "``vera verify --merkle-proof`` — tampered leaf"
* "``vera verify --merkle-proof`` — tampered sibling"
* "``vera verify --merkle-proof`` — wrong root"

All inputs are built in-process — we mirror the same tree shape the
backend uses (binary, padded to next power-of-two with last-leaf
duplication, see ``backend/app/services/merkle.py:67-70``). That keeps
the SDK tests free of backend imports.
"""

from __future__ import annotations

import hashlib

import pytest

from vera.verify.proof import (
    canonical_record_to_leaf_hash,
    verify_merkle_path,
)


def _hash_pair(left: str, right: str) -> str:
    return hashlib.sha256((left + right).encode("utf-8")).hexdigest()


def _build_proof(leaves: list[str], leaf_index: int) -> dict:
    """Build a `{leaf_hash, merkle_path, merkle_root}` dict over ``leaves``.

    Mirrors ``MerkleTree.get_proof`` from the backend — pad to next
    power of two with the last leaf, hash pairs level by level, emit
    sibling + direction at each level.
    """
    if not leaves:
        raise ValueError("need at least one leaf")
    n = len(leaves)
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

    return {
        "leaf_hash": leaves[leaf_index],
        "merkle_path": [
            {"sibling_hash": h, "direction": d}
            for h, d in zip(proof_hashes, proof_directions)
        ],
        "merkle_root": levels[-1][0],
    }


# ── Happy path ────────────────────────────────────────────────────────


def test_verify_merkle_path_well_formed():
    """A well-formed proof for a middle leaf should verify."""
    leaves = [hashlib.sha256(f"leaf_{i}".encode()).hexdigest() for i in range(7)]
    proof = _build_proof(leaves, leaf_index=3)
    ok, reason = verify_merkle_path(proof)
    assert ok is True
    assert reason is None


def test_verify_merkle_path_single_record():
    """Single-leaf tree: root == leaf, path is empty, verifies trivially."""
    leaves = [hashlib.sha256(b"only_leaf").hexdigest()]
    proof = _build_proof(leaves, leaf_index=0)
    assert proof["merkle_path"] == []
    assert proof["merkle_root"] == proof["leaf_hash"]
    ok, reason = verify_merkle_path(proof)
    assert ok is True
    assert reason is None


@pytest.mark.parametrize("n_leaves", [2, 3, 5, 7, 9, 16, 17])
def test_verify_merkle_path_padding_edge_cases(n_leaves):
    """Padding to next power-of-two doesn't corrupt proofs at boundaries."""
    leaves = [hashlib.sha256(f"l_{i}".encode()).hexdigest() for i in range(n_leaves)]
    for idx in range(n_leaves):
        proof = _build_proof(leaves, leaf_index=idx)
        ok, _ = verify_merkle_path(proof)
        assert ok, f"failed at n={n_leaves}, idx={idx}"


# ── Tamper tests ──────────────────────────────────────────────────────


def test_tampered_leaf_hash_fails():
    """Flip a bit in leaf_hash → root no longer matches."""
    leaves = [hashlib.sha256(f"l_{i}".encode()).hexdigest() for i in range(5)]
    proof = _build_proof(leaves, leaf_index=2)
    # Replace leaf_hash with a different valid hex digest.
    proof["leaf_hash"] = hashlib.sha256(b"tampered").hexdigest()
    ok, reason = verify_merkle_path(proof)
    assert ok is False
    assert reason == "merkle_root_mismatch"


def test_tampered_sibling_hash_fails():
    """Flip a bit in proof_hashes[0] → root no longer matches."""
    leaves = [hashlib.sha256(f"l_{i}".encode()).hexdigest() for i in range(5)]
    proof = _build_proof(leaves, leaf_index=2)
    proof["merkle_path"][0]["sibling_hash"] = hashlib.sha256(
        b"tampered_sibling"
    ).hexdigest()
    ok, reason = verify_merkle_path(proof)
    assert ok is False
    assert reason == "merkle_root_mismatch"


def test_wrong_root_fails():
    """Replace root with a different valid root → mismatch."""
    leaves = [hashlib.sha256(f"l_{i}".encode()).hexdigest() for i in range(5)]
    proof = _build_proof(leaves, leaf_index=2)
    proof["merkle_root"] = hashlib.sha256(b"other_root").hexdigest()
    ok, reason = verify_merkle_path(proof)
    assert ok is False
    assert reason == "merkle_root_mismatch"


def test_wrong_direction_fails():
    """Flip a direction → folds the wrong way → root mismatch."""
    leaves = [hashlib.sha256(f"l_{i}".encode()).hexdigest() for i in range(4)]
    proof = _build_proof(leaves, leaf_index=2)
    proof["merkle_path"][0]["direction"] = (
        "left" if proof["merkle_path"][0]["direction"] == "right" else "right"
    )
    ok, reason = verify_merkle_path(proof)
    assert ok is False
    assert reason == "merkle_root_mismatch"


def test_missing_fields_fail():
    """Missing required fields → ``missing_field`` reason, not a crash."""
    ok, reason = verify_merkle_path({"leaf_hash": "x"})
    assert ok is False
    assert reason == "missing_field"


def test_invalid_path_step_fails():
    """Bad direction value → typed ``invalid_path_step`` reason."""
    leaves = [hashlib.sha256(f"l_{i}".encode()).hexdigest() for i in range(4)]
    proof = _build_proof(leaves, leaf_index=1)
    proof["merkle_path"][0]["direction"] = "sideways"  # not left/right
    ok, reason = verify_merkle_path(proof)
    assert ok is False
    assert reason == "invalid_path_step"


# ── Chain-rule helper ─────────────────────────────────────────────────


def test_canonical_record_to_leaf_hash_matches_backend_rule():
    """``sha256(previous_hash + canonical)`` — same rule the backend uses."""
    canonical = '{"a":1,"b":"x"}'
    previous = "f" * 64  # any 64-char hex stand-in
    expected = hashlib.sha256((previous + canonical).encode("utf-8")).hexdigest()
    assert (
        canonical_record_to_leaf_hash(canonical=canonical, previous_hash=previous)
        == expected
    )


def test_canonical_record_to_leaf_hash_empty_previous_for_first_record():
    """First record in the chain: previous_hash is the empty string."""
    canonical = '{"first":"record"}'
    expected = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    assert (
        canonical_record_to_leaf_hash(canonical=canonical, previous_hash="")
        == expected
    )
    # Also tolerate None as "no predecessor".
    assert (
        canonical_record_to_leaf_hash(canonical=canonical, previous_hash=None)
        == expected
    )
