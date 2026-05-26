/**
 * In-browser Merkle proof verifier — Wave 3D.2.
 *
 * Mirrors the canonical reproduction path in
 * ``backend/app/services/merkle_proof.py``:
 *
 *   1. Fold ``merkle_path`` from ``leaf_hash`` toward the root using
 *      SHA-256 over (sibling+current) or (current+sibling) per the
 *      direction marker.
 *   2. Assert the folded result equals ``merkle_root``.
 *   3. (Asymmetric only) Verify the checkpoint's KMS signature over
 *      the merkle_root using the public key PEM via Web Crypto API
 *      ``crypto.subtle.verify``.
 *
 * The dashboard uses this as the dogfooding moment: the same verifier
 * an auditor would run on a downloaded bundle runs in the browser
 * against the live API's per-record proof endpoint. If the verifier
 * fails, the panel goes red; if it passes, it goes green.
 *
 * HMAC limitation
 * ---------------
 * HMAC-SHA256 (the local-dev key and AWS KMS HMAC mode) requires the
 * shared secret to verify. The secret must never live in the browser,
 * so the panel disables the inline Verify button on HMAC chains and
 * documents the reason. The Merkle-path check above still runs
 * client-side because it doesn't depend on the signature; the
 * signature check is what we skip.
 *
 * Pure functions, no React. Tests live in ``__tests__``.
 */

import type { MerkleProofPayload, MerklePathStep } from "./api-types";

// ── Pure hash helpers ─────────────────────────────────────────────────

/** SHA-256(input) as lowercase hex. Uses ``window.crypto.subtle``
 *  on the browser; ``node:crypto`` on node (so the unit tests can
 *  exercise the same function path without jsdom). */
export async function sha256Hex(input: string): Promise<string> {
  // Detect a usable subtle.digest. The Edge runtime + jsdom both
  // expose ``crypto.subtle``; node has it under ``globalThis.crypto``
  // since 19+. Fall through to ``node:crypto`` on older runtimes so
  // the contract-shape tests can still import this module.
  const subtle =
    (typeof globalThis !== "undefined" &&
      (globalThis as { crypto?: { subtle?: SubtleCrypto } }).crypto?.subtle) ||
    undefined;
  if (subtle) {
    const enc = new TextEncoder();
    const buf = await subtle.digest("SHA-256", enc.encode(input));
    return Array.from(new Uint8Array(buf))
      .map((b) => b.toString(16).padStart(2, "0"))
      .join("");
  }
  // Eager require so we don't ship node:crypto into the browser
  // bundle; this branch only runs in test environments without a
  // SubtleCrypto polyfill. Webpack tree-shakes this away in client
  // bundles because ``subtle`` is always present in supported
  // browsers.
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const nodeCrypto = require("node:crypto") as typeof import("node:crypto");
  return nodeCrypto.createHash("sha256").update(input, "utf-8").digest("hex");
}

/**
 * Fold a Merkle path from ``leafHash`` toward the root and return the
 * folded result. Does NOT compare to the expected root — the caller
 * does that so it can report the mismatch detail.
 */
export async function foldMerklePath(
  leafHash: string,
  path: MerklePathStep[],
): Promise<string> {
  let current = leafHash;
  for (const step of path) {
    const combined =
      step.direction === "left"
        ? step.sibling_hash + current
        : current + step.sibling_hash;
    current = await sha256Hex(combined);
  }
  return current;
}

// ── Verification result shape ─────────────────────────────────────────

/**
 * One row in the verification result table. We surface every record
 * we attempted to verify (with the outcome) so the dashboard can show
 * "847 of 847 verified" or, on failure, "Record 7234 — Merkle path
 * does not lead to checkpoint root."
 */
export type RecordVerification =
  | {
      status: "verified";
      action_record_id: string;
      checkpoint_id: string;
      merkle_root: string;
    }
  | {
      status: "merkle_path_invalid";
      action_record_id: string;
      checkpoint_id: string;
      expected_root: string;
      computed_root: string;
    }
  | {
      status: "signature_invalid";
      action_record_id: string;
      checkpoint_id: string;
    }
  | {
      status: "signature_unsupported";
      action_record_id: string;
      checkpoint_id: string;
      reason: "hmac_symmetric_no_shared_secret" | "missing_public_key";
    }
  | {
      status: "fetch_failed";
      action_record_id: string;
      error: string;
    };

export interface VerificationSummary {
  total: number;
  verified: number;
  failed: number;
  records: RecordVerification[];
  /**
   * ISO timestamp the run completed. Powers the "Last verified: <time>"
   * status line.
   */
  completed_at: string;
}

// ── Merkle path + signature verification ──────────────────────────────

/**
 * Verify one proof payload's Merkle path. Returns ``{ok: true}`` when
 * the folded root equals ``payload.merkle_root``; otherwise returns
 * the computed-vs-expected pair so the caller can surface the diff.
 */
export async function verifyMerklePath(
  payload: MerkleProofPayload,
): Promise<{ ok: true } | { ok: false; computed: string }> {
  const folded = await foldMerklePath(payload.leaf_hash, payload.merkle_path);
  if (folded === payload.merkle_root) {
    return { ok: true };
  }
  return { ok: false, computed: folded };
}

/**
 * Web Crypto API helpers for asymmetric signature verification. HMAC
 * is intentionally NOT covered — the shared secret must never live in
 * the browser. The caller upstream checks the chain's algorithm and
 * either invokes this or surfaces the documented unsupported reason.
 */

function pemToArrayBuffer(pem: string): ArrayBuffer {
  // Strip the BEGIN/END framing and base64-decode the body.
  const body = pem
    .replace(/-----BEGIN [^-]+-----/g, "")
    .replace(/-----END [^-]+-----/g, "")
    .replace(/\s+/g, "");
  const bin = atob(body);
  const buf = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i += 1) buf[i] = bin.charCodeAt(i);
  return buf.buffer;
}

function hexToArrayBuffer(hex: string): ArrayBuffer {
  if (hex.length % 2 !== 0) throw new Error("hex string must have even length");
  const buf = new Uint8Array(hex.length / 2);
  for (let i = 0; i < buf.length; i += 1) {
    buf[i] = parseInt(hex.substr(i * 2, 2), 16);
  }
  return buf.buffer;
}

/**
 * Verify an asymmetric KMS signature over ``merkle_root`` (encoded as
 * UTF-8 bytes, matching the backend's ``sign(message=root.encode())``
 * convention). Returns ``true`` if the signature verifies under the
 * supplied public key PEM.
 *
 * Supported algorithms (mirroring future server-side options):
 *   * ``rsa-pss-sha256`` — RSA-PSS with SHA-256 and salt length 32.
 *   * ``ecdsa-p256-sha256`` — ECDSA on P-256 with SHA-256.
 *
 * Anything else returns ``false`` — defense-in-depth so a future
 * algorithm name added server-side without a matching client update
 * fails closed rather than silently passing.
 */
export async function verifyAsymmetricSignature(args: {
  publicKeyPem: string;
  algorithm: string;
  message: string;
  signatureHex: string;
}): Promise<boolean> {
  const subtle =
    (typeof globalThis !== "undefined" &&
      (globalThis as { crypto?: { subtle?: SubtleCrypto } }).crypto?.subtle) ||
    undefined;
  if (!subtle) return false;

  const keyBuf = pemToArrayBuffer(args.publicKeyPem);
  const sigBuf = hexToArrayBuffer(args.signatureHex);
  const msgBuf = new TextEncoder().encode(args.message);

  try {
    if (args.algorithm === "rsa-pss-sha256") {
      const key = await subtle.importKey(
        "spki",
        keyBuf,
        { name: "RSA-PSS", hash: "SHA-256" },
        false,
        ["verify"],
      );
      return await subtle.verify(
        { name: "RSA-PSS", saltLength: 32 },
        key,
        sigBuf,
        msgBuf,
      );
    }
    if (args.algorithm === "ecdsa-p256-sha256") {
      const key = await subtle.importKey(
        "spki",
        keyBuf,
        { name: "ECDSA", namedCurve: "P-256" },
        false,
        ["verify"],
      );
      return await subtle.verify(
        { name: "ECDSA", hash: "SHA-256" },
        key,
        sigBuf,
        msgBuf,
      );
    }
    return false;
  } catch {
    // PEM parse error, algorithm mismatch, etc. — fail closed.
    return false;
  }
}

// ── Orchestrator: verify N records ────────────────────────────────────

/**
 * Run Merkle-path verification on every supplied proof payload and
 * optionally verify the asymmetric KMS signature on each.
 *
 * The caller (the panel) fetches proofs via ``getMerkleProof`` and
 * passes them in here; this function knows nothing about networking,
 * which keeps the unit tests deterministic. Returns a
 * ``VerificationSummary`` shaped for direct display.
 *
 * The ``verifySignatures`` flag controls whether we attempt the
 * crypto.subtle verify path. The panel sets this to ``false`` for
 * HMAC chains (the chain-summary endpoint surfaces this via
 * ``verification_supported=false``) and ``true`` for asymmetric ones.
 */
export async function verifyRecordProofs(args: {
  proofs: MerkleProofPayload[];
  verifySignatures: boolean;
}): Promise<VerificationSummary> {
  const records: RecordVerification[] = [];
  for (const proof of args.proofs) {
    const merkleCheck = await verifyMerklePath(proof);
    if (!merkleCheck.ok) {
      records.push({
        status: "merkle_path_invalid",
        action_record_id: proof.action_record_id,
        checkpoint_id: proof.checkpoint_id,
        expected_root: proof.merkle_root,
        computed_root: merkleCheck.computed,
      });
      continue;
    }
    if (!args.verifySignatures) {
      records.push({
        status: "signature_unsupported",
        action_record_id: proof.action_record_id,
        checkpoint_id: proof.checkpoint_id,
        reason: proof.kms_algorithm === "hmac-sha256"
          ? "hmac_symmetric_no_shared_secret"
          : "missing_public_key",
      });
      continue;
    }
    if (!proof.kms_public_key_pem) {
      records.push({
        status: "signature_unsupported",
        action_record_id: proof.action_record_id,
        checkpoint_id: proof.checkpoint_id,
        reason: "missing_public_key",
      });
      continue;
    }
    const sigOk = await verifyAsymmetricSignature({
      publicKeyPem: proof.kms_public_key_pem,
      algorithm: proof.kms_algorithm,
      message: proof.merkle_root,
      signatureHex: proof.kms_signature,
    });
    if (sigOk) {
      records.push({
        status: "verified",
        action_record_id: proof.action_record_id,
        checkpoint_id: proof.checkpoint_id,
        merkle_root: proof.merkle_root,
      });
    } else {
      records.push({
        status: "signature_invalid",
        action_record_id: proof.action_record_id,
        checkpoint_id: proof.checkpoint_id,
      });
    }
  }

  const verified = records.filter((r) => r.status === "verified").length;
  return {
    total: records.length,
    verified,
    failed: records.length - verified,
    records,
    completed_at: new Date().toISOString(),
  };
}
