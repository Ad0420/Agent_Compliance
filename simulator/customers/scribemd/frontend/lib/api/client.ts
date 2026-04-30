/**
 * Thin fetch wrapper for the ScribeMD backend.
 *
 * - Reads `NEXT_PUBLIC_SCRIBEMD_API_URL` once at module load (default
 *   `http://localhost:8001`).
 * - Sends cookies cross-origin via `credentials: 'include'`.
 * - Throws `ApiError` on any non-2xx — callers don't have to remember to
 *   check `res.ok`.
 */

const DEFAULT_BASE_URL = "http://localhost:8001";

export const API_BASE_URL: string = (() => {
  const raw =
    typeof process !== "undefined"
      ? process.env.NEXT_PUBLIC_SCRIBEMD_API_URL
      : undefined;
  const trimmed = (raw ?? "").trim().replace(/\/+$/, "");
  return trimmed.length > 0 ? trimmed : DEFAULT_BASE_URL;
})();

export class ApiError extends Error {
  readonly status: number;
  readonly detail: unknown;

  constructor(status: number, detail: unknown, message?: string) {
    super(message ?? deriveMessage(status, detail));
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

function deriveMessage(status: number, detail: unknown): string {
  if (typeof detail === "string" && detail.length > 0) return detail;
  if (
    detail &&
    typeof detail === "object" &&
    "detail" in (detail as Record<string, unknown>)
  ) {
    const inner = (detail as Record<string, unknown>).detail;
    if (typeof inner === "string" && inner.length > 0) return inner;
  }
  return `Request failed with status ${status}`;
}

export interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  body?: unknown;
  /** Extra headers; `Content-Type: application/json` is set automatically when `body` is given. */
  headers?: Record<string, string>;
  /** Forwarded to fetch — used by SSE-adjacent callers and tests. */
  signal?: AbortSignal;
  /** Optional query string params; null/undefined are skipped. */
  query?: Record<string, string | number | boolean | null | undefined>;
}

function buildUrl(
  path: string,
  query?: RequestOptions["query"],
): string {
  const base = path.startsWith("http") ? path : `${API_BASE_URL}${path}`;
  if (!query) return base;
  const usp = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === null || value === undefined) continue;
    usp.set(key, String(value));
  }
  const qs = usp.toString();
  if (qs.length === 0) return base;
  return `${base}${base.includes("?") ? "&" : "?"}${qs}`;
}

async function parseBody(res: Response): Promise<unknown> {
  // 204 / 205 explicitly carry no body.
  if (res.status === 204 || res.status === 205) return null;
  const text = await res.text();
  if (text.length === 0) return null;
  const ctype = res.headers.get("content-type") ?? "";
  if (ctype.includes("application/json")) {
    try {
      return JSON.parse(text);
    } catch {
      return text;
    }
  }
  return text;
}

/**
 * Make a JSON request against the ScribeMD backend.
 *
 * Returns the parsed JSON body typed as `T`, or `null` for empty
 * responses (`204`). Throws `ApiError` on any non-2xx response.
 */
export async function request<T>(
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  const headers: Record<string, string> = {
    Accept: "application/json",
    ...(options.headers ?? {}),
  };
  let body: BodyInit | undefined;
  if (options.body !== undefined && options.body !== null) {
    headers["Content-Type"] ??= "application/json";
    body = JSON.stringify(options.body);
  }

  const url = buildUrl(path, options.query);
  let res: Response;
  try {
    res = await fetch(url, {
      method: options.method ?? "GET",
      credentials: "include",
      headers,
      body,
      signal: options.signal,
    });
  } catch (cause) {
    // Network-level failure (DNS, offline, CORS preflight reject, etc.)
    const message =
      cause instanceof Error ? cause.message : "Network request failed";
    const err = new ApiError(0, null, message);
    (err as { cause?: unknown }).cause = cause;
    throw err;
  }

  const parsed = await parseBody(res);
  if (!res.ok) {
    throw new ApiError(res.status, parsed);
  }
  return parsed as T;
}

/** Build a same-origin URL string for use with `EventSource`. */
export function apiUrl(path: string): string {
  return path.startsWith("http") ? path : `${API_BASE_URL}${path}`;
}
