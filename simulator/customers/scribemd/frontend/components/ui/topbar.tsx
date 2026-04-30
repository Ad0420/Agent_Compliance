/**
 * Topbar — sticky brand header for the ScribeMD demo app.
 *
 * Renders the wordmark on the left and a soft avatar bubble + signed-in
 * identity on the right. Designed for clinician-first usage: the NPI is shown
 * in mono so it's easy to spot when copying for billing.
 *
 * Wave 2 will render this above the encounter pipeline. The topbar exposes a
 * `slot` prop so a "Live encounter" indicator can be slotted into the center.
 */

import * as React from "react";
import { Wordmark } from "@/components/brand/Wordmark";
import { cn } from "@/lib/utils";

export interface TopbarProps extends React.HTMLAttributes<HTMLElement> {
  signedInAs?: {
    name: string;
    credentials?: string; // e.g. "M.D.", "D.O.", "P.A."
    npi?: string;
    avatarInitials?: string;
  };
  /** Center slot — used by Wave 2 to surface the live encounter status. */
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
                {signedInAs.credentials ? `, ${signedInAs.credentials}` : ""}
              </span>
              {signedInAs.npi && (
                <span className="font-mono text-[11px] text-[var(--ink-3)]">
                  NPI {signedInAs.npi}
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
        "bg-[var(--cobalt-soft)] text-[var(--cobalt-ink)]",
        "font-sans text-xs font-semibold",
        "ring-1 ring-inset ring-[rgba(46,91,216,0.18)]",
      )}
    >
      {initials || "MD"}
    </div>
  );
}
