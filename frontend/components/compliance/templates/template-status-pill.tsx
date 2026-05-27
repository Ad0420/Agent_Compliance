"use client";

/**
 * TemplateStatusPill — colored dot + label for the three template states.
 *
 * Phase 5 PR B1. Same shape as ``StatusDot`` from
 * ``components/ui/status-indicator.tsx`` but with the template-specific
 * label rendering (counsel-attested includes the full-date attestation
 * timestamp, which the generic StatusDot can't synthesise on its own).
 *
 * The dot is always paired with a text label per the dashboard design
 * system (color alone is never a meaningful signal).
 */

import * as React from "react";

import { cn } from "@/lib/utils";

import type { TemplateStatus } from "@/lib/api-client";

import { formatFullDate } from "./format";

export interface TemplateStatusPillProps
  extends React.HTMLAttributes<HTMLSpanElement> {
  status: TemplateStatus;
  /** Required when status is ``counsel_attested``; ignored otherwise. */
  attested_at?: string | null;
}

/**
 * Pure mapping from status → (dot color class, label text).
 * Exported so the test surface can pin the contract without rendering.
 */
export const TEMPLATE_STATUS_LABELS: Record<TemplateStatus, string> = {
  not_started: "Not started",
  in_progress: "In progress",
  counsel_attested: "Counsel-attested",
};

export const TEMPLATE_STATUS_DOT_CLASSES: Record<TemplateStatus, string> = {
  not_started: "bg-[color:var(--ink-3)]",
  in_progress: "bg-[color:var(--amber)]",
  counsel_attested: "bg-[color:var(--olive)]",
};

export function TemplateStatusPill({
  status,
  attested_at,
  className,
  ...rest
}: TemplateStatusPillProps) {
  // For attested templates the label includes the full date so the
  // reader sees "Counsel-attested · May 27, 2026" in one glance. For the
  // other two states the label is just the static word.
  const label =
    status === "counsel_attested" && attested_at
      ? `${TEMPLATE_STATUS_LABELS[status]} · ${formatFullDate(attested_at)}`
      : TEMPLATE_STATUS_LABELS[status];

  return (
    <span
      className={cn(
        "inline-flex items-center gap-2 text-[13px] leading-none tabular-nums",
        status === "not_started"
          ? "text-[color:var(--ink-2)]"
          : "text-[color:var(--ink)]",
        className,
      )}
      {...rest}
    >
      <span
        aria-hidden="true"
        className={cn(
          "inline-block size-2 rounded-full",
          TEMPLATE_STATUS_DOT_CLASSES[status],
        )}
      />
      <span>{label}</span>
    </span>
  );
}
