# ADR 0001: No OpenTimestamps anchor in v1

**Status:** Accepted
**Date:** 2026-05-25
**Deciders:** Vera engineering (Phase 3 eng review)

## Context

The original Phase 3 plan included an OpenTimestamps Bitcoin blockchain
anchor on each checkpoint as a tamper-evidence backstop. CEO review
([v1-implementation-plan.md](../../v1-implementation-plan.md) lines 390-396)
flagged this as low-ROI:

> P6: OpenTimestamps Bitcoin anchor — Low confidence. Solves a problem
> already 80% solved by S3 WORM mirror. "You anchored healthcare to
> Bitcoin?" procurement objection.

Eng review concurred: customer-controlled S3 WORM bucket already gives
"Vera can't tamper with this." OTS adds:

- Bitcoin blockchain dependency (the public OTS calendar can be
  unreachable; test plan flags this as a gap)
- Crypto-coded optics in a healthcare procurement conversation
- Async retry complexity (anchor lag of hours to days)

## Decision

OpenTimestamps anchoring is OUT of scope for Vera v1. The
[v1-implementation-plan.md](../../v1-implementation-plan.md) §Phase 3
reference to OTS is honored by emitting an empty `ots_proof_url: null`
field in the checkpoint response and skipping anchor work entirely.

`backend/app/services/external_store.py::TransparencyLogStore` is a
Sigstore/Rekor-style stub that may or may not be used in v2.

## Consequences

**Positive:**

- Phase 3 ships ~3 days faster.
- No "Bitcoin in healthcare" procurement friction.
- Acceptance gate "Bitcoin lookup resolves"
  ([v1-implementation-plan.md](../../v1-implementation-plan.md) line 162)
  is formally dropped; replaced with "S3 mirror round-trip resolves."

**Negative:**

- If a regulator ever specifically asks for blockchain anchoring (no
  current HIPAA citation requires it), revisit as opt-in feature.
- The [v1-test-plan.md](../../v1-test-plan.md) rows "OTS calendar
  unreachable" and "OTS anchor on Merkle root" stay deferred — flipped
  to "deferred per ADR 0001" in the same wave that landed this ADR
  rather than "gap" so the deferral is auditable.

## Revisit when

A real customer ask, regulatory citation, or compliance officer
specifically requests blockchain anchoring. Until then, S3 WORM +
KMS-signed checkpoints are the v1 tamper-evidence story.
