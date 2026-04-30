"use client";

/**
 * LivePipeline — vertical stack of SessionSteps driven by the SSE
 * event stream.
 *
 * The four narrative stages map to the named events from
 * `backend/contract.md`:
 *   1. Listening to symptoms        — done after `session_started`.
 *   2. Classifying triage level     — active during draft, done on `triage_classified`.
 *      Payload: AI level + confidence.
 *   3. Checking for red flags       — active until `red_flag_evaluated`.
 *      Payload: "Red-flag terms detected:" + list.
 *   4. Awaiting your triage decision — active when `nurse_review_requested` fires.
 *
 * The component is purely a view: it derives the step states from the
 * event list, never mutates anything itself.
 */

import * as React from "react";

import {
  SessionStep,
  type SessionStepState,
} from "@/components/ui/session-step";
import { RiskPill } from "@/components/ui/risk-pill";
import { Badge } from "@/components/ui/badge";
import type {
  SessionEvent,
  SessionEventType,
} from "@/lib/api/types";

interface LivePipelineProps {
  events: SessionEvent[];
}

interface TriageClassifiedPayload {
  level?: string;
  reasoning?: string;
  confidence?: number;
  model?: string;
  duration_ms?: number;
}

interface RedFlagEvaluatedPayload {
  flagged?: boolean;
  terms?: unknown[];
  recommended_override?: string;
  reasoning?: string;
}

function lastEventOfType<T extends SessionEventType>(
  events: SessionEvent[],
  type: T,
): SessionEvent | undefined {
  for (let i = events.length - 1; i >= 0; i--) {
    if (events[i].event === type) return events[i];
  }
  return undefined;
}

function hasEvent(events: SessionEvent[], type: SessionEventType): boolean {
  return events.some((e) => e.event === type);
}

export function LivePipeline({ events }: LivePipelineProps) {
  // Latest event drives "what's the active stage right now".
  const lastEvent = events[events.length - 1]?.event ?? null;

  const sessionStarted = hasEvent(events, "session_started");
  const classified = lastEventOfType(events, "triage_classified");
  const redFlagEvaluated = lastEventOfType(events, "red_flag_evaluated");
  const nurseReviewRequested = hasEvent(events, "nurse_review_requested");
  const nurseDecided = hasEvent(events, "nurse_decided");
  const routed = hasEvent(events, "routed");
  const routingBlocked = hasEvent(events, "routing_blocked");
  const errored = hasEvent(events, "error");
  const terminal = routed || routingBlocked || errored;

  // Step 1 — listening. Done as soon as `session_started` fires.
  const listeningState: SessionStepState = sessionStarted ? "done" : "active";

  // Step 2 — classifying.
  const classifyingState: SessionStepState = classified
    ? "done"
    : sessionStarted
      ? "active"
      : "idle";

  // Step 3 — red-flag check.
  const redFlagState: SessionStepState = redFlagEvaluated
    ? "done"
    : classified
      ? "active"
      : "idle";

  // Step 4 — review. Active when waiting on the nurse, done after a
  // decision lands. Blocked if the workflow ended in `routing_blocked`.
  const reviewState: SessionStepState = (() => {
    if (routingBlocked) return "blocked";
    if (routed || nurseDecided) return "done";
    if (nurseReviewRequested) return "active";
    return "idle";
  })();

  const classifiedPayload = classified?.data as
    | TriageClassifiedPayload
    | undefined;
  const redFlagPayload = redFlagEvaluated?.data as
    | RedFlagEvaluatedPayload
    | undefined;

  return (
    <div
      className="pt-1"
      aria-live="polite"
      aria-label="Triage session pipeline"
      data-last-event={lastEvent ?? "idle"}
      data-terminal={terminal ? "true" : "false"}
    >
      <SessionStep
        state={listeningState}
        label="Listening to symptoms"
        sublabel={
          listeningState === "active"
            ? "Capturing the patient's report"
            : "Captured · handed off to the classifier"
        }
      />
      <SessionStep
        state={classifyingState}
        label="Classifying triage level"
        sublabel={
          classifyingState === "done"
            ? formatClassifierMeta(classifiedPayload)
            : classifyingState === "active"
              ? "Picking a care level"
              : "Waiting on intake"
        }
        payload={
          classifiedPayload?.level ? (
            <div className="flex items-center gap-2">
              <span>AI proposed:</span>
              <Badge variant="neutral" withDot>
                {formatLevel(classifiedPayload.level)}
              </Badge>
            </div>
          ) : null
        }
      />
      <SessionStep
        state={redFlagState}
        label="Checking for red flags"
        sublabel={
          redFlagState === "done"
            ? redFlagPayload?.flagged
              ? "Red-flag terms found — held for nurse review"
              : "Cleared — no red-flag terms detected"
            : redFlagState === "active"
              ? "Scanning for clinical red-flag terms"
              : "Waiting on the classifier"
        }
        payload={
          redFlagPayload?.flagged && Array.isArray(redFlagPayload.terms) && redFlagPayload.terms.length > 0
            ? (
              <div className="flex flex-col gap-1.5">
                <span className="font-medium text-[var(--ink)]">
                  Red-flag terms detected:
                </span>
                <div className="flex flex-wrap gap-1.5">
                  {redFlagPayload.terms.map((t, i) => (
                    <RiskPill
                      key={`${String(t)}-${i}`}
                      tier="high"
                      compact
                      label={String(t)}
                    />
                  ))}
                </div>
              </div>
            )
            : null
        }
      />
      <SessionStep
        state={reviewState}
        label="Awaiting your triage decision"
        sublabel={
          reviewState === "blocked"
            ? "Decision expired — patient not routed"
            : reviewState === "done"
              ? "Decision recorded · patient routed"
              : reviewState === "active"
                ? "One review needed before the patient sees this"
                : "Will surface here when the AI finishes"
        }
        isLast
      />
    </div>
  );
}

function formatClassifierMeta(p: TriageClassifiedPayload | undefined): string {
  if (!p) return "Classification ready";
  const bits: string[] = [];
  if (p.model) bits.push(p.model);
  if (typeof p.duration_ms === "number" && p.duration_ms > 0) {
    bits.push(`${(p.duration_ms / 1000).toFixed(1)}s`);
  }
  if (typeof p.confidence === "number") {
    bits.push(`${Math.round(p.confidence * 100)}% confidence`);
  }
  return bits.length > 0 ? bits.join(" · ") : "Classification ready";
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
