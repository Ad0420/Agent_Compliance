"use client";

/**
 * /encounter — the protected single-page app.
 *
 * Three states driven by the encounter lifecycle:
 *   1. selector — no encounter started; pick a fixture or write a transcript.
 *   2. running — pipeline streams events; approval gate appears at the HITL.
 *   3. terminal — EHR mock for committed/blocked/errored encounters.
 *
 * The page itself owns the local "current encounter id" + a "reset" button
 * that drops the id and routes the user back to the selector. Everything
 * else (events, polling, decisions) flows through the shared hooks.
 */

import * as React from "react";
import { useRouter } from "next/navigation";

import { useAuth } from "@/hooks/use-auth";
import { useEncounter, useStartEncounter } from "@/hooks/use-encounter";
import { useEncounterEvents } from "@/hooks/use-encounter-events";
import { useDecideApproval } from "@/hooks/use-decide-approval";
import {
  isTerminalStatus,
  type EncounterEvent,
  type RiskTier,
  type StartEncounterInput,
} from "@/lib/api/types";

import { Topbar } from "@/components/ui/topbar";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { StatusDot } from "@/components/ui/status-dot";
import { RiskPill } from "@/components/ui/risk-pill";

import { EncounterSelector } from "@/components/encounter/encounter-selector";
import { LivePipeline } from "@/components/encounter/live-pipeline";
import { ApprovalGate } from "@/components/encounter/approval-gate";
import { EhrMock } from "@/components/encounter/ehr-mock";

export default function EncounterPage() {
  const { signedInAs, isLoading: authLoading } = useAuth();
  const router = useRouter();

  const [encounterId, setEncounterId] = React.useState<string | null>(null);

  const {
    start,
    isStarting,
    error: startError,
  } = useStartEncounter();
  const { data: snapshot } = useEncounter(encounterId);
  const { events: liveEvents, status: streamStatus } =
    useEncounterEvents(encounterId);
  const { decide, isDeciding, error: decideError } = useDecideApproval();

  // Auth guard. The provider's initial probe is async — wait for it to
  // settle before redirecting, otherwise we'd kick freshly-signed-in
  // clinicians back to /login on every refresh.
  React.useEffect(() => {
    if (authLoading) return;
    if (!signedInAs) router.replace("/login");
  }, [authLoading, signedInAs, router]);

  // Prefer the live SSE feed, but fall back to the snapshot's `events`
  // array — that way refreshes on a finished encounter still render
  // the right state instead of an empty pipeline.
  const events: EncounterEvent[] =
    liveEvents.length > 0 ? liveEvents : (snapshot?.events ?? []);

  const handleStart = React.useCallback(
    async (input: StartEncounterInput) => {
      try {
        const { id } = await start(input);
        setEncounterId(id);
      } catch {
        // useStartEncounter exposes the error as `startError`; nothing
        // else to do here.
      }
    },
    [start],
  );

  const handleReset = React.useCallback(() => {
    setEncounterId(null);
  }, []);

  const handleDecide = React.useCallback(
    (approvalId: string, decision: "approve" | "reject") => {
      void decide(approvalId, decision).catch(() => {
        // useDecideApproval exposes the error as `decideError`.
      });
    },
    [decide],
  );

  // While the auth probe runs, render a quiet shell so we don't flash
  // the selector and immediately yank it away.
  if (authLoading || !signedInAs) {
    return (
      <div className="min-h-screen bg-[var(--paper)] flex items-center justify-center">
        <StatusDot status="running" label="Loading" />
      </div>
    );
  }

  const status = snapshot?.status ?? null;
  const showTerminal =
    encounterId !== null && status !== null && isTerminalStatus(status);

  return (
    <div className="min-h-screen bg-[var(--paper)]">
      <Topbar
        signedInAs={{ name: signedInAs }}
        centerSlot={
          encounterId && !showTerminal ? (
            <StatusDot
              status={
                streamStatus === "error"
                  ? "error"
                  : status === "awaiting_approval"
                    ? "waiting"
                    : "running"
              }
              label={
                status === "awaiting_approval"
                  ? "Awaiting your sign-off"
                  : "Encounter live"
              }
            />
          ) : null
        }
      />

      <main className="mx-auto max-w-5xl px-6 py-10">
        {!encounterId && (
          <EncounterSelector
            onStart={handleStart}
            isStarting={isStarting}
            startError={startError}
          />
        )}

        {encounterId && !showTerminal && (
          <RunningView
            patient={snapshot?.patient_summary ?? null}
            chiefComplaint={snapshot?.patient_summary?.chief_complaint ?? null}
            events={events}
            riskTier={
              snapshot?.patient_summary?.expected_risk ?? "medium"
            }
            isDeciding={isDeciding}
            decideError={decideError}
            onDecide={handleDecide}
          />
        )}

        {encounterId && showTerminal && snapshot && (
          <EhrMock
            encounter={snapshot}
            signedInAs={signedInAs}
            errorMessage={
              snapshot.status === "error"
                ? extractErrorMessage(events)
                : null
            }
            onReset={handleReset}
          />
        )}
      </main>
    </div>
  );
}

function RunningView({
  patient,
  chiefComplaint,
  events,
  riskTier,
  isDeciding,
  decideError,
  onDecide,
}: {
  patient: import("@/lib/api/types").PatientSummary | null;
  chiefComplaint: string | null;
  events: EncounterEvent[];
  riskTier: RiskTier;
  isDeciding: boolean;
  decideError: Error | null;
  onDecide(approvalId: string, decision: "approve" | "reject"): void;
}) {
  const lastEvent = events[events.length - 1];
  // Find the most recent approval_requested event — once a decision
  // has landed we hide the gate so the pipeline transitions cleanly.
  const approvalEvent = (() => {
    if (lastEvent?.event === "approval_requested") return lastEvent;
    // If decision happened locally but the SSE stream hasn't sent
    // `approval_decided` yet, still hide the gate.
    return null;
  })();

  return (
    <div className="mx-auto w-full max-w-3xl">
      <Card elevation="lg">
        <CardHeader>
          <div className="flex items-start justify-between gap-3">
            <div>
              <span className="font-mono text-[11px] uppercase tracking-wider text-[var(--ink-3)]">
                Live encounter
              </span>
              <CardTitle className="mt-1 text-xl">
                {chiefComplaint ?? "Drafting your note"}
              </CardTitle>
              {patient && (
                <p className="mt-1 font-sans text-sm text-[var(--ink-3)]">
                  {patient.name} · DOB {patient.dob} · {patient.sex}
                </p>
              )}
            </div>
            <RiskPill tier={riskTier} />
          </div>
        </CardHeader>
        <CardContent>
          <LivePipeline events={events} />
        </CardContent>
      </Card>

      {approvalEvent && (
        <ApprovalGate
          approvalEvent={approvalEvent}
          patient={patient}
          fallbackRiskTier={riskTier}
          isDeciding={isDeciding}
          decideError={decideError}
          onDecide={onDecide}
        />
      )}
    </div>
  );
}

function extractErrorMessage(events: EncounterEvent[]): string | null {
  for (let i = events.length - 1; i >= 0; i--) {
    if (events[i].event === "error") {
      const data = events[i].data as { message?: unknown };
      if (typeof data.message === "string") return data.message;
    }
  }
  return null;
}
