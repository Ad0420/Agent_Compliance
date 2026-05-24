/**
 * GET /api/dashboard/baa-status — proxy to /v1/organizations/me/baa-status.
 *
 * Phase 1 PR 4 (Stream C item C5): the API-keys create dialog calls this
 * when the operator switches to the "Production" tab so the "Create live
 * key" button is gated against the BAA state without leaking a Clerk
 * session token to the client island. Pure read; no CSRF needed.
 *
 * The backend bypasses its 60s freshness cache on this endpoint so the
 * operator who *just* uploaded a BAA sees the green light immediately.
 */
import { NextResponse } from "next/server";

import { getOrganizationBaaStatus, VeraApiError } from "@/lib/api-server";

export async function GET() {
  try {
    const status = await getOrganizationBaaStatus();
    return NextResponse.json(status);
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
