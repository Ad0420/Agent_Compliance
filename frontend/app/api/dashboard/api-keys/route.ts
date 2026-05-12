/**
 * Route handlers that proxy POST/GET `/api/dashboard/api-keys` to the Vera
 * backend's `/v1/dashboard/api-keys` endpoint. The proxy exists so the
 * client island (`ApiKeyTable`) can mutate state without ever holding the
 * Clerk backend-bound JWT — the token only ever leaves the server.
 *
 * Errors are forwarded with their original status so the client can decide
 * how to render them. The response body of POST contains the raw key
 * exactly once.
 */
import { NextResponse } from "next/server";

import {
  createDashboardApiKey,
  listDashboardApiKeys,
  VeraApiError,
  type DashboardApiKeyCreateInput,
} from "@/lib/api-server";
import { csrfGuard } from "@/lib/csrf";

export async function GET() {
  try {
    const keys = await listDashboardApiKeys();
    return NextResponse.json(keys);
  } catch (err) {
    return errorResponse(err);
  }
}

export async function POST(req: Request) {
  // CSRF: same-origin allow-list on the mutating handler. Clerk's
  // SameSite=Lax cookies already block top-level navigation CSRF, but a
  // same-site XSS could still mint keys without this guard.
  const forbidden = csrfGuard(req);
  if (forbidden) return forbidden;

  let payload: DashboardApiKeyCreateInput;
  try {
    payload = (await req.json()) as DashboardApiKeyCreateInput;
  } catch {
    return NextResponse.json({ error: "Invalid JSON body" }, { status: 400 });
  }
  if (!payload?.name || typeof payload.name !== "string") {
    return NextResponse.json(
      { error: "Field 'name' is required" },
      { status: 400 },
    );
  }
  try {
    const created = await createDashboardApiKey(payload);
    return NextResponse.json(created);
  } catch (err) {
    return errorResponse(err);
  }
}

function errorResponse(err: unknown): NextResponse {
  if (err instanceof VeraApiError) {
    const body =
      err.body && typeof err.body === "object"
        ? err.body
        : { error: err.message };
    return NextResponse.json(body, { status: err.status });
  }
  return NextResponse.json({ error: "Internal error" }, { status: 500 });
}
