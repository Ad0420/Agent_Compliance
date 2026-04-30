"use client";

/**
 * EhrMock — closing screen for a committed (or blocked, or errored)
 * encounter.
 *
 * "committed" / "auto_committed" — hero "Chart updated.", a faux EHR
 * receipt with the signer + MRN, the SOAP note in mono, a small "View
 * audit trail" link to Vera, and a "New encounter" button.
 *
 * "blocked" — coral risk pill + a calmer "Note not signed" panel.
 *
 * "error" — short error panel with a captured message + "Try again".
 */

import * as React from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { RiskPill } from "@/components/ui/risk-pill";
import type { EncounterSnapshot } from "@/lib/api/types";
import { veraDeeplink } from "@/lib/vera-deeplink";

interface EhrMockProps {
  encounter: EncounterSnapshot;
  signedInAs: string;
  errorMessage?: string | null;
  onReset(): void;
}

export function EhrMock({
  encounter,
  signedInAs,
  errorMessage,
  onReset,
}: EhrMockProps) {
  if (encounter.status === "blocked") {
    return <BlockedView onReset={onReset} />;
  }
  if (encounter.status === "error") {
    return <ErrorView message={errorMessage ?? null} onReset={onReset} />;
  }
  return (
    <CommittedView
      encounter={encounter}
      signedInAs={signedInAs}
      onReset={onReset}
    />
  );
}

function CommittedView({
  encounter,
  signedInAs,
  onReset,
}: {
  encounter: EncounterSnapshot;
  signedInAs: string;
  onReset(): void;
}) {
  const note = encounter.terminal_outcome?.note ?? null;
  const mrn =
    (encounter.patient_summary as { mrn?: string } | null)?.mrn ??
    "MRN-XXXXXXXX";
  const auto = encounter.status === "auto_committed";

  // Last record id is the chart commit. Fall back gracefully.
  const lastRecord =
    encounter.vera_record_ids[encounter.vera_record_ids.length - 1] ?? null;
  const auditLink = lastRecord ? veraDeeplink(lastRecord) : null;

  const committedAt = encounter.updated_at ?? encounter.created_at;
  const time = committedAt ? formatTime(committedAt) : "just now";

  return (
    <div className="mx-auto w-full max-w-3xl">
      <h1
        className="font-serif text-4xl font-semibold text-[var(--ink)]"
        style={{ letterSpacing: "-0.025em" }}
      >
        Chart updated.
      </h1>
      <p className="mt-2 font-sans text-sm text-[var(--ink-3)]">
        {auto
          ? "No clinical orders to review — the note saved automatically."
          : "Your sign-off was captured and the chart is now up to date."}
      </p>

      <Card elevation="md" tone="sage" className="mt-6">
        <CardHeader>
          <div className="flex items-center justify-between gap-3">
            <span className="font-mono text-[11px] uppercase tracking-wider text-[var(--ink-3)]">
              Chart receipt
            </span>
            <span className="font-mono text-[11px] text-[var(--ink-3)]">
              {encounter.id}
            </span>
          </div>
          <p className="mt-2 font-sans text-base text-[var(--ink)]">
            {auto ? "Note auto-saved" : `Note signed by ${signedInAs}`} at{" "}
            <span className="font-medium">{time}</span>. Committed to chart{" "}
            <span className="font-mono text-sm">{mrn}</span>.
          </p>
        </CardHeader>
        {note && (
          <CardContent>
            <div className="rounded-xl bg-[var(--paper-2)] p-4 ring-1 ring-inset ring-[var(--hairline)]">
              <pre className="max-h-[400px] overflow-auto font-mono text-xs leading-relaxed text-[var(--ink-2)] whitespace-pre-wrap">
                {note}
              </pre>
            </div>
          </CardContent>
        )}
      </Card>

      <div className="mt-5 flex flex-wrap items-center justify-between gap-3">
        {auditLink ? (
          <a
            href={auditLink}
            target="_blank"
            rel="noreferrer noopener"
            className="font-sans text-sm text-[var(--cobalt)] underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--cobalt)] rounded"
          >
            View audit trail
          </a>
        ) : (
          <span />
        )}
        <Button variant="secondary" size="md" onClick={onReset}>
          New encounter
        </Button>
      </div>
    </div>
  );
}

function BlockedView({ onReset }: { onReset(): void }) {
  return (
    <div className="mx-auto w-full max-w-2xl">
      <div className="flex items-center gap-3">
        <RiskPill tier="high" label="Not signed" />
      </div>
      <h1
        className="mt-3 font-serif text-3xl font-semibold text-[var(--ink)]"
        style={{ letterSpacing: "-0.02em" }}
      >
        Note not signed.
      </h1>
      <p className="mt-2 font-sans text-sm text-[var(--ink-2)] max-w-prose leading-relaxed">
        The note was rejected and never reached the chart. Nothing about
        the visit was saved on your behalf.
      </p>

      <div className="mt-6">
        <Button variant="primary" size="md" onClick={onReset}>
          New encounter
        </Button>
      </div>
    </div>
  );
}

function ErrorView({
  message,
  onReset,
}: {
  message: string | null;
  onReset(): void;
}) {
  return (
    <div className="mx-auto w-full max-w-2xl">
      <Card elevation="md" tone="coral">
        <CardHeader>
          <span className="font-mono text-[11px] uppercase tracking-wider text-[var(--ink-3)]">
            Something went wrong
          </span>
          <h2
            className="mt-1.5 font-serif text-2xl font-semibold text-[var(--ink)]"
            style={{ letterSpacing: "-0.015em" }}
          >
            We couldn&rsquo;t finish that encounter.
          </h2>
        </CardHeader>
        <CardContent>
          <p className="font-sans text-sm text-[var(--ink-2)] leading-relaxed">
            {message ??
              "An unexpected error stopped the workflow. The chart was not updated."}
          </p>
          <div className="mt-5">
            <Button variant="primary" size="md" onClick={onReset}>
              Try again
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

function formatTime(iso: string): string {
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    return d.toLocaleTimeString(undefined, {
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}
