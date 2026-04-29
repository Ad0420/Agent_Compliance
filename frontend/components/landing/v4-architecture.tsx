import { V4SectionHeader } from "./v4-section-header";
import { TrustPipelineDiagram } from "./v4-trust-pipeline-diagram";

type Layer = { l: string; n: string; d: string; em?: boolean };

const LAYERS: Layer[] = [
  {
    l: "01",
    n: "Database triggers",
    d: "Every agent write is intercepted at the DB layer. App code can't skip it.",
  },
  {
    l: "02",
    n: "SHA-256 hash chain",
    d: "Each row hashes the previous. Tampering breaks the chain visibly.",
    em: true,
  },
  {
    l: "03",
    n: "KMS-signed checkpoints",
    d: "Periodic checkpoints signed by AWS KMS. Cryptographic non-repudiation.",
  },
  {
    l: "04",
    n: "S3 Object Lock (WORM)",
    d: "External tamper-proof storage. Even AWS root cannot edit.",
  },
];

export function V4Architecture() {
  return (
    <section style={{ padding: "120px 88px 0" }}>
      <V4SectionHeader
        kicker="ARCHITECTURE"
        title={
          <>
            Four layers.
            <br />
            <span style={{ color: "var(--ink-2)" }}>
              Each one a fence regulators recognize.
            </span>
          </>
        }
        sub="No black boxes. Each layer maps to a control auditors already know how to verify — so you don't have to teach them a new vocabulary."
      />
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 1.1fr",
          gap: 56,
          alignItems: "start",
        }}
      >
        <div>
          {LAYERS.map((L, i) => (
            <div
              key={L.l}
              style={{
                display: "grid",
                gridTemplateColumns: "80px 1fr",
                alignItems: "baseline",
                padding: "28px 0",
                gap: 28,
                borderTop: "1px solid var(--ink-4)",
                borderBottom:
                  i === LAYERS.length - 1 ? "1px solid var(--ink-4)" : "none",
              }}
            >
              <span
                style={{
                  fontFamily: "var(--mono)",
                  fontSize: 48,
                  fontWeight: 700,
                  color: L.em ? "var(--emerald-ink)" : "var(--ink)",
                  letterSpacing: "-0.04em",
                  lineHeight: 0.85,
                }}
              >
                {L.l}
              </span>
              <div>
                <div
                  style={{
                    fontSize: 22,
                    fontWeight: 700,
                    letterSpacing: "-0.02em",
                    marginBottom: 6,
                  }}
                >
                  {L.n}
                </div>
                <p
                  style={{
                    margin: 0,
                    fontSize: 15,
                    color: "var(--ink-2)",
                    lineHeight: 1.5,
                  }}
                >
                  {L.d}
                </p>
              </div>
            </div>
          ))}
        </div>
        <TrustPipelineDiagram />
      </div>
    </section>
  );
}
