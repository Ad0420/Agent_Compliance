"use client";

/**
 * EncounterSelector — the "what should we draft today?" entry surface.
 *
 * Two tabs:
 *   - Fixture: pick one of three canned cases. Each card is a clickable
 *     option with a one-line description and a soft cobalt ring on
 *     selection.
 *   - Custom: paste a transcript and a chief complaint. Validates that
 *     both are non-empty before enabling the "Start encounter" button.
 *
 * The tab toggle and card selection are accessible via keyboard — the
 * radio role + arrow keys aren't worth the ceremony for three options,
 * but every card is a plain `<button>` so Enter and Space activate it.
 */

import * as React from "react";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import type { FixtureKey, StartEncounterInput } from "@/lib/api/types";

interface FixtureOption {
  key: FixtureKey;
  title: string;
  description: string;
  badge: string;
}

const FIXTURES: FixtureOption[] = [
  {
    key: "pancreatitis",
    title: "Acute pancreatitis",
    description:
      "Severe epigastric pain × 1 day with vomiting. Urgent visit, high risk.",
    badge: "Urgent",
  },
  {
    key: "followup",
    title: "Hypertension follow-up",
    description:
      "Stable patient on lisinopril. Routine office visit, low risk.",
    badge: "Routine",
  },
  {
    key: "chest_pain",
    title: "New chest pain",
    description:
      "Atypical chest discomfort with exertion. Workup pending, medium risk.",
    badge: "Workup",
  },
];

interface EncounterSelectorProps {
  onStart(input: StartEncounterInput): Promise<void> | void;
  isStarting: boolean;
  startError: Error | null;
}

type Tab = "fixture" | "custom";

export function EncounterSelector({
  onStart,
  isStarting,
  startError,
}: EncounterSelectorProps) {
  const [tab, setTab] = React.useState<Tab>("fixture");
  const [selected, setSelected] = React.useState<FixtureKey>("pancreatitis");
  const [transcript, setTranscript] = React.useState("");
  const [chiefComplaint, setChiefComplaint] = React.useState("");

  const customValid =
    transcript.trim().length > 0 && chiefComplaint.trim().length > 0;
  const canStart = tab === "fixture" ? !isStarting : !isStarting && customValid;

  const handleStart = () => {
    if (tab === "fixture") {
      void onStart({ fixture: selected });
    } else if (customValid) {
      void onStart({
        custom: {
          transcript: transcript.trim(),
          chief_complaint: chiefComplaint.trim(),
        },
      });
    }
  };

  return (
    <div className="mx-auto w-full max-w-3xl">
      <div className="mb-6">
        <h1
          className="font-serif text-3xl font-semibold text-[var(--ink)]"
          style={{ letterSpacing: "-0.02em" }}
        >
          Start an encounter
        </h1>
        <p className="mt-1.5 font-sans text-sm text-[var(--ink-3)]">
          Pick a sample case or paste your own transcript. The note drafts
          itself while you keep your hands free.
        </p>
      </div>

      <Card elevation="lg">
        <div className="px-6 pt-5">
          <TabToggle tab={tab} onChange={setTab} />
        </div>

        <div className="px-6 pb-6 pt-5">
          {tab === "fixture" ? (
            <FixturePicker
              fixtures={FIXTURES}
              selected={selected}
              onSelect={setSelected}
            />
          ) : (
            <CustomFields
              transcript={transcript}
              setTranscript={setTranscript}
              chiefComplaint={chiefComplaint}
              setChiefComplaint={setChiefComplaint}
            />
          )}

          {startError && (
            <div
              role="alert"
              className="mt-5 rounded-xl bg-[var(--coral-soft)] px-3.5 py-2.5 font-sans text-sm text-[var(--coral)] ring-1 ring-inset ring-[rgba(180,35,24,0.22)]"
            >
              {startError.message}
            </div>
          )}

          <div className="mt-6 flex items-center justify-end gap-3">
            <Button
              variant="primary"
              size="lg"
              onClick={handleStart}
              disabled={!canStart}
            >
              {isStarting ? "Starting…" : "Start encounter"}
            </Button>
          </div>
        </div>
      </Card>
    </div>
  );
}

function TabToggle({
  tab,
  onChange,
}: {
  tab: Tab;
  onChange(next: Tab): void;
}) {
  return (
    <div
      role="tablist"
      aria-label="Encounter source"
      className="inline-flex rounded-xl bg-[var(--paper-2)] p-1 ring-1 ring-inset ring-[var(--hairline)]"
    >
      <TabButton active={tab === "fixture"} onClick={() => onChange("fixture")}>
        Fixture
      </TabButton>
      <TabButton active={tab === "custom"} onClick={() => onChange("custom")}>
        Custom transcript
      </TabButton>
    </div>
  );
}

function TabButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick(): void;
  children: React.ReactNode;
}) {
  return (
    <button
      role="tab"
      aria-selected={active}
      onClick={onClick}
      type="button"
      className={cn(
        "h-8 px-3.5 rounded-lg font-sans text-sm font-medium transition-colors",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--cobalt)]",
        active
          ? "bg-[var(--surface)] text-[var(--ink)] shadow-sm"
          : "text-[var(--ink-3)] hover:text-[var(--ink-2)]",
      )}
    >
      {children}
    </button>
  );
}

function FixturePicker({
  fixtures,
  selected,
  onSelect,
}: {
  fixtures: FixtureOption[];
  selected: FixtureKey;
  onSelect(k: FixtureKey): void;
}) {
  return (
    <div
      role="radiogroup"
      aria-label="Sample encounter"
      className="grid gap-3 sm:grid-cols-3"
    >
      {fixtures.map((f) => {
        const isSelected = f.key === selected;
        return (
          <button
            key={f.key}
            type="button"
            role="radio"
            aria-checked={isSelected}
            onClick={() => onSelect(f.key)}
            className={cn(
              "text-left rounded-2xl bg-[var(--surface)] p-4 transition-shadow",
              "shadow-sm hover:shadow-md",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--cobalt)]",
              isSelected
                ? "ring-2 ring-[var(--cobalt)]"
                : "ring-1 ring-[var(--hairline)]",
            )}
          >
            <div className="flex items-center justify-between gap-2">
              <span
                className="font-serif text-base font-semibold text-[var(--ink)]"
                style={{ letterSpacing: "-0.01em" }}
              >
                {f.title}
              </span>
              <Badge
                variant={isSelected ? "cobalt" : "neutral"}
                size="sm"
              >
                {f.badge}
              </Badge>
            </div>
            <p className="mt-2 font-sans text-xs text-[var(--ink-3)] leading-relaxed">
              {f.description}
            </p>
          </button>
        );
      })}
    </div>
  );
}

function CustomFields({
  transcript,
  setTranscript,
  chiefComplaint,
  setChiefComplaint,
}: {
  transcript: string;
  setTranscript(v: string): void;
  chiefComplaint: string;
  setChiefComplaint(v: string): void;
}) {
  return (
    <div className="flex flex-col gap-4">
      <label className="flex flex-col gap-1.5">
        <span className="font-sans text-xs font-medium text-[var(--ink-2)]">
          Chief complaint
        </span>
        <Input
          placeholder="e.g. New onset headache with photophobia"
          value={chiefComplaint}
          onChange={(e) => setChiefComplaint(e.target.value)}
        />
      </label>

      <label className="flex flex-col gap-1.5">
        <span className="font-sans text-xs font-medium text-[var(--ink-2)]">
          Transcript
        </span>
        <Textarea
          rows={8}
          placeholder={
            "PHYSICIAN: Tell me what brought you in today.\nPATIENT: …"
          }
          value={transcript}
          onChange={(e) => setTranscript(e.target.value)}
        />
      </label>
    </div>
  );
}
