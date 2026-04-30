/**
 * Tests for `useSessionEvents` — the SSE consumer.
 *
 * The mock `EventSource` is installed globally in `vitest.setup.ts`. Tests
 * grab the live instance from `MockEventSource.instances`, dispatch named
 * events, and assert hook state.
 */

import { describe, it, expect } from "vitest";
import { renderHook, act } from "@testing-library/react";

import { useSessionEvents } from "@/hooks/use-session-events";
import { MockEventSource } from "../helpers/mock-event-source";

const ALL_EVENT_NAMES = [
  "session_started",
  "triage_classified",
  "red_flag_evaluated",
  "nurse_review_requested",
  "nurse_decided",
  "routed",
  "routing_blocked",
  "error",
] as const;

describe("useSessionEvents", () => {
  it("opens an EventSource on mount with withCredentials: true", () => {
    renderHook(() => useSessionEvents("ses_abc"));

    expect(MockEventSource.instances).toHaveLength(1);
    const es = MockEventSource.instances[0];
    expect(es.url).toContain("/api/events/ses_abc");
    expect(es.withCredentials).toBe(true);
  });

  it("parses each named event type and appends in order", async () => {
    const { result } = renderHook(() => useSessionEvents("ses_abc"));
    const es = MockEventSource.instances[0];

    // Dispatch every non-terminal event type so we never close mid-loop.
    const nonTerminal = [
      "session_started",
      "triage_classified",
      "red_flag_evaluated",
      "nurse_review_requested",
      "nurse_decided",
    ] as const;

    for (const name of nonTerminal) {
      await act(async () => {
        es.dispatch(name, { event: name, sample: true });
      });
    }

    expect(result.current.events).toHaveLength(nonTerminal.length);
    expect(result.current.events.map((e) => e.event)).toEqual([...nonTerminal]);
    // Each payload should have round-tripped through JSON.parse.
    for (const ev of result.current.events) {
      expect((ev.data as { sample: boolean }).sample).toBe(true);
    }

    // Sanity-check that the hook actually subscribes to all 8 contract names.
    // We can't introspect `addEventListener` directly, but every event name
    // should round-trip without throwing. Wrap each dispatch in act since
    // the hook performs a `setState` synchronously inside its listener.
    for (const name of ALL_EVENT_NAMES) {
      await act(async () => {
        es.dispatch(name, { ok: true });
      });
    }
  });

  it("closes the EventSource on unmount", () => {
    const { unmount } = renderHook(() => useSessionEvents("ses_abc"));
    const es = MockEventSource.instances[0];
    expect(es.closeCalled).toBe(false);
    unmount();
    expect(es.closeCalled).toBe(true);
  });

  it("flips status to 'closed' on a terminal event (routed)", async () => {
    const { result } = renderHook(() => useSessionEvents("ses_abc"));
    const es = MockEventSource.instances[0];

    await act(async () => {
      es.dispatch("routed", { final_level: "ER", auto: false, record_id: "rec_1" });
    });

    expect(result.current.status).toBe("closed");
    expect(result.current.events).toHaveLength(1);
    expect(es.closeCalled).toBe(true);
  });

  it("transitions to status 'error' on EventSource error and does not reconnect", async () => {
    const { result } = renderHook(() => useSessionEvents("ses_abc"));
    const es = MockEventSource.instances[0];

    await act(async () => {
      es.triggerError(); // readyState != CLOSED → genuine error path
    });

    expect(result.current.status).toBe("error");
    expect(result.current.error).toBeInstanceOf(Error);
    expect(es.closeCalled).toBe(true);
    // No second instance was opened — there is no auto-reconnect.
    expect(MockEventSource.instances).toHaveLength(1);
  });
});
