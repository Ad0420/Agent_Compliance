import type { ReactNode } from "react";

export function V4SectionHeader({
  kicker,
  title,
  sub,
  accent = "emerald",
}: {
  kicker: string;
  title: ReactNode;
  sub?: ReactNode;
  accent?: "emerald" | "amber";
}) {
  const c = accent === "amber" ? "var(--amber-ink)" : "var(--emerald-ink)";
  return (
    <div style={{ marginBottom: 48 }}>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 14,
          marginBottom: 18,
        }}
      >
        <span
          style={{
            width: 28,
            height: 1,
            background: c,
          }}
        />
        <span
          style={{
            fontFamily: "var(--mono)",
            fontSize: 11,
            fontWeight: 700,
            color: c,
            letterSpacing: 1.8,
          }}
        >
          {kicker}
        </span>
      </div>
      <h2
        style={{
          fontFamily: "var(--sans)",
          fontSize: 56,
          fontWeight: 700,
          letterSpacing: "-0.035em",
          lineHeight: 1.02,
          margin: "0 0 18px",
          maxWidth: 1000,
        }}
      >
        {title}
      </h2>
      {sub && (
        <p
          style={{
            fontSize: 19,
            lineHeight: 1.5,
            color: "var(--ink-2)",
            margin: 0,
            maxWidth: 720,
          }}
        >
          {sub}
        </p>
      )}
    </div>
  );
}
