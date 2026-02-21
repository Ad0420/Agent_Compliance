"""Merkle tree for O(log n) tamper-proof verification of any single record.

Instead of walking the entire chain to verify one record, we build a Merkle tree
over blocks of records. Each leaf is a record hash. Internal nodes are
SHA-256(left || right). The root is stored in checkpoints.

This enables:
- O(log n) proof that a specific record exists and hasn't been tampered with
- Efficient incremental verification (only verify new records since last checkpoint)
- Compact audit proofs that can be shared with external verifiers
"""

import hashlib
import math
from dataclasses import dataclass, field


def _hash_pair(left: str, right: str) -> str:
    """Hash two hex digest strings together."""
    payload = left + right
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass
class MerkleProof:
    """A proof that a leaf exists in a Merkle tree at a given position."""
    leaf_hash: str
    leaf_index: int
    proof_hashes: list[str]  # sibling hashes from leaf to root
    proof_directions: list[str]  # "left" or "right" — direction of the sibling
    root: str

    def to_dict(self) -> dict:
        return {
            "leaf_hash": self.leaf_hash,
            "leaf_index": self.leaf_index,
            "proof_hashes": self.proof_hashes,
            "proof_directions": self.proof_directions,
            "root": self.root,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "MerkleProof":
        return cls(
            leaf_hash=d["leaf_hash"],
            leaf_index=d["leaf_index"],
            proof_hashes=d["proof_hashes"],
            proof_directions=d["proof_directions"],
            root=d["root"],
        )


@dataclass
class MerkleTree:
    """A binary Merkle tree built from a list of leaf hashes."""
    leaves: list[str]
    levels: list[list[str]] = field(default_factory=list)

    def __post_init__(self):
        if not self.leaves:
            self.levels = [[]]
            return
        self._build()

    def _build(self):
        """Build the tree bottom-up."""
        # Pad to next power of 2 with duplicates of last leaf
        n = len(self.leaves)
        next_pow2 = 1 << (n - 1).bit_length() if n > 1 else 1
        padded = list(self.leaves) + [self.leaves[-1]] * (next_pow2 - n)

        self.levels = [padded]
        current = padded

        while len(current) > 1:
            next_level = []
            for i in range(0, len(current), 2):
                next_level.append(_hash_pair(current[i], current[i + 1]))
            self.levels.append(next_level)
            current = next_level

    @property
    def root(self) -> str:
        """The Merkle root hash."""
        if not self.levels or not self.levels[-1]:
            return hashlib.sha256(b"EMPTY_TREE").hexdigest()
        return self.levels[-1][0]

    def get_proof(self, leaf_index: int) -> MerkleProof:
        """Generate a Merkle proof for the leaf at the given index."""
        if leaf_index < 0 or leaf_index >= len(self.leaves):
            raise IndexError(f"Leaf index {leaf_index} out of range [0, {len(self.leaves)})")

        proof_hashes = []
        proof_directions = []
        idx = leaf_index

        # Pad index into the padded tree
        for level in self.levels[:-1]:
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

        return MerkleProof(
            leaf_hash=self.leaves[leaf_index],
            leaf_index=leaf_index,
            proof_hashes=proof_hashes,
            proof_directions=proof_directions,
            root=self.root,
        )


def verify_proof(proof: MerkleProof) -> bool:
    """Verify a Merkle proof against the claimed root."""
    current = proof.leaf_hash

    for sibling_hash, direction in zip(proof.proof_hashes, proof.proof_directions):
        if direction == "left":
            current = _hash_pair(sibling_hash, current)
        else:
            current = _hash_pair(current, sibling_hash)

    return current == proof.root


def build_tree_from_records(record_hashes: list[str]) -> MerkleTree:
    """Build a Merkle tree from a list of record hashes."""
    return MerkleTree(leaves=record_hashes)
