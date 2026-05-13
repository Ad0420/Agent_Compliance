/**
 * Proxy for the compliance dashboard's "Export evidence (PDF)" button.
 *
 * Why a proxy instead of opening the backend URL directly:
 *   - The Clerk backend-bound JWT lives in a server-side cookie. We MUST
 *     never put it in a URL or expose it to the client to attach as a
 *     query param.
 *   - The browser opens this route as a plain `<a>` link / `window.open`
 *     (no JS fetch needed), so it must be a GET that streams the PDF
 *     bytes back with the right Content-Disposition for the download.
 *
 * Auth model: Clerk middleware already protects `/api/dashboard/*` (see
 * `frontend/middleware.ts`). `fetchFromVera` then attaches the backend-bound
 * JWT. The backend `compliance_review_audit` middleware records the export
 * to `compliance_review_records`.
 */
import { NextResponse } from "next/server";

import { getClerkBackendToken } from "@/lib/auth-server";
import { VeraApiError } from "@/lib/api-server";

const API_BASE =
  process.env.VERA_API_URL ??
  process.env.NEXT_PUBLIC_API_BASE ??
  "http://localhost:8000";

export async function GET(req: Request) {
  const token = await getClerkBackendToken();
  if (!token) {
    return NextResponse.json(
      { error: "Not authenticated" },
      { status: 401 },
    );
  }

  // Forward whitelisted filter params. We avoid forwarding the entire query
  // string blindly so a malicious caller can't smuggle backend-only params.
  const incoming = new URL(req.url).searchParams;
  const forwarded = new URLSearchParams();
  for (const key of [
    "start_date",
    "end_date",
    "agent_name",
    "action_type",
    "result",
  ]) {
    const v = incoming.get(key);
    if (v) forwarded.set(key, v);
  }

  // The compliance dashboard sends `range=30` (days). The backend export
  // endpoint takes start_date/end_date instead — derive both from the
  // range if no explicit dates were provided.
  if (!forwarded.has("start_date") && !forwarded.has("end_date")) {
    const range = parseInt(incoming.get("range") ?? "30", 10);
    if (Number.isFinite(range) && range > 0 && range <= 365) {
      const end = new Date();
      const start = new Date(end.getTime() - range * 24 * 60 * 60 * 1000);
      forwarded.set("start_date", start.toISOString());
      forwarded.set("end_date", end.toISOString());
    }
  }

  const qs = forwarded.toString();
  const url = `${API_BASE}/v1/dashboard/export/pdf${qs ? `?${qs}` : ""}`;

  let res: Response;
  try {
    res = await fetch(url, {
      method: "GET",
      headers: {
        Authorization: `Bearer ${token}`,
      },
      cache: "no-store",
    });
  } catch (err) {
    const message =
      err instanceof Error ? err.message : "Could not reach the Vera backend.";
    return NextResponse.json({ error: message }, { status: 502 });
  }

  if (!res.ok) {
    // Try to surface a useful error body; fall back to status if it's
    // binary or unparseable.
    let body: unknown;
    try {
      const text = await res.text();
      try {
        body = JSON.parse(text);
      } catch {
        body = { error: text || `Backend returned ${res.status}` };
      }
    } catch {
      body = { error: `Backend returned ${res.status}` };
    }
    return NextResponse.json(
      body instanceof VeraApiError ? { error: body.message } : body,
      { status: res.status },
    );
  }

  // Stream the PDF body back. Preserve Content-Type and
  // Content-Disposition (the backend already sets the filename).
  const contentType = res.headers.get("content-type") ?? "application/pdf";
  const disposition =
    res.headers.get("content-disposition") ??
    'attachment; filename="vera_compliance_report.pdf"';

  return new Response(res.body, {
    status: 200,
    headers: {
      "content-type": contentType,
      "content-disposition": disposition,
      "cache-control": "no-store",
    },
  });
}
