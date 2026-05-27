"use client";

/**
 * TemplateCard — single card in the templates list grid.
 *
 * Phase 5 PR B1. Wraps the whole card in a ``<Link>`` so the entire
 * surface is clickable (the spec asks for a card grid where each cell
 * routes into the editor view on ``?key=<template_key>``).
 *
 * Status (dot + label) sits below the title so the reader's eye lands
 * on the document name first, then the state — same hierarchy as the
 * compliance dimension cards.
 */

import * as React from "react";
import Link from "next/link";

import { cn } from "@/lib/utils";

import type {
  GeneratedTemplateSummary,
  TemplateKey,
} from "@/lib/api-client";

import {
  TEMPLATE_DISPLAY_NAMES,
  TEMPLATE_DESCRIPTIONS,
} from "./template-metadata";
import { TemplateStatusPill } from "./template-status-pill";

export interface TemplateCardProps {
  summary: GeneratedTemplateSummary;
}

export function TemplateCard({ summary }: TemplateCardProps) {
  const key = summary.template_key as TemplateKey;
  return (
    <Link
      href={`/compliance/templates?key=${encodeURIComponent(key)}`}
      data-testid={`templates-card-${key}`}
      className={cn(
        "group flex flex-col gap-3 rounded-[14px] border border-[color:var(--ink-4)] bg-[color:var(--paper)] p-5 transition-colors",
        "hover:bg-[color:var(--paper-2)]",
        "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--ink)]",
      )}
    >
      <div className="flex flex-col gap-1">
        <h2 className="text-[16px] font-medium leading-snug text-[color:var(--ink)]">
          {TEMPLATE_DISPLAY_NAMES[key]}
        </h2>
        <p className="text-[13px] leading-snug text-[color:var(--ink-2)]">
          {TEMPLATE_DESCRIPTIONS[key]}
        </p>
      </div>
      <TemplateStatusPill
        status={summary.status}
        attested_at={summary.attested_at}
        data-testid={`templates-status-${key}`}
      />
    </Link>
  );
}
