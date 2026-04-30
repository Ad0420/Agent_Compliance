/**
 * Tests for `useEncounter` and `useStartEncounter`.
 *
 * Polling is timer-driven; we use `vi.useFakeTimers()` plus
 * `await vi.advanceTimersByTimeAsync(...)` so each test is fully
 * deterministic and finishes in milliseconds.
 */

import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { renderHook, waitFor, act } from "@testing-library/react";

import { useEncounter, useStartEncounter } from "@/hooks/use-encounter";
import type { EncounterSnapshot } from "@/lib/api/types";

function snapshot(
  overrides: Partial<EncounterSnapshot> = {},
): EncounterSnapshot {
  return {
    id: "enc_123",
    source: "fixture",
    fixture_key: "pancreatitis",
    patient_summary: null,
    status: "running",
    last_event: null,
    vera_approval_id: null,
    vera_record_ids: [],
    terminal_outcome: null,
    events: [],
    input_payload: { fixture: "pancreatitis" },
    created_at: "2026-04-29T14:22:13.123456+00:00",
    updated_at: "2026-04-29T14:22:13.123456+00:00",
    ...overrides,
  };
}

function jsonResponse(body: unknown, init: ResponseInit = {}): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "content-type": "application/json" },
    ...init,
  });
}

beforeEach(() => {
  vi.restoreAllMocks();
});

afterEach(() => {
  // Drain anything still pending on the fake clock so it can't bleed into
  // the next test as an unwrapped React state update.
  if (vi.isFakeTimers()) {
    vi.clearAllTimers();
    vi.useRealTimers();
  }
});

describe("useEncounter", () => {
  it("is idle when id is null — no fetch, no loading", () => {
    const fetchFn = vi.fn();
    globalThis.fetch = fetchFn as unknown as typeof fetch;

    const { result } = renderHook(() => useEncounter(null));

    expect(result.current.data).toBeNull();
    expect(result.current.isLoading).toBe(false);
    expect(result.current.error).toBeNull();
    expect(fetchFn).not.toHaveBeenCalled();
  });

  it("fetches once on mount and exposes data", async () => {
    const fetchFn = vi.fn(async () => jsonResponse(snapshot({ status: "committed" })));
    globalThis.fetch = fetchFn as unknown as typeof fetch;

    const { result } = renderHook(() => useEncounter("enc_123"));
    expect(result.current.isLoading).toBe(true);

    await waitFor(() => expect(result.current.data).not.toBeNull());
    expect(result.current.data?.id).toBe("enc_123");
    expect(result.current.error).toBeNull();
    expect(fetchFn).toHaveBeenCalledTimes(1);
    const call = fetchFn.mock.calls[0]?.[0] as string;
    expect(call).toContain("/api/encounters/enc_123");
  });

  it("polls every 1s while running and stops once committed", async () => {
    const responses = [
      snapshot({ status: "running" }),
      snapshot({ status: "running" }),
      snapshot({ status: "committed" }),
    ];
    const fetchFn = vi.fn(async () => {
      const body = responses.shift() ?? snapshot({ status: "committed" });
      return jsonResponse(body);
    });
    globalThis.fetch = fetchFn as unknown as typeof fetch;

    // shouldAdvanceTime keeps Promise microtasks flowing while we drive the
    // 1s polling clock manually with `advanceTimersByTimeAsync`. waitFor's
    // own setTimeout still ticks because shouldAdvanceTime is on.
    vi.useFakeTimers({ shouldAdvanceTime: true });

    const { result } = renderHook(() => useEncounter("enc_123"));

    await waitFor(() => expect(result.current.data?.status).toBe("running"));
    expect(fetchFn).toHaveBeenCalledTimes(1);

    // Drive the second poll @ +1s.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
      // drain the fetch promise + setState so it flushes inside act()
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(fetchFn).toHaveBeenCalledTimes(2);

    // Drive the third poll @ +1s — committed snapshot lands.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(fetchFn).toHaveBeenCalledTimes(3);
    await waitFor(() =>
      expect(result.current.data?.status).toBe("committed"),
    );

    // Many seconds later — still no new fetch (polling stopped on terminal).
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
      await Promise.resolve();
    });
    expect(fetchFn).toHaveBeenCalledTimes(3);
  });

  it("populates error on 404 and does not loop forever", async () => {
    const fetchFn = vi.fn(async () =>
      new Response(JSON.stringify({ detail: "not found" }), {
        status: 404,
        headers: { "content-type": "application/json" },
      }),
    );
    globalThis.fetch = fetchFn as unknown as typeof fetch;

    vi.useFakeTimers({ shouldAdvanceTime: true });

    const { result } = renderHook(() => useEncounter("missing"));

    await waitFor(() => expect(result.current.error).not.toBeNull());
    expect(result.current.isLoading).toBe(false);

    // The hook reschedules a poll even after an error (drives error recovery).
    // Bound the assertion: 5s should yield ~5 polls, never an infinite loop.
    const callsAfterFirstError = fetchFn.mock.calls.length;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(fetchFn.mock.calls.length).toBeLessThanOrEqual(
      callsAfterFirstError + 6,
    );
  });
});

describe("useStartEncounter", () => {
  it("POSTs the input and returns { id }", async () => {
    const fetchFn = vi.fn(async () =>
      new Response(JSON.stringify({ id: "enc_new", status: "running" }), {
        status: 201,
        headers: { "content-type": "application/json" },
      }),
    );
    globalThis.fetch = fetchFn as unknown as typeof fetch;

    const { result } = renderHook(() => useStartEncounter());

    let res: { id: string } | null = null;
    await act(async () => {
      res = await result.current.start({ fixture: "pancreatitis" });
    });

    expect(res).toEqual({ id: "enc_new" });
    expect(fetchFn).toHaveBeenCalledTimes(1);
    const [url, init] = fetchFn.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/api/encounters");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({ fixture: "pancreatitis" });
    expect(result.current.isStarting).toBe(false);
  });

  it("surfaces start errors and resets isStarting", async () => {
    const fetchFn = vi.fn(async () =>
      new Response(JSON.stringify({ detail: "bad fixture" }), {
        status: 400,
        headers: { "content-type": "application/json" },
      }),
    );
    globalThis.fetch = fetchFn as unknown as typeof fetch;

    const { result } = renderHook(() => useStartEncounter());

    let caught: unknown = null;
    await act(async () => {
      try {
        await result.current.start({ fixture: "pancreatitis" });
      } catch (err) {
        caught = err;
      }
    });

    expect(caught).toMatchObject({ name: "ApiError", status: 400 });
    expect(result.current.isStarting).toBe(false);
    expect(result.current.error).not.toBeNull();
  });
});
