/**
 * Tests for `useDecideApproval` — verifies the approver propagates from
 * `useAuth` and the in-flight `isDeciding` flag toggles correctly.
 */

import { act, renderHook, waitFor } from "@testing-library/react";
import * as React from "react";
import { describe, expect, it, vi } from "vitest";

import { AuthProvider, useAuth } from "@/hooks/use-auth";
import { useDecideApproval } from "@/hooks/use-decide-approval";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(body === null ? null : JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function wrapper({ children }: { children: React.ReactNode }) {
  return <AuthProvider>{children}</AuthProvider>;
}

describe("useDecideApproval", () => {
  it("posts to /api/approvals/{id}/decide with the approver from useAuth", async () => {
    const fetchMock = vi
      .fn()
      // /me probe — returns a signed-in user.
      .mockResolvedValueOnce(jsonResponse(200, { signed_in_as: "Dr. Ramirez" }))
      // The decide POST.
      .mockResolvedValueOnce(
        jsonResponse(200, {
          approval_id: "apr_x",
          decision: "approve",
          approver: "Dr. Ramirez",
          received: true,
        }),
      );
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const { result } = renderHook(
      () => ({ decide: useDecideApproval(), auth: useAuth() }),
      { wrapper },
    );

    // Wait for the AuthProvider to finish probing /me — otherwise the hook
    // would fall back to the "ScribeMD User" default approver.
    await waitFor(() =>
      expect(result.current.auth.signedInAs).toBe("Dr. Ramirez"),
    );

    await act(async () => {
      await result.current.decide.decide("apr_x", "approve", "lgtm");
    });

    expect(fetchMock).toHaveBeenCalledTimes(2);
    const [url, init] = fetchMock.mock.calls[1];
    expect(url).toContain("/api/approvals/apr_x/decide");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({
      decision: "approve",
      approver: "Dr. Ramirez",
      note: "lgtm",
    });
  });

  it("toggles isDeciding true while the request is in flight", async () => {
    let resolveDecide: ((value: Response) => void) | undefined;
    const decidePromise = new Promise<Response>((resolve) => {
      resolveDecide = resolve;
    });
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(200, { signed_in_as: "Dr. Lee" }))
      .mockReturnValueOnce(decidePromise);
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const { result } = renderHook(
      () => ({ decide: useDecideApproval(), auth: useAuth() }),
      { wrapper },
    );
    await waitFor(() => expect(result.current.auth.signedInAs).toBe("Dr. Lee"));

    expect(result.current.decide.isDeciding).toBe(false);

    let decideCall: Promise<void> | undefined;
    act(() => {
      decideCall = result.current.decide.decide("apr_y", "reject");
    });

    await waitFor(() => expect(result.current.decide.isDeciding).toBe(true));

    await act(async () => {
      resolveDecide!(
        jsonResponse(200, {
          approval_id: "apr_y",
          decision: "reject",
          approver: "Dr. Lee",
          received: true,
        }),
      );
      await decideCall;
    });

    expect(result.current.decide.isDeciding).toBe(false);
    expect(result.current.decide.error).toBeNull();
  });
});
