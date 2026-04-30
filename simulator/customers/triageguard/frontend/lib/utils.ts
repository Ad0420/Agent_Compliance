import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/**
 * Merge Tailwind class names with proper conflict resolution.
 * Standard shadcn-style helper. Same shape as ScribeMD's, kept identical so
 * snippets shared with the Wave 2 view-layer agent compose without surprises.
 */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
