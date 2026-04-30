"use client";

/**
 * /triage — the protected single-page app.
 *
 * Three states driven by the session lifecycle:
 *   1. selector — no session started; pick a fixture or paste symptoms.
 *   2. running — pipeline streams events; review gate appears at the HITL.
 *   3. terminal — RoutedScreen for routed/blocked/errored sessions.
 *
 * The page itself owns the local "current session id" + a "reset" button
 * that drops the id and routes the user back to the selector. Everything
 * else (events, polling, decisions) flows through the shared hooks.
 */

import * as React from "react";
import { useRouter } from "next/navigation";

import { useAuth } from "@/hooks/use-auth";
import { useSession, useStartSession } from "@/hooks/use-session";
import { useSessionEvents } from "@/hooks/use-session-events";
import { useDecideReview } from "@/hooks/use-decide-review";
import {
  isTerminalStatus,
  type SessionEvent,
  type RiskTier,
  type StartSessionInput,
} from "@/lib/api/types";

import { Topbar } from "@/components/ui/topbar";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { StatusDot } from "@/components/ui/status-dot";
import { RiskPill } from "@/components/ui/risk-pill";

import { SessionSelector } from "@/components/triage/session-selector";
import { LivePipeline } from "@/components/triage/live-pipeline";
import { ReviewGate } from "@/components/triage/review-gate";
import { RoutedScreen } from "@/components/triage/routed-screen";

export default function TriagePage() {
  const { signedInAs, isLoading: authLoading } = useAuth();
  const router = useRouter();

  const [sessionId, setSessionId] = React.useState<string | null>(null);

  const {
    start,
    isStarting,
    error: startError,
  } = useStartSession();
  const { data: snapshot } = useSession(sessionId);
  const { events: liveEvents, status: streamStatus } =
    useSessionEvents(sessionId);
  const { decide, isDeciding, error: decideError } = useDecideReview();

  // Auth guard. The provider's initial probe is async — wait for it to
  // settle before redirecting, otherwise we'd kick freshly-signed-in
  // nurses back to /login on every refresh.
  React.useEffect(() => {
    if (authLoading) return;
    if (!signedInAs) router.replace("/login");
  }, [authLoading, signedInAs, router]);

  // Prefer the live SSE feed, but fall back to the snapshot's `events`
  // array — that way refreshes on a finished session still render the
  // right state instead of an empty pipeline.
  const events: SessionEvent[] =
    liveEvents.length > 0 ? liveEvents : (snapshot?.events ?? []);

  const handleStart = React.useCallback(
    async (input: StartSessionInput) => {
      try {
        const { id } = await start(input);
        setSessionId(id);
      } catch {
        // useStartSession exposes the error as `startError`; nothing
        // else to do here.
      }
    },
    [start],
  );

  const handleReset = React.useCallback(() => {
    setSessionId(null);
  }, []);

  const handleDecide = React.useCallback(
    (reviewId: string, decision: "confirm" | "escalate") => {
      void decide(reviewId, decision).catch(() => {
        // useDecideReview exposes the error as `decideError`.
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
    sessionId !== null && status !== null && isTerminalStatus(status);

  return (
    <div className="min-h-screen bg-[var(--paper)]">
      <Topbar
        signedInAs={{ name: signedInAs, role: "RN" }}
        centerSlot={
          sessionId && !showTerminal ? (
            <StatusDot
              status={
                streamStatus === "error"
                  ? "error"
                  : status === "awaiting_review"
                    ? "waiting"
                    : "running"
              }
              label={
                status === "awaiting_review"
                  ? "Awaiting your triage decision"
                  : "Triage session live"
              }
            />
          ) : null
        }
      />

      <main className="mx-auto max-w-5xl px-6 py-10">
        {!sessionId && (
          <SessionSelector
            onStart={handleStart}
            isStarting={isStarting}
            startError={startError}
          />
        )}

        {sessionId && !showTerminal && (
          <RunningView
            patient={snapshot?.patient_summary ?? null}
            chiefComplaint={snapshot?.patient_summary?.chief_complaint ?? null}
            events={events}
            riskTier={"medium"}
            isDeciding={isDeciding}
            decideError={decideError}
            onDecide={handleDecide}
          />
        )}

        {sessionId && showTerminal && snapshot && (
          <RoutedScreen
            session={snapshot}
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
  events: SessionEvent[];
  riskTier: RiskTier;
  isDeciding: boolean;
  decideError: Error | null;
  onDecide(reviewId: string, decision: "confirm" | "escalate"): void;
}) {
  const lastEvent = events[events.length - 1];
  // Find the most recent nurse_review_requested event — once a decision
  // has landed we hide the gate so the pipeline transitions cleanly.
  const reviewEvent = (() => {
    if (lastEvent?.event === "nurse_review_requested") return lastEvent;
    return null;
  })();

  return (
    <div className="mx-auto w-full max-w-3xl">
      <Card elevation="lg">
        <CardHeader>
          <div className="flex items-start justify-between gap-3">
            <div>
              <span className="font-mono text-[11px] uppercase tracking-wider text-[var(--ink-3)]">
                Live triage session
              </span>
              <CardTitle className="mt-1 text-xl">
                {chiefComplaint ?? "Patient symptoms · Last reported"}
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

      {reviewEvent && (
        <ReviewGate
          reviewEvent={reviewEvent}
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

function extractErrorMessage(events: SessionEvent[]): string | null {
  for (let i = events.length - 1; i >= 0; i--) {
    if (events[i].event === "error") {
      const data = events[i].data as { message?: unknown };
      if (typeof data.message === "string") return data.message;
    }
  }
  return null;
}
