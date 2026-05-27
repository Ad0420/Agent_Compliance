// Generate Audit PDF modal — Phase 4 Wave 1 PR C3-scaffold.
//
// Pattern C (centered modal — see dashboard-design-system.md §Pattern C).
// Triggered from the Customer detail header; submits a synchronous
// POST /v1/audits/{customer_id} (Stream A1) and streams the returned
// PDF blob to a browser download.
//
// Form fields:
//   - Sections to include — 8 checkboxes, all on by default
//   - Date range — from / to, default last 30 days
//   - Branding — Customer-branded (default) / Vera-neutral
//
// Submit state shows an inline spinner on the primary button; modal
// stays open until the render finishes (~5-30s) or fails. On success
// the blob auto-downloads silently (no toast, per CLAUDE.md "no
// marketing chrome on the dashboard").
//
// Error mapping (stable codes from A1 contract):
//   - baa_expired         → "BAA expired — renew on Settings → BAA Management"
//   - pdf_render_timeout  → "Generation timed out — retry in a moment"
//   - default             → "Failed to generate audit PDF"
//
// Out of scope here (C4 / v1.1):
//   - Section-by-section progress bar (backend is sync, only a spinner)
//   - Cancel mid-render
//   - "Generated PDFs history" table
//   - "Renew BAA" deep-link button on the error banner

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
import { Checkbox } from "@/components/ui/checkbox";
import { RadioGroup, RadioOption } from "@/components/ui/radio-group";
import { Loading } from "@/components/ui/loading";
import {
  AUDIT_PDF_ERROR_CODES,
  AUDIT_PDF_SECTION_KEYS,
  generateAuditPdf,
  readAuditPdfErrorCode,
  type AuditPdfBranding,
  type AuditPdfSectionKey,
} from "@/lib/api-client";

interface AuditPdfModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  customer_id: string;
  customer_display_name: string;
}

// Plain-English labels. Order matches AUDIT_PDF_SECTION_KEYS so the
// modal renders in spec order and the body we POST is deterministic.
const SECTION_LABELS: Record<AuditPdfSectionKey, string> = {
  cover: "Cover page",
  scope: "Scope of AI use",
  audit_controls: "Audit controls (HIPAA § 164.312(b))",
  hitl_evidence: "HITL evidence",
  demographic_monitoring: "Demographic monitoring (§ 92.210)",
  workforce_training: "Workforce training",
  baa_chain: "BAA chain",
  technical_appendix: "Technical appendix",
};

// Formats a YYYY-MM-DD date string as "Apr 26, 2026" for display next
// to the inputs. Per CLAUDE.md, dashboard dates always include the year.
function formatDateLong(iso: string): string {
  if (!iso) return "";
  // Parse as UTC date-only to avoid the off-by-one timezone shift the
  // ``new Date("2026-04-26")`` constructor inflicts on browsers in
  // negative-UTC-offset locales.
  const [yStr, mStr, dStr] = iso.split("-");
  const y = Number(yStr);
  const m = Number(mStr);
  const d = Number(dStr);
  if (!y || !m || !d) return iso;
  const months = [
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
  ];
  return `${months[m - 1]} ${d}, ${y}`;
}

function isoToday(): string {
  return new Date().toISOString().slice(0, 10);
}

function isoDaysAgo(days: number): string {
  const d = new Date();
  d.setUTCDate(d.getUTCDate() - days);
  return d.toISOString().slice(0, 10);
}

// Pure error-code → inline-banner copy mapping. Exported so the test
// file can pin the contract — if a banner string changes the test
// regresses.
export function mapAuditPdfErrorMessage(code: string | null): string {
  if (code === AUDIT_PDF_ERROR_CODES.baaExpired) {
    return "BAA expired — renew on Settings › BAA Management.";
  }
  if (code === AUDIT_PDF_ERROR_CODES.pdfRenderTimeout) {
    return "Generation timed out — retry in a moment.";
  }
  return "Failed to generate audit PDF.";
}

// Pure helper exported for the test file to pin the default range.
export function defaultDateRange(): { from: string; to: string } {
  return { from: isoDaysAgo(30), to: isoToday() };
}

export function AuditPdfModal({
  open,
  onOpenChange,
  customer_id,
  customer_display_name,
}: AuditPdfModalProps) {
  const [sections, setSections] = React.useState<Set<AuditPdfSectionKey>>(
    () => new Set(AUDIT_PDF_SECTION_KEYS),
  );
  const initial = defaultDateRange();
  const [dateFrom, setDateFrom] = React.useState(initial.from);
  const [dateTo, setDateTo] = React.useState(initial.to);
  const [branding, setBranding] = React.useState<AuditPdfBranding>("customer");
  const [submitting, setSubmitting] = React.useState(false);
  const [errorMessage, setErrorMessage] = React.useState<string | null>(null);

  // Reset form every time the modal re-opens — a stale section toggle
  // from a previous session shouldn't leak into a fresh attempt.
  React.useEffect(() => {
    if (open) {
      setSections(new Set(AUDIT_PDF_SECTION_KEYS));
      const fresh = defaultDateRange();
      setDateFrom(fresh.from);
      setDateTo(fresh.to);
      setBranding("customer");
      setSubmitting(false);
      setErrorMessage(null);
    }
  }, [open]);

  const dateRangeInvalid = !dateFrom || !dateTo || dateFrom > dateTo;
  const noSections = sections.size === 0;
  const primaryDisabled = submitting || dateRangeInvalid || noSections;

  const toggleSection = React.useCallback((key: AuditPdfSectionKey) => {
    setSections((prev) => {
      const next = new Set(prev);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  }, []);

  const onSubmit = React.useCallback(async () => {
    if (primaryDisabled) return;
    setSubmitting(true);
    setErrorMessage(null);
    try {
      // Preserve the spec section order in the POST body — sets don't
      // preserve insertion order across all engines reliably for our
      // purposes, and the backend canonicalises on this order.
      const orderedSections = AUDIT_PDF_SECTION_KEYS.filter((k) =>
        sections.has(k),
      );
      await generateAuditPdf(customer_id, {
        date_from: dateFrom,
        date_to: dateTo,
        sections: orderedSections,
        branding,
      });
      // Silent close on success per "no marketing chrome" rule.
      onOpenChange(false);
    } catch (e) {
      const code = readAuditPdfErrorCode(e);
      setErrorMessage(mapAuditPdfErrorMessage(code));
    } finally {
      setSubmitting(false);
    }
  }, [
    primaryDisabled,
    sections,
    dateFrom,
    dateTo,
    branding,
    customer_id,
    onOpenChange,
  ]);

  return (
    <Dialog open={open} onOpenChange={submitting ? undefined : onOpenChange}>
      <DialogContent className="max-w-lg" data-testid="audit-pdf-modal">
        <DialogHeader>
          <DialogTitle>Generate audit PDF</DialogTitle>
          <DialogDescription>
            Compile a regulator-ready audit for{" "}
            <span className="text-[color:var(--ink)]">
              {customer_display_name}
            </span>
            . Other customers&apos; records are not included.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-5">
          {/* Section 1 — Sections to include */}
          <fieldset className="space-y-2" data-testid="audit-pdf-sections">
            <legend className="mb-1 text-[12px] font-medium uppercase tracking-[0.06em] text-[color:var(--ink-2)]">
              Sections to include
            </legend>
            <div className="grid grid-cols-1 gap-1 sm:grid-cols-2">
              {AUDIT_PDF_SECTION_KEYS.map((key) => (
                <Checkbox
                  key={key}
                  label={SECTION_LABELS[key]}
                  checked={sections.has(key)}
                  onChange={() => toggleSection(key)}
                  disabled={submitting}
                  data-testid={`audit-pdf-section-${key}`}
                />
              ))}
            </div>
          </fieldset>

          {/* Section 2 — Date range */}
          <fieldset className="space-y-2" data-testid="audit-pdf-date-range">
            <legend className="mb-1 text-[12px] font-medium uppercase tracking-[0.06em] text-[color:var(--ink-2)]">
              Date range
            </legend>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <label className="flex flex-col gap-1 text-[12px] text-[color:var(--ink-2)]">
                From
                <input
                  type="date"
                  value={dateFrom}
                  onChange={(e) => setDateFrom(e.target.value)}
                  disabled={submitting}
                  className="block rounded-md border border-[color:var(--ink-4)] bg-[color:var(--paper)] px-3 py-2 text-[14px] text-[color:var(--ink)] tabular-nums focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-[color:var(--ink)]"
                  data-testid="audit-pdf-date-from"
                />
                <span className="text-[11px] tabular-nums text-[color:var(--ink-3)]">
                  {formatDateLong(dateFrom)}
                </span>
              </label>
              <label className="flex flex-col gap-1 text-[12px] text-[color:var(--ink-2)]">
                To
                <input
                  type="date"
                  value={dateTo}
                  onChange={(e) => setDateTo(e.target.value)}
                  disabled={submitting}
                  className="block rounded-md border border-[color:var(--ink-4)] bg-[color:var(--paper)] px-3 py-2 text-[14px] text-[color:var(--ink)] tabular-nums focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-[color:var(--ink)]"
                  data-testid="audit-pdf-date-to"
                />
                <span className="text-[11px] tabular-nums text-[color:var(--ink-3)]">
                  {formatDateLong(dateTo)}
                </span>
              </label>
            </div>
            {dateRangeInvalid && dateFrom && dateTo ? (
              <p
                className="text-[12px] text-[color:var(--brick)]"
                data-testid="audit-pdf-date-error"
              >
                End date must be on or after start date.
              </p>
            ) : null}
          </fieldset>

          {/* Section 3 — Branding */}
          <RadioGroup
            name="audit-pdf-branding"
            value={branding}
            onChange={(v) => setBranding(v as AuditPdfBranding)}
            disabled={submitting}
            label="Branding"
          >
            <RadioOption
              value="customer"
              label="Customer-branded"
              description={`Cover page and footer carry ${customer_display_name}'s name.`}
            />
            <RadioOption
              value="vera-neutral"
              label="Vera-neutral"
              description="Cover page and footer carry the Vera mark only."
            />
          </RadioGroup>

          {errorMessage ? (
            <div
              role="alert"
              className="rounded-md border border-[color:var(--brick)]/30 bg-[color:var(--paper-2)] px-3 py-2 text-[13px] text-[color:var(--brick)]"
              data-testid="audit-pdf-error"
            >
              {errorMessage}
            </div>
          ) : null}
        </div>

        <DialogFooter>
          <button
            type="button"
            onClick={() => onOpenChange(false)}
            disabled={submitting}
            className="inline-flex h-9 items-center justify-center rounded-[10px] border border-[color:var(--ink-4)] px-4 text-[14px] font-medium text-[color:var(--ink-2)] transition-colors hover:bg-[color:var(--paper-2)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--ink)] disabled:cursor-not-allowed disabled:opacity-50"
            data-testid="audit-pdf-cancel"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onSubmit}
            disabled={primaryDisabled}
            className="inline-flex h-9 items-center justify-center gap-2 rounded-[10px] border border-[color:var(--ink)] bg-[color:var(--ink)] px-4 text-[14px] font-medium text-[color:var(--paper)] transition-colors hover:bg-[color:var(--ink-2)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--ink)] disabled:cursor-not-allowed disabled:opacity-50"
            data-testid="audit-pdf-submit"
          >
            {submitting ? (
              <>
                <Loading.Spinner
                  size={12}
                  label="Generating audit PDF"
                  className="text-[color:var(--paper)]"
                />
                <span>Generating audit PDF…</span>
              </>
            ) : (
              <span>Generate audit PDF</span>
            )}
          </button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
