"use client";

/**
 * SessionSelector — the "what should we triage today?" entry surface.
 *
 * Two tabs:
 *   - Fixture: pick one of three canned cases. Each card is a clickable
 *     option with a one-line description and a teal ring on selection.
 *   - Custom: paste symptoms and a chief complaint. Validates that
 *     both are non-empty before enabling the "Start triage session" button.
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
import type { FixtureKey, StartSessionInput } from "@/lib/api/types";

interface FixtureOption {
  key: FixtureKey;
  title: string;
  description: string;
  badge: string;
}

const FIXTURES: FixtureOption[] = [
  {
    key: "easy_self_care",
    title: "Mild cough — self-care",
    description:
      "Adult with low-grade dry cough × 2 days, no red flags. AI proposes self-care.",
    badge: "Self-care",
  },
  {
    key: "red_flag_chest_pain",
    title: "Chest pain — possible STEMI",
    description:
      "Exertional chest pain with diaphoresis and jaw radiation. Detector flags red terms.",
    badge: "Red flag",
  },
  {
    key: "ambiguous",
    title: "Ambiguous abdominal pain",
    description:
      "RLQ pain × 6h, no fever yet. Classifier ambivalent between urgent care and ER.",
    badge: "Ambiguous",
  },
];

interface SessionSelectorProps {
  onStart(input: StartSessionInput): Promise<void> | void;
  isStarting: boolean;
  startError: Error | null;
}

type Tab = "fixture" | "custom";

export function SessionSelector({
  onStart,
  isStarting,
  startError,
}: SessionSelectorProps) {
  const [tab, setTab] = React.useState<Tab>("fixture");
  const [selected, setSelected] = React.useState<FixtureKey>(
    "red_flag_chest_pain",
  );
  const [symptoms, setSymptoms] = React.useState("");
  const [chiefComplaint, setChiefComplaint] = React.useState("");

  const customValid =
    symptoms.trim().length > 0 && chiefComplaint.trim().length > 0;
  const canStart = tab === "fixture" ? !isStarting : !isStarting && customValid;

  const handleStart = () => {
    if (tab === "fixture") {
      void onStart({ fixture: selected });
    } else if (customValid) {
      void onStart({
        custom: {
          symptoms: symptoms.trim(),
          chief_complaint: chiefComplaint.trim(),
        },
      });
    }
  };

  return (
    <div className="mx-auto w-full max-w-3xl">
      <div className="mb-6">
        <h1
          className="font-serif text-3xl font-normal text-[var(--ink)]"
          style={{ letterSpacing: "-0.02em" }}
        >
          Start a triage session
        </h1>
        <p className="mt-1.5 font-sans text-sm text-[var(--ink-3)]">
          Pick a sample case or paste your own symptoms. The AI assesses while
          you watch — you decide what reaches the patient.
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
              symptoms={symptoms}
              setSymptoms={setSymptoms}
              chiefComplaint={chiefComplaint}
              setChiefComplaint={setChiefComplaint}
            />
          )}

          {startError && (
            <div
              role="alert"
              className="mt-5 rounded-xl bg-[var(--crimson-soft)] px-3.5 py-2.5 font-sans text-sm text-[var(--crimson)] ring-1 ring-inset ring-[rgba(185,28,28,0.22)]"
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
              {isStarting ? "Starting…" : "Start triage session"}
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
      aria-label="Session source"
      className="inline-flex rounded-xl bg-[var(--paper-2)] p-1 ring-1 ring-inset ring-[var(--hairline)]"
    >
      <TabButton active={tab === "fixture"} onClick={() => onChange("fixture")}>
        Fixture
      </TabButton>
      <TabButton active={tab === "custom"} onClick={() => onChange("custom")}>
        Custom symptoms
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
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--teal)]",
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
      aria-label="Sample triage session"
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
              "text-left rounded-xl bg-[var(--surface)] p-4 transition-shadow",
              "shadow-sm hover:shadow-md",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--teal)]",
              isSelected
                ? "ring-2 ring-[var(--teal)]"
                : "ring-1 ring-[var(--hairline)]",
            )}
          >
            <div className="flex items-center justify-between gap-2">
              <span
                className="font-serif text-base font-normal text-[var(--ink)]"
                style={{ letterSpacing: "-0.01em" }}
              >
                {f.title}
              </span>
              <Badge variant={isSelected ? "teal" : "neutral"} size="sm">
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
  symptoms,
  setSymptoms,
  chiefComplaint,
  setChiefComplaint,
}: {
  symptoms: string;
  setSymptoms(v: string): void;
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
          placeholder="e.g. Sudden right-sided weakness"
          value={chiefComplaint}
          onChange={(e) => setChiefComplaint(e.target.value)}
        />
      </label>

      <label className="flex flex-col gap-1.5">
        <span className="font-sans text-xs font-medium text-[var(--ink-2)]">
          Patient symptoms
        </span>
        <Textarea
          rows={8}
          placeholder={
            "Patient describes their symptoms here…\nWhat hurts, when it started, anything making it better/worse."
          }
          value={symptoms}
          onChange={(e) => setSymptoms(e.target.value)}
        />
      </label>
    </div>
  );
}
