import { V4SectionHeader } from "./v4-section-header";
import { DashboardPreview } from "./v4-dashboard-preview";

const TABS: string[] = ["Sync", "Async", "LangChain", "OpenAI", "Anthropic"];

export function V4Code() {
  return (
    <section className="v4-section">
      <V4SectionHeader
        kicker="INTEGRATION"
        title={
          <>
            Wrap a function.{" "}
            <span style={{ color: "var(--ink-2)" }}>You're done.</span>
          </>
        }
        sub="One decorator, one import. No infra to provision, no schemas to design."
      />
      <div className="v4-grid-2" style={{ alignItems: "stretch" }}>
        <div className="v4-code-shell">
          <div className="v4-code-tabs">
            {TABS.map((t, i) => (
              <button
                key={t}
                data-active={i === 0 ? "true" : undefined}
                style={{
                  display: "block",
                  textAlign: "left",
                  padding: "14px 22px",
                  background: "transparent",
                  fontFamily: "var(--mono)",
                  fontSize: 13.5,
                  color: i === 0 ? "var(--emerald-ink)" : "var(--ink-2)",
                  fontWeight: i === 0 ? 700 : 400,
                  cursor: "pointer",
                }}
              >
                {t}
              </button>
            ))}
          </div>
          <div
            style={{
              background: "var(--paper)",
              padding: "28px 32px",
              fontFamily: "var(--mono)",
              fontSize: 14,
              lineHeight: 1.7,
              overflowX: "auto",
            }}
          >
            <div style={{ color: "var(--ink-3)" }}># pip install vera-sdk</div>
            <div style={{ height: 14 }} />
            <div>
              <span style={{ color: "var(--emerald-ink)" }}>from</span> vera{" "}
              <span style={{ color: "var(--emerald-ink)" }}>import</span> audit
            </div>
            <div style={{ height: 14 }} />
            <div>
              <span style={{ color: "var(--amber-ink)" }}>@audit</span>(agent=
              <span style={{ color: "var(--ink-2)" }}>"decision-agent"</span>)
            </div>
            <div>
              <span style={{ color: "var(--emerald-ink)" }}>def</span>{" "}
              <span style={{ fontWeight: 700 }}>make_decision</span>(application):
            </div>
            <div>
              {"    "}
              <span style={{ color: "var(--emerald-ink)" }}>return</span>{" "}
              llm.invoke(...)
            </div>
            <div style={{ height: 14 }} />
            <div style={{ color: "var(--ink-3)" }}>
              # every call is hashed, chained, signed.
            </div>
          </div>
        </div>

        <DashboardPreview />
      </div>
    </section>
  );
}
