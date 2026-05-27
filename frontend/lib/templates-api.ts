/**
 * Local templates API helper — Phase 5 PR B2.
 *
 * Why this file exists: B1 (the Templates page PR) ships
 * ``generateTemplates`` as a first-class export on ``lib/api-client.ts``.
 * B1 and B2 are landing in parallel; this module exists so B2 can be
 * tested + reviewed + merged independently of B1's order. When B1
 * merges, follow-up cleanup consolidates the two by re-exporting from
 * ``api-client`` and dropping this file.
 *
 * Wire shape mirrors the backend route ``POST /v1/templates/generate``
 * (see ``backend/app/routes/templates.py`` and
 * ``backend/app/schemas/template.py::TemplateGenerateResponse``).
 *
 * The endpoint:
 *
 *  - Requires the caller's org has completed the onboarding wizard.
 *    If not, returns 400 with ``{code: "wizard_incomplete", ...}``.
 *  - Is idempotent on every key:
 *      * un-attested or missing rows → ``generated``
 *      * counsel-attested rows       → ``skipped_attested`` (preserved)
 *  - Returns 5-key lists (``TEMPLATE_KEYS`` order).
 *
 * Auth: piggybacks on the shared ``request`` helper in
 * ``api-client.ts`` so the Clerk bearer token is attached the same
 * way every other dashboard call attaches it. Mirrors the minimal
 * style of ``generateComplianceInsights`` (POST + empty body).
 */

import { ApiError } from "./api-client";
import { getClerkToken } from "./clerk-token";

export interface TemplateGenerateResponse {
  /** template_keys whose rows were created or refreshed. */
  generated: string[];
  /**
   * template_keys whose rows existed AND were counsel-attested — NEVER
   * overwritten by generate (the operator must explicitly clear
   * attestation first). Empty on first-completion of the wizard.
   */
  skipped_attested: string[];
}

const BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

/**
 * Kick off template generation against the caller's org. Returns the
 * lists of generated + skipped (attested) keys. See module docstring
 * for idempotency rules and the wizard-incomplete error envelope.
 *
 * Throws ``ApiError`` on non-2xx so callers can narrow on
 * ``err.detail.code === "wizard_incomplete"`` if needed.
 */
export async function generateTemplates(): Promise<TemplateGenerateResponse> {
  const token = await getClerkToken();
  const response = await fetch(`${BASE_URL}/v1/templates/generate`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({}),
  });

  if (response.status === 401) {
    throw new ApiError(401, "Unauthorized");
  }
  if (!response.ok) {
    const error = await response
      .json()
      .catch(() => ({ detail: "Request failed" }));
    const detail = error?.detail;
    const message =
      typeof detail === "string"
        ? detail
        : detail &&
            typeof detail === "object" &&
            "detail" in detail &&
            typeof (detail as { detail?: unknown }).detail === "string"
          ? (detail as { detail: string }).detail
          : typeof error?.message === "string"
            ? error.message
            : `Request failed (${response.status})`;
    throw new ApiError(response.status, message, detail ?? error);
  }
  return (await response.json()) as TemplateGenerateResponse;
}
