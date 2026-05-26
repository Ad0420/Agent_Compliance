# Offline verification walkthrough

A runnable, self-contained walkthrough of Vera's offline evidence
verification flow. No Vera credentials, no network calls, no AWS
access. Read top-to-bottom in about ten minutes.

## What this example demonstrates

The audit story Vera ships to your compliance team or an external
auditor:

1. **Export evidence** for one customer over a date range. The export
   produces a single tar.gz bundle containing the Merkle proofs, the
   signed checkpoints, and the KMS key history needed to validate
   every record offline.
2. **Verify the bundle offline**. The verifier needs only the bundle
   file and (for HMAC-signed bundles) the shared secret. No Vera
   credentials, no live API, no S3 reach-back.
3. **Tamper detection**. The verifier rejects any modified record
   without ambiguity — wrong leaf hash, wrong sibling, wrong root,
   bad signature.

In production this is `vera evidence-export` followed by
`vera verify --offline`. This walkthrough mirrors the same logic
with local fixtures so you can see the bundle shape, read the
verifier top-to-bottom, and confirm the contract.

## What's in the box

```
verify_offline_walkthrough/
  produce_bundle.py    fixture data → bundle.tar.gz (mirrors `vera evidence-export`)
  verify_bundle.py     bundle.tar.gz → exit 0 / 1 (mirrors `vera verify --offline`)
  run.sh               orchestrates produce → verify → tamper-detect
  README.md            this file
```

The produced bundle shape is identical to what `vera evidence-export`
emits:

```
bundle.tar.gz
  manifest.json                   bundle metadata + record + checkpoint counts
  checkpoints/<id>.json           one per sealed checkpoint
  records/<id>.json               one Merkle proof payload per record
  kms_keys.json                   KMS key history (algorithm + PEM per key_id)
```

See [the SDK README "Verification" section](../../README.md#verification)
for the field-by-field documentation of each file.

## Running it

Python 3.10 or newer. No package install needed — the scripts use only
the standard library.

```bash
./run.sh
```

Expected output (timestamps will vary):

```
[1/3] producing bundle at /tmp/vera_walkthrough.xxx/bundle.tar.gz...
[2/3] verifying bundle (happy path)...
OK 6 record(s) verified across 2 checkpoint(s) (algorithm: hmac-sha256; key history: vera-prod-2026q2)
[3/3] tampering with bundle and confirming verifier rejects...
FAIL merkle_proof_invalid: record 'act_001': folded root ... does not match claimed ...
OK: verifier correctly rejected the tampered bundle

walkthrough complete — happy path and tamper detection both behaved as expected.
```

Exit code 0 means both the happy path and the tamper-detection step
behaved as expected.

## Running the steps individually

If you want to inspect the bundle between produce and verify:

```bash
# Build a bundle in the current directory.
python3 produce_bundle.py --out bundle.tar.gz

# List its contents.
tar -tzf bundle.tar.gz

# Pretty-print a single record's proof.
mkdir -p /tmp/peek && tar -xzf bundle.tar.gz -C /tmp/peek
cat /tmp/peek/records/act_001.json | python3 -m json.tool

# Verify (the HMAC secret must match what produce_bundle.py used).
export VERA_HMAC_SECRET="walkthrough-demo-secret-do-not-use-in-production"
python3 verify_bundle.py bundle.tar.gz
```

## HMAC vs asymmetric signing

The walkthrough uses HMAC-SHA256 because it has the simplest reader
profile — there's one secret, no PEM indirection, the verifier fits
on a screen. This is also the default for Vera's local dev stack and
for orgs that haven't migrated to asymmetric KMS yet.

The trade-off:

| Mode | Bundle self-contained? | What the auditor needs |
|---|---|---|
| `hmac-sha256` | No — needs the shared secret out-of-band | The bundle + `VERA_HMAC_SECRET` |
| `rsa-pss-sha256` / `ecdsa-p256-sha256` | Yes — public keys travel inside `kms_keys.json` | Just the bundle |

For asymmetric verification, the verifier reads `public_key_pem` from
`kms_keys.json` and validates with the `cryptography` package
(>=42). The verifier branch is in `verify_bundle.py::_verify_signature`.

The asymmetric path is what you should be running in production. Talk
to <support@usevera.xyz> about migrating your org to asymmetric KMS.

## What this walkthrough does NOT exercise

- **The live `vera evidence-export` and `vera verify --offline` CLI
  commands.** Those are the production interface to the same logic
  and require API credentials. This walkthrough is the contract-by-example
  for that surface.
- **Chain-level previous_hash continuity across checkpoint boundaries.**
  The Merkle path inside a checkpoint window is fully verified; chain
  continuity between records sealed in different windows is exercised
  by the SDK's full offline verifier (`vera.verify`, refactored in
  Wave 3C.1).
- **KMS key rotation mid-checkpoint.** The walkthrough uses a single
  key. The real verifier walks `kms_keys.json` and picks the right
  historical key per checkpoint via `key_id`.
- **OTS (OpenTimestamps) anchors.** Deferred from v1 — see
  [ADR 0001](../../../docs/adr/0001-no-opentimestamps-in-v1.md).

## See also

- [SDK README — Verification](../../README.md#verification) — production
  CLI reference for `vera evidence-export` and `vera verify --offline`
- [Merkle proof exposure (Wave 3B.2)](../../../v1-implementation-plan.md)
  — the server-side endpoint that supplies each per-record proof
- [Customer S3 mirror (Wave 3B.1)](../../../v1-implementation-plan.md)
  — the export path that lands signed checkpoints in the customer's
  bucket with Object Lock COMPLIANCE mode
