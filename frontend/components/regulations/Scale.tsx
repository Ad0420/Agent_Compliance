"use client";

import { useState } from "react";
import type { ScalePayload } from "@/lib/regulations-data";

export type { ScalePayload };

// Compact USD formatter — $X / $XK / $XM / $XB. Five-line helper, no shared import.
function formatCurrency(n: number): string {
  if (n >= 1_000_000_000) return `$${(n / 1_000_000_000).toFixed(n >= 10_000_000_000 ? 0 : 1)}B`;
  if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(n >= 10_000_000 ? 0 : 1)}M`;
  if (n >= 1_000) return `$${(n / 1_000).toFixed(0)}K`;
  // copy-allow: string-helper return value; rendering surface owns the tabular-nums treatment, not this formatter
  return `$${n.toLocaleString()}`;
}

// ── Variant 1 — tiers (EU, HIPAA) ─────────────────────────────────────
type TiersPayload = Extract<ScalePayload, { kind: "tiers" }>;
function TiersBar({ payload }: { payload: TiersPayload }) {
  return (
    <div className="r2-scale-tiers">
      <div className="r2-scale__header">{`EXPOSURE TIERS · ${payload.rows.length}`}</div>
      {payload.rows.map((r, i) => (
        <div key={i} className="r2-scale-tiers__row">
          <div className="r2-scale-tiers__head">
            <span className="r2-scale-tiers__lbl">{r.lbl}</span>
            <span className="r2-scale-tiers__val">{r.val}</span>
          </div>
          <div className="r2-scale-tiers__bar">
            <div
              className="r2-scale-tiers__fill"
              data-tier={r.tier}
              style={{ width: `${r.pct}%` }}
            />
          </div>
        </div>
      ))}
    </div>
  );
}

// ── Variant 2 — multiplier (CO, TX) ───────────────────────────────────
type MultiplierPayload = Extract<ScalePayload, { kind: "multiplier" }>;
function MultiplierSlider({ payload }: { payload: MultiplierPayload }) {
  const [count, setCount] = useState<number>(payload.defaultCount);
  const max = Math.max(payload.defaultCount * 100, 10000);
  const step = payload.per >= 100_000 ? 1 : 100;
  const noun = payload.unit === "$/consumer" ? "consumer" : "violation";
  const mid = Math.round(max / 2);

  return (
    <div className="r2-scale-mult">
      <div className="r2-scale__header">{`MULTIPLIER · ${payload.unit}`}</div>
      <div className="r2-scale-mult__total">{formatCurrency(count * payload.per)}</div>
      <div className="r2-scale-mult__formula">
        {/* copy-allow: .r2-scale-mult__formula uses var(--mono) — monospace fonts are already tabular by construction */}
        {`${count.toLocaleString()} ${noun}${count === 1 ? "" : "s"} × ${formatCurrency(payload.per)}`}
      </div>
      <input
        className="r2-scale-mult__slider"
        type="range"
        min={1}
        max={max}
        step={step}
        value={count}
        onChange={(e) => setCount(parseInt(e.target.value, 10))}
        aria-label={`${noun} count`}
      />
      {/* copy-allow: .r2-scale-mult__ticks uses var(--mono) — already digit-aligned */}
      <div className="r2-scale-mult__ticks">
        {/* copy-allow: see parent .r2-scale-mult__ticks (mono font) */}
        <span>{(1).toLocaleString()}</span>
        {/* copy-allow: see parent .r2-scale-mult__ticks (mono font) */}
        <span>{payload.defaultCount.toLocaleString()}</span>
        {/* copy-allow: see parent .r2-scale-mult__ticks (mono font) */}
        <span>{mid.toLocaleString()}</span>
        {/* copy-allow: see parent .r2-scale-mult__ticks (mono font) */}
        <span>{max.toLocaleString()}</span>
      </div>
      <p className="r2-scale-mult__caption">{payload.label}</p>
    </div>
  );
}

// ── Variant 3 — daily (CA) ────────────────────────────────────────────
type DailyPayload = Extract<ScalePayload, { kind: "daily" }>;
function DailyDecay({ payload }: { payload: DailyPayload }) {
  const maxMark = Math.max(...payload.marks);
  return (
    <div className="r2-scale-daily">
      <div className="r2-scale__header">DAILY COMPOUNDING</div>
      {payload.marks.map((mark) => {
        const pct = (mark / maxMark) * 100;
        const total = payload.perDay * mark;
        return (
          <div key={mark} className="r2-scale-daily__row">
            <span className="r2-scale-daily__day">{`Day ${mark}`}</span>
            <div className="r2-scale-daily__bar">
              <div className="r2-scale-daily__fill" style={{ width: `${pct}%` }} />
            </div>
            <span className="r2-scale-daily__total">{formatCurrency(total)}</span>
          </div>
        );
      })}
      <p className="r2-scale-daily__caption">{payload.label}</p>
    </div>
  );
}

// ── Variant 4 — examples (FINRA) ──────────────────────────────────────
type ExamplesPayload = Extract<ScalePayload, { kind: "examples" }>;
function ExamplesList({ payload }: { payload: ExamplesPayload }) {
  return (
    <div className="r2-scale-examples">
      <div className="r2-scale__header">RECENT ENFORCEMENT THEMES</div>
      {payload.items.map((item, i) => (
        <div key={i} className="r2-scale-examples__row">
          <span className="r2-scale-examples__name">{item.name}</span>
          <span className="r2-scale-examples__meta">
            <span className="r2-scale-examples__year">{item.year}</span>
            <span className="r2-scale-examples__fine">{item.fine}</span>
          </span>
        </div>
      ))}
      <p className="r2-scale-examples__caption">
        Categories drawn from FINRA&rsquo;s 2024 enforcement themes; specific case data should be
        verified against FINRA&rsquo;s enforcement DB before publication.
      </p>
    </div>
  );
}

// ── Variant 5 — ladder (FDA) ──────────────────────────────────────────
type LadderPayload = Extract<ScalePayload, { kind: "ladder" }>;
function EnforcementLadder({ payload }: { payload: LadderPayload }) {
  const lastIdx = payload.steps.length - 1;
  return (
    <div className="r2-scale-ladder">
      <div className="r2-scale__header">ENFORCEMENT LADDER · escalation order</div>
      {payload.steps.map((step, i) => (
        <div
          key={i}
          className={`r2-scale-ladder__step${i === lastIdx ? " r2-scale-ladder__step--top" : ""}`}
          style={{ marginLeft: `${i * 12}px` }}
        >
          <span className="r2-scale-ladder__num">{String(i + 1).padStart(2, "0")}</span>
          <span className="r2-scale-ladder__label">{step.label}</span>
          {step.note && <span className="r2-scale-ladder__note">{step.note}</span>}
        </div>
      ))}
    </div>
  );
}

// ── Top-level dispatcher ──────────────────────────────────────────────
export function Scale({ payload }: { payload: ScalePayload }) {
  switch (payload.kind) {
    case "tiers":
      return <TiersBar payload={payload} />;
    case "multiplier":
      return <MultiplierSlider payload={payload} />;
    case "daily":
      return <DailyDecay payload={payload} />;
    case "examples":
      return <ExamplesList payload={payload} />;
    case "ladder":
      return <EnforcementLadder payload={payload} />;
  }
}
