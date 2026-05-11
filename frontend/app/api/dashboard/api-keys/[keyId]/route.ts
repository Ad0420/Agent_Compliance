/**
 * DELETE proxy for `/api/dashboard/api-keys/[keyId]`. Forwards to
 * `DELETE /v1/dashboard/api-keys/{keyId}` on the backend.
 */
import { NextResponse } from "next/server";

import { revokeDashboardApiKey, VeraApiError } from "@/lib/api-server";

export async function DELETE(
  _req: Request,
  { params }: { params: Promise<{ keyId: string }> },
) {
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
