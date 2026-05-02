"use client";

import { Fragment, useEffect, useState, type ReactNode } from "react";
import Link from "next/link";
import { HashStamp, PrototypeDisclaimer, Tick, Wordmark } from "@/components/landing/brand";
import { V4Nav } from "@/components/landing/v4-nav";
import {
  REGS,
  TODAY,
  computeDeadlineState,
  formatDate,
  type DeadlineInfo,
  type Reg,
  type ThermoRow,
} from "@/lib/regulations-data";

export default function RegulationsPage() {
  const [active, setActive] = useState<string>("eu");
  const [drawerId, setDrawerId] = useState<string | null>(null);
  const [register, setRegister] = useState<Record<string, "plain" | "statute">>({});
  const [moreReqs, setMoreReqs] = useState<Record<string, boolean>>({});

  const activeReg = REGS.find((r) => r.id === active);
  const drawerReg = REGS.find((r) => r.id === drawerId);

  useEffect(() => {
    if (!drawerId) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setDrawerId(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [drawerId]);

  const reg = (id: string): "plain" | "statute" => register[id] || "plain";
  const setReg = (id: string, v: "plain" | "statute") =>
    setRegister((s) => ({ ...s, [id]: v }));

  return (
    <div style={{ background: "var(--paper)", color: "var(--ink)", fontFamily: "var(--sans)" }}>
      <V4Nav />
      <RegsV2Hero />
      <RegsV2DeadlineGantt active={active} onPick={setActive} />

      <section className="v3-section" style={{ paddingTop: 56, paddingBottom: 32 }}>
        <RiskCalculator />
      </section>

      <RegsV2Tabs active={active} onClick={setActive} />

      <section className="v3-section" style={{ paddingTop: 24, paddingBottom: 48 }}>
        {activeReg && (
          <DossierCard
            reg={activeReg}
            register={reg(active)}
            setRegister={(v) => setReg(active, v)}
            moreReqs={!!moreReqs[active]}
            toggleMoreReqs={() => setMoreReqs((s) => ({ ...s, [active]: !s[active] }))}
            onOpen={() => setDrawerId(active)}
          />
        )}
      </section>

      <section className="v3-section" style={{ paddingTop: 24, paddingBottom: 48 }}>
        <CoverageQuiz />
      </section>

      <section className="v3-section" style={{ paddingTop: 24, paddingBottom: 80 }}>
        <ChainOfCustody />
      </section>

      <RegsV2CTA />
      <RegsV2Footer />

      <StatuteDrawer reg={drawerReg} open={!!drawerId} onClose={() => setDrawerId(null)} />
    </div>
  );
}

// ── Hero ───────────────────────────────────────────────────────────────
function RegsV2Hero() {
  return (
    <section className="v3-section" style={{ paddingTop: 56, paddingBottom: 32 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 18, marginBottom: 24 }}>
        <span
          style={{
            fontFamily: "var(--mono)",
            fontSize: 11,
            color: "var(--emerald-ink)",
            fontWeight: 700,
            letterSpacing: 1.8,
          }}
        >
          EXHIBIT R · REGULATORY MANIFEST
        </span>
        <span style={{ flex: 1, height: 1, background: "var(--ink-4)" }} />
        <HashStamp value="last fact-checked · 2026-04-30" tone="emerald" />
      </div>

      <h1 className="v3-hero-h1" style={{ marginBottom: 22 }}>
        Seven laws.<br />
        <span style={{ color: "var(--ink-2)" }}>Three already enforceable.</span>
        <br />
        <span
          style={{
            fontFamily: "var(--serif)",
            fontStyle: "italic",
            fontWeight: 500,
            letterSpacing: "-0.03em",
          }}
        >
          One audit away.
        </span>
      </h1>

      <p
        style={{
          fontSize: 18,
          lineHeight: 1.5,
          color: "var(--ink)",
          margin: "0 0 18px",
          maxWidth: 720,
          fontWeight: 400,
        }}
      >
        Pick a law. See the fine, the date, and what it actually requires. The full statute lives one
        click away.
      </p>

      <p
        style={{
          fontFamily: "var(--serif)",
          fontStyle: "italic",
          fontSize: 13.5,
          lineHeight: 1.6,
          color: "var(--ink-2)",
          margin: 0,
          maxWidth: 720,
          paddingLeft: 14,
          borderLeft: "2px solid var(--ink-4)",
        }}
      >
        Informational. Not legal advice. Vera tracks AI regulation publicly because accurate references
        help everyone. Talk to qualified counsel for an opinion on your specific situation.
      </p>
    </section>
  );
}

// ── Deadline timeline (lane-based) ────────────────────────────────────
type TLEvent = {
  id: string;        // unique
  tabId: string;     // which dossier tab to activate on click
  date: string;      // ISO yyyy-mm-dd
  label: string;     // short label
  sub?: string;      // optional sub
};

type TLLane = {
  key: string;
  title: string;
  events: TLEvent[];
};

function RegsV2DeadlineGantt({
  active,
  onPick,
}: {
  active: string;
  onPick: (id: string) => void;
}) {
  // Window: Jan 2026 → Sep 2027. Anchored to keep TODAY (Apr 30, 2026) at ~20% in.
  const start = new Date(2026, 0, 1).getTime();
  const end = new Date(2027, 8, 30).getTime();
  const today = TODAY.getTime();
  const span = end - start;
  const pctOf = (iso: string) => {
    const t = new Date(iso).getTime();
    return Math.max(0, Math.min(100, ((t - start) / span) * 100));
  };
  const todayPct = ((today - start) / span) * 100;

  const lanesRaw: TLLane[] = [
    {
      key: "eu",
      title: "European Union",
      events: [
        { id: "eu-26", tabId: "eu", date: "2026-08-02", label: "EU AI Act", sub: "high-risk obligations" },
        { id: "eu-27", tabId: "eu", date: "2027-08-02", label: "EU embedded", sub: "Annex II products" },
      ],
    },
    {
      key: "fed",
      title: "US Federal",
      events: [
        { id: "finra", tabId: "finra", date: "2026-01-01", label: "FINRA 24-09", sub: "in force" },
        { id: "fda", tabId: "fda", date: "2026-02-02", label: "FDA QMSR", sub: "in force" },
        { id: "hipaa", tabId: "hipaa", date: "2026-05-15", label: "HIPAA update", sub: "AI workflows" },
      ],
    },
    {
      key: "state",
      title: "US State",
      events: [
        { id: "tx", tabId: "tx", date: "2026-01-01", label: "TX TRAIGA", sub: "in force" },
        { id: "ca-ab", tabId: "ca", date: "2026-01-01", label: "CA AB 316 / 2013", sub: "in force" },
        { id: "co", tabId: "co", date: "2026-06-30", label: "CO SB 24-205", sub: "consequential AI" },
        { id: "ca-sb", tabId: "ca", date: "2026-08-02", label: "CA SB 942", sub: "AI disclosures" },
      ],
    },
  ];

  // Auto-stack: assign a "row" (0..n) to each event so chips that share an x-band don't overlap.
  // Two events collide if their pct positions differ by less than `MIN_GAP_PCT`.
  const MIN_GAP_PCT = 12; // chips are ~14% wide on most viewports
  const lanes = lanesRaw.map((lane) => {
    const sorted = [...lane.events]
      .map((e) => ({ ...e, _pct: pctOf(e.date) }))
      .sort((a, b) => a._pct - b._pct);
    const rowEnds: number[] = [];
    const placed = sorted.map((e) => {
      let row = rowEnds.findIndex((end) => e._pct - end >= MIN_GAP_PCT);
      if (row === -1) {
        row = rowEnds.length;
        rowEnds.push(e._pct);
      } else {
        rowEnds[row] = e._pct;
      }
      return { ...e, _row: row };
    });
    const rows = Math.max(1, rowEnds.length);
    return { ...lane, events: placed, rows };
  });

  // Quarter ticks across the window.
  const ticks: Array<{ label: string; pct: number }> = [];
  for (let y = 2026; y <= 2027; y++) {
    for (let q = 0; q < 4; q++) {
      const t = new Date(y, q * 3, 1).getTime();
      if (t < start || t > end) continue;
      ticks.push({
        label: `Q${q + 1} ${String(y).slice(2)}`,
        pct: ((t - start) / span) * 100,
      });
    }
  }

  return (
    <section className="v3-section" style={{ paddingTop: 28, paddingBottom: 8 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 14, marginBottom: 12 }}>
        <span
          style={{
            fontFamily: "var(--mono)",
            fontSize: 11,
            color: "var(--ink-3)",
            fontWeight: 700,
            letterSpacing: 1.6,
          }}
        >
          ENFORCEMENT WINDOW · NEXT 18 MONTHS
        </span>
        <span style={{ flex: 1, height: 1, background: "var(--ink-4)" }} />
        <span
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 8,
            fontFamily: "var(--mono)",
            fontSize: 11,
            color: "var(--ink-3)",
            fontWeight: 700,
            letterSpacing: 1.4,
          }}
        >
          <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
            <span style={{ width: 9, height: 9, background: "var(--emerald)", border: "1px solid var(--emerald-ink)" }} />
            IN FORCE
          </span>
          <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
            <span style={{ width: 9, height: 9, background: "var(--paper)", border: "1px solid var(--amber-ink)" }} />
            UPCOMING
          </span>
        </span>
      </div>

      <div className="r2-tl">
        {/* today indicator: label above the frame, scrubber line through it */}
        <div className="r2-tl__today-rail">
          <span
            className="r2-tl__today-marker"
            style={{ left: `calc(var(--tl-label-col) + var(--tl-track-pad) + (100% - var(--tl-label-col) - var(--tl-track-pad) * 2) * ${todayPct / 100})` }}
          >
            <span className="r2-tl__today-tag">TODAY · {formatDate(TODAY)}</span>
          </span>
        </div>

        <div className="r2-tl__head">
          <div className="r2-tl__head-axis">
            {ticks.map((t) => (
              <span key={t.label} className="r2-tl__tick" style={{ left: `${t.pct}%` }}>
                {t.label}
              </span>
            ))}
          </div>
        </div>

        <div className="r2-tl__body">
          {/* vertical quarter rules behind everything */}
          <div className="r2-tl__rules">
            {ticks.map((t) => (
              <span key={t.label} className="r2-tl__rule" style={{ left: `${t.pct}%` }} />
            ))}
            <span className="r2-tl__today-line" style={{ left: `${todayPct}%` }} />
          </div>

          {lanes.map((lane) => (
            <div
              key={lane.key}
              className="r2-tl__lane"
              data-lane={lane.key}
              data-rows={lane.rows}
              style={{ minHeight: 38 + lane.rows * 56 }}
            >
              <div className="r2-tl__lane-lbl">
                <span className="r2-tl__lane-flag" aria-hidden />
                <span className="r2-tl__lane-title">{lane.title}</span>
                <span className="r2-tl__lane-count">
                  {lane.events.length} {lane.events.length === 1 ? "law" : "laws"}
                </span>
              </div>
              <div className="r2-tl__lane-track">
                {lane.events.map((e) => {
                  const eventTime = new Date(e.date).getTime();
                  const live = eventTime <= today;
                  const days = Math.round((eventTime - today) / (1000 * 60 * 60 * 24));
                  const daysLabel = live ? null : `T+${days}d`;
                  const anchor: "left" | "right" = e._pct >= 65 ? "right" : "left";
                  const rowOffset = lane.rows === 1
                    ? 50
                    : 28 + e._row * (44 / Math.max(1, lane.rows - 1));
                  const positionStyle: React.CSSProperties =
                    anchor === "left"
                      ? { left: `${e._pct}%`, top: `${rowOffset}%` }
                      : { right: `${100 - e._pct}%`, top: `${rowOffset}%` };
                  return (
                    <Fragment key={e.id}>
                      <span
                        className="r2-tl__stem"
                        style={{ left: `${e._pct}%`, top: `${rowOffset}%` }}
                        data-state={live ? "live" : "soon"}
                        aria-hidden
                      />
                      <button
                        type="button"
                        className="r2-tl__chip"
                        data-state={live ? "live" : "soon"}
                        data-active={e.tabId === active ? "true" : "false"}
                        data-anchor={anchor}
                        data-lane={lane.key}
                        aria-pressed={e.tabId === active}
                        style={positionStyle}
                        onClick={() => onPick(e.tabId)}
                        title={`${e.label} · ${formatDate(e.date)}${e.sub ? ` — ${e.sub}` : ""}`}
                      >
                        <span className="r2-tl__chip-mark" aria-hidden>{live ? "✓" : "◇"}</span>
                        <span className="r2-tl__chip-text">
                          <span className="r2-tl__chip-label">{e.label}</span>
                          <span className="r2-tl__chip-date">
                            <span className="r2-tl__chip-when">
                              {new Date(e.date).toLocaleDateString("en-US", {
                                month: "short",
                                day: "numeric",
                                year: "2-digit",
                              })}
                            </span>
                            {e.sub && <span className="r2-tl__chip-sub">{e.sub}</span>}
                          </span>
                        </span>
                        {daysLabel && (
                          <span className="r2-tl__chip-days" aria-hidden>{daysLabel}</span>
                        )}
                      </button>
                    </Fragment>
                  );
                })}
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

// ── Risk calculator ────────────────────────────────────────────────────
function RiskCalculator() {
  const [revM, setRevM] = useState(50);
  const fmt = (n: number) => {
    if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(1)}M`;
    if (n >= 1_000) return `$${(n / 1_000).toFixed(0)}K`;
    return `$${n}`;
  };
  const revUSD = revM * 1_000_000;
  const rows = [
    { id: "EU", lbl: "EU AI Act · Art. 5", amt: Math.max(35_000_000, revUSD * 0.07), note: "or €35M, whichever higher" },
    { id: "CA", lbl: "CA SB 942 · 1 yr · daily", amt: 5000 * 365, note: "$5K/day, compounding" },
    { id: "HIPAA", lbl: "HIPAA · per category/yr", amt: 2_100_000, note: "tiered, per category" },
    { id: "TX", lbl: "TX TRAIGA · per violation", amt: 200_000, note: "per discrete violation" },
  ];
  const total = rows.reduce((s, r) => s + r.amt, 0);

  return (
    <div className="r2-calc">
      <div className="r2-calc__left">
        <span className="r2-calc__label">Step 1 · annual revenue (USD)</span>
        <div className="r2-calc__rev">${revM}M</div>
        <input
          className="r2-calc__slider"
          type="range"
          min={1}
          max={2000}
          step={1}
          value={revM}
          onChange={(e) => setRevM(parseInt(e.target.value, 10))}
        />
        <div className="r2-calc__ticks">
          <span>$1M</span>
          <span>$50M</span>
          <span>$500M</span>
          <span>$2B</span>
        </div>
        <p
          style={{
            marginTop: 22,
            fontFamily: "var(--serif)",
            fontStyle: "italic",
            fontSize: 14.5,
            color: "var(--ink-2)",
            lineHeight: 1.55,
            maxWidth: 380,
          }}
        >
          Move the slider. The right side shows the maximum statutory exposure across the four laws with
          hard fine ceilings. Real-world penalties are tiered and rarely max, but every number on the
          right is theoretically reachable.
        </p>
      </div>
      <div className="r2-calc__right">
        <span className="r2-calc__label">Maximum statutory exposure</span>
        <div className="r2-calc__total">{fmt(total)}</div>
        <div
          style={{
            fontFamily: "var(--mono)",
            fontSize: 11,
            color: "rgba(243,239,231,.55)",
            letterSpacing: 1.4,
            fontWeight: 600,
          }}
        >
          per year, summed across four enforcement regimes
        </div>
        <div className="r2-calc__rows">
          {rows.map((r) => (
            <div key={r.id} className="r2-calc__row">
              <span>{r.id}</span>
              <span>{r.lbl}</span>
              <span>{fmt(r.amt)}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ── Sticky tabs ────────────────────────────────────────────────────────
function RegsV2Tabs({
  active,
  onClick,
}: {
  active: string;
  onClick: (id: string) => void;
}) {
  return (
    <div className="r2-tabs">
      <div className="r2-tabs__inner">
        {REGS.map((r) => {
          const ds: DeadlineInfo = r.targetDate
            ? computeDeadlineState(r.targetDate, r.anchorDate)
            : { state: "live", deadlineLine: "In force", daysLine: "", fillPct: 100 };
          return (
            <button
              key={r.id}
              className="r2-tab"
              data-active={active === r.id ? "true" : "false"}
              onClick={() => onClick(r.id)}
            >
              <span>{r.label}</span>
              <span className="r2-tab__sub">{r.sub}</span>
              <span className="r2-tab__state" data-state={ds.state}>
                {ds.state === "live" ? "● IN FORCE" : `● ${ds.deadlineLine}`}
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}

// ── Citation chip ──────────────────────────────────────────────────────
function Cite({ children, body }: { children: ReactNode; body: string }) {
  return (
    <span className="r2-cite">
      {children}
      <span className="r2-cite__pop">{body}</span>
    </span>
  );
}

function withCitations(text: string, citations?: Record<string, string>): ReactNode {
  if (!citations) return text;
  const parts: ReactNode[] = [];
  const re = /\[([^\]]+)\]/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let i = 0;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) parts.push(text.slice(last, m.index));
    const key = m[1];
    if (citations[key]) {
      parts.push(
        <Cite key={i++} body={citations[key]}>
          {key}
        </Cite>
      );
    } else {
      parts.push(m[0]);
    }
    last = m.index + m[0].length;
  }
  if (last < text.length) parts.push(text.slice(last));
  return parts;
}

// ── Dossier card ───────────────────────────────────────────────────────
function DossierCard({
  reg,
  register,
  setRegister,
  moreReqs,
  toggleMoreReqs,
  onOpen,
}: {
  reg: Reg;
  register: "plain" | "statute";
  setRegister: (v: "plain" | "statute") => void;
  moreReqs: boolean;
  toggleMoreReqs: () => void;
  onOpen: () => void;
}) {
  const triadOverride = reg.triadOverride;
  const fine = (triadOverride && triadOverride.fine) || reg.fine;
  const verdict = (triadOverride && triadOverride.verdict) || reg.verdict;
  const verdictAfter = (triadOverride && triadOverride.verdictAfter) || reg.verdictAfter;

  const ds: DeadlineInfo = reg.targetDate
    ? computeDeadlineState(reg.targetDate, reg.anchorDate)
    : {
        state: "live",
        deadlineLine: "Already in force",
        daysLine: reg.forceDate ? `enforced since ${formatDate(reg.forceDate)}` : "ongoing",
        fillPct: 100,
      };

  const reqs = register === "statute" ? reg.statute.reqs : reg.plain.reqs;
  const reqsExtra = register === "statute" ? [] : reg.plain.reqsExtra || [];
  const visibleReqs = moreReqs ? [...reqs, ...reqsExtra] : reqs;

  return (
    <div className="r2-card">
      <div className="r2-card__head">
        <span className="r2-card__num">FOLIO {reg.num}</span>
        <h2 className="r2-card__title">
          {reg.label}
          <span className="r2-card__title-sub">· {reg.sub}</span>
        </h2>
        <div className="r2-card__toggle" role="tablist" aria-label="Register">
          <button
            data-active={register === "plain" ? "true" : "false"}
            onClick={() => setRegister("plain")}
          >
            Plain
          </button>
          <button
            data-active={register === "statute" ? "true" : "false"}
            onClick={() => setRegister("statute")}
          >
            Statute
          </button>
        </div>
      </div>

      <div className="r2-triad">
        <div className="r2-triad__cell r2-triad__cell--fine">
          <span className="r2-triad__lbl">Maximum exposure</span>
          {fine ? (
            <Fragment>
              <div className="r2-fine">{fine.big}</div>
              <div className="r2-fine__sub">{fine.sub}</div>
              {fine.per && <span className="r2-fine__per">{fine.per}</span>}
            </Fragment>
          ) : (
            <div
              className="r2-fine"
              style={{ color: "var(--ink)", fontSize: "clamp(28px, 4vw, 44px)" }}
            >
              No statutory cap
            </div>
          )}
        </div>

        <div className="r2-triad__cell r2-triad__cell--dead">
          <span className="r2-triad__lbl">{ds.state === "live" ? "Status" : "Time remaining"}</span>
          <div className={`r2-deadline r2-deadline--${ds.state}`}>{ds.deadlineLine}</div>
          <div className="r2-deadline__sub">{ds.daysLine}</div>
          <div className="r2-deadline__bar">
            <div
              className={`r2-deadline__bar-fill ${
                ds.state === "live" ? "r2-deadline__bar-fill--live" : ""
              }`}
              style={{ width: `${ds.fillPct}%` }}
            />
          </div>
        </div>

        <div className="r2-triad__cell r2-triad__cell--verd">
          <span className="r2-triad__lbl">Verdict</span>
          {verdict && <p className="r2-verdict">{verdict}</p>}
          {verdictAfter && <p className="r2-verdict__after">{verdictAfter}</p>}
        </div>
      </div>

      <div className="r2-card__body">
        <div className="r2-card__copy">
          <h3>{register === "statute" ? "What it is" : "What it is, in plain terms"}</h3>
          <p>
            {withCitations(
              register === "statute" ? reg.statute.what : reg.plain.what,
              reg.citations
            )}
          </p>

          <h3 style={{ marginTop: 18 }}>
            {register === "statute" ? "Who it affects" : "Who it actually hits"}
          </h3>
          <p>
            {withCitations(
              register === "statute" ? reg.statute.who : reg.plain.who,
              reg.citations
            )}
          </p>

          {register === "statute" && reg.statute.nuance && (
            <p
              style={{
                fontFamily: "var(--serif)",
                fontStyle: "italic",
                color: "var(--amber-ink)",
                marginTop: 16,
              }}
            >
              Important nuance: {reg.statute.nuance}
            </p>
          )}
        </div>

        <div className="r2-card__visual">
          <span className="r2-triad__lbl" style={{ marginBottom: 14, display: "block" }}>
            {register === "statute" ? "Requirements" : "What you need to do"}
          </span>
          <ul className="r2-reqs">
            {visibleReqs.map((q, i) => (
              <li key={i}>
                <span className="r2-reqs__tick">
                  <Tick size={14} />
                </span>
                <span>{q}</span>
              </li>
            ))}
          </ul>
          {reqsExtra.length > 0 && register !== "statute" && (
            <button className="r2-reqs__more" onClick={toggleMoreReqs}>
              {moreReqs ? "− show fewer" : `+ ${reqsExtra.length} more requirements`}
            </button>
          )}

          {reg.thermo && (
            <div style={{ marginTop: 24 }}>
              <span className="r2-triad__lbl" style={{ marginBottom: 12, display: "block" }}>
                Penalty thermometer
              </span>
              <PenaltyThermometer rows={reg.thermo} />
            </div>
          )}
        </div>
      </div>

      <div className="r2-card__foot">
        <div className="r2-bar-spaced">
          <span className="r2-card__foot-meta">EXHIBIT {reg.num} · case file</span>
          <span className="r2-ribbon" data-state={ds.state}>
            <span className="r2-ribbon__dot" />
            {ds.state === "live" ? "ENFORCEABLE NOW" : "INCOMING"}
          </span>
        </div>
        <button className="r2-openfile" onClick={onOpen}>
          <span style={{ fontFamily: "var(--mono)", fontSize: 14, fontWeight: 700 }}>↗</span>
          Open the case file
        </button>
      </div>
    </div>
  );
}

function PenaltyThermometer({ rows }: { rows: ThermoRow[] }) {
  return (
    <div className="r2-thermo">
      {rows.map((r, i) => (
        <div key={i} className="r2-thermo__group">
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "baseline",
              gap: 12,
            }}
          >
            <span className="r2-thermo__lbl">{r.lbl}</span>
            <span className="r2-thermo__val">{r.val}</span>
          </div>
          <div className="r2-thermo__bar">
            <div
              className={`r2-thermo__fill r2-thermo__fill--${r.tier}`}
              style={{ width: `${r.pct}%` }}
            />
          </div>
        </div>
      ))}
    </div>
  );
}

// ── Coverage quiz ──────────────────────────────────────────────────────
function CoverageQuiz() {
  const Q = [
    "Can you produce, on demand, every prompt and tool call that led to a customer-facing AI decision in the last 90 days?",
    "Are your AI logs cryptographically signed in a way a regulator can verify offline?",
    "Do you have a documented human-oversight policy for high-risk AI workflows?",
    "Can you identify, within minutes, every AI-generated communication that left your firm yesterday?",
    "Do you have a current Business Associate Agreement with every AI vendor that touches PHI?",
    "If an EU regulator asked tomorrow, could you produce automatic operation logs covering the past six months?",
    "Have you completed an impact assessment for every consequential-decision AI deployed in Colorado-touching workflows?",
    "Do your AI-generated outputs carry both manifest and latent disclosures where required?",
  ];
  const [answers, setAnswers] = useState<Record<number, "yes" | "no" | null>>({});
  const total = Q.length;
  const yesCount = Object.values(answers).filter((v) => v === "yes").length;
  const noCount = Object.values(answers).filter((v) => v === "no").length;
  const answered = yesCount + noCount;

  const tier: "bad" | "ok" | "good" = noCount >= 4 ? "bad" : noCount >= 2 ? "ok" : "good";
  const msg =
    answered === 0
      ? "Eight questions. None of them rhetorical. Each one maps to a specific obligation that takes effect this year."
      : tier === "bad"
        ? "Most clients in this position underestimate the lift. The chain of custody is the difference between a six-figure penalty and a clean audit."
        : tier === "ok"
          ? "Closer than most, but the gaps are exactly where examiners look first. Worth closing them before someone asks."
          : "Strong baseline. The remaining gaps are usually about provability, not control. That is the layer Vera adds.";

  return (
    <div className="r2-quiz">
      <div className="r2-quiz__head">
        <h3>Are you covered? Eight questions.</h3>
        <span className="r2-quiz__count">
          {answered} / {total} answered
        </span>
      </div>
      <div className="r2-quiz__rows">
        {Q.map((q, i) => (
          <div key={i} className="r2-quiz__row">
            <span className="r2-quiz__num">Q.{String(i + 1).padStart(2, "0")}</span>
            <span className="r2-quiz__q">{q}</span>
            <button
              className="r2-quiz__btn"
              data-active={answers[i] === "yes" ? "true" : "false"}
              onClick={() =>
                setAnswers((a) => ({ ...a, [i]: a[i] === "yes" ? null : "yes" }))
              }
            >
              Yes
            </button>
            <button
              className="r2-quiz__btn"
              data-active={answers[i] === "no" ? "true" : "false"}
              onClick={() =>
                setAnswers((a) => ({ ...a, [i]: a[i] === "no" ? null : "no" }))
              }
            >
              No
            </button>
          </div>
        ))}
      </div>
      <div className="r2-quiz__score">
        <div className={`r2-quiz__score-num r2-quiz__score-num--${tier}`}>
          {answered === 0 ? "—" : `${noCount}/${total}`}
        </div>
        <div>
          <div
            style={{
              fontFamily: "var(--mono)",
              fontSize: 11,
              color: "rgba(243,239,231,.55)",
              letterSpacing: 1.6,
              fontWeight: 700,
              textTransform: "uppercase",
              marginBottom: 6,
            }}
          >
            {answered === 0 ? "Standing by" : `${noCount} gaps`}
          </div>
          <div className="r2-quiz__score-msg">{msg}</div>
        </div>
        <Link
          href="/"
          style={{
            background: "var(--paper)",
            color: "var(--ink)",
            padding: "14px 22px",
            fontSize: 14,
            fontWeight: 600,
            fontFamily: "var(--sans)",
            textDecoration: "none",
            whiteSpace: "nowrap",
          }}
        >
          See how Vera closes them →
        </Link>
      </div>
    </div>
  );
}

// ── Chain of custody ──────────────────────────────────────────────────
function ChainOfCustody() {
  const STEPS = [
    { step: "Step 01", action: "fetch_credit_report", hash: "d93c9c02…0011" },
    { step: "Step 02", action: "analyze_application", hash: "f706a2b4…c188" },
    { step: "Step 03", action: "assess_risk", hash: "1d9f7b2e…aa5c" },
    { step: "Step 04", action: "human_approval", hash: "a91e0c45…8842" },
    { step: "Step 05", action: "make_decision", hash: "7a5e9f06…79ae" },
  ];
  const [active, setActive] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setActive((i) => (i + 1) % STEPS.length), 1100);
    return () => clearInterval(id);
  }, [STEPS.length]);

  return (
    <div className="r2-chain">
      <div style={{ display: "flex", alignItems: "baseline", gap: 14, marginBottom: 6 }}>
        <span className="r2-chain__lbl">EXHIBIT A · WHAT REGULATORS ASK FOR</span>
        <span style={{ flex: 1, height: 1, background: "var(--ink-4)" }} />
        <HashStamp value="chain · 5/5 verified" tone="emerald" />
      </div>
      <h2 className="r2-chain__h2">Every action. Hashed. Signed. Replayable.</h2>
      <p
        style={{
          fontSize: 15.5,
          color: "var(--ink-2)",
          lineHeight: 1.55,
          maxWidth: 720,
          margin: "0 0 28px",
        }}
      >
        Each block hashes the previous. Tamper with any step, the chain breaks. The artifact below is
        what gets handed to an auditor. The animation runs the chain once a second so you can watch the
        order propagate.
      </p>
      <div className="r2-chain__stage">
        {STEPS.map((s, i) => (
          <div key={i} className="r2-chain__node" data-active={i === active ? "true" : "false"}>
            <span className="r2-chain__step">{s.step}</span>
            <span className="r2-chain__action">{s.action}</span>
            <span className="r2-chain__hash">{s.hash}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Statute drawer ────────────────────────────────────────────────────
function StatuteDrawer({
  reg,
  open,
  onClose,
}: {
  reg: Reg | undefined;
  open: boolean;
  onClose: () => void;
}) {
  return (
    <Fragment>
      <div
        className="r2-drawer-scrim"
        data-open={open ? "true" : "false"}
        onClick={onClose}
      />
      <aside className="r2-drawer" data-open={open ? "true" : "false"} aria-hidden={!open}>
        {reg && (
          <Fragment>
            <div className="r2-drawer__head">
              <span className="r2-drawer__head-num">FOLIO {reg.num} · CASE FILE</span>
              <span className="r2-drawer__head-title">{reg.label}</span>
              <button className="r2-drawer__close" onClick={onClose}>
                Close · Esc
              </button>
            </div>
            <div className="r2-drawer__body">
              <div className="r2-drawer__section">
                <span className="r2-drawer__section-lbl">§ 01 · what it is</span>
                <p>{reg.statute.what}</p>
              </div>
              <div className="r2-drawer__section">
                <span className="r2-drawer__section-lbl">§ 02 · when it hits</span>
                <table>
                  <thead>
                    <tr>
                      <th style={{ width: "30%" }}>Date</th>
                      <th>What applies</th>
                    </tr>
                  </thead>
                  <tbody>
                    {reg.statute.timeline.map((row, i) => (
                      <tr key={i}>
                        <td
                          style={{
                            color: "var(--ink)",
                            fontWeight: 700,
                            whiteSpace: "nowrap",
                          }}
                        >
                          {row[0]}
                        </td>
                        <td>{row[1]}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="r2-drawer__section">
                <span className="r2-drawer__section-lbl">§ 03 · who it affects</span>
                <p>{reg.statute.who}</p>
              </div>
              <div className="r2-drawer__section">
                <span className="r2-drawer__section-lbl">§ 04 · penalties</span>
                <table>
                  <thead>
                    <tr>
                      <th style={{ width: "45%" }}>Tier</th>
                      <th>Maximum</th>
                    </tr>
                  </thead>
                  <tbody>
                    {reg.statute.penalties.map((row, i) => (
                      <tr key={i}>
                        <td>{row[0]}</td>
                        <td style={{ color: "var(--ink)", fontWeight: 700 }}>{row[1]}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {reg.statute.penaltyNote && (
                  <p style={{ marginTop: 10, fontStyle: "italic" }}>{reg.statute.penaltyNote}</p>
                )}
              </div>
              <div className="r2-drawer__section">
                <span className="r2-drawer__section-lbl">§ 05 · what it requires</span>
                <ul>
                  {reg.statute.reqs.map((r, i) => (
                    <li key={i}>{r}</li>
                  ))}
                </ul>
              </div>
              {reg.statute.proposed && (
                <div className="r2-drawer__section">
                  <span className="r2-drawer__section-lbl">§ 06 · proposed update</span>
                  <ul>
                    {reg.statute.proposed.map((r, i) => (
                      <li key={i}>{r}</li>
                    ))}
                  </ul>
                </div>
              )}
              {reg.statute.nuance && (
                <div className="r2-drawer__section">
                  <span
                    className="r2-drawer__section-lbl"
                    style={{ color: "var(--amber-ink)" }}
                  >
                    important nuance
                  </span>
                  <p
                    style={{
                      fontFamily: "var(--serif)",
                      fontStyle: "italic",
                      color: "var(--amber-ink)",
                    }}
                  >
                    {reg.statute.nuance}
                  </p>
                </div>
              )}
            </div>
          </Fragment>
        )}
      </aside>
    </Fragment>
  );
}

// ── CTA + Footer ──────────────────────────────────────────────────────
function RegsV2CTA() {
  return (
    <section
      className="v3-section"
      style={{
        paddingTop: 120,
        paddingBottom: 96,
        borderTop: "1px solid var(--ink)",
        background: "var(--ink)",
        color: "var(--paper)",
      }}
    >
      <div className="v3-cta-grid">
        <h2 className="v3-cta-h2">
          The deadlines are real.<br />
          <span
            style={{
              fontFamily: "var(--serif)",
              fontStyle: "italic",
              fontWeight: 500,
              color: "rgba(243,239,231,.7)",
            }}
          >
            So is the chain.
          </span>
        </h2>
        <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
          <p
            style={{
              fontSize: 17,
              color: "rgba(243,239,231,.75)",
              margin: 0,
              lineHeight: 1.5,
              maxWidth: 360,
            }}
          >
            Vera records every agent action into a tamper-evident, signed audit chain. When a regulator
            asks, the answer is provable in seconds.
          </p>
          <Link
            href="/"
            style={{
              alignSelf: "flex-start",
              background: "var(--paper)",
              color: "var(--ink)",
              border: "1px solid var(--paper)",
              padding: "16px 24px",
              fontSize: 15,
              fontWeight: 600,
              cursor: "pointer",
              fontFamily: "var(--sans)",
              textDecoration: "none",
            }}
          >
            Get started →
          </Link>
        </div>
      </div>
    </section>
  );
}

function RegsV2Footer() {
  return (
    <footer
      className="v3-section"
      style={{
        paddingTop: 0,
        paddingBottom: 32,
        background: "var(--ink)",
        color: "rgba(243,239,231,.7)",
      }}
    >
      <div className="v3-footer-row">
        <Wordmark size={14} color="var(--paper)" />
        <span>· file no. vera/0.2.0 · regulations</span>
        <div style={{ flex: 1 }} />
        {["Docs", "Regulations", "Security", "Privacy", "Contact"].map((l) => (
          <a
            key={l}
            href="#"
            style={{ color: "rgba(243,239,231,.7)", textDecoration: "none" }}
          >
            {l}
          </a>
        ))}
      </div>
      <PrototypeDisclaimer tone="dark" />
    </footer>
  );
}
