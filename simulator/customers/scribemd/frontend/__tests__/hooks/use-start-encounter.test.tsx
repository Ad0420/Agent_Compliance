/**
 * Tests for `useStartEncounter` — fixture POST shape and 4xx error surface.
 */

import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { useStartEncounter } from "@/hooks/use-encounter";
import { ApiError } from "@/lib/api/client";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(body === null ? null : JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("useStartEncounter", () => {
  it("posts the fixture body and returns { id }", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        jsonResponse(200, { id: "enc_42", status: "running" }),
      );
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const { result } = renderHook(() => useStartEncounter());

    let returned: { id: string } | undefined;
    await act(async () => {
      returned = await result.current.start({ fixture: "pancreatitis" });
    });

    expect(returned).toEqual({ id: "enc_42" });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toContain("/api/encounters");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({ fixture: "pancreatitis" });
  });

  it("surfaces ApiError on 4xx", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        jsonResponse(422, { detail: "unsupported fixture" }),
      );
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const { result } = renderHook(() => useStartEncounter());

    let caught: unknown;
    await act(async () => {
      try {
        await result.current.start({ fixture: "pancreatitis" });
      } catch (err) {
        caught = err;
      }
    });

    expect(caught).toBeInstanceOf(ApiError);
    expect((caught as ApiError).status).toBe(422);
    expect(result.current.error).toBeInstanceOf(ApiError);
    expect((result.current.error as ApiError).status).toBe(422);
  });
});
