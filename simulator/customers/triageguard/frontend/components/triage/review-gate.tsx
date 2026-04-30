"use client";

/**
 * ReviewGate — the HITL surface.
 *
 * Renders when a `nurse_review_requested` event has been seen. Shows
 * the patient's chief complaint, the AI classifier's proposed level,
 * the detector's flagged terms, and the recommended override. The
 * nurse picks "Confirm AI level" or "Escalate to ER"; the SSE stream
 * then delivers the terminal `routed` event.
 */

import * as React from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { RiskPill } from "@/components/ui/risk-pill";
import { Badge } from "@/components/ui/badge";
import type {
  PatientSummary,
  RiskTier,
  SessionEvent,
} from "@/lib/api/types";

interface ReviewRequestedContext {
  session_id?: string;
  patient_mrn?: string;
  classifier_level?: string;
  classifier_reasoning?: string;
  red_flag_terms?: string[];
  red_flag_reasoning?: string;
  recommended_override?: string;
  classifier_record_id?: string;
  red_flag_record_id?: string;
}

interface ReviewRequestedPayload {
  approval_id?: string;
  risk_tier?: RiskTier;
  context?: ReviewRequestedContext;
}

interface ReviewGateProps {
  reviewEvent: SessionEvent;
  patient: PatientSummary | null;
  fallbackRiskTier: RiskTier;
  isDeciding: boolean;
  decideError: Error | null;
  onDecide(reviewId: string, decision: "confirm" | "escalate"): void;
}

export function ReviewGate({
  reviewEvent,
  patient,
  fallbackRiskTier,
  isDeciding,
  decideError,
  onDecide,
}: ReviewGateProps) {
  const data = (reviewEvent.data ?? {}) as ReviewRequestedPayload;
  const reviewId = data.approval_id;
  const tier: RiskTier = data.risk_tier ?? fallbackRiskTier;
  const ctx = data.context ?? {};

  const classifierLevel = ctx.classifier_level ?? null;
  const classifierReasoning = ctx.classifier_reasoning ?? null;
  const redFlagTerms = Array.isArray(ctx.red_flag_terms)
    ? ctx.red_flag_terms
    : [];
  const redFlagReasoning = ctx.red_flag_reasoning ?? null;
  const recommendedOverride = ctx.recommended_override ?? null;

  const handleConfirm = () => {
    if (!reviewId || isDeciding) return;
    onDecide(reviewId, "confirm");
  };
  const handleEscalate = () => {
    if (!reviewId || isDeciding) return;
    onDecide(reviewId, "escalate");
  };

  return (
    <Card elevation="lg" tone="crimson" className="mt-6">
      <CardHeader>
        <div className="flex items-start justify-between gap-4">
          <div className="flex flex-col gap-1.5">
            <span className="font-mono text-[11px] uppercase tracking-wider text-[var(--ink-3)]">
              Awaiting your triage decision
            </span>
            <CardTitle className="text-xl">
              {patient?.chief_complaint ??
                "New triage case ready for your review"}
            </CardTitle>
            {patient && <PatientRow patient={patient} />}
          </div>
          <RiskPill tier={tier} />
        </div>
      </CardHeader>

      <CardContent>
        <div className="grid gap-5 lg:grid-cols-2">
          <div>
            <h3 className="font-sans text-xs font-semibold text-[var(--ink-2)] uppercase tracking-wide">
              AI recommendation
            </h3>
            <div className="mt-2 flex items-center gap-2">
              <Badge variant="neutral" withDot>
                {classifierLevel ? formatLevel(classifierLevel) : "—"}
              </Badge>
              {recommendedOverride && (
                <span className="font-sans text-xs text-[var(--ink-3)]">
                  override: {formatLevel(recommendedOverride)}
                </span>
              )}
            </div>
            {classifierReasoning && (
              <p className="mt-2 font-sans text-sm text-[var(--ink-2)] leading-relaxed">
                {classifierReasoning}
              </p>
            )}
          </div>

          <div>
            <h3 className="font-sans text-xs font-semibold text-[var(--ink-2)] uppercase tracking-wide">
              Red-flag terms detected:
            </h3>
            {redFlagTerms.length === 0 ? (
              <p className="mt-2 font-sans text-sm text-[var(--ink-3)] italic">
                No red-flag terms reported.
              </p>
            ) : (
              <div className="mt-2 flex flex-wrap gap-1.5">
                {redFlagTerms.map((t, i) => (
                  <RiskPill
                    key={`${t}-${i}`}
                    tier="high"
                    compact
                    label={t}
                  />
                ))}
              </div>
            )}
            {redFlagReasoning && (
              <p className="mt-2 font-sans text-sm text-[var(--ink-2)] leading-relaxed">
                {redFlagReasoning}
              </p>
            )}
          </div>
        </div>

        {decideError && (
          <div
            role="alert"
            className="mt-5 rounded-xl bg-[var(--crimson-soft)] px-3.5 py-2.5 font-sans text-sm text-[var(--crimson)] ring-1 ring-inset ring-[rgba(185,28,28,0.22)]"
          >
            {decideError.message}
          </div>
        )}

        <div className="mt-6 flex flex-wrap items-center justify-end gap-3">
          <Button
            variant="secondary"
            size="lg"
            onClick={handleConfirm}
            disabled={!reviewId || isDeciding}
          >
            Confirm AI level
          </Button>
          <Button
            variant="escalate"
            size="lg"
            onClick={handleEscalate}
            disabled={!reviewId || isDeciding}
          >
            {isDeciding ? "Saving…" : "Escalate to ER"}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

function PatientRow({ patient }: { patient: PatientSummary }) {
  const allergies = patient.allergies?.filter(Boolean) ?? [];
  return (
    <div className="flex flex-wrap items-center gap-x-2 gap-y-1.5 mt-1">
      <span className="font-sans text-sm text-[var(--ink-2)]">
        {patient.name}
      </span>
      <Dot />
      <span className="font-sans text-sm text-[var(--ink-3)]">
        DOB {patient.dob}
      </span>
      <Dot />
      <span className="font-sans text-sm text-[var(--ink-3)]">
        {patient.sex}
      </span>
      {allergies.length > 0 && (
        <>
          <Dot />
          <div className="flex flex-wrap items-center gap-1.5">
            {allergies.map((a) => (
              <Badge key={a} variant="amber" size="sm">
                {a}
              </Badge>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

function Dot() {
  return (
    <span aria-hidden className="text-[var(--ink-4)] font-sans text-xs">
      ·
    </span>
  );
}

function formatLevel(level: string): string {
  switch (level) {
    case "self_care":
      return "Self-care";
    case "virtual_visit":
      return "Virtual visit";
    case "urgent_care":
      return "Urgent care";
    case "ER":
      return "ER";
    default:
      return level;
  }
}
