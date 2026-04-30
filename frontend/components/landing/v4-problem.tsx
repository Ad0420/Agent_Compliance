import { V4SectionHeader } from "./v4-section-header";
import { ForensicChainExhibit } from "./v4-forensic-chain-exhibit";

const QUESTIONS: string[] = [
  "What did the agent decide?",
  "Who approved this action?",
  "Has the log been tampered with?",
  "Who was affected?",
];

export function V4Problem() {
  return (
    <section style={{ padding: "120px 88px 0" }}>
      <V4SectionHeader
        kicker="THE PROBLEM"
        title={
          <>
            When something goes wrong,
            <br />
            <span style={{ color: "var(--ink-2)" }}>
              can you answer these?
            </span>
          </>
        }
        sub="Today, when an AI agent makes a decision your customer disputes, your team scrambles through three log systems to assemble an answer that is unverifiable."
      />
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 1fr",
          gap: 48,
          alignItems: "center",
        }}
      >
        <ol style={{ listStyle: "none", padding: 0, margin: 0 }}>
          {QUESTIONS.map((q, i) => (
            <li
              key={q}
              style={{
                display: "grid",
                gridTemplateColumns: "80px 1fr auto",
                alignItems: "baseline",
                padding: "26px 0",
                gap: 24,
                borderTop: i
                  ? "1px solid var(--ink-4)"
                  : "1px solid var(--ink)",
                borderBottom:
                  i === QUESTIONS.length - 1
                    ? "1px solid var(--ink)"
                    : "none",
              }}
            >
              <span
                style={{
                  fontFamily: "var(--mono)",
                  fontSize: 13,
                  color: "var(--ink-3)",
                  letterSpacing: 1.4,
                  fontWeight: 600,
                }}
              >
                Q.{String(i + 1).padStart(2, "0")}
              </span>
              <span
                style={{
                  fontSize: 28,
                  fontWeight: 600,
                  letterSpacing: "-0.02em",
                  lineHeight: 1.15,
                }}
              >
                {q}
              </span>
              <span
                style={{
                  fontFamily: "var(--mono)",
                  fontSize: 10.5,
                  color: "var(--red)",
                  fontWeight: 700,
                  letterSpacing: 1.2,
                  textTransform: "uppercase",
                  padding: "4px 10px",
                  border: "1px solid var(--red)",
                  borderRadius: 4,
                }}
              >
                ✕ NO ANSWER
              </span>
            </li>
          ))}
        </ol>
        <ForensicChainExhibit />
      </div>
    </section>
  );
}
