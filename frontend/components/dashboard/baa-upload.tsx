"use client";

/**
 * BAA upload widget — Phase 1 PR 13.
 *
 * Used in two surfaces:
 *
 *   - The Customer detail "Complete setup" inline wizard (Variant A)
 *   - The Customer detail BAA management section (Variant B), where it
 *     re-uploads to supersede an expiring agreement
 *
 * Phase 1 contract: the user pastes / supplies a pre-signed
 * ``document_uri`` rather than wiring multipart-to-S3. A follow-up will
 * add the actual file upload (browse + drag + S3 PUT); the wire shape
 * does not change.
 *
 * Validation runs client-side as a UX courtesy — the server (see
 * ``schemas/customer.py``'s ``BAAUploadRequest``) is the authoritative
 * check. The widget refuses obvious garbage (empty URI, missing ``://``)
 * before posting so the operator gets immediate feedback.
 *
 * Re-upload semantics: per ``dashboard-design.md`` §Supporting flow —
 * BAA renewal, the new BAA replaces the active one and the old BAA
 * stays in document history. This widget only emits the POST; the
 * supersede semantics live server-side in a follow-up PR.
 */

import * as React from "react";
import { CheckCircle2 } from "lucide-react";

import { Loading } from "@/components/ui/loading";
import { useUploadBaa } from "@/hooks/use-customers";

interface BaaUploadProps {
  tenant_id: string;
  customer_display_name?: string | null;
  /** Render compact (used inside the inline wizard) vs full (full section). */
  variant?: "wizard" | "section";
  onSuccess?: () => void;
}

// Light client-side URI validation. Mirrors the server's
// ``BAAUploadRequest._validate_uri_shape`` — keeping the rules in sync
// avoids a server round-trip for the obvious-garbage case.
function validateDocumentUri(value: string): string | null {
  const trimmed = value.trim();
  if (!trimmed) return "Provide a link to the signed BAA PDF.";
  if (!/^(https?|s3):\/\//i.test(trimmed)) {
    return "Link must start with https://, http://, or s3://.";
  }
  if (trimmed.length > 512) {
    return "Link is too long (max 512 characters).";
  }
  return null;
}

export function BaaUploadWidget({
  tenant_id,
  customer_display_name,
  variant = "wizard",
  onSuccess,
}: BaaUploadProps) {
  const [documentUri, setDocumentUri] = React.useState("");
  const [effectiveAt, setEffectiveAt] = React.useState("");
  const [expiresAt, setExpiresAt] = React.useState("");
  const [clientError, setClientError] = React.useState<string | null>(null);

  const upload = useUploadBaa(tenant_id);

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    setClientError(null);
    const err = validateDocumentUri(documentUri);
    if (err) {
      setClientError(err);
      return;
    }
    // Validate temporal order client-side too — server enforces but
    // we don't want a 400 round-trip for a typo.
    if (effectiveAt && expiresAt && effectiveAt > expiresAt) {
      setClientError("Effective date must be on or before the expiry date.");
      return;
    }

    upload.mutate(
      {
        document_uri: documentUri.trim(),
        effective_at: effectiveAt ? new Date(effectiveAt).toISOString() : null,
        expires_at: expiresAt ? new Date(expiresAt).toISOString() : null,
        is_unrestricted: true,
      },
      {
        onSuccess: () => onSuccess?.(),
      },
    );
  };

  // Success state — show a confirmation message rather than the form.
  // The parent page invalidates the customer query so the populated
  // variant kicks in on the next render; this is the bridge.
  if (upload.isSuccess) {
    return (
      <div
        className="flex items-start gap-3 rounded-md border border-[color:var(--olive)]/30 bg-[color:var(--olive-bg)] p-4"
        data-testid="baa-upload-success"
      >
        <CheckCircle2
          aria-hidden="true"
          className="mt-[2px] size-4 text-[color:var(--olive)]"
        />
        <div className="space-y-1">
          <p className="text-[13px] font-medium text-[color:var(--ink)]">
            BAA in effect{customer_display_name ? ` for ${customer_display_name}` : ""}.
          </p>
          <p className="text-[13px] text-[color:var(--ink-2)]">
            Setup complete — decisions captured for this customer will now
            be included in audit packets.
          </p>
        </div>
      </div>
    );
  }

  const isBusy = upload.isPending;
  const serverError = upload.isError
    ? upload.error?.message ?? "Could not upload BAA. Try again."
    : null;
  const displayedError = clientError ?? serverError;

  return (
    <form
      onSubmit={submit}
      className={
        variant === "wizard"
          ? "space-y-4"
          : "space-y-4 rounded-md border border-[color:var(--ink-4)] bg-[color:var(--paper)] p-5"
      }
      data-testid="baa-upload-form"
      aria-busy={isBusy}
    >
      <div className="space-y-1">
        <label
          htmlFor={`${tenant_id}-baa-uri`}
          className="block text-[11px] font-semibold uppercase tracking-[0.08em] text-[color:var(--ink-2)]"
        >
          Signed BAA link
        </label>
        <input
          id={`${tenant_id}-baa-uri`}
          name="document_uri"
          type="url"
          required
          placeholder="https://… or s3://…"
          value={documentUri}
          onChange={(e) => setDocumentUri(e.target.value)}
          disabled={isBusy}
          className="block w-full rounded-md border border-[color:var(--ink-4)] bg-[color:var(--paper)] px-3 py-2 text-[14px] text-[color:var(--ink)] placeholder:text-[color:var(--ink-3)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-[color:var(--ink)]"
        />
        <p className="text-[12px] text-[color:var(--ink-3)]">
          Paste a link to the signed BAA PDF. File upload ships in a follow-up.
        </p>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <div className="space-y-1">
          <label
            htmlFor={`${tenant_id}-baa-effective`}
            className="block text-[11px] font-semibold uppercase tracking-[0.08em] text-[color:var(--ink-2)]"
          >
            Effective date (optional)
          </label>
          <input
            id={`${tenant_id}-baa-effective`}
            name="effective_at"
            type="date"
            value={effectiveAt}
            onChange={(e) => setEffectiveAt(e.target.value)}
            disabled={isBusy}
            className="block w-full rounded-md border border-[color:var(--ink-4)] bg-[color:var(--paper)] px-3 py-2 text-[14px] text-[color:var(--ink)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-[color:var(--ink)]"
          />
        </div>
        <div className="space-y-1">
          <label
            htmlFor={`${tenant_id}-baa-expires`}
            className="block text-[11px] font-semibold uppercase tracking-[0.08em] text-[color:var(--ink-2)]"
          >
            Expiry date (optional)
          </label>
          <input
            id={`${tenant_id}-baa-expires`}
            name="expires_at"
            type="date"
            value={expiresAt}
            onChange={(e) => setExpiresAt(e.target.value)}
            disabled={isBusy}
            className="block w-full rounded-md border border-[color:var(--ink-4)] bg-[color:var(--paper)] px-3 py-2 text-[14px] text-[color:var(--ink)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-[color:var(--ink)]"
          />
        </div>
      </div>

      {displayedError ? (
        <div
          role="alert"
          className="rounded-md border border-[color:var(--brick)]/30 bg-[color:var(--brick-bg)] px-3 py-2 text-[13px] text-[color:var(--brick)]"
        >
          {displayedError}
        </div>
      ) : null}

      <div className="flex items-center gap-3">
        <button
          type="submit"
          disabled={isBusy}
          className="inline-flex h-9 items-center gap-2 rounded-[10px] bg-[color:var(--ink)] px-4 text-[14px] font-medium text-[color:var(--paper)] transition-colors hover:bg-[color:var(--ink-hover)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--ink)] disabled:cursor-not-allowed disabled:opacity-50"
          data-testid="baa-upload-submit"
        >
          {isBusy ? (
            <>
              <Loading.Spinner size={14} label="Uploading BAA" />
              <span>Uploading…</span>
            </>
          ) : (
            <span>Confirm BAA</span>
          )}
        </button>
      </div>
    </form>
  );
}
