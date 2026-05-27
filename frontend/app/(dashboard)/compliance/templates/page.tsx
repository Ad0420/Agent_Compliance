"use client";

/**
 * /compliance/templates — Phase 5 PR B1.
 *
 * Customer-facing surface for the five counsel-attestable compliance
 * templates. Two views switch on a ``?key=<template_key>`` URL search
 * param:
 *
 *   * No param            → list view (5-card grid + regenerate button)
 *   * ?key=<template_key> → editor view (markdown body + preview +
 *                          sticky attestation bar)
 *
 * Data flow:
 *   * List view fetches ``GET /v1/templates`` (always 5 items, missing
 *     rows synthesised as ``not_started`` stubs).
 *   * Editor view fetches ``GET /v1/templates/{key}``; on 404 it
 *     renders the empty-state with a generate CTA.
 *
 * The page intentionally mirrors the shape of
 * ``app/(dashboard)/compliance/page.tsx`` so the navigation, header,
 * and error-banner conventions stay consistent across the section.
 */

import * as React from "react";
import { useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Skeleton } from "@/components/ui/skeleton";

import {
  ApiError,
  generateTemplates,
  getTemplate,
  getTemplates,
  readTemplatesErrorCode,
  TEMPLATE_KEYS,
  TEMPLATES_ERROR_CODES,
  type TemplateKey,
} from "@/lib/api-client";

import { TemplateCard } from "@/components/compliance/templates/template-card";
import {
  EmptyTemplateState,
  TemplateEditor,
} from "@/components/compliance/templates/template-editor";

const VALID_KEYS = new Set<string>(TEMPLATE_KEYS);

function isTemplateKey(value: string | null): value is TemplateKey {
  return typeof value === "string" && VALID_KEYS.has(value);
}

export default function TemplatesPage() {
  const searchParams = useSearchParams();
  const rawKey = searchParams.get("key");
  const key = isTemplateKey(rawKey) ? rawKey : null;

  return (
    <div className="mx-auto max-w-6xl space-y-8 py-2">
      {key === null ? <TemplatesListView /> : <TemplatesEditorView templateKey={key} />}
    </div>
  );
}

// ── List view ────────────────────────────────────────────────────────

function TemplatesListView() {
  const queryClient = useQueryClient();
  const list = useQuery({
    queryKey: ["templates"],
    queryFn: getTemplates,
    staleTime: 30_000,
  });

  const [regenerateMessage, setRegenerateMessage] =
    React.useState<string | null>(null);

  const regenerate = useMutation({
    mutationFn: generateTemplates,
    onSuccess: (response) => {
      const generatedCount = response.generated.length;
      const skippedCount = response.skipped_attested.length;
      const generatedNoun = generatedCount === 1 ? "template" : "templates";
      const skippedNoun = skippedCount === 1 ? "template" : "templates";
      const skipFragment =
        skippedCount > 0
          ? ` (${skippedCount} attested ${skippedNoun} left untouched)`
          : "";
      // copy-allow: voice-rule full date format does not apply to count strings
      setRegenerateMessage(
        `Regenerated ${generatedCount} ${generatedNoun}${skipFragment}.`,
      );
      queryClient.invalidateQueries({ queryKey: ["templates"] });
    },
    onError: () => {
      setRegenerateMessage(null);
    },
  });

  const regenerateErrorCode =
    regenerate.error !== null
      ? readTemplatesErrorCode(regenerate.error)
      : "unknown";

  return (
    <>
      <header className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="space-y-2">
          <h1 className="font-display text-4xl font-normal leading-tight text-[color:var(--ink)]">
            Templates
          </h1>
          <p className="text-[14px] text-[color:var(--ink-2)]">
            Counsel-attestable compliance templates generated from your
            onboarding answers.
          </p>
        </div>
        <div className="flex flex-col items-stretch gap-2 sm:items-end">
          <button
            type="button"
            data-testid="templates-regenerate-button"
            onClick={() => regenerate.mutate()}
            disabled={regenerate.isPending}
            className="rounded-[10px] border border-[color:var(--ink-4)] bg-[color:var(--paper)] px-3 py-2 text-[13px] font-medium text-[color:var(--ink)] hover:bg-[color:var(--paper-2)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--ink)] disabled:cursor-not-allowed disabled:opacity-60"
          >
            {regenerate.isPending ? "Regenerating…" : "Regenerate templates"}
          </button>
          {regenerateMessage && (
            <p
              data-testid="templates-regenerate-confirmation"
              role="status"
              className="text-[12px] text-[color:var(--ink-2)]"
            >
              {regenerateMessage}
            </p>
          )}
        </div>
      </header>

      {list.isError && (
        <div
          role="alert"
          data-testid="templates-error-banner"
          className="flex items-center justify-between gap-4 rounded-[10px] border border-[color:var(--brick)]/40 bg-[color:var(--brick-bg)] px-4 py-3 text-[14px] text-[color:var(--ink)]"
        >
          <span>Could not load templates. Try again.</span>
          <button
            type="button"
            onClick={() => list.refetch()}
            className="rounded-md border border-[color:var(--ink-4)] bg-[color:var(--paper)] px-3 py-1 text-[13px] font-medium text-[color:var(--ink)] hover:bg-[color:var(--paper-2)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--ink)]"
          >
            Retry
          </button>
        </div>
      )}

      {regenerate.isError && (
        <div
          role="alert"
          data-testid="templates-regenerate-error"
          className="rounded-[10px] border border-[color:var(--brick)]/40 bg-[color:var(--brick-bg)] px-4 py-3 text-[14px] text-[color:var(--ink)]"
        >
          {regenerateErrorCode === TEMPLATES_ERROR_CODES.wizardIncomplete
            ? "Finish the onboarding wizard before generating templates."
            : regenerate.error instanceof ApiError
              ? regenerate.error.message
              : "Could not regenerate templates. Try again."}
        </div>
      )}

      {list.isLoading && (
        <div
          data-testid="templates-loading-skeleton"
          className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3"
        >
          {[0, 1, 2, 3, 4].map((i) => (
            <Skeleton key={i} className="h-32 w-full" />
          ))}
        </div>
      )}

      {list.data && (
        <div
          data-testid="templates-grid"
          className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3"
        >
          {list.data.map((summary) => (
            <TemplateCard key={summary.template_key} summary={summary} />
          ))}
        </div>
      )}
    </>
  );
}

// ── Editor view ──────────────────────────────────────────────────────

interface TemplatesEditorViewProps {
  templateKey: TemplateKey;
}

function TemplatesEditorView({ templateKey }: TemplatesEditorViewProps) {
  const detail = useQuery({
    queryKey: ["templates", templateKey],
    queryFn: () => getTemplate(templateKey),
    staleTime: 30_000,
    // 404 (row missing) is an expected state, not an error to retry.
    retry: (failureCount, error) => {
      if (error instanceof ApiError && error.status === 404) return false;
      return failureCount < 2;
    },
  });

  const errorCode =
    detail.error !== null ? readTemplatesErrorCode(detail.error) : "unknown";

  if (detail.isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-8 w-1/2" />
        <Skeleton className="h-[60vh] w-full" />
      </div>
    );
  }

  if (detail.isError) {
    if (errorCode === TEMPLATES_ERROR_CODES.templateNotFound) {
      return <EmptyTemplateState templateKey={templateKey} />;
    }
    return (
      <div
        role="alert"
        data-testid="templates-editor-load-error"
        className="rounded-[10px] border border-[color:var(--brick)]/40 bg-[color:var(--brick-bg)] px-4 py-3 text-[14px] text-[color:var(--ink)]"
      >
        Could not load template. Try again.
      </div>
    );
  }

  if (!detail.data) {
    return null;
  }

  return <TemplateEditor detail={detail.data} />;
}
