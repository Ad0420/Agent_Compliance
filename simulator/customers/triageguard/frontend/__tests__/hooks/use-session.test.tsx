/**
 * Tests for `useSession` and `useStartSession`.
 *
 * Polling is timer-driven; we use `vi.useFakeTimers()` plus
 * `await vi.advanceTimersByTimeAsync(...)` so each test is fully
 * deterministic and finishes in milliseconds.
 */

import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { renderHook, waitFor, act } from "@testing-library/react";

import { useSession, useStartSession } from "@/hooks/use-session";
import type { SessionSnapshot } from "@/lib/api/types";

function snapshot(
  overrides: Partial<SessionSnapshot> = {},
): SessionSnapshot {
  return {
    id: "ses_123",
    source: "fixture",
    fixture_key: "red_flag_chest_pain",
    patient_summary: null,
    status: "running",
    last_event: null,
    vera_approval_id: null,
    vera_record_ids: [],
    terminal_outcome: null,
    events: [],
    input_payload: { fixture: "red_flag_chest_pain" },
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

describe("useSession", () => {
  it("is idle when id is null — no fetch, no loading", () => {
    const fetchFn = vi.fn();
    globalThis.fetch = fetchFn as unknown as typeof fetch;

    const { result } = renderHook(() => useSession(null));

    expect(result.current.data).toBeNull();
    expect(result.current.isLoading).toBe(false);
    expect(result.current.error).toBeNull();
    expect(fetchFn).not.toHaveBeenCalled();
  });

  it("fetches once on mount and exposes data", async () => {
    const fetchFn = vi.fn<typeof fetch>(
      async () => jsonResponse(snapshot({ status: "routed" })),
    );
    globalThis.fetch = fetchFn as unknown as typeof fetch;

    const { result } = renderHook(() => useSession("ses_123"));
    expect(result.current.isLoading).toBe(true);

    await waitFor(() => expect(result.current.data).not.toBeNull());
    expect(result.current.data?.id).toBe("ses_123");
    expect(result.current.error).toBeNull();
    expect(fetchFn).toHaveBeenCalledTimes(1);
    const call = String(fetchFn.mock.calls[0]?.[0] ?? "");
    expect(call).toContain("/api/sessions/ses_123");
  });

  it("polls every 1s while running and stops once routed", async () => {
    const responses = [
      snapshot({ status: "running" }),
      snapshot({ status: "running" }),
      snapshot({ status: "routed" }),
    ];
    const fetchFn = vi.fn(async () => {
      const body = responses.shift() ?? snapshot({ status: "routed" });
      return jsonResponse(body);
    });
    globalThis.fetch = fetchFn as unknown as typeof fetch;

    // shouldAdvanceTime keeps Promise microtasks flowing while we drive the
    // 1s polling clock manually with `advanceTimersByTimeAsync`. waitFor's
    // own setTimeout still ticks because shouldAdvanceTime is on.
    vi.useFakeTimers({ shouldAdvanceTime: true });

    const { result } = renderHook(() => useSession("ses_123"));

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

    // Drive the third poll @ +1s — routed snapshot lands.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(fetchFn).toHaveBeenCalledTimes(3);
    await waitFor(() =>
      expect(result.current.data?.status).toBe("routed"),
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

    const { result } = renderHook(() => useSession("missing"));

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

describe("useStartSession", () => {
  it("POSTs the input and returns { id }", async () => {
    const fetchFn = vi.fn<typeof fetch>(
      async () =>
        new Response(JSON.stringify({ id: "ses_new", status: "running" }), {
          status: 201,
          headers: { "content-type": "application/json" },
        }),
    );
    globalThis.fetch = fetchFn as unknown as typeof fetch;

    const { result } = renderHook(() => useStartSession());

    let res: { id: string } | null = null;
    await act(async () => {
      res = await result.current.start({ fixture: "red_flag_chest_pain" });
    });

    expect(res).toEqual({ id: "ses_new" });
    expect(fetchFn).toHaveBeenCalledTimes(1);
    const firstCall = fetchFn.mock.calls[0];
    expect(firstCall).toBeDefined();
    const url = String(firstCall![0]);
    const init = firstCall![1] as RequestInit;
    expect(url).toContain("/api/sessions");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({
      fixture: "red_flag_chest_pain",
    });
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

    const { result } = renderHook(() => useStartSession());

    let caught: unknown = null;
    await act(async () => {
      try {
        await result.current.start({ fixture: "easy_self_care" });
      } catch (err) {
        caught = err;
      }
    });

    expect(caught).toMatchObject({ name: "ApiError", status: 400 });
    expect(result.current.isStarting).toBe(false);
    expect(result.current.error).not.toBeNull();
  });
});
