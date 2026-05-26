"use client";

/**
 * ChainIntegrityTile — Phase 3 Wave 3D.1.
 *
 * The at-a-glance "is our evidence trail intact right now?" tile that
 * lives in the Home page Chain integrity section. Reads from the new
 * ``GET /v1/dashboard/chain-integrity`` aggregate so all five rendered
 * facts (status, latest checkpoint, chain depth, KMS key, cadence)
 * land in one round-trip.
 *
 * Audience: CEOs / in-house counsel of regulated AI vendors. No
 * engineering vernacular — we render a short KMS key prefix and an
 * algorithm label, never the raw signature or full key ARN. Per the
 * voice rules: "Customer" not "Tenant", "evidence trail" rather than
 * the engineering-vocab alternatives, full dates with year, comma-
 * separated numbers, ``tabular-nums`` on every digit column.
 *
 * No skeleton screens (per ``dashboard-design-system.md`` §Loading
 * state — "skeletons read as marketing slop"). The loading state
 * renders a static placeholder block matching the loaded tile's
 * geometry so the page doesn't jump.
 */

import * as React from "react";
import Link from "next/link";

import { Loading } from "@/components/ui/loading";
import { StatusDot, type StatusVariant } from "@/components/ui/status-indicator";
import type {
  ChainIntegrityResponse,
  ChainIntegrityStatus,
  CheckpointCadence,
} from "@/lib/api-types";
import { cn } from "@/lib/utils";

// ── Pure formatting helpers ───────────────────────────────────────────

/**
 * Full-date format with year + UTC time. Per the voice rules, we
 * always show the year ("Mar 15, 2026 at 14:30 UTC", not "Mar 15").
 *
 * Exported so component-contract tests can lock the shape.
 */
export function formatSealedAt(iso: string): string {
  // ``sealed_at`` from the backend is an ISO-8601 timestamp without
  // timezone (the column stores naive UTC). We append ``Z`` so the
  // browser parses it as UTC; otherwise it would be interpreted as
  // local time and the rendered string would shift per user timezone.
  // copy-allow: ISO suffix, not user-visible date text.
  const utcIso = iso.endsWith("Z") || /[+-]\d{2}:?\d{2}$/.test(iso) ? iso : `${iso}Z`;
  const d = new Date(utcIso);
  if (Number.isNaN(d.getTime())) return iso;
  const datePart = new Intl.DateTimeFormat("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  }).format(d);
  const timePart = new Intl.DateTimeFormat("en-US", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: "UTC",
  }).format(d);
  return `Sealed ${datePart} at ${timePart} UTC`;
}

/**
 * Comma-separated integer — "12,500" not "12500", never "12.5K" (per
 * voice spec).
 */
export function formatCount(n: number): string {
  return new Intl.NumberFormat("en-US").format(n);
}

/** Short fingerprint for the KMS key. Keeps the tile uncluttered. */
export function shortKeyId(keyId: string): string {
  if (keyId.length <= 12) return keyId;
  return `${keyId.slice(0, 8)}…${keyId.slice(-4)}`;
}

/** Short fingerprint for a checkpoint UUID. */
export function shortCheckpointId(id: string): string {
  if (id.length <= 8) return id;
  return id.slice(0, 8);
}

const cadenceLabel: Record<CheckpointCadence, string> = {
  hourly: "Hourly",
  daily: "Daily",
  disabled: "Disabled",
};

const statusToVariant: Record<ChainIntegrityStatus, StatusVariant> = {
  ok: "ok",
  warn: "warn",
  error: "error",
};

const statusToLabel: Record<ChainIntegrityStatus, string> = {
  ok: "Evidence trail intact",
  warn: "Checkpoint overdue",
  error: "Evidence trail at risk",
};

// ── Component ─────────────────────────────────────────────────────────

export interface ChainIntegrityTileProps {
  loading: boolean;
  data: ChainIntegrityResponse | undefined;
  /**
   * Destination for the "Download evidence bundle" CTA. Wave 3D.2
   * (Customer Verification panel) owns the actual destination; we
   * accept it as a prop so this tile doesn't hard-code a route that
   * the parallel wave is still placing. Default ``/customers``.
   */
  evidenceBundleHref?: string;
  /**
   * Destination for the "View key history" link. The history page
   * lands in a follow-up; until then we link to ``/settings`` as the
   * placeholder home for KMS configuration (documented in the PR
   * body so the gap is tracked). Override via prop when the page
   * lands.
   */
  kmsKeyHistoryHref?: string;
}

export function ChainIntegrityTile({
  loading,
  data,
  evidenceBundleHref = "/customers",
  kmsKeyHistoryHref = "/settings",
}: ChainIntegrityTileProps) {
  if (loading || !data) {
    return (
      <div
        aria-busy="true"
        data-testid="chain-integrity-tile-loading"
        className="rounded-[10px] border border-[color:var(--ink-4)] bg-[color:var(--paper-2)] p-5"
      >
        <div className="flex h-6 items-center text-[color:var(--ink-3)]">
          <Loading.Spinner size={14} label="Loading chain integrity" />
        </div>
      </div>
    );
  }

  const variant = statusToVariant[data.status];
  const statusLabel = statusToLabel[data.status];

  return (
    <article
      data-testid="chain-integrity-tile"
      data-status={data.status}
      className={cn(
        "rounded-[10px] border border-[color:var(--ink-4)] bg-[color:var(--paper-2)] p-5",
        "shadow-[var(--shadow-1)]",
      )}
    >
      {/* Header row: status + cadence */}
      <header className="flex items-start justify-between gap-4">
        <div className="space-y-1.5">
          <StatusDot variant={variant} label={statusLabel} />
          <p className="text-[13px] text-[color:var(--ink-2)]">
            {data.message}
          </p>
        </div>
        <dl className="text-right">
          <dt className="sr-only">Checkpoint cadence</dt>
          <dd className="text-[11px] font-semibold uppercase tracking-[0.1em] text-[color:var(--ink-3)]">
            {cadenceLabel[data.cadence]}
          </dd>
          <dt className="sr-only">Cadence label</dt>
          <dd className="text-[11px] text-[color:var(--ink-3)]">
            cadence
          </dd>
        </dl>
      </header>

      {/* Facts grid: latest checkpoint, chain depth, KMS key */}
      <dl className="mt-4 grid grid-cols-1 gap-4 border-t border-[color:var(--ink-4)] pt-4 sm:grid-cols-3">
        {/* Latest checkpoint */}
        <div className="space-y-1">
          <dt className="text-[11px] font-semibold uppercase tracking-[0.1em] text-[color:var(--ink-3)]">
            Latest checkpoint
          </dt>
          <dd className="text-[13px] text-[color:var(--ink)] tabular-nums">
            {data.latest_checkpoint ? (
              <>
                <span className="font-mono">
                  {shortCheckpointId(data.latest_checkpoint.checkpoint_id)}
                </span>
                <span className="block text-[color:var(--ink-2)] tabular-nums">
                  {formatSealedAt(data.latest_checkpoint.sealed_at)}
                </span>
                <span className="block text-[color:var(--ink-2)] tabular-nums">
                  {formatCount(data.latest_checkpoint.record_count)} record
                  {data.latest_checkpoint.record_count === 1 ? "" : "s"}{" "}
                  sealed
                </span>
              </>
            ) : (
              <span className="text-[color:var(--ink-2)]">
                No checkpoint sealed yet.
              </span>
            )}
          </dd>
        </div>

        {/* Chain depth */}
        <div className="space-y-1">
          <dt className="text-[11px] font-semibold uppercase tracking-[0.1em] text-[color:var(--ink-3)]">
            Chain depth
          </dt>
          <dd className="text-[13px] text-[color:var(--ink)] tabular-nums">
            {formatCount(data.chain_depth)} sealed checkpoint
            {data.chain_depth === 1 ? "" : "s"}
          </dd>
        </div>

        {/* KMS key */}
        <div className="space-y-1">
          <dt className="text-[11px] font-semibold uppercase tracking-[0.1em] text-[color:var(--ink-3)]">
            Signing key
          </dt>
          <dd className="text-[13px] text-[color:var(--ink)] tabular-nums">
            {data.kms_key ? (
              <>
                <span className="font-mono">
                  {shortKeyId(data.kms_key.key_id)}
                </span>
                <span className="block text-[color:var(--ink-2)]">
                  {data.kms_key.algorithm}
                </span>
                <Link
                  href={kmsKeyHistoryHref}
                  className="mt-0.5 inline-block text-[12px] text-[color:var(--ink-2)] underline-offset-2 hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--ink)]"
                >
                  View key history →
                </Link>
              </>
            ) : (
              <span className="text-[color:var(--ink-2)]">Not configured.</span>
            )}
          </dd>
        </div>
      </dl>

      {/* CTA row */}
      <footer className="mt-5 flex items-center justify-end border-t border-[color:var(--ink-4)] pt-4">
        <Link
          href={evidenceBundleHref}
          data-testid="chain-integrity-tile-cta"
          className="inline-flex items-center gap-1 text-[13px] font-medium text-[color:var(--ink)] underline-offset-2 hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--ink)]"
        >
          Download evidence bundle
          <span aria-hidden="true">→</span>
        </Link>
      </footer>
    </article>
  );
}
