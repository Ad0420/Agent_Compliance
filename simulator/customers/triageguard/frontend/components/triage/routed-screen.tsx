"use client";

/**
 * RoutedScreen — terminal screen for a triage session.
 *
 * "routed" — hero "Patient routed to <level>." plus a small receipt
 * card with the deciding nurse + final level + a tasteful "View
 * audit trail" link to Vera. The link is the *only* place the nurse
 * surface mentions Vera.
 *
 * "blocked" — calmer "Decision not recorded." panel.
 *
 * "error" — short error panel with a captured message + "Try again".
 */

import * as React from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { RiskPill } from "@/components/ui/risk-pill";
import type { SessionSnapshot } from "@/lib/api/types";
import { veraDeeplink } from "@/lib/vera-deeplink";

interface RoutedScreenProps {
  session: SessionSnapshot;
  signedInAs: string;
  errorMessage?: string | null;
  onReset(): void;
}

export function RoutedScreen({
  session,
  signedInAs,
  errorMessage,
  onReset,
}: RoutedScreenProps) {
  if (session.status === "routing_blocked") {
    return <BlockedView onReset={onReset} />;
  }
  if (session.status === "error") {
    return <ErrorView message={errorMessage ?? null} onReset={onReset} />;
  }
  return (
    <RoutedView
      session={session}
      signedInAs={signedInAs}
      onReset={onReset}
    />
  );
}

function RoutedView({
  session,
  signedInAs,
  onReset,
}: {
  session: SessionSnapshot;
  signedInAs: string;
  onReset(): void;
}) {
  const outcome = session.terminal_outcome;
  const finalLevel = outcome?.final_level ?? "the recommended level";
  const finalLevelLabel = formatLevel(finalLevel);
  const auto = outcome?.nurse_status === "auto" || (outcome && !outcome.approval_id);
  const mrn = session.patient_summary?.mrn ?? "";

  // Last record id is the routing record. Fall back gracefully.
  const lastRecord =
    session.vera_record_ids[session.vera_record_ids.length - 1] ?? null;
  const auditLink = lastRecord ? veraDeeplink(lastRecord) : null;

  const decidedAt = session.updated_at ?? session.created_at;
  const time = decidedAt ? formatTime(decidedAt) : "just now";

  return (
    <div className="mx-auto w-full max-w-3xl">
      <h1
        className="font-serif text-4xl font-normal text-[var(--ink)]"
        style={{ letterSpacing: "-0.02em" }}
      >
        Patient routed to {finalLevelLabel}.
      </h1>
      <p className="mt-2 font-sans text-sm text-[var(--ink-3)]">
        {auto
          ? "No red flags detected — the patient saw the AI's level directly."
          : `Your decision was captured and the patient has been routed.`}
      </p>

      <Card elevation="md" tone="moss" className="mt-6">
        <CardHeader>
          <div className="flex items-center justify-between gap-3">
            <span className="font-mono text-[11px] uppercase tracking-wider text-[var(--ink-3)]">
              Routing receipt
            </span>
            <span className="font-mono text-[11px] text-[var(--ink-3)]">
              {session.id}
            </span>
          </div>
          <p className="mt-2 font-sans text-base text-[var(--ink)]">
            {auto
              ? "Auto-routed"
              : `Decision by ${signedInAs}`}{" "}
            at <span className="font-medium">{time}</span>. Final level{" "}
            <span className="font-medium">{finalLevelLabel}</span>
            {mrn ? (
              <>
                {" "}for chart <span className="font-mono text-sm">{mrn}</span>
              </>
            ) : null}
            .
          </p>
        </CardHeader>
        {outcome && (
          <CardContent>
            <div className="flex flex-wrap items-center gap-2">
              <RiskPill tier={outcome.risk_tier} />
              {outcome.red_flag_fired && (
                <span className="font-sans text-sm text-[var(--ink-2)]">
                  Red-flag fired ·{" "}
                  {outcome.red_flag_terms.length > 0
                    ? outcome.red_flag_terms.join(", ")
                    : "no terms"}
                </span>
              )}
            </div>
            {outcome.classifier_reasoning && (
              <p className="mt-3 font-sans text-sm text-[var(--ink-2)] leading-relaxed">
                {outcome.classifier_reasoning}
              </p>
            )}
          </CardContent>
        )}
      </Card>

      <div className="mt-5 flex flex-wrap items-center justify-between gap-3">
        {auditLink ? (
          <a
            href={auditLink}
            target="_blank"
            rel="noreferrer noopener"
            className="font-sans text-sm text-[var(--teal)] underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--teal)] rounded"
          >
            View audit trail
          </a>
        ) : (
          <span />
        )}
        <Button variant="secondary" size="md" onClick={onReset}>
          New session
        </Button>
      </div>
    </div>
  );
}

function BlockedView({ onReset }: { onReset(): void }) {
  return (
    <div className="mx-auto w-full max-w-2xl">
      <div className="flex items-center gap-3">
        <RiskPill tier="high" label="Not routed" />
      </div>
      <h1
        className="mt-3 font-serif text-3xl font-normal text-[var(--ink)]"
        style={{ letterSpacing: "-0.015em" }}
      >
        Decision not recorded.
      </h1>
      <p className="mt-2 font-sans text-sm text-[var(--ink-2)] max-w-prose leading-relaxed">
        The review timed out before a decision was captured. The patient
        was not routed and nothing was sent on your behalf.
      </p>

      <div className="mt-6">
        <Button variant="primary" size="md" onClick={onReset}>
          New session
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
      <Card elevation="md" tone="crimson">
        <CardHeader>
          <span className="font-mono text-[11px] uppercase tracking-wider text-[var(--ink-3)]">
            Something went wrong
          </span>
          <h2
            className="mt-1.5 font-serif text-2xl font-normal text-[var(--ink)]"
            style={{ letterSpacing: "-0.015em" }}
          >
            We couldn&rsquo;t finish that triage session.
          </h2>
        </CardHeader>
        <CardContent>
          <p className="font-sans text-sm text-[var(--ink-2)] leading-relaxed">
            {message ??
              "An unexpected error stopped the workflow. The patient was not routed."}
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

function formatLevel(level: string): string {
  switch (level) {
    case "self_care":
      return "self-care";
    case "virtual_visit":
      return "virtual visit";
    case "urgent_care":
      return "urgent care";
    case "ER":
      return "ER";
    default:
      return level;
  }
}
