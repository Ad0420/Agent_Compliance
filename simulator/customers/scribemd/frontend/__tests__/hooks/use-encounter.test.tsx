/**
 * Tests for `useEncounter` — null-id no-op, 1s polling, polling stops on
 * terminal status.
 */

import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { useEncounter } from "@/hooks/use-encounter";
import type { EncounterSnapshot, EncounterStatus } from "@/lib/api/types";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(body === null ? null : JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function snapshot(id: string, status: EncounterStatus): EncounterSnapshot {
  return {
    id,
    source: "fixture",
    fixture_key: "pancreatitis",
    patient_summary: null,
    status,
    last_event: null,
    vera_approval_id: null,
    vera_record_ids: [],
    terminal_outcome: null,
    events: [],
    input_payload: null,
    created_at: null,
    updated_at: null,
  };
}

describe("useEncounter", () => {
  it("returns null and never calls fetch when id is null", async () => {
    const fetchMock = vi.fn();
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const { result } = renderHook(() => useEncounter(null));

    expect(result.current.data).toBeNull();
    expect(result.current.isLoading).toBe(false);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("polls every 1s while status is non-terminal", async () => {
    const fetchMock = vi.fn().mockImplementation(() =>
      Promise.resolve(jsonResponse(200, snapshot("enc_1", "running"))),
    );
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    // Fake only the timers the hook uses for its poll cadence; leave
    // microtasks / queueMicrotask alone so RTL's renderHook + the React
    // scheduler can flush updates between fetches.
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });

    const { result } = renderHook(() => useEncounter("enc_1"));

    // Drain the initial fetch microtask chain.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(result.current.data?.status).toBe("running");

    // Advance past the 1s poll boundary.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1100);
    });

    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("stops polling when status is terminal", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(200, snapshot("enc_1", "committed")));
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });

    const { result } = renderHook(() => useEncounter("enc_1"));

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(result.current.data?.status).toBe("committed");

    // Advance well past the poll interval — no further fetches.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
