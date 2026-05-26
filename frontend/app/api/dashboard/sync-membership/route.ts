/**
 * Route handler proxying POST `/api/dashboard/sync-membership` to the Vera
 * backend's `/v1/dashboard/sync-membership`. Same proxy pattern as
 * `/api/dashboard/api-keys/route.ts` — keeps the Clerk backend-bound JWT
 * server-side and forwards the backend's status verbatim.
 *
 * Used by the api-keys page's provisioning-state card to let the user
 * trigger membership reconciliation manually when the webhook pipeline
 * has missed an event.
 */
import { NextResponse } from "next/server";

import { fetchFromVera, VeraApiError } from "@/lib/api-server";
import { csrfGuard } from "@/lib/csrf";

export async function POST(req: Request) {
  const forbidden = csrfGuard(req);
  if (forbidden) return forbidden;

  try {
    const result = await fetchFromVera<{ status: string; role: string }>(
      "/v1/dashboard/sync-membership",
      { method: "POST" },
    );
    return NextResponse.json(result);
  } catch (err) {
    if (err instanceof VeraApiError) {
      const body =
        err.body && typeof err.body === "object"
          ? err.body
          : { error: err.message };
      return NextResponse.json(body, { status: err.status });
    }
    return NextResponse.json({ error: "Internal error" }, { status: 500 });
  }
}
