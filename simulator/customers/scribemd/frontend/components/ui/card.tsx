/**
 * Card — soft-shadow, rounded-2xl. The signature ScribeMD surface.
 *
 * Where Vera uses hairline borders + hover-emerald, ScribeMD uses depth: a soft
 * shadow on a near-white tile floating over the cream paper background. This
 * primitive is the visual workhorse — almost everything in the app sits on a
 * Card.
 */

import * as React from "react";
import { cn } from "@/lib/utils";

interface CardProps extends React.HTMLAttributes<HTMLDivElement> {
  /** Density of shadow / hover treatment. Default "md". */
  elevation?: "flat" | "sm" | "md" | "lg";
  /** Highlight tone for risk / status rails. Adds a left rule + soft tint. */
  tone?: "neutral" | "cobalt" | "amber" | "coral" | "sage";
}

const elevationMap = {
  flat: "shadow-none border border-[var(--hairline)]",
  sm: "shadow-sm",
  md: "shadow-md",
  lg: "shadow-lg",
} as const;

const toneMap: Record<NonNullable<CardProps["tone"]>, string> = {
  neutral: "",
  cobalt: "ring-1 ring-[var(--cobalt-soft)]",
  amber: "ring-1 ring-[var(--amber-soft)]",
  coral: "ring-1 ring-[var(--coral-soft)]",
  sage: "ring-1 ring-[var(--sage-soft)]",
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
        "bg-[var(--surface)] rounded-2xl",
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
        "font-serif text-lg font-semibold text-[var(--ink)] tracking-tight",
        className,
      )}
      style={{ letterSpacing: "-0.01em" }}
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
