/**
 * Date + Markdown formatting helpers shared by the templates surface.
 *
 * Centralised so the date format obeys the dashboard voice rule (full
 * date including the year, e.g. "May 27, 2026") in exactly one place —
 * the card grid, the editor header, and the attestation badge all read
 * from here.
 */

/**
 * Render an ISO 8601 timestamp as "May 27, 2026".
 *
 * Returns the original string on parse failure so a bad backend
 * timestamp doesn't blow up the page.
 */
export function formatFullDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return new Intl.DateTimeFormat("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  }).format(d);
}

/**
 * Render an ISO 8601 timestamp as "May 27, 2026 at 22:30 UTC". Used on
 * the editor header so the operator sees the precise generated-at /
 * updated-at timestamps; the card grid uses the shorter
 * ``formatFullDate``.
 */
export function formatFullDateTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const datePart = new Intl.DateTimeFormat("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  }).format(d);
  const timePart = new Intl.DateTimeFormat("en-US", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: "UTC",
  }).format(d);
  return `${datePart} at ${timePart} UTC`;
}

/**
 * The placeholder marker that the template generator drops anywhere a
 * customer needs to substitute their own practice copy. The editor
 * preview highlights every occurrence in brick so the reader sees at a
 * glance what still needs filling in.
 *
 * Pinned as a constant so both the editor and its test exercise the
 * exact same string; a drift in the marker text would silently
 * disable the highlight.
 */
export const REPLACE_MARKER = "<<REPLACE WITH YOUR ACTUAL PRACTICE>>";

/**
 * Escape an arbitrary string so it can be safely interpolated into HTML.
 * Necessary because the preview pane renders the markdown body via
 * ``dangerouslySetInnerHTML`` so we can wrap ``REPLACE_MARKER`` in a
 * styled ``<mark>`` span without resorting to a Markdown parser.
 *
 * Covers the five XSS-relevant characters (& < > " ') — sufficient for
 * the text-only preview surface this powers. Do not use elsewhere
 * without re-evaluating the threat model.
 */
export function escapeHtml(input: string): string {
  return input
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

/**
 * Render a template body for the preview pane: HTML-escape the entire
 * body, then wrap every ``REPLACE_MARKER`` occurrence in a styled
 * highlight span. Returns the resulting HTML string for use with
 * ``dangerouslySetInnerHTML``.
 *
 * The order matters: we escape first (so any ``<`` in the body becomes
 * ``&lt;``), then split on the literal marker and wrap. Because the
 * marker contains ``<<`` and ``>>``, the post-escape body has the
 * marker as the literal text ``&lt;&lt;REPLACE WITH YOUR ACTUAL
 * PRACTICE&gt;&gt;`` — so we split on that escaped form, never on the
 * raw marker.
 */
export function renderMarkdownPreviewHtml(body: string): string {
  const escaped = escapeHtml(body);
  const escapedMarker = escapeHtml(REPLACE_MARKER);
  const parts = escaped.split(escapedMarker);
  if (parts.length === 1) {
    return escaped;
  }
  return parts.join(
    `<mark data-replace-marker="true" class="rounded-sm bg-[color:var(--brick-bg)] px-1 py-[1px] text-[color:var(--brick)]">${escapedMarker}</mark>`,
  );
}
