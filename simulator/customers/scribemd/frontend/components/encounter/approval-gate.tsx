"use client";

/**
 * ApprovalGate — the HITL surface.
 *
 * Renders when the latest event is `approval_requested`. Shows the
 * patient's chief complaint, demographics, allergies, and the three
 * order lists (diagnoses / medications / labs). The clinician picks
 * "Sign and commit" or "Reject"; the SSE stream then delivers the
 * terminal event.
 *
 * Order rows show their record id chip on hover (mono, tasteful) — it
 * stays out of the way until the clinician needs it.
 */

import * as React from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { RiskPill } from "@/components/ui/risk-pill";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import type {
  EncounterEvent,
  PatientSummary,
  RiskTier,
} from "@/lib/api/types";

interface ApprovalRequestedContext {
  diagnoses?: string[];
  medication_orders?: string[];
  lab_or_imaging_orders?: string[];
  encounter_id?: string;
  patient_mrn?: string;
  note_record_id?: string;
  extraction_record_id?: string;
}

interface ApprovalRequestedPayload {
  approval_id?: string;
  risk_tier?: RiskTier;
  context?: ApprovalRequestedContext;
}

interface ApprovalGateProps {
  approvalEvent: EncounterEvent;
  patient: PatientSummary | null;
  fallbackRiskTier: RiskTier;
  isDeciding: boolean;
  decideError: Error | null;
  onDecide(approvalId: string, decision: "approve" | "reject"): void;
}

export function ApprovalGate({
  approvalEvent,
  patient,
  fallbackRiskTier,
  isDeciding,
  decideError,
  onDecide,
}: ApprovalGateProps) {
  const data = (approvalEvent.data ?? {}) as ApprovalRequestedPayload;
  const approvalId = data.approval_id;
  const tier: RiskTier = data.risk_tier ?? fallbackRiskTier;
  const ctx = data.context ?? {};

  const diagnoses = Array.isArray(ctx.diagnoses) ? ctx.diagnoses : [];
  const meds = Array.isArray(ctx.medication_orders)
    ? ctx.medication_orders
    : [];
  const labs = Array.isArray(ctx.lab_or_imaging_orders)
    ? ctx.lab_or_imaging_orders
    : [];

  const noteRecordId = ctx.note_record_id;
  const extractionRecordId = ctx.extraction_record_id;

  const handleApprove = () => {
    if (!approvalId || isDeciding) return;
    onDecide(approvalId, "approve");
  };
  const handleReject = () => {
    if (!approvalId || isDeciding) return;
    onDecide(approvalId, "reject");
  };

  return (
    <Card elevation="lg" tone="cobalt" className="mt-6">
      <CardHeader>
        <div className="flex items-start justify-between gap-4">
          <div className="flex flex-col gap-1.5">
            <span className="font-mono text-[11px] uppercase tracking-wider text-[var(--ink-3)]">
              Awaiting sign-off
            </span>
            <CardTitle className="text-xl">
              {patient?.chief_complaint ??
                "New orders ready for your review"}
            </CardTitle>
            {patient && (
              <PatientRow patient={patient} />
            )}
          </div>
          <RiskPill tier={tier} />
        </div>
      </CardHeader>

      <CardContent>
        <div className="grid gap-5 lg:grid-cols-3">
          <OrderSection
            title="Diagnoses"
            items={diagnoses}
            recordId={extractionRecordId}
            emptyText="No diagnoses identified."
          />
          <OrderSection
            title="Medication orders"
            items={meds}
            recordId={extractionRecordId}
            emptyText="No medications ordered."
          />
          <OrderSection
            title="Labs / imaging"
            items={labs}
            recordId={extractionRecordId}
            emptyText="No labs ordered."
          />
        </div>

        {noteRecordId && (
          <div className="mt-5 flex items-center gap-2 font-mono text-[11px] text-[var(--ink-3)]">
            <span>Draft</span>
            <span className="rounded-md bg-[var(--paper-2)] px-1.5 py-0.5">
              {noteRecordId}
            </span>
          </div>
        )}

        {decideError && (
          <div
            role="alert"
            className="mt-5 rounded-xl bg-[var(--coral-soft)] px-3.5 py-2.5 font-sans text-sm text-[var(--coral)] ring-1 ring-inset ring-[rgba(180,35,24,0.22)]"
          >
            {decideError.message}
          </div>
        )}

        <div className="mt-6 flex flex-wrap items-center justify-end gap-3">
          <Button
            variant="destructive"
            size="lg"
            onClick={handleReject}
            disabled={!approvalId || isDeciding}
          >
            Reject
          </Button>
          <Button
            variant="primary"
            size="lg"
            onClick={handleApprove}
            disabled={!approvalId || isDeciding}
          >
            {isDeciding ? "Saving…" : "Sign and commit"}
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

function OrderSection({
  title,
  items,
  recordId,
  emptyText,
}: {
  title: string;
  items: string[];
  recordId: string | undefined;
  emptyText: string;
}) {
  return (
    <div>
      <div className="mb-2 flex items-center justify-between">
        <h3 className="font-sans text-xs font-semibold text-[var(--ink-2)] uppercase tracking-wide">
          {title}
        </h3>
        <span className="font-sans text-xs text-[var(--ink-4)]">
          {items.length}
        </span>
      </div>
      {items.length === 0 ? (
        <p className="font-sans text-sm text-[var(--ink-3)] italic">
          {emptyText}
        </p>
      ) : (
        <ul className="flex flex-col gap-1.5">
          {items.map((label, idx) => (
            <li
              key={`${label}-${idx}`}
              className={cn(
                "group rounded-xl bg-[var(--paper-2)] px-3 py-2",
                "flex items-start justify-between gap-3",
              )}
            >
              <span className="font-sans text-sm text-[var(--ink)] leading-snug">
                {label}
              </span>
              {recordId && (
                <span
                  className={cn(
                    "shrink-0 self-center rounded-md bg-[var(--surface)]",
                    "px-1.5 py-0.5 font-mono text-[10px] text-[var(--ink-3)]",
                    "opacity-0 group-hover:opacity-100 transition-opacity",
                    "ring-1 ring-inset ring-[var(--hairline)]",
                  )}
                >
                  {recordId}
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
