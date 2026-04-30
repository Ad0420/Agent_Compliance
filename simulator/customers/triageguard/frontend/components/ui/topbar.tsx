/**
 * Topbar — sticky brand header for the TriageGuard demo app.
 *
 * Renders the wordmark on the left and the signed-in nurse on the right.
 * The nurse's RN license number is shown in mono below their name — easy
 * to spot when escalation paperwork needs co-signing.
 *
 * Wave 2 will compose this above the queue view. The topbar exposes a
 * `centerSlot` so a "queue · 12 cases waiting" indicator can sit between.
 */

import * as React from "react";
import { Wordmark } from "@/components/brand/Wordmark";
import { cn } from "@/lib/utils";

export interface TopbarProps extends React.HTMLAttributes<HTMLElement> {
  signedInAs?: {
    name: string;
    /** Role suffix — "RN", "MD", "PA-C", or "Triage Lead". */
    role?: string;
    /** State board license number (rendered in mono). */
    license?: string;
    avatarInitials?: string;
  };
  /** Center slot — used by Wave 2 to surface the live queue counter. */
  centerSlot?: React.ReactNode;
}

export function Topbar({
  signedInAs,
  centerSlot,
  className,
  ...rest
}: TopbarProps) {
  return (
    <header
      className={cn(
        "sticky top-0 z-30 w-full",
        "bg-[var(--paper)]/85 backdrop-blur-md",
        "border-b border-[var(--hairline)]",
        className,
      )}
      {...rest}
    >
      <div className="mx-auto flex h-16 max-w-7xl items-center justify-between gap-4 px-6">
        <Wordmark size="sm" />

        {centerSlot && (
          <div className="hidden md:flex items-center justify-center flex-1">
            {centerSlot}
          </div>
        )}

        {signedInAs && (
          <div className="flex items-center gap-3">
            <div className="hidden sm:flex flex-col items-end leading-tight">
              <span className="font-sans text-sm font-medium text-[var(--ink)]">
                {signedInAs.name}
                {signedInAs.role ? `, ${signedInAs.role}` : ""}
              </span>
              {signedInAs.license && (
                <span className="font-mono text-[11px] text-[var(--ink-3)]">
                  {signedInAs.license}
                </span>
              )}
            </div>
            <Avatar initials={signedInAs.avatarInitials ?? initialsFor(signedInAs.name)} />
          </div>
        )}
      </div>
    </header>
  );
}

function initialsFor(name: string): string {
  return name
    .split(" ")
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? "")
    .join("");
}

function Avatar({ initials }: { initials: string }) {
  return (
    <div
      aria-hidden
      className={cn(
        "flex size-9 items-center justify-center rounded-full",
        "bg-[var(--teal-soft)] text-[var(--teal-ink)]",
        "font-sans text-xs font-semibold",
        "ring-1 ring-inset ring-[rgba(15,118,110,0.18)]",
      )}
    >
      {initials || "RN"}
    </div>
  );
}
