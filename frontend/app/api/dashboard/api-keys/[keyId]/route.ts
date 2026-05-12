/**
 * DELETE proxy for `/api/dashboard/api-keys/[keyId]`. Forwards to
 * `DELETE /v1/dashboard/api-keys/{keyId}` on the backend.
 */
import { NextResponse } from "next/server";

import { revokeDashboardApiKey, VeraApiError } from "@/lib/api-server";
import { csrfGuard } from "@/lib/csrf";

export async function DELETE(
  req: Request,
  { params }: { params: Promise<{ keyId: string }> },
) {
  // CSRF: same-origin allow-list on the mutating handler. See route.ts
  // sibling for the rationale.
  const forbidden = csrfGuard(req);
  if (forbidden) return forbidden;

  const { keyId } = await params;
  try {
    const body = await revokeDashboardApiKey(keyId);
    return NextResponse.json(body ?? { ok: true });
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
