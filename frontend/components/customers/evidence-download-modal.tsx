// Evidence bundle download confirmation modal — Wave 3D.2.
//
// Three states:
//
//   1. Initial — user picks a date range (default last 90 days) and
//      hits "Preview". The modal calls the preview endpoint, which
//      returns counts + warnings, and renders the selective-disclosure
//      preview line ("This export will contain X records belonging
//      only to {customer_name}").
//   2. Preview shown — user can either back out or hit "Download".
//      Downloading streams the tar.gz to the browser via the existing
//      ``downloadEvidenceBundle`` helper (same code path the CSV /
//      PDF exports use).
//   3. Done — modal closes; the panel reflects the new "Last
//      downloaded" hint on next refresh.

"use client";

import * as React from "react";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  downloadEvidenceBundle,
  previewEvidenceExport,
} from "@/lib/api-client";
import type { EvidenceExportPreview } from "@/lib/api-types";

interface EvidenceDownloadModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  tenant_id: string;
  customer_display_name: string;
}

function defaultStart(): string {
  const d = new Date();
  d.setUTCDate(d.getUTCDate() - 89);
  return d.toISOString().slice(0, 10);
}

function defaultEnd(): string {
  return new Date().toISOString().slice(0, 10);
}

export function EvidenceDownloadModal({
  open,
  onOpenChange,
  tenant_id,
  customer_display_name,
}: EvidenceDownloadModalProps) {
  const [start, setStart] = React.useState<string>(defaultStart);
  const [end, setEnd] = React.useState<string>(defaultEnd);
  const [preview, setPreview] = React.useState<EvidenceExportPreview | null>(
    null,
  );
  const [loading, setLoading] = React.useState(false);
  const [downloading, setDownloading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [done, setDone] = React.useState<string | null>(null);

  // Reset modal state every time it opens — otherwise a previous
  // preview leaks into a fresh modal session.
  React.useEffect(() => {
    if (open) {
      setStart(defaultStart());
      setEnd(defaultEnd());
      setPreview(null);
      setError(null);
      setDone(null);
    }
  }, [open]);

  const onPreview = React.useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await previewEvidenceExport(tenant_id, {
        start_date: start,
        end_date: end,
      });
      setPreview(result);
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Preview failed";
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, [tenant_id, start, end]);

  const onDownload = React.useCallback(async () => {
    setDownloading(true);
    setError(null);
    try {
      const { filename } = await downloadEvidenceBundle(tenant_id, {
        start_date: start,
        end_date: end,
      });
      setDone(filename);
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Download failed";
      setError(msg);
    } finally {
      setDownloading(false);
    }
  }, [tenant_id, start, end]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="max-w-lg"
        data-testid="evidence-download-modal"
      >
        <DialogHeader>
          <DialogTitle>Download evidence bundle</DialogTitle>
          <DialogDescription>
            Generate a regulator-ready evidence bundle scoped to{" "}
            <span className="text-[color:var(--ink)]">
              {customer_display_name}
            </span>
            . Other customers&apos; records are not included.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <label className="flex flex-col gap-1 text-[12px] text-[color:var(--ink-2)]">
              Start date
              <input
                type="date"
                value={start}
                onChange={(e) => {
                  setStart(e.target.value);
                  setPreview(null);
                }}
                disabled={loading || downloading}
                className="block rounded-md border border-[color:var(--ink-4)] bg-[color:var(--paper)] px-3 py-2 text-[14px] text-[color:var(--ink)] tabular-nums focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-[color:var(--ink)]"
                data-testid="evidence-start-date"
              />
            </label>
            <label className="flex flex-col gap-1 text-[12px] text-[color:var(--ink-2)]">
              End date
              <input
                type="date"
                value={end}
                onChange={(e) => {
                  setEnd(e.target.value);
                  setPreview(null);
                }}
                disabled={loading || downloading}
                className="block rounded-md border border-[color:var(--ink-4)] bg-[color:var(--paper)] px-3 py-2 text-[14px] text-[color:var(--ink)] tabular-nums focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-[color:var(--ink)]"
                data-testid="evidence-end-date"
              />
            </label>
          </div>
          <p className="text-[12px] text-[color:var(--ink-3)]">
            Format: gzipped tarball (.tar.gz) containing
            <code className="mx-1 rounded-sm bg-[color:var(--paper-2)] px-1 py-0.5 text-[11px] text-[color:var(--ink-2)]">
              manifest.json
            </code>{" "}
            +{" "}
            <code className="mx-1 rounded-sm bg-[color:var(--paper-2)] px-1 py-0.5 text-[11px] text-[color:var(--ink-2)]">
              checkpoints/
            </code>{" "}
            +{" "}
            <code className="mx-1 rounded-sm bg-[color:var(--paper-2)] px-1 py-0.5 text-[11px] text-[color:var(--ink-2)]">
              records/
            </code>
            . Verifies with{" "}
            <code className="mx-1 rounded-sm bg-[color:var(--paper-2)] px-1 py-0.5 text-[11px] text-[color:var(--ink-2)]">
              vera verify --offline
            </code>
            .
          </p>

          {preview ? (
            <div
              className="space-y-2 rounded-md border border-[color:var(--ink-4)] bg-[color:var(--paper-2)] p-3"
              data-testid="evidence-preview"
            >
              <p className="text-[13px] text-[color:var(--ink)]">
                This export will contain{" "}
                <span className="font-semibold tabular-nums">
                  {preview.customer_record_count.toLocaleString()}
                </span>{" "}
                record
                {preview.customer_record_count === 1 ? "" : "s"} belonging
                only to{" "}
                <span className="text-[color:var(--ink)]">
                  {preview.customer_display_name ?? tenant_id}
                </span>
                . Other customers&apos; records are not included.
              </p>
              <p className="text-[12px] tabular-nums text-[color:var(--ink-2)]">
                Spans {preview.checkpoint_count.toLocaleString()} checkpoint
                {preview.checkpoint_count === 1 ? "" : "s"} between{" "}
                {preview.date_range.start} and {preview.date_range.end}.
              </p>
              {preview.warnings.length > 0 ? (
                <ul className="space-y-1 text-[12px] text-[color:var(--amber)]">
                  {preview.warnings.map((w) => (
                    <li key={w}>{warningCopy(w)}</li>
                  ))}
                </ul>
              ) : null}
            </div>
          ) : null}

          {done ? (
            <p
              className="text-[13px] text-[color:var(--olive)]"
              data-testid="evidence-done"
            >
              Downloaded{" "}
              <code className="text-[12px] tabular-nums text-[color:var(--ink)]">
                {done}
              </code>
              .
            </p>
          ) : null}

          {error ? (
            <p
              className="text-[13px] text-[color:var(--error)]"
              data-testid="evidence-error"
            >
              {error}
            </p>
          ) : null}
        </div>

        <DialogFooter>
          <button
            type="button"
            onClick={() => onOpenChange(false)}
            className="inline-flex h-9 items-center justify-center rounded-[10px] border border-[color:var(--ink-4)] px-4 text-[14px] font-medium text-[color:var(--ink-2)] transition-colors hover:bg-[color:var(--paper-2)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--ink)]"
          >
            Close
          </button>
          {preview ? (
            <button
              type="button"
              onClick={onDownload}
              disabled={downloading || preview.customer_record_count === 0}
              className="inline-flex h-9 items-center justify-center rounded-[10px] border border-[color:var(--ink)] bg-[color:var(--ink)] px-4 text-[14px] font-medium text-[color:var(--paper)] transition-colors hover:bg-[color:var(--ink-2)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--ink)] disabled:cursor-not-allowed disabled:opacity-50"
              data-testid="evidence-download-confirm"
            >
              {downloading ? "Downloading…" : "Download"}
            </button>
          ) : (
            <button
              type="button"
              onClick={onPreview}
              disabled={loading || !start || !end || start > end}
              className="inline-flex h-9 items-center justify-center rounded-[10px] border border-[color:var(--ink)] bg-[color:var(--ink)] px-4 text-[14px] font-medium text-[color:var(--paper)] transition-colors hover:bg-[color:var(--ink-2)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--ink)] disabled:cursor-not-allowed disabled:opacity-50"
              data-testid="evidence-preview-trigger"
            >
              {loading ? "Loading preview…" : "Preview"}
            </button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function warningCopy(code: string): string {
  if (code === "hmac_chain_no_offline_signature_verify") {
    return "Heads-up: this chain uses an HMAC key. The bundle's Merkle paths verify without secrets, but the checkpoint signature itself requires the shared HMAC secret (held out-of-band by your team).";
  }
  if (code === "tail_records_excluded") {
    return "Heads-up: some records in this date range have not yet been sealed into a checkpoint. They will be included once the next cadence tick seals them.";
  }
  return code;
}
