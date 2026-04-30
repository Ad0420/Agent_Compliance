"use client";

/**
 * LivePipeline — vertical stack of EncounterSteps driven by the SSE
 * event stream.
 *
 * The four narrative stages map to the named events from
 * `backend/contract.md`:
 *   1. Listening to the visit   — done after `draft_started`.
 *   2. Drafting note            — active during draft, done on `draft_complete`.
 *      Payload: model name + token count.
 *   3. Extracting orders        — active until `orders_extracted`.
 *      Payload: counts ("3 diagnoses · 2 med orders · 4 lab orders").
 *   4. Awaiting your sign-off   — active when `approval_requested` fires.
 *
 * The component is purely a view: it derives the step states from the
 * event list, never mutates anything itself. Order events also drive
 * the data shown to the clinician in the approval gate below.
 */

import * as React from "react";

import {
  EncounterStep,
  type EncounterStepState,
} from "@/components/ui/encounter-step";
import type {
  EncounterEvent,
  EncounterEventType,
} from "@/lib/api/types";

interface LivePipelineProps {
  events: EncounterEvent[];
}

interface DraftCompletePayload {
  model?: string;
  tokens?: { input?: number; output?: number };
  duration_ms?: number;
}

interface OrdersExtractedPayload {
  diagnoses?: unknown[];
  medication_orders?: unknown[];
  lab_or_imaging_orders?: unknown[];
}

function lastEventOfType<T extends EncounterEventType>(
  events: EncounterEvent[],
  type: T,
): EncounterEvent | undefined {
  for (let i = events.length - 1; i >= 0; i--) {
    if (events[i].event === type) return events[i];
  }
  return undefined;
}

function hasEvent(events: EncounterEvent[], type: EncounterEventType): boolean {
  return events.some((e) => e.event === type);
}

export function LivePipeline({ events }: LivePipelineProps) {
  // Latest non-error event drives "what's the active stage right now".
  const lastEvent = events[events.length - 1]?.event ?? null;

  const draftStartedSeen = hasEvent(events, "draft_started");
  const draftComplete = lastEventOfType(events, "draft_complete");
  const ordersExtracted = lastEventOfType(events, "orders_extracted");
  const approvalRequested = hasEvent(events, "approval_requested");
  const terminal =
    hasEvent(events, "chart_committed") ||
    hasEvent(events, "chart_blocked") ||
    hasEvent(events, "error");

  // Step 1 — listening. Done as soon as draft starts (the recording has
  // been handed off to the drafter); active while we wait for that.
  const listeningState: EncounterStepState = draftStartedSeen ? "done" : "active";

  // Step 2 — drafting.
  const draftingState: EncounterStepState = draftComplete
    ? "done"
    : draftStartedSeen
      ? "active"
      : "idle";

  // Step 3 — extracting.
  const extractingState: EncounterStepState = ordersExtracted
    ? "done"
    : draftComplete
      ? "active"
      : "idle";

  // Step 4 — sign-off. Active when waiting on the human, done after a
  // decision lands. Blocked if the encounter ended in `chart_blocked`.
  const signOffState: EncounterStepState = (() => {
    if (hasEvent(events, "chart_blocked")) return "blocked";
    if (
      hasEvent(events, "chart_committed") ||
      hasEvent(events, "approval_decided")
    ) {
      return "done";
    }
    if (approvalRequested) return "active";
    return "idle";
  })();

  const draftPayload = draftComplete?.data as DraftCompletePayload | undefined;
  const ordersPayload = ordersExtracted?.data as
    | OrdersExtractedPayload
    | undefined;

  const draftPayloadText = draftPayload
    ? formatDraftPayload(draftPayload)
    : null;

  const ordersPayloadText = ordersPayload
    ? formatOrdersPayload(ordersPayload)
    : null;

  return (
    <div
      className="pt-1"
      aria-live="polite"
      aria-label="Encounter pipeline"
      data-last-event={lastEvent ?? "idle"}
      data-terminal={terminal ? "true" : "false"}
    >
      <EncounterStep
        state={listeningState}
        label="Listening to the visit"
        sublabel={
          listeningState === "active"
            ? "Capturing audio and transcribing live"
            : "Captured · handed off to the drafter"
        }
      />
      <EncounterStep
        state={draftingState}
        label="Drafting note"
        sublabel={
          draftingState === "done"
            ? "SOAP draft ready for review"
            : draftingState === "active"
              ? "Writing the SOAP note"
              : "Waiting on the transcript"
        }
        payload={draftPayloadText}
      />
      <EncounterStep
        state={extractingState}
        label="Extracting orders"
        sublabel={
          extractingState === "done"
            ? "Diagnoses, meds and labs identified"
            : extractingState === "active"
              ? "Pulling orders out of the draft"
              : "Waiting on the draft"
        }
        payload={ordersPayloadText}
      />
      <EncounterStep
        state={signOffState}
        label="Awaiting your sign-off"
        sublabel={
          signOffState === "blocked"
            ? "Rejected — chart not signed"
            : signOffState === "done"
              ? "Decision recorded"
              : signOffState === "active"
                ? "One review needed before we save"
                : "Will surface here when the draft is ready"
        }
        isLast
      />
    </div>
  );
}

function formatDraftPayload(p: DraftCompletePayload): string | null {
  const bits: string[] = [];
  if (p.model) bits.push(p.model);
  const tokens = p.tokens;
  if (tokens) {
    const total =
      (typeof tokens.input === "number" ? tokens.input : 0) +
      (typeof tokens.output === "number" ? tokens.output : 0);
    if (total > 0) bits.push(`${total.toLocaleString()} tokens`);
  }
  if (typeof p.duration_ms === "number" && p.duration_ms > 0) {
    bits.push(`${(p.duration_ms / 1000).toFixed(1)}s`);
  }
  return bits.length > 0 ? bits.join(" · ") : null;
}

function formatOrdersPayload(p: OrdersExtractedPayload): string | null {
  const dx = Array.isArray(p.diagnoses) ? p.diagnoses.length : 0;
  const meds = Array.isArray(p.medication_orders)
    ? p.medication_orders.length
    : 0;
  const labs = Array.isArray(p.lab_or_imaging_orders)
    ? p.lab_or_imaging_orders.length
    : 0;
  if (dx + meds + labs === 0) return null;
  return `${pluralize(dx, "diagnosis", "diagnoses")} · ${pluralize(
    meds,
    "med order",
    "med orders",
  )} · ${pluralize(labs, "lab order", "lab orders")}`;
}

function pluralize(n: number, singular: string, plural: string): string {
  return `${n} ${n === 1 ? singular : plural}`;
}
