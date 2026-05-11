import { V4SectionHeader } from "./v4-section-header";

const MILESTONES: { d: string; n: string; live?: boolean; big?: string }[] = [
  { d: "Jan 1, 2026", n: "California AB 316", live: true },
  { d: "Jun 30, 2026", n: "Colorado AI Act" },
  {
    d: "Aug 2, 2026",
    n: "EU AI Act · high-risk systems",
    big: "€15M / 3% turnover",
  },
  { d: "Q4 2026", n: "SEC + FINRA AI Audit Rules" },
];

export function V4Deadline() {
  return (
    <section className="v4-section">
      <V4SectionHeader
        kicker="THE DEADLINE"
        accent="amber"
        title={
          <>
            The dates are real.
            <br />
            <span style={{ color: "var(--amber-ink)" }}>
              So are the fines.
            </span>
          </>
        }
        sub="Four laws. Four hard deadlines. The first is already live; the rest land within 18 months."
      />
      <div className="v4-deadline-card">
        <span
          style={{
            position: "absolute",
            top: -14,
            left: "clamp(20px, 3vw, 36px)",
            background: "var(--amber)",
            color: "var(--paper)",
            padding: "6px 14px",
            fontFamily: "var(--mono)",
            fontSize: 10.5,
            fontWeight: 700,
            letterSpacing: 2,
            borderRadius: 4,
            boxShadow: "var(--shadow-1)",
          }}
        >
          REGULATORY TIMELINE
        </span>
        <div className="v4-grid-4" style={{ alignItems: "start", position: "relative" }}>
          <div className="v4-deadline-line" />
          {MILESTONES.map((m) => (
            <div
              key={m.d}
              style={{
                display: "flex",
                flexDirection: "column",
                gap: 12,
                position: "relative",
              }}
            >
              <span
                style={{
                  width: 18,
                  height: 18,
                  borderRadius: 999,
                  background: m.live ? "var(--red)" : "var(--amber)",
                  border: "3px solid var(--amber-paper)",
                  boxShadow: m.live
                    ? "0 0 0 1px var(--red), 0 0 0 6px rgba(168,42,29,.15)"
                    : "0 0 0 1px var(--amber)",
                }}
              />
              {m.live && (
                <span
                  style={{
                    fontFamily: "var(--mono)",
                    fontSize: 10,
                    color: "var(--red)",
                    fontWeight: 700,
                    letterSpacing: 1.5,
                  }}
                >
                  ● LIVE NOW
                </span>
              )}
              <span
                style={{
                  fontFamily: "var(--mono)",
                  fontSize: 12,
                  color: "var(--amber-ink)",
                  fontWeight: 700,
                  letterSpacing: 0.5,
                }}
              >
                {m.d}
              </span>
              <span
                style={{
                  fontSize: 22,
                  fontWeight: 600,
                  lineHeight: 1.2,
                  letterSpacing: "-0.02em",
                }}
              >
                {m.n}
              </span>
              {m.big && (
                <span
                  style={{
                    fontFamily: "var(--mono)",
                    fontSize: 13,
                    color: "var(--red)",
                    fontWeight: 700,
                    marginTop: 4,
                  }}
                >
                  {m.big}
                </span>
              )}
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
