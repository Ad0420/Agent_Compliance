type Row = {
  n: string;
  a: string;
  t: string;
  h: string;
  state: "ok" | "pending";
};

const ROWS: Row[] = [
  { n: "01", a: "Agent started", t: "10:21:03", h: "7a5e9f06", state: "ok" },
  { n: "02", a: "Searched vector store", t: "10:21:05", h: "8f7c2d9b", state: "ok" },
  { n: "03", a: "Human approval", t: "10:21:09", h: "a91e0c45", state: "pending" },
  { n: "04", a: "Executed command", t: "10:21:11", h: "1d9f7b2e", state: "ok" },
  { n: "05", a: "Wrote to database", t: "10:21:14", h: "d93c9c02", state: "ok" },
];

type NavItem = { l: string; active?: boolean };

const NAV: NavItem[] = [
  { l: "Overview" },
  { l: "Agents" },
  { l: "Evidence", active: true },
  { l: "Policies" },
  { l: "Approvals" },
  { l: "Settings" },
];

export function DashboardPreview() {
  return (
    <div
      style={{
        borderRadius: 12,
        overflow: "hidden",
        background: "var(--paper)",
        border: "1px solid var(--ink-4)",
        boxShadow: "var(--shadow-3)",
        display: "grid",
        gridTemplateColumns: "180px 1fr",
        aspectRatio: "16/10",
      }}
    >
      <aside
        style={{
          background: "var(--paper-2)",
          borderRight: "1px solid var(--ink-4)",
          padding: "20px 16px",
          display: "flex",
          flexDirection: "column",
          gap: 14,
        }}
      >
        <div
          style={{
            fontFamily: "var(--sans)",
            fontSize: 22,
            fontWeight: 700,
            letterSpacing: "-0.04em",
            color: "var(--ink)",
            marginBottom: 8,
          }}
        >
          vera
        </div>
        {NAV.map((it) => (
          <div
            key={it.l}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              padding: "6px 10px",
              borderRadius: 6,
              fontSize: 12.5,
              fontWeight: it.active ? 600 : 500,
              color: it.active ? "var(--ink)" : "var(--ink-2)",
              background: it.active ? "var(--paper)" : "transparent",
              border: it.active ? "1px solid var(--ink-4)" : "1px solid transparent",
            }}
          >
            <span
              style={{
                width: 6,
                height: 6,
                borderRadius: "50%",
                background: it.active ? "var(--emerald-ink)" : "transparent",
                border: it.active ? "none" : "1px solid var(--ink-3)",
              }}
            />
            {it.l}
          </div>
        ))}
        <div style={{ flex: 1 }} />
        <div
          style={{
            paddingTop: 12,
            borderTop: "1px solid var(--ink-4)",
            fontFamily: "var(--mono)",
            fontSize: 10,
            color: "var(--ink-3)",
            letterSpacing: 1.2,
            fontWeight: 600,
            lineHeight: 1.5,
          }}
        >
          RUNTIME TRUST
          <br />
          FOR AI AGENTS
        </div>
      </aside>

      <main
        style={{
          padding: "20px 24px",
          display: "flex",
          flexDirection: "column",
          minHeight: 0,
        }}
      >
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "baseline",
            marginBottom: 4,
          }}
        >
          <h3
            style={{
              fontFamily: "var(--sans)",
              margin: 0,
              fontSize: 22,
              fontWeight: 700,
              letterSpacing: "-0.025em",
            }}
          >
            Evidence Chain
          </h3>
          <span
            style={{
              fontFamily: "var(--mono)",
              fontSize: 10,
              color: "var(--ink-3)",
              letterSpacing: 1.2,
              fontWeight: 600,
            }}
          >
            application_4821 · LIVE
          </span>
        </div>
        <p
          style={{
            margin: 0,
            fontSize: 12,
            color: "var(--ink-2)",
            marginBottom: 16,
          }}
        >
          Immutable record of agent actions and approvals.
        </p>

        <div style={{ display: "flex", flexDirection: "column", gap: 8, flex: 1 }}>
          {ROWS.map((r) => {
            const pending = r.state === "pending";
            return (
              <div
                key={r.n}
                style={{
                  display: "grid",
                  gridTemplateColumns: "28px 1fr auto auto",
                  alignItems: "center",
                  gap: 12,
                  padding: "10px 12px",
                  background: pending ? "rgba(154,93,18,0.08)" : "var(--paper)",
                  border:
                    "1px solid " + (pending ? "rgba(154,93,18,0.35)" : "var(--ink-4)"),
                  borderRadius: 6,
                }}
              >
                <span
                  style={{
                    fontFamily: "var(--mono)",
                    fontSize: 10,
                    fontWeight: 700,
                    color: "var(--ink-3)",
                    letterSpacing: 1,
                  }}
                >
                  {r.n}
                </span>
                <div style={{ display: "flex", flexDirection: "column", gap: 1 }}>
                  <span
                    style={{
                      fontSize: 12.5,
                      fontWeight: 600,
                      letterSpacing: "-0.005em",
                    }}
                  >
                    {r.a}
                  </span>
                  <span
                    style={{
                      fontFamily: "var(--mono)",
                      fontSize: 9.5,
                      color: "var(--ink-3)",
                    }}
                  >
                    May 16, 2025 · {r.t} UTC
                  </span>
                </div>
                <span
                  style={{
                    fontFamily: "var(--mono)",
                    fontSize: 10,
                    color: "var(--ink-2)",
                  }}
                >
                  sha256:{r.h}…
                </span>
                <span
                  style={{
                    width: 18,
                    height: 18,
                    borderRadius: "50%",
                    display: "inline-flex",
                    alignItems: "center",
                    justifyContent: "center",
                    background: pending ? "var(--amber-ink)" : "var(--emerald-ink)",
                    color: "var(--paper)",
                    fontSize: 10,
                    fontWeight: 700,
                  }}
                >
                  {pending ? "◐" : "✓"}
                </span>
              </div>
            );
          })}
        </div>
      </main>
    </div>
  );
}
