/**
 * Build a Vera dashboard URL for a given record id.
 *
 * The base lives in `NEXT_PUBLIC_VERA_DASHBOARD_URL`; if it's unset we
 * fall back to the public dashboard. This is the *only* place
 * TriageGuard crosses the streams with Vera — the routed terminal
 * screen surfaces a tiny "View audit trail" link out of courtesy.
 * Everywhere else the customer surface stays Vera-agnostic.
 *
 * NOTE: PR 0c retired the legacy /actions route. The audit-trail viewer
 * lives under /compliance today (Phase 4 will ship per-record PDF deep
 * links). We append the record id as a query param so the eventual
 * /compliance view can filter to a single record; until then /compliance
 * just renders the list and the recordId is ignored gracefully.
 */

const DEFAULT_BASE = "https://usevera.xyz/compliance";

function resolveBase(): string {
  const raw =
    typeof process !== "undefined"
      ? process.env.NEXT_PUBLIC_VERA_DASHBOARD_URL
      : undefined;
  const trimmed = (raw ?? "").trim().replace(/\/+$/, "");
  return trimmed.length > 0 ? trimmed : DEFAULT_BASE;
}

export function veraDeeplink(recordId: string): string {
  const base = resolveBase();
  return `${base}?record=${encodeURIComponent(recordId)}`;
}
