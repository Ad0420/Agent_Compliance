/**
 * Tests for `AuthProvider` + `useAuth`.
 *
 * Each test stubs `fetch` directly — the auth hook calls `apiMe` /
 * `apiLogin`, which both go through the shared `request()` wrapper, so
 * we can fully control state via response shapes.
 */

import { act, renderHook, waitFor } from "@testing-library/react";
import * as React from "react";
import { describe, expect, it, vi } from "vitest";

import { AuthProvider, useAuth } from "@/hooks/use-auth";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(body === null ? null : JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function wrapper({ children }: { children: React.ReactNode }) {
  return <AuthProvider>{children}</AuthProvider>;
}

describe("useAuth", () => {
  it("resolves signedInAs from /me on mount when 200", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(200, { signed_in_as: "Dr. Chen" }));
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const { result } = renderHook(() => useAuth(), { wrapper });

    expect(result.current.isLoading).toBe(true);
    expect(result.current.signedInAs).toBeNull();

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.signedInAs).toBe("Dr. Chen");
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][0]).toContain("/api/auth/me");
  });

  it("keeps signedInAs null when /me returns 401", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(401, { detail: "no session" }));
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const { result } = renderHook(() => useAuth(), { wrapper });

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.signedInAs).toBeNull();
  });

  it("login('good-passkey') succeeds and updates signedInAs", async () => {
    const fetchMock = vi
      .fn()
      // Initial /me probe — 401, signed out.
      .mockResolvedValueOnce(jsonResponse(401, { detail: "no session" }))
      // login() POST — 204 no content.
      .mockResolvedValueOnce(new Response(null, { status: 204 }))
      // Re-probe /me after login — now signed in.
      .mockResolvedValueOnce(jsonResponse(200, { signed_in_as: "Dr. Wells" }));
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await act(async () => {
      await result.current.login("good-passkey");
    });

    expect(result.current.signedInAs).toBe("Dr. Wells");

    // Verify the login call shape.
    const loginCall = fetchMock.mock.calls[1];
    expect(loginCall[0]).toContain("/api/auth/login");
    expect(loginCall[1].method).toBe("POST");
    expect(JSON.parse(loginCall[1].body)).toEqual({ passkey: "good-passkey" });
  });

  it("login('bad') rejects on 401 and signedInAs stays null", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(401, { detail: "no session" }))
      .mockResolvedValueOnce(jsonResponse(401, { detail: "bad passkey" }));
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await expect(
      act(async () => {
        await result.current.login("bad");
      }),
    ).rejects.toThrow();

    expect(result.current.signedInAs).toBeNull();
  });
});
