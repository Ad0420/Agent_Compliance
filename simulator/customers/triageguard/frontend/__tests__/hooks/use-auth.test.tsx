/**
 * Tests for `AuthProvider` + `useAuth` — the data-layer source of truth for
 * "is the nurse signed in?". We assert the /me probe lifecycle and the
 * login/logout flows. fetch is mocked at the global level; no real network.
 */

import { describe, it, expect, beforeEach, vi } from "vitest";
import { act, waitFor } from "@testing-library/react";

import { useAuth } from "@/hooks/use-auth";
import { renderHookWithAuth } from "../helpers/render-with-auth";

interface FetchCall {
  url: string;
  init: RequestInit | undefined;
}

function mockFetchSequence(
  responders: Array<(url: string, init?: RequestInit) => Promise<Response> | Response>,
) {
  const calls: FetchCall[] = [];
  let i = 0;
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();
    calls.push({ url, init });
    const responder = responders[Math.min(i, responders.length - 1)];
    i += 1;
    return responder(url, init);
  });
  globalThis.fetch = fn as unknown as typeof fetch;
  return { fn, calls };
}

function jsonResponse(body: unknown, init: ResponseInit = {}): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "content-type": "application/json" },
    ...init,
  });
}

function emptyResponse(status = 204): Response {
  return new Response(null, { status });
}

beforeEach(() => {
  vi.restoreAllMocks();
});

describe("useAuth — /me probe on mount", () => {
  it("exposes signedInAs once /api/auth/me resolves", async () => {
    mockFetchSequence([
      () => jsonResponse({ signed_in_as: "Nurse Rivera, RN" }),
    ]);

    const { result } = renderHookWithAuth(() => useAuth());

    expect(result.current.signedInAs).toBeNull();
    expect(result.current.isLoading).toBe(true);

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });
    expect(result.current.signedInAs).toBe("Nurse Rivera, RN");
  });

  it("leaves signedInAs null on a 401 from /me and flips isLoading false", async () => {
    mockFetchSequence([
      () => new Response(JSON.stringify({ detail: "no session" }), {
        status: 401,
        headers: { "content-type": "application/json" },
      }),
    ]);

    const { result } = renderHookWithAuth(() => useAuth());

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.signedInAs).toBeNull();
  });
});

describe("useAuth — login / logout", () => {
  it("login('right-key') succeeds and a follow-up /me populates signedInAs", async () => {
    const { calls } = mockFetchSequence([
      // initial mount probe
      () => new Response(null, { status: 401 }),
      // POST /api/auth/login
      () => emptyResponse(204),
      // GET /api/auth/me after login
      () => jsonResponse({ signed_in_as: "Nurse Rivera, RN" }),
    ]);

    const { result } = renderHookWithAuth(() => useAuth());
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await act(async () => {
      await result.current.login("right-key");
    });

    expect(result.current.signedInAs).toBe("Nurse Rivera, RN");
    // Last two requests should be the POST and the /me probe.
    const tail = calls.slice(-2);
    expect(tail[0].url).toContain("/api/auth/login");
    expect(tail[0].init?.method).toBe("POST");
    expect(tail[1].url).toContain("/api/auth/me");
  });

  it("login('wrong-key') rejects with ApiError and leaves state untouched", async () => {
    mockFetchSequence([
      () => new Response(null, { status: 401 }),
      () => new Response(JSON.stringify({ detail: "Invalid passkey" }), {
        status: 401,
        headers: { "content-type": "application/json" },
      }),
    ]);

    const { result } = renderHookWithAuth(() => useAuth());
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await expect(
      act(async () => {
        await result.current.login("wrong-key");
      }),
    ).rejects.toMatchObject({ name: "ApiError", status: 401 });

    expect(result.current.signedInAs).toBeNull();
  });

  it("logout() clears signedInAs", async () => {
    mockFetchSequence([
      () => jsonResponse({ signed_in_as: "Nurse Rivera, RN" }),
      () => emptyResponse(204), // logout
    ]);

    const { result } = renderHookWithAuth(() => useAuth());
    await waitFor(() => expect(result.current.signedInAs).toBe("Nurse Rivera, RN"));

    await act(async () => {
      await result.current.logout();
    });

    expect(result.current.signedInAs).toBeNull();
  });
});
