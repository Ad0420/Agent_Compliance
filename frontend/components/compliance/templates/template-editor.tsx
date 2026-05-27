"use client";

/**
 * TemplateEditor — two-pane editor + sticky attestation bar.
 *
 * Phase 5 PR B1. Renders to the right of a Back-to-list affordance on
 * the templates editor view (``/compliance/templates?key=<key>``).
 *
 * Layout (stacked < lg, side-by-side ≥ lg):
 *
 *   ┌──────────────────────┬───────────────────────┐
 *   │ <textarea>           │ <preview pane>        │
 *   │ markdown_body editor │ HTML-rendered preview │
 *   │ (debounced PUT)      │ with marker highlight │
 *   └──────────────────────┴───────────────────────┘
 *   ┌────────────────────────────────────────────────┐
 *   │ Sticky attestation bar (brick border-top)      │
 *   │ ☐ checkbox  [reviewer name]  [Mark / Re-attest]│
 *   └────────────────────────────────────────────────┘
 *
 * Why two panes: the generated body is salted with
 * ``<<REPLACE WITH YOUR ACTUAL PRACTICE>>`` markers that need to be
 * visually obvious. Rendering them inside a textarea is impossible
 * (textareas don't style text); a side-by-side preview keeps the
 * editor experience honest without rebuilding a full Markdown editor.
 *
 * Attestation gesture: the bar disables the submit button until BOTH
 * the checkbox is ticked AND the reviewer name is ≥ 3 chars (matches
 * the backend ``min_length=3`` constraint on ``reviewer_name``).
 */

import * as React from "react";
import Link from "next/link";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { cn } from "@/lib/utils";
import {
  ApiError,
  attestTemplate,
  generateTemplates,
  putTemplate,
  type GeneratedTemplateDetail,
  type TemplateKey,
} from "@/lib/api-client";

import { formatFullDate, formatFullDateTime, renderMarkdownPreviewHtml } from "./format";
import { TEMPLATE_DISPLAY_NAMES } from "./template-metadata";

/** Debounce window for auto-save. 800ms matches the brief. */
const AUTOSAVE_DEBOUNCE_MS = 800;

/** Backend constraint mirror — keep aligned with TemplateAttestRequest. */
export const MIN_REVIEWER_NAME_LENGTH = 3;

export interface TemplateEditorProps {
  detail: GeneratedTemplateDetail;
}

export function TemplateEditor({ detail }: TemplateEditorProps) {
  const key = detail.template_key as TemplateKey;
  const queryClient = useQueryClient();

  // Local body state is seeded from the server detail. Re-seed whenever
  // the upstream record id changes (regenerate, navigation between
  // templates) so we don't drop the user's in-flight edits but DO pick
  // up a fresh refetch.
  const [body, setBody] = React.useState(detail.markdown_body);
  const [reviewerName, setReviewerName] = React.useState("");
  const [counselReviewed, setCounselReviewed] = React.useState(false);
  // ``attestationCleared`` flips on the first successful PUT to a row
  // that had been attested before the edit. The yellow notice below
  // the textarea reads this flag; it stays sticky until the next
  // navigation so the operator doesn't miss it.
  const [attestationCleared, setAttestationCleared] = React.useState(false);

  // Re-seed the textarea when we navigate to a different template (the
  // ``detail`` prop swaps wholesale). We also re-seed when the upstream
  // ``updated_at`` advances past whatever the editor last persisted —
  // that handles regenerate, which rewrites the body server-side.
  const lastSeededUpdatedAt = React.useRef(detail.updated_at);
  const lastSeededKey = React.useRef(detail.template_key);
  React.useEffect(() => {
    if (
      detail.template_key !== lastSeededKey.current ||
      detail.updated_at !== lastSeededUpdatedAt.current
    ) {
      setBody(detail.markdown_body);
      setAttestationCleared(false);
      setCounselReviewed(false);
      setReviewerName("");
      lastSeededKey.current = detail.template_key;
      lastSeededUpdatedAt.current = detail.updated_at;
    }
  }, [detail.template_key, detail.updated_at, detail.markdown_body]);

  // ── Auto-save mutation ───────────────────────────────────────────────
  const putMutation = useMutation({
    mutationFn: (markdown_body: string) => putTemplate(key, markdown_body),
    onSuccess: (next) => {
      // If the server cleared the attestation triple on this PUT, flag
      // it so the reset notice renders. We detect this by checking the
      // *pre-update* status — if it was attested and the response is
      // no longer attested, the backend cleared it.
      if (detail.attested_at !== null && next.attested_at === null) {
        setAttestationCleared(true);
      }
      // Update the cached detail so the editor stays in sync without
      // a full refetch. ``setQueryData`` is safe here because we own
      // the cache key shape.
      queryClient.setQueryData(["templates", key], next);
      // Invalidate the list so the card grid picks up the new status.
      queryClient.invalidateQueries({ queryKey: ["templates"] });
      lastSeededUpdatedAt.current = next.updated_at;
    },
  });

  // Debounce the body → PUT. The deps include ``key`` so swapping
  // templates doesn't fire a save for the previous key.
  React.useEffect(() => {
    if (body === detail.markdown_body) return; // no diff yet
    const timer = setTimeout(() => {
      putMutation.mutate(body);
    }, AUTOSAVE_DEBOUNCE_MS);
    return () => clearTimeout(timer);
    // ``putMutation`` is stable from useMutation; depending on it would
    // re-fire the timer on each render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [body, key, detail.markdown_body]);

  // ── Attest mutation ──────────────────────────────────────────────────
  const attestMutation = useMutation({
    mutationFn: (name: string) => attestTemplate(key, name),
    onSuccess: (next) => {
      queryClient.setQueryData(["templates", key], next);
      queryClient.invalidateQueries({ queryKey: ["templates"] });
      setCounselReviewed(false);
      setReviewerName("");
      setAttestationCleared(false);
      lastSeededUpdatedAt.current = next.updated_at;
    },
  });

  const attestEnabled =
    counselReviewed && reviewerName.trim().length >= MIN_REVIEWER_NAME_LENGTH;
  const isAttested = detail.attested_at !== null;

  const handleAttest = () => {
    if (!attestEnabled || attestMutation.isPending) return;
    attestMutation.mutate(reviewerName.trim());
  };

  const previewHtml = React.useMemo(
    () => renderMarkdownPreviewHtml(body),
    [body],
  );

  return (
    <div className="flex flex-col gap-6">
      {/* Back link + title block */}
      <header className="space-y-3">
        <Link
          href="/compliance/templates"
          aria-label="Back to all templates"
          className={cn(
            "inline-flex items-center gap-1 text-[13px] text-[color:var(--ink-2)] hover:text-[color:var(--ink)]",
            "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--ink)]",
          )}
        >
          <span aria-hidden="true">←</span> All templates
        </Link>
        <h1 className="font-display text-4xl font-normal leading-tight text-[color:var(--ink)]">
          {TEMPLATE_DISPLAY_NAMES[key]}
        </h1>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[12px] text-[color:var(--ink-3)] tabular-nums">
          <span>Generated {formatFullDateTime(detail.generated_at)}</span>
          <span aria-hidden="true">·</span>
          <span>Updated {formatFullDateTime(detail.updated_at)}</span>
          {putMutation.isPending && (
            <span aria-live="polite" className="text-[color:var(--ink-2)]">
              Saving…
            </span>
          )}
        </div>
        {isAttested && (
          <div
            data-testid="templates-attested-badge"
            role="status"
            className="inline-flex items-center gap-2 rounded-[10px] border border-[color:var(--olive)]/30 bg-[color:var(--olive-bg)] px-3 py-2 text-[13px] text-[color:var(--ink)]"
          >
            <span
              aria-hidden="true"
              className="inline-block size-2 rounded-full bg-[color:var(--olive)]"
            />
            <span>
              Counsel-attested by {detail.attested_by_name ?? "—"} on{" "}
              <span className="tabular-nums">
                {formatFullDate(detail.attested_at!)}
              </span>
            </span>
          </div>
        )}
      </header>

      {/* Editor + Preview */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <div className="flex flex-col gap-2">
          <label
            htmlFor="templates-editor-textarea"
            className="text-[12px] uppercase tracking-wide text-[color:var(--ink-3)]"
          >
            Markdown body
          </label>
          <textarea
            id="templates-editor-textarea"
            data-testid="templates-editor-textarea"
            value={body}
            onChange={(e) => setBody(e.target.value)}
            spellCheck={false}
            className={cn(
              "w-full min-h-[60vh] resize-y rounded-[10px] border border-[color:var(--ink-4)] bg-[color:var(--paper)] p-4",
              "font-mono text-[13px] leading-relaxed text-[color:var(--ink)]",
              "focus:outline focus:outline-2 focus:outline-offset-1 focus:outline-[color:var(--ink)]",
            )}
          />
          {attestationCleared && (
            <div
              data-testid="templates-attestation-reset-notice"
              role="status"
              className="rounded-[10px] border border-[color:var(--amber)]/40 bg-[color:var(--amber-bg)] px-3 py-2 text-[13px] text-[color:var(--ink)]"
            >
              Attestation reset — re-attest after counsel review.
            </div>
          )}
          {putMutation.isError && (
            <div
              role="alert"
              data-testid="templates-editor-error"
              className="rounded-[10px] border border-[color:var(--brick)]/40 bg-[color:var(--brick-bg)] px-3 py-2 text-[13px] text-[color:var(--ink)]"
            >
              Could not save changes. Retrying on next edit.
            </div>
          )}
        </div>
        <div className="flex flex-col gap-2">
          <span className="text-[12px] uppercase tracking-wide text-[color:var(--ink-3)]">
            Preview
          </span>
          <div
            data-testid="templates-editor-preview"
            className={cn(
              "min-h-[60vh] overflow-auto rounded-[10px] border border-[color:var(--ink-4)] bg-[color:var(--paper-2)] p-4",
            )}
          >
            <pre
              className="whitespace-pre-wrap break-words font-mono text-[13px] leading-relaxed text-[color:var(--ink)]"
              // ``renderMarkdownPreviewHtml`` HTML-escapes the body and
              // wraps only the literal REPLACE marker in a styled span;
              // this is the lone place the editor injects raw HTML. See
              // the format.ts docstring for the threat-model note.
              dangerouslySetInnerHTML={{ __html: previewHtml }}
            />
          </div>
        </div>
      </div>

      {/* Sticky attestation bar */}
      <div
        className={cn(
          "sticky bottom-0 -mx-2 mt-4 rounded-[10px] border border-t-2 border-[color:var(--ink-4)] border-t-[color:var(--brick)] bg-[color:var(--paper)] px-4 py-4 shadow-[0_-4px_12px_rgba(31,22,16,0.06)]",
        )}
      >
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex items-start gap-3">
            <input
              id="templates-attest-checkbox"
              data-testid="templates-attest-checkbox"
              type="checkbox"
              checked={counselReviewed}
              onChange={(e) => setCounselReviewed(e.target.checked)}
              className="mt-1 size-4 cursor-pointer accent-[color:var(--ink)]"
            />
            <label
              htmlFor="templates-attest-checkbox"
              className="text-[13px] leading-snug text-[color:var(--ink)]"
            >
              {isAttested
                ? "Re-attest after editing — counsel has re-reviewed this document and I attest the statements reflect my organization's actual practices."
                : "Counsel has reviewed this document. I attest the statements reflect my organization's actual practices."}
            </label>
          </div>
          <div className="flex flex-col gap-2 lg:flex-row lg:items-center">
            <input
              data-testid="templates-attest-reviewer-name"
              type="text"
              placeholder="Reviewer name"
              value={reviewerName}
              onChange={(e) => setReviewerName(e.target.value)}
              minLength={MIN_REVIEWER_NAME_LENGTH}
              className={cn(
                "rounded-[10px] border border-[color:var(--ink-4)] bg-[color:var(--paper)] px-3 py-2 text-[13px] text-[color:var(--ink)]",
                "focus:outline focus:outline-2 focus:outline-offset-1 focus:outline-[color:var(--ink)]",
                "lg:w-56",
              )}
            />
            <button
              type="button"
              data-testid="templates-attest-button"
              onClick={handleAttest}
              disabled={!attestEnabled || attestMutation.isPending}
              className={cn(
                "rounded-[10px] border px-4 py-2 text-[13px] font-medium transition-colors",
                "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--ink)]",
                attestEnabled && !attestMutation.isPending
                  ? "border-[color:var(--ink)] bg-[color:var(--ink)] text-[color:var(--paper)] hover:bg-[color:var(--ink-hover)]"
                  : "cursor-not-allowed border-[color:var(--ink-4)] bg-[color:var(--paper-2)] text-[color:var(--ink-3)]",
              )}
            >
              {attestMutation.isPending
                ? "Saving…"
                : isAttested
                  ? "Re-attest"
                  : "Mark counsel-reviewed"}
            </button>
          </div>
        </div>
        {attestMutation.isError && (
          <p
            role="alert"
            data-testid="templates-attest-error"
            className="mt-2 text-[12px] text-[color:var(--brick)]"
          >
            {attestMutation.error instanceof ApiError
              ? attestMutation.error.message
              : "Could not record attestation. Try again."}
          </p>
        )}
      </div>
    </div>
  );
}

/**
 * EmptyTemplateState — rendered when the per-key GET returns 404
 * (the row doesn't exist yet). Offers a generate button that calls
 * the idempotent ``POST /v1/templates/generate``.
 */
export interface EmptyTemplateStateProps {
  templateKey: TemplateKey;
  onGenerated?: () => void;
}

export function EmptyTemplateState({
  templateKey,
  onGenerated,
}: EmptyTemplateStateProps) {
  const queryClient = useQueryClient();
  const mutation = useMutation({
    mutationFn: generateTemplates,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["templates"] });
      queryClient.invalidateQueries({ queryKey: ["templates", templateKey] });
      onGenerated?.();
    },
  });

  return (
    <div className="flex flex-col gap-6">
      <header className="space-y-2">
        <Link
          href="/compliance/templates"
          aria-label="Back to all templates"
          className="inline-flex items-center gap-1 text-[13px] text-[color:var(--ink-2)] hover:text-[color:var(--ink)]"
        >
          <span aria-hidden="true">←</span> All templates
        </Link>
        <h1 className="font-display text-4xl font-normal leading-tight text-[color:var(--ink)]">
          {TEMPLATE_DISPLAY_NAMES[templateKey]}
        </h1>
      </header>
      <div className="rounded-[14px] border border-[color:var(--ink-4)] bg-[color:var(--paper-2)] p-6 text-[14px] text-[color:var(--ink)]">
        <p className="mb-4">This template hasn&apos;t been generated yet.</p>
        <button
          type="button"
          data-testid="templates-generate-this-button"
          onClick={() => mutation.mutate()}
          disabled={mutation.isPending}
          className={cn(
            "rounded-[10px] border border-[color:var(--ink)] bg-[color:var(--ink)] px-4 py-2 text-[13px] font-medium text-[color:var(--paper)]",
            "hover:bg-[color:var(--ink-hover)]",
            "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--ink)]",
            "disabled:cursor-not-allowed disabled:opacity-60",
          )}
        >
          {mutation.isPending ? "Generating…" : "Generate this template"}
        </button>
        {mutation.isError && (
          <p
            role="alert"
            className="mt-3 text-[13px] text-[color:var(--brick)]"
          >
            {mutation.error instanceof ApiError
              ? mutation.error.message
              : "Could not generate templates. Try again."}
          </p>
        )}
      </div>
    </div>
  );
}
