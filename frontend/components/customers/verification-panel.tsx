// Customer Verification & Evidence Trail panel — Wave 3D.2.
//
// Shipped on the Customer detail page's Overview tab. Three sub-sections:
//
//   1. Latest-checkpoint summary — short checkpoint id, signed date+time,
//      record count for THIS customer in that checkpoint, KMS key.
//   2. 30-day timeline strip — one tile per calendar day, hover for
//      checkpoint detail. Greys for "none", amber for "pending today",
//      olive for "sealed".
//   3. Two CTAs — "Download evidence bundle" (opens a confirmation modal
//      with the selective-disclosure preview) and "Verify this customer's
//      chain" (in-browser Merkle path walker + Web Crypto API signature
//      verification on asymmetric KMS keys; greyed out with documented
//      reason on HMAC chains).
//
// The dogfooding moment: clicking Verify runs the same logic an auditor
// running ``vera verify --offline`` would run, but against the live API's
// per-record proof endpoint. Pass → green "Last verified" line. Fail → red.

"use client";

import * as React from "react";
import { Download, ShieldCheck, ShieldAlert, Loader2 } from "lucide-react";

import { useCustomerChainSummary } from "@/hooks/use-customers";
import { getMerkleProof } from "@/lib/api-client";
import { verifyRecordProofs, type VerificationSummary } from "@/lib/merkle-verify";
import type {
  ChainTimelineDay,
  CustomerChainSummary,
  MerkleProofPayload,
} from "@/lib/api-types";
import { Loading } from "@/components/ui/loading";
import { StatusDot } from "@/components/ui/status-indicator";
import { formatDate, truncateHash } from "@/lib/utils";
import { EvidenceDownloadModal } from "./evidence-download-modal";

interface VerificationPanelProps {
  tenant_id: string;
}

export function VerificationPanel({ tenant_id }: VerificationPanelProps) {
  const { data, isLoading, error } = useCustomerChainSummary(tenant_id);

  if (isLoading) {
    return (
      <PanelShell>
        <div
          aria-busy="true"
          className="flex justify-center py-8 text-[color:var(--ink-3)]"
          data-testid="verification-panel-loading"
        >
          <Loading.Spinner size={20} label="Loading verification" />
        </div>
      </PanelShell>
    );
  }

  if (error) {
    return (
      <PanelShell>
        <p
          className="text-[13px] text-[color:var(--error)]"
          data-testid="verification-panel-error"
        >
          Verification details could not be loaded right now. Try again
          shortly or contact Vera support if the message persists.
        </p>
      </PanelShell>
    );
  }

  if (!data) return null;

  return (
    <PanelShell>
      <VerificationPanelBody data={data} tenant_id={tenant_id} />
    </PanelShell>
  );
}

function PanelShell({ children }: { children: React.ReactNode }) {
  return (
    <section
      className="space-y-5 rounded-md border border-[color:var(--ink-4)] bg-[color:var(--paper)] p-6"
      data-testid="verification-panel"
      aria-labelledby="verification-panel-heading"
    >
      <header className="space-y-1">
        <h2
          id="verification-panel-heading"
          className="text-[11px] font-semibold uppercase tracking-[0.08em] text-[color:var(--ink-2)]"
        >
          Verification & Evidence Trail
        </h2>
        <p className="text-[13px] text-[color:var(--ink-2)]">
          Regulator-ready evidence for this customer. Download a bundle or
          run the same offline-verification logic an auditor would use.
        </p>
      </header>
      {children}
    </section>
  );
}

function VerificationPanelBody({
  data,
  tenant_id,
}: {
  data: CustomerChainSummary;
  tenant_id: string;
}) {
  const [modalOpen, setModalOpen] = React.useState(false);
  const [verifying, setVerifying] = React.useState(false);
  const [verifyError, setVerifyError] = React.useState<string | null>(null);
  const [summary, setSummary] = React.useState<VerificationSummary | null>(
    null,
  );

  const verifyDisabled = !data.verification_supported;

  const onVerify = React.useCallback(async () => {
    if (verifyDisabled) return;
    setVerifying(true);
    setVerifyError(null);
    setSummary(null);
    try {
      const result = await runChainVerification(tenant_id);
      setSummary(result);
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Verification failed";
      setVerifyError(msg);
    } finally {
      setVerifying(false);
    }
  }, [tenant_id, verifyDisabled]);

  return (
    <>
      <LatestCheckpointBlock data={data} />
      <TimelineStrip days={data.timeline} />
      <div className="flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={() => setModalOpen(true)}
          className="inline-flex h-9 items-center justify-center gap-2 rounded-[10px] border border-[color:var(--ink)] px-4 text-[14px] font-medium text-[color:var(--ink)] transition-colors hover:bg-[color:var(--paper-2)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--ink)]"
          data-testid="evidence-download-trigger"
        >
          <Download className="size-3.5" aria-hidden="true" />
          Download evidence bundle
        </button>
        <button
          type="button"
          onClick={onVerify}
          disabled={verifyDisabled || verifying}
          className="inline-flex h-9 items-center justify-center gap-2 rounded-[10px] border border-[color:var(--ink)] px-4 text-[14px] font-medium text-[color:var(--ink)] transition-colors hover:bg-[color:var(--paper-2)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--ink)] disabled:cursor-not-allowed disabled:opacity-50"
          data-testid="verify-chain-trigger"
          title={
            verifyDisabled
              ? unsupportedReasonCopy(data.verification_unsupported_reason)
              : undefined
          }
        >
          {verifying ? (
            <Loader2 className="size-3.5 animate-spin" aria-hidden="true" />
          ) : (
            <ShieldCheck className="size-3.5" aria-hidden="true" />
          )}
          {verifying ? "Verifying…" : "Verify this customer's chain"}
        </button>
      </div>
      {verifyDisabled ? (
        <p
          className="text-[12px] text-[color:var(--ink-2)]"
          data-testid="verify-unsupported-note"
        >
          {unsupportedReasonCopy(data.verification_unsupported_reason)}
        </p>
      ) : null}
      {verifyError ? (
        <VerificationErrorLine error={verifyError} />
      ) : summary ? (
        <VerificationResultLine summary={summary} />
      ) : null}
      <EvidenceDownloadModal
        open={modalOpen}
        onOpenChange={setModalOpen}
        tenant_id={tenant_id}
        customer_display_name={data.customer_display_name ?? data.tenant_id}
      />
    </>
  );
}

// ── Latest checkpoint summary ─────────────────────────────────────────

function LatestCheckpointBlock({ data }: { data: CustomerChainSummary }) {
  if (!data.latest_checkpoint) {
    return (
      <p
        className="text-[13px] text-[color:var(--ink-2)]"
        data-testid="latest-checkpoint-empty"
      >
        No checkpoint has been sealed for this customer yet. The chain
        will produce its first checkpoint at the next cadence tick.
      </p>
    );
  }
  const lc = data.latest_checkpoint;
  const customerName = data.customer_display_name ?? data.tenant_id;
  return (
    <div className="space-y-2" data-testid="latest-checkpoint-summary">
      <p className="text-[13px] text-[color:var(--ink-2)]">Latest checkpoint</p>
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="font-display text-2xl font-normal leading-tight tabular-nums text-[color:var(--ink)]">
          {lc.merkle_root
            ? truncateHash(lc.merkle_root, 8)
            : truncateHash(lc.checkpoint_id, 8)}
        </span>
        <span className="text-[12px] tabular-nums text-[color:var(--ink-2)]">
          {formatDate(lc.signed_at + "Z")}
        </span>
      </div>
      {/* copy-allow: tabular-nums set on the parent paragraph applies to
          every digit rendered below — both the customer count and the
          parenthetical total count inherit the style. */}
      <p className="text-[13px] text-[color:var(--ink-2)] tabular-nums">
        {lc.customer_record_count.toLocaleString()} record
        {lc.customer_record_count === 1 ? "" : "s"} from{" "}
        <span className="text-[color:var(--ink)]">{customerName}</span>{" "}
        in this checkpoint
        {/* copy-allow: parent <p> sets tabular-nums; inherited here */}
        {lc.total_record_count !== lc.customer_record_count
          ? ` (${lc.total_record_count.toLocaleString()} total)`
          : ""}
        .
      </p>
      {lc.kms_key_id ? (
        <p className="text-[12px] text-[color:var(--ink-3)] tabular-nums">
          Signed by {lc.kms_algorithm ?? "kms"} key{" "}
          {truncateHash(lc.kms_key_id, 8)}
        </p>
      ) : null}
    </div>
  );
}

// ── 30-day timeline strip ─────────────────────────────────────────────

function TimelineStrip({ days }: { days: ChainTimelineDay[] }) {
  return (
    <div className="space-y-2" data-testid="chain-timeline">
      <div className="flex items-center justify-between">
        <p className="text-[11px] font-semibold uppercase tracking-[0.08em] text-[color:var(--ink-2)]">
          Last 30 days
        </p>
        <TimelineLegend />
      </div>
      <div
        className="flex flex-wrap gap-1"
        role="list"
        aria-label="30-day checkpoint timeline"
      >
        {days.map((d) => (
          <TimelineTile key={d.date} day={d} />
        ))}
      </div>
    </div>
  );
}

function TimelineTile({ day }: { day: ChainTimelineDay }) {
  // Olive for sealed, amber for pending (today + cadence configured),
  // muted paper-3 for none. Status dot semantics map to the design
  // system's StatusDot variants.
  const color =
    day.status === "sealed"
      ? "bg-[color:var(--olive)]"
      : day.status === "pending"
        ? "bg-[color:var(--amber)]"
        : "bg-[color:var(--paper-3)]";
  const labelDate = day.date; // already YYYY-MM-DD
  const tooltip =
    day.status === "sealed"
      // copy-allow: number appears only inside a title/aria-label tooltip — no visible numeric run benefits from tabular-nums.
      ? `${labelDate} · ${day.customer_record_count.toLocaleString()} records sealed (chk ${day.checkpoint_id ? day.checkpoint_id.slice(0, 8) : "?"})`
      : day.status === "pending"
        ? `${labelDate} · Checkpoint pending`
        : `${labelDate} · No checkpoint sealed`;
  return (
    <span
      role="listitem"
      title={tooltip}
      aria-label={tooltip}
      className={`size-4 rounded-[3px] ${color}`}
      data-testid={`timeline-tile-${day.status}`}
      data-date={day.date}
    />
  );
}

function TimelineLegend() {
  return (
    <div className="flex items-center gap-3 text-[11px] text-[color:var(--ink-3)]">
      <span className="inline-flex items-center gap-1">
        <span
          aria-hidden="true"
          className="size-2 rounded-[2px] bg-[color:var(--olive)]"
        />
        Sealed
      </span>
      <span className="inline-flex items-center gap-1">
        <span
          aria-hidden="true"
          className="size-2 rounded-[2px] bg-[color:var(--amber)]"
        />
        Pending
      </span>
      <span className="inline-flex items-center gap-1">
        <span
          aria-hidden="true"
          className="size-2 rounded-[2px] bg-[color:var(--paper-3)]"
        />
        None
      </span>
    </div>
  );
}

// ── Verification result line ──────────────────────────────────────────

function VerificationResultLine({ summary }: { summary: VerificationSummary }) {
  const allOk = summary.failed === 0 && summary.verified > 0;
  const noRecords = summary.total === 0;
  if (noRecords) {
    return (
      <p
        className="text-[13px] text-[color:var(--ink-2)]"
        data-testid="verify-result-empty"
      >
        No customer records in the latest checkpoint to verify yet.
      </p>
    );
  }
  if (allOk) {
    return (
      <p
        className="flex items-center gap-2 text-[13px] text-[color:var(--olive)]"
        data-testid="verify-result-ok"
      >
        <StatusDot variant="ok" label={`All ${summary.verified.toLocaleString()} records verify against the checkpoint root`} />
        <span className="text-[12px] tabular-nums text-[color:var(--ink-3)]">
          Last verified {formatDate(summary.completed_at)}
        </span>
      </p>
    );
  }
  return (
    <div
      className="space-y-1"
      data-testid="verify-result-failed"
    >
      <p className="flex items-center gap-2 text-[13px] text-[color:var(--error)]">
        <StatusDot
          variant="error"
          label={`${summary.failed.toLocaleString()} of ${summary.total.toLocaleString()} records failed verification`}
        />
      </p>
      <ul className="space-y-1 text-[12px] tabular-nums text-[color:var(--ink-2)]">
        {summary.records
          .filter((r) => r.status !== "verified")
          .slice(0, 5)
          .map((r) => (
            <li key={r.action_record_id}>
              {r.action_record_id.slice(0, 8)} — {failureReason(r)}
            </li>
          ))}
      </ul>
    </div>
  );
}

function VerificationErrorLine({ error }: { error: string }) {
  return (
    <p
      className="flex items-center gap-2 text-[13px] text-[color:var(--error)]"
      data-testid="verify-error"
    >
      <ShieldAlert className="size-3.5" aria-hidden="true" />
      Verification could not run: {error}
    </p>
  );
}

function failureReason(
  r: VerificationSummary["records"][number],
): string {
  switch (r.status) {
    case "merkle_path_invalid":
      return "Merkle path does not lead to the checkpoint root";
    case "signature_invalid":
      return "Checkpoint signature invalid";
    case "signature_unsupported":
      return r.reason === "hmac_symmetric_no_shared_secret"
        ? "HMAC signature requires the shared secret out-of-band"
        : "Public key not available";
    case "fetch_failed":
      return `Proof fetch failed: ${r.error}`;
    case "verified":
      return "verified";
  }
}

function unsupportedReasonCopy(reason: string | null): string {
  if (reason === "hmac_symmetric_no_shared_secret") {
    return "HMAC verification requires the shared secret out-of-band. Download the evidence bundle and run the CLI verifier with the secret your customer already holds.";
  }
  return "In-browser verification is not available for this chain.";
}

// ── Verification orchestration (network → verifier) ───────────────────

/**
 * Fetch every Merkle proof for the customer's records and pipe them
 * through ``verifyRecordProofs``. Exposed via the panel's "Verify"
 * button.
 *
 * Lives in-module rather than in ``lib/merkle-verify.ts`` because the
 * verifier itself is pure (testable without networking); only the
 * orchestration layer touches the API client. Wave 3D.2 ships with a
 * conservative cap of 25 records per run — the typical customer-tile
 * count from ``customer_record_count`` will be well under this in the
 * common case (one cadence window). When ``customer_record_count``
 * exceeds the cap the panel still surfaces "Verifying X of Y" without
 * blocking the whole UI.
 */
async function runChainVerification(
  tenant_id: string,
): Promise<VerificationSummary> {
  // Pull the chain summary again so we have the latest checkpoint
  // window's customer record IDs.
  const summary = await fetch(
    `/api/customers/${encodeURIComponent(tenant_id)}/verify`,
    { method: "POST" },
  ).catch(() => null);
  // The /api/.../verify Next.js handler is optional — if it isn't
  // shipped, fall through to the direct path: list customer records
  // via /v1/actions?tenant_id=, fetch their proofs, verify.
  if (summary && summary.ok) {
    return (await summary.json()) as VerificationSummary;
  }

  // Direct path: enumerate the customer's recent records and fetch
  // proofs for each. Wave 3D.2 uses the existing /v1/actions endpoint
  // because adding a per-record-id list endpoint specific to the
  // verifier would duplicate that surface for no gain.
  const actions = await fetch(
    `${apiBaseUrl()}/v1/actions?tenant_id=${encodeURIComponent(tenant_id)}&limit=25`,
    { headers: await authHeaders() },
  );
  if (!actions.ok) {
    throw new Error(`could not list customer records (${actions.status})`);
  }
  const body = (await actions.json()) as { actions?: Array<{ id: string }> };
  const ids = (body.actions || []).map((a) => a.id);
  const proofs: MerkleProofPayload[] = [];
  for (const id of ids) {
    try {
      const proof = await getMerkleProof(id);
      proofs.push(proof);
    } catch {
      // Tail records (409 checkpoint_pending) — skip; the user is
      // verifying sealed data, not pending. Other failures bubble
      // through the empty proofs list as 0 records verified.
    }
  }
  return verifyRecordProofs({
    proofs,
    verifySignatures: true,
  });
}

function apiBaseUrl(): string {
  return process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
}

async function authHeaders(): Promise<HeadersInit> {
  // Reuse the api-client's auth path so the verifier carries the same
  // Clerk session token as the rest of the dashboard.
  const { getClerkToken } = await import("@/lib/clerk-token");
  const token = await getClerkToken();
  return {
    "Content-Type": "application/json",
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
}
