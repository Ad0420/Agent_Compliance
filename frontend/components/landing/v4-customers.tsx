interface Integration {
  name: string;
  kind: string;
}

const INTEGRATIONS: Integration[] = [
  { name: "OpenAI", kind: "LLM" },
  { name: "Anthropic", kind: "LLM" },
  { name: "LangChain", kind: "FRAMEWORK" },
  { name: "CrewAI", kind: "FRAMEWORK" },
];

export function V4Customers() {
  return (
    <section
      style={{
        padding: "clamp(40px, 6vw, 56px) var(--gutter) clamp(48px, 8vw, 72px)",
        borderBottom: "1px solid var(--ink-4)",
      }}
    >
      <div className="v4-customers-headline">
        <span
          style={{
            fontFamily: "var(--mono)",
            fontSize: 11,
            fontWeight: 700,
            color: "var(--ink-3)",
            letterSpacing: 1.6,
          }}
        >
          BUILT TO INTEGRATE WITH
        </span>
        <span className="v4-customers-headline-line" />
        <span
          style={{
            fontFamily: "var(--mono)",
            fontSize: 10.5,
            color: "var(--ink-3)",
            letterSpacing: 1.4,
            fontWeight: 600,
          }}
        >
          04 SURFACES · SDK · v1.4
        </span>
      </div>
      <div className="v4-customers-row">
        {INTEGRATIONS.map((it, i) => (
          <div
            key={it.name}
            style={{
              padding: "28px 20px 24px",
              display: "flex",
              flexDirection: "column",
              gap: 10,
              position: "relative",
            }}
          >
            <span
              style={{
                fontFamily: "var(--mono)",
                fontSize: 10,
                fontWeight: 700,
                color: "var(--emerald-ink)",
                letterSpacing: 1.2,
              }}
            >
              {String(i + 1).padStart(2, "0")} · {it.kind}
            </span>
            <span
              style={{
                fontFamily: "var(--sans)",
                fontSize: 22,
                fontWeight: 600,
                letterSpacing: "-0.025em",
                color: "var(--ink)",
              }}
            >
              {it.name}
            </span>
            <span
              style={{
                fontFamily: "var(--mono)",
                fontSize: 10.5,
                color: "var(--ink-3)",
                letterSpacing: 0.4,
              }}
            >
              connected
            </span>
            <span
              style={{
                position: "absolute",
                top: 28,
                right: 20,
                width: 6,
                height: 6,
                borderRadius: "50%",
                background: "var(--emerald-ink)",
                boxShadow: "0 0 0 4px rgba(10,122,79,0.12)",
              }}
            />
          </div>
        ))}
      </div>
      <div
        style={{
          marginTop: 18,
          display: "flex",
          justifyContent: "space-between",
          flexWrap: "wrap",
          gap: 8,
          fontFamily: "var(--mono)",
          fontSize: 10.5,
          color: "var(--ink-3)",
          letterSpacing: 1.2,
          fontWeight: 600,
        }}
      >
        <span>HOOK → INTERCEPT → SIGN → STORE</span>
        <span>~ 8 ms median overhead</span>
      </div>
    </section>
  );
}
