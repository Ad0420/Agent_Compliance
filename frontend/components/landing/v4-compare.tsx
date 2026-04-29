import { V4SectionHeader } from "./v4-section-header";

type V4CompareColProps = {
  title: string;
  kicker: string;
  rows: [string, string][];
  tone: "good" | "bad";
};

function V4CompareCol({ title, kicker, rows, tone }: V4CompareColProps) {
  const isGood = tone === "good";
  return (
    <div
      style={{
        background: isGood
          ? "linear-gradient(180deg, var(--emerald-paper), #dee9df)"
          : "var(--paper-2)",
        borderRight: !isGood ? "1px solid var(--ink)" : "none",
        padding: "36px 40px",
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 12,
          marginBottom: 28,
        }}
      >
        <span
          style={{
            fontFamily: "var(--mono)",
            fontSize: 11,
            fontWeight: 700,
            letterSpacing: 1.8,
            color: isGood ? "var(--emerald-ink)" : "var(--red)",
            padding: "5px 12px",
            borderRadius: 4,
            background: isGood
              ? "rgba(10,122,79,.14)"
              : "rgba(168,42,29,.1)",
          }}
        >
          {kicker}
        </span>
        <h3
          style={{
            margin: 0,
            fontSize: 26,
            fontWeight: 700,
            letterSpacing: "-0.02em",
          }}
        >
          {title}
        </h3>
      </div>
      <div>
        {rows.map((r, i) => (
          <div
            key={r[0]}
            style={{
              display: "grid",
              gridTemplateColumns: "32px 1fr",
              padding: "20px 0",
              gap: 16,
              borderTop: "1px solid var(--ink-4)",
            }}
          >
            <span
              style={{
                fontFamily: "var(--mono)",
                fontSize: 11,
                color: "var(--ink-3)",
                paddingTop: 4,
              }}
            >
              {String(i + 1).padStart(2, "0")}
            </span>
            <div>
              <div
                style={{
                  fontSize: 18,
                  fontWeight: 600,
                  letterSpacing: "-0.01em",
                }}
              >
                {r[0]}
              </div>
              <div
                style={{
                  fontSize: 13.5,
                  color: "var(--ink-2)",
                  marginTop: 4,
                  lineHeight: 1.45,
                }}
              >
                {r[1]}
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export function V4Compare() {
  return (
    <section style={{ padding: "120px 88px 0" }}>
      <V4SectionHeader
        kicker="WHY LOGS AREN'T ENOUGH"
        title={
          <>
            Datadog can be silently edited.
            <br />
            Vera{" "}
            <em
              style={{
                fontFamily: "var(--serif)",
                fontWeight: 500,
                color: "var(--emerald-ink)",
              }}
            >
              can&rsquo;t
            </em>
            .
          </>
        }
        sub="Logs were designed for debugging, not evidence. Evidence has different requirements: capture point, immutability, signing, external storage."
      />
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 1fr",
          gap: 0,
          border: "1px solid var(--ink)",
          borderRadius: 14,
          overflow: "hidden",
          boxShadow: "var(--shadow-2)",
        }}
      >
        <V4CompareCol
          title="Datadog / CloudWatch"
          kicker="MUTABLE"
          rows={[
            ["Mutable text logs", "anyone with prod access can edit"],
            ["Plaintext, copyable", "exfiltration risk"],
            ["App-layer only", "skipped if app skips"],
            ["No signatures", "non-repudiation: none"],
          ]}
          tone="bad"
        />
        <V4CompareCol
          title="Vera evidence chain"
          kicker="IMMUTABLE"
          rows={[
            ["DB-trigger captured", "app code can't skip"],
            ["SHA-256 hash chain", "tamper breaks chain"],
            ["KMS-signed checkpoints", "cryptographic proof"],
            ["S3 Object Lock (WORM)", "even AWS root can't edit"],
          ]}
          tone="good"
        />
      </div>
    </section>
  );
}
