/**
 * Tests for the Review Inbox hooks (W2.1).
 *
 * `useReviewInbox` — polls the list endpoint and exposes items.
 * `useDecideReview` — POSTs an approve/reject decision through the
 *   backend (which itself routes through the Vera SDK).
 */

import { describe, it, expect, beforeEach, vi } from "vitest";
import { act, waitFor } from "@testing-library/react";

import {
  useDecideReview,
  useReviewInbox,
} from "@/hooks/use-review-inbox";
import type { ReviewInboxItem } from "@/lib/api/types";
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

const SAMPLE_ITEM: ReviewInboxItem = {
  approval_id: "apr_test_1",
  encounter_id: "enc_1",
  status: "pending",
  risk_tier: "high",
  required_role: "attending_physician",
  action_name: "commit_orders",
  agent_name: "scribemd-chart-committer",
  data_subject_id: "pt_1",
  context_excerpt: {
    diagnoses: ["Acute pancreatitis"],
    medication_orders: ["Ondansetron 4mg IV"],
    lab_or_imaging_orders: ["Lipase"],
  },
  decided_by: null,
  decided_at: null,
  decision_note: null,
  requested_at: "2026-05-26T11:30:00+00:00",
  expires_at: "2026-05-26T15:30:00+00:00",
  created_at: "2026-05-26T11:30:00+00:00",
  updated_at: "2026-05-26T11:30:00+00:00",
};

beforeEach(() => {
  vi.restoreAllMocks();
});

describe("useReviewInbox", () => {
  it("fetches pending reviews by default", async () => {
    const calls = installFetch((url) => {
      if (url.endsWith("/api/auth/me")) {
        return jsonResponse({ signed_in_as: "Dr. Adams" });
      }
      return jsonResponse({ items: [SAMPLE_ITEM], total: 1 });
    });

    const { result } = renderHookWithAuth(() => useReviewInbox());

    await waitFor(() => {
      expect(result.current.items.length).toBe(1);
    });

    const listingCall = calls.find((c) =>
      c.url.includes("/api/reviews?") || c.url.endsWith("/api/reviews"),
    );
    expect(listingCall).toBeDefined();
    expect(listingCall!.url).toContain("status=pending");
    expect(result.current.items[0].approval_id).toBe("apr_test_1");
    expect(result.current.total).toBe(1);
    expect(result.current.error).toBeNull();
  });

  it("honors the status filter", async () => {
    const calls = installFetch((url) => {
      if (url.endsWith("/api/auth/me")) {
        return jsonResponse({ signed_in_as: "Dr. Adams" });
      }
      return jsonResponse({
        items: [{ ...SAMPLE_ITEM, status: "approved" }],
        total: 1,
      });
    });

    const { result } = renderHookWithAuth(() =>
      useReviewInbox({ status: "approved" }),
    );

    await waitFor(() => {
      expect(result.current.items.length).toBe(1);
    });

    const listingCall = calls.find((c) => c.url.includes("/api/reviews"));
    expect(listingCall!.url).toContain("status=approved");
    expect(result.current.items[0].status).toBe("approved");
  });

  it("surfaces an error response", async () => {
    installFetch((url) => {
      if (url.endsWith("/api/auth/me")) {
        return jsonResponse({ signed_in_as: "Dr. Adams" });
      }
      return new Response(JSON.stringify({ detail: "boom" }), {
        status: 500,
        headers: { "content-type": "application/json" },
      });
    });

    const { result } = renderHookWithAuth(() => useReviewInbox());

    await waitFor(() => {
      expect(result.current.error).not.toBeNull();
    });
    expect(result.current.items.length).toBe(0);
  });
});

describe("useDecideReview", () => {
  it("approve(id) posts decision + role + note", async () => {
    const calls = installFetch((url) => {
      if (url.endsWith("/api/auth/me")) {
        return jsonResponse({ signed_in_as: "Dr. Adams" });
      }
      return jsonResponse({
        ...SAMPLE_ITEM,
        decided_by: "Dr. Adams",
        decision_note: "lgtm",
      });
    });

    const { result } = renderHookWithAuth(() => useDecideReview());

    let returned: ReviewInboxItem | undefined;
    await act(async () => {
      returned = await result.current.decide("apr_test_1", "approve", "lgtm");
    });

    const decideCall = calls.find(
      (c) => c.url.includes("/api/reviews/") && c.init?.method === "POST",
    );
    expect(decideCall).toBeDefined();
    expect(decideCall!.url).toContain("/api/reviews/apr_test_1/decide");
    const body = JSON.parse(decideCall!.init!.body as string);
    expect(body).toEqual({
      decision: "approve",
      reviewer_role: "attending_physician",
      note: "lgtm",
    });
    expect(returned?.decided_by).toBe("Dr. Adams");
    expect(result.current.isDeciding).toBe(false);
    expect(result.current.error).toBeNull();
  });

  it("reject(id) passes through the reject decision + role override", async () => {
    const calls = installFetch((url) => {
      if (url.endsWith("/api/auth/me")) {
        return jsonResponse({ signed_in_as: "Dr. Adams" });
      }
      return jsonResponse({ ...SAMPLE_ITEM });
    });

    const { result } = renderHookWithAuth(() => useDecideReview());

    await act(async () => {
      await result.current.decide(
        "apr_test_1",
        "reject",
        "not warranted",
        "dea_licensed_physician",
      );
    });

    const decideCall = calls.find(
      (c) => c.url.includes("/api/reviews/") && c.init?.method === "POST",
    );
    const body = JSON.parse(decideCall!.init!.body as string);
    expect(body).toEqual({
      decision: "reject",
      reviewer_role: "dea_licensed_physician",
      note: "not warranted",
    });
  });

  it("surfaces ApiError on 403", async () => {
    installFetch((url) => {
      if (url.endsWith("/api/auth/me")) {
        return jsonResponse({ signed_in_as: "Dr. Adams" });
      }
      return new Response(
        JSON.stringify({ detail: "reviewer_credentials_insufficient" }),
        { status: 403, headers: { "content-type": "application/json" } },
      );
    });

    const { result } = renderHookWithAuth(() => useDecideReview());

    let caught: unknown = null;
    await act(async () => {
      try {
        await result.current.decide("apr_test_1", "approve");
      } catch (err) {
        caught = err;
      }
    });

    expect(caught).toMatchObject({ name: "ApiError", status: 403 });
    expect(result.current.error).not.toBeNull();
  });
});
