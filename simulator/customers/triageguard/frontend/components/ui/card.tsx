/**
 * Card — hairline + soft shadow, rounded-xl. The TriageGuard "case file" surface.
 *
 * Where Vera uses pure hairline borders and ScribeMD uses pure soft shadows,
 * TriageGuard pairs both: a thin hairline outline plus a subdued shadow. The
 * read is "structured worksheet" rather than "floating tile" — which fits the
 * triage-queue mental model.
 *
 * Corners are `rounded-xl` (1rem) — tighter than ScribeMD's `rounded-2xl`.
 */

import * as React from "react";
import { cn } from "@/lib/utils";

interface CardProps extends React.HTMLAttributes<HTMLDivElement> {
  /** Density of shadow / hover treatment. Default "md". */
  elevation?: "flat" | "sm" | "md" | "lg";
  /** Highlight tone for risk / status rails. Adds a soft ring tint. */
  tone?: "neutral" | "teal" | "amber" | "crimson" | "moss";
}

const elevationMap = {
  flat: "shadow-none border border-[var(--hairline)]",
  sm: "border border-[var(--hairline)] shadow-[0_1px_2px_rgba(14,26,26,0.05)]",
  md: "border border-[var(--hairline)] shadow-[0_1px_3px_rgba(14,26,26,0.06),0_4px_16px_rgba(14,26,26,0.05)]",
  lg: "border border-[var(--hairline)] shadow-[0_2px_6px_rgba(14,26,26,0.07),0_12px_32px_rgba(14,26,26,0.08)]",
} as const;

const toneMap: Record<NonNullable<CardProps["tone"]>, string> = {
  neutral: "",
  teal: "ring-1 ring-[var(--teal-soft)]",
  amber: "ring-1 ring-[var(--amber-soft)]",
  crimson: "ring-1 ring-[var(--crimson-soft)]",
  moss: "ring-1 ring-[var(--moss-soft)]",
};

export function Card({
  className,
  elevation = "md",
  tone = "neutral",
  ...rest
}: CardProps) {
  return (
    <div
      className={cn(
        "bg-[var(--surface)] rounded-xl",
        elevationMap[elevation],
        toneMap[tone],
        className,
      )}
      {...rest}
    />
  );
}

export function CardHeader({
  className,
  ...rest
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn("px-6 pt-6 pb-3 flex flex-col gap-1.5", className)}
      {...rest}
    />
  );
}

export function CardTitle({
  className,
  ...rest
}: React.HTMLAttributes<HTMLHeadingElement>) {
  return (
    <h3
      className={cn(
        "font-serif text-lg font-normal text-[var(--ink)] tracking-tight",
        className,
      )}
      style={{ letterSpacing: "-0.005em" }}
      {...rest}
    />
  );
}

export function CardDescription({
  className,
  ...rest
}: React.HTMLAttributes<HTMLParagraphElement>) {
  return (
    <p
      className={cn("font-sans text-sm text-[var(--ink-3)]", className)}
      {...rest}
    />
  );
}

export function CardContent({
  className,
  ...rest
}: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("px-6 pb-6 pt-1", className)} {...rest} />;
}

export function CardFooter({
  className,
  ...rest
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "px-6 py-4 border-t border-[var(--hairline)] flex items-center gap-3",
        className,
      )}
      {...rest}
    />
  );
}
