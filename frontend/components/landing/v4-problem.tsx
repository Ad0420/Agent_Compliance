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
    <section className="v4-section">
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
        sub="Today, when an AI agent makes a decision your customer disputes, your team scrambles to reconstruct what happened — and the reconstruction is unverifiable."
      />
      <div className="v4-grid-2" style={{ alignItems: "center" }}>
        <ol style={{ listStyle: "none", padding: 0, margin: 0 }}>
          {QUESTIONS.map((q, i) => (
            <li
              key={q}
              className="v4-problem-row"
              style={{
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
                className="v4-problem-qnum"
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
                className="v4-problem-text"
                style={{
                  fontSize: "clamp(20px, 3.6vw, 28px)",
                  fontWeight: 600,
                  letterSpacing: "-0.02em",
                  lineHeight: 1.15,
                }}
              >
                {q}
              </span>
              <span
                className="v4-problem-badge"
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
