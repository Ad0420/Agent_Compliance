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
