/**
 * Tests for `useDecideReview` — wraps `decideReview` and pulls the
 * nurse name from `useAuth`. Renders inside `<AuthProvider />` so the
 * `signedInAs` value can be observed in the request body.
 */

import { describe, it, expect, beforeEach, vi } from "vitest";
import { act, waitFor } from "@testing-library/react";

import { useDecideReview } from "@/hooks/use-decide-review";
import { useAuth } from "@/hooks/use-auth";
import { renderHookWithAuth } from "../helpers/render-with-auth";

interface Recorded {
  url: string;
  init: RequestInit | undefined;
}

function jsonResponse(body: unknown, init: ResponseInit = {}): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "content-type": "application/json" },
    ...init,
  });
}

function installFetch(
  responder: (url: string, init?: RequestInit) => Response | Promise<Response>,
) {
  const calls: Recorded[] = [];
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();
    calls.push({ url, init });
    return responder(url, init);
  });
  globalThis.fetch = fn as unknown as typeof fetch;
  return calls;
}

beforeEach(() => {
  vi.restoreAllMocks();
});

describe("useDecideReview", () => {
  it("decide(id, 'confirm') uses the signed-in nurse and 'confirm' decision", async () => {
    // /me returns Nurse Rivera, RN; the decide POST returns the canonical 200 body.
    const calls = installFetch((url) => {
      if (url.endsWith("/api/auth/me")) {
        return jsonResponse({ signed_in_as: "Nurse Rivera, RN" });
      }
      return jsonResponse({
        approval_id: "apr_1",
        decision: "confirm",
        nurse: "Nurse Rivera, RN",
        received: true,
      });
    });

    const { result } = renderHookWithAuth(() => ({
      auth: useAuth(),
      decide: useDecideReview(),
    }));

    await waitFor(() =>
      expect(result.current.auth.signedInAs).toBe("Nurse Rivera, RN"),
    );

    await act(async () => {
      await result.current.decide.decide("apr_1", "confirm");
    });

    const decideCall = calls.find((c) => c.url.includes("/api/reviews/"));
    expect(decideCall).toBeDefined();
    expect(decideCall!.url).toContain("/api/reviews/apr_1/decide");
    expect(decideCall!.init?.method).toBe("POST");
    const body = JSON.parse(decideCall!.init!.body as string);
    expect(body).toEqual({
      decision: "confirm",
      nurse: "Nurse Rivera, RN",
      note: null,
    });
  });

  it("propagates the optional note on escalation", async () => {
    const calls = installFetch((url) => {
      if (url.endsWith("/api/auth/me")) {
        return jsonResponse({ signed_in_as: "Nurse Rivera, RN" });
      }
      return jsonResponse({
        approval_id: "apr_2",
        decision: "escalate",
        nurse: "Nurse Rivera, RN",
        received: true,
      });
    });

    const { result } = renderHookWithAuth(() => ({
      auth: useAuth(),
      decide: useDecideReview(),
    }));

    await waitFor(() =>
      expect(result.current.auth.signedInAs).toBe("Nurse Rivera, RN"),
    );

    await act(async () => {
      await result.current.decide.decide(
        "apr_2",
        "escalate",
        "obvious red flags",
      );
    });

    const decideCall = calls.find((c) => c.url.includes("/api/reviews/"));
    const body = JSON.parse(decideCall!.init!.body as string);
    expect(body).toEqual({
      decision: "escalate",
      nurse: "Nurse Rivera, RN",
      note: "obvious red flags",
    });
  });

  it("toggles isDeciding around the call", async () => {
    let resolveDecide: ((value: Response) => void) | null = null;
    installFetch((url) => {
      if (url.endsWith("/api/auth/me")) {
        return jsonResponse({ signed_in_as: "Nurse Rivera, RN" });
      }
      return new Promise<Response>((resolve) => {
        resolveDecide = resolve;
      });
    });

    const { result } = renderHookWithAuth(() => ({
      auth: useAuth(),
      decide: useDecideReview(),
    }));

    await waitFor(() =>
      expect(result.current.auth.signedInAs).toBe("Nurse Rivera, RN"),
    );
    expect(result.current.decide.isDeciding).toBe(false);

    let pending: Promise<void>;
    act(() => {
      pending = result.current.decide.decide("apr_3", "confirm");
    });

    await waitFor(() => expect(result.current.decide.isDeciding).toBe(true));

    await act(async () => {
      resolveDecide!(
        jsonResponse({
          approval_id: "apr_3",
          decision: "confirm",
          nurse: "Nurse Rivera, RN",
          received: true,
        }),
      );
      await pending!;
    });

    expect(result.current.decide.isDeciding).toBe(false);
  });

  it("surfaces ApiError on the error path", async () => {
    installFetch((url) => {
      if (url.endsWith("/api/auth/me")) {
        return jsonResponse({ signed_in_as: "Nurse Rivera, RN" });
      }
      return new Response(JSON.stringify({ detail: "review not found" }), {
        status: 404,
        headers: { "content-type": "application/json" },
      });
    });

    const { result } = renderHookWithAuth(() => ({
      auth: useAuth(),
      decide: useDecideReview(),
    }));

    await waitFor(() =>
      expect(result.current.auth.signedInAs).toBe("Nurse Rivera, RN"),
    );

    let caught: unknown = null;
    await act(async () => {
      try {
        await result.current.decide.decide("apr_missing", "escalate");
      } catch (err) {
        caught = err;
      }
    });

    expect(caught).toMatchObject({ name: "ApiError", status: 404 });
    expect(result.current.decide.isDeciding).toBe(false);
    expect(result.current.decide.error).not.toBeNull();
  });
});
