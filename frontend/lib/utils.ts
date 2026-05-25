import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"
import { format, formatDistanceToNow } from "date-fns"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export function formatDate(iso: string): string {
  return format(new Date(iso), "MMM d, yyyy HH:mm:ss")
}

export function formatRelativeTime(iso: string): string {
  return formatDistanceToNow(new Date(iso), { addSuffix: true })
}

export function truncateHash(hash: string, chars: number = 8): string {
  if (hash.length <= chars * 2) return hash
  return `${hash.slice(0, chars)}...${hash.slice(-4)}`
}

export function formatDuration(ms: number | null | undefined): string {
  if (ms == null) return "—"
  if (ms < 1000) return `${ms}ms`
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`
  return `${(ms / 60000).toFixed(1)}m`
}

/**
 * Absolute UTC timestamp suitable for tooltip use (e.g. "2026-05-25 14:23 UTC").
 * Used alongside ``formatRelativeTime`` so dense list rows show "3m ago" with
 * the exact instant on hover — matches the dashboard design-system rule that
 * every relative time has an absolute fallback for audit grade.
 */
export function formatAbsoluteUTC(iso: string): string {
  const d = new Date(iso)
  const pad = (n: number) => String(n).padStart(2, "0")
  return (
    `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())} ` +
    `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())} UTC`
  )
}

/**
 * Short HH:MM UTC for retry-window messaging (e.g. "Retry 3/7, next at 14:23").
 * Returns the empty string for nullish input so callers can ``${''}`` cheaply.
 */
export function formatHourMinuteUTC(iso: string | null | undefined): string {
  if (!iso) return ""
  const d = new Date(iso)
  const pad = (n: number) => String(n).padStart(2, "0")
  return `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())} UTC`
}

/**
 * Human-readable countdown to a future ISO timestamp (e.g. "in 2h 14m").
 * Returns ``"expired"`` for past or null inputs. Used by the HITL row
 * to show time-to-expiry without churning every second — Decisions tab
 * re-renders on React Query polls, not on a setInterval.
 */
export function formatTimeUntil(iso: string | null | undefined): string {
  if (!iso) return ""
  const ms = new Date(iso).getTime() - Date.now()
  if (Number.isNaN(ms) || ms <= 0) return "expired"
  const totalMinutes = Math.floor(ms / 60_000)
  if (totalMinutes < 60) return `in ${totalMinutes}m`
  const hours = Math.floor(totalMinutes / 60)
  const minutes = totalMinutes % 60
  if (hours < 24) return `in ${hours}h ${minutes}m`
  const days = Math.floor(hours / 24)
  const remainderHours = hours % 24
  return `in ${days}d ${remainderHours}h`
}
