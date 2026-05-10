import { V4SectionHeader } from "./v4-section-header";

type V4CompareColProps = {
  title: string;
  kicker: string;
  rows: string[];
  tone: "good" | "bad";
};

function V4CompareCol({ title, kicker, rows, tone }: V4CompareColProps) {
  const isGood = tone === "good";
  return (
    <div
      className={!isGood ? "v4-compare-divider" : undefined}
      style={{
        background: isGood
          ? "linear-gradient(180deg, var(--emerald-paper), #dee9df)"
          : "var(--paper-2)",
        padding: "clamp(24px, 4vw, 36px) clamp(24px, 4vw, 40px)",
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
            key={r}
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
            <div
              style={{
                fontSize: 18,
                fontWeight: 600,
                letterSpacing: "-0.01em",
              }}
            >
              {r}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export function V4Compare() {
  return (
    <section className="v4-section">
      <V4SectionHeader
        kicker="WHY LOGS AREN'T ENOUGH"
        title={
          <>
            Logs can be silently edited.
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
        sub="Logs were designed for debugging, not evidence. Evidence has to be sealed the moment it's created and impossible to alter afterward."
      />
      <div
        className="v4-compare-grid"
        style={{
          border: "1px solid var(--ink)",
          borderRadius: 14,
          overflow: "hidden",
          boxShadow: "var(--shadow-2)",
        }}
      >
        <V4CompareCol
          title="Conventional logging"
          kicker="EDITABLE"
          rows={[
            "Anyone with access can rewrite history",
            "No way to prove what really happened",
            "An employee can quietly edit yesterday's record",
          ]}
          tone="bad"
        />
        <V4CompareCol
          title="Vera evidence chain"
          kicker="TAMPER-EVIDENT"
          rows={[
            "A single character change breaks the seal",
            "Sealed by a third-party signer",
            "Verifiable without our software",
          ]}
          tone="good"
        />
      </div>
    </section>
  );
}
