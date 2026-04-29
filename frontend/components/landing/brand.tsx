import type { CSSProperties, ReactNode } from "react";

export function LogomarkB({
  size = 28,
  color = "currentColor",
  emerald = "var(--emerald)",
}: {
  size?: number;
  color?: string;
  emerald?: string;
}) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 48 48"
      fill="none"
      stroke={color}
      strokeWidth="2.4"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-label="vera"
    >
      <path d="M 14 8 L 8 8 L 8 40 L 14 40" />
      <path d="M 34 8 L 40 8 L 40 40 L 34 40" />
      <circle cx="18" cy="24" r="2.2" fill={color} stroke="none" />
      <circle cx="24" cy="24" r="2.2" fill={emerald} stroke="none" />
      <circle cx="30" cy="24" r="2.2" fill={color} stroke="none" />
    </svg>
  );
}

export function Wordmark({
  size = 22,
  gap = 10,
  color = "currentColor",
}: {
  size?: number;
  gap?: number;
  color?: string;
}) {
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap, color }}>
      <LogomarkB size={size * 1.25} color={color} />
      <span
        style={{
          fontFamily: "var(--sans)",
          fontWeight: 700,
          fontSize: size,
          letterSpacing: "-0.02em",
        }}
      >
        vera
      </span>
    </span>
  );
}

export function Serial({
  children,
  color = "var(--ink-3)",
}: {
  children: ReactNode;
  color?: string;
}) {
  return (
    <span
      className="brackets"
      style={{
        fontSize: 11,
        color,
        fontWeight: 500,
      }}
    >
      {children}
    </span>
  );
}

export function HashStamp({
  value = "7a5e9f06d2c41b…79ae",
  tone = "emerald",
}: {
  value?: string;
  tone?: "emerald" | "amber" | "default";
}) {
  const cls =
    tone === "amber"
      ? "hash hash--am"
      : tone === "emerald"
      ? "hash hash--em"
      : "hash";
  return <span className={cls}>{value}</span>;
}

export function Tick({
  size = 14,
  tone = "emerald",
}: {
  size?: number;
  tone?: "emerald" | "amber";
}) {
  const bg = tone === "amber" ? "var(--amber)" : "var(--emerald)";
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        width: size,
        height: size,
        borderRadius: 999,
        background: bg,
        color: "var(--paper)",
        flexShrink: 0,
      }}
    >
      <svg
        width={size * 0.6}
        height={size * 0.6}
        viewBox="0 0 12 12"
        fill="none"
      >
        <path
          d="M3 6.5 L5 8.5 L9 4"
          stroke="currentColor"
          strokeWidth="1.8"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    </span>
  );
}

export function Cross({ size = 14 }: { size?: number }) {
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        width: size,
        height: size,
        borderRadius: 999,
        background: "var(--red)",
        color: "var(--paper)",
        flexShrink: 0,
      }}
    >
      <svg
        width={size * 0.55}
        height={size * 0.55}
        viewBox="0 0 12 12"
        fill="none"
      >
        <path
          d="M3 3 L9 9 M9 3 L3 9"
          stroke="currentColor"
          strokeWidth="1.8"
          strokeLinecap="round"
        />
      </svg>
    </span>
  );
}

export function PrototypeDisclaimer({
  tone = "default",
}: {
  tone?: "default" | "dark";
}) {
  const isDark = tone === "dark";
  const wrap: CSSProperties = {
    borderTop: `1px solid ${isDark ? "rgba(243,239,231,.12)" : "var(--ink-4)"}`,
    padding: "32px 0",
    display: "flex",
    alignItems: "flex-start",
    gap: 18,
  };
  return (
    <div style={wrap}>
      <Serial color={isDark ? "rgba(243,239,231,.45)" : "var(--ink-3)"}>
        NOTICE · 0001
      </Serial>
      <p
        style={{
          margin: 0,
          fontFamily: "var(--serif)",
          fontStyle: "italic",
          fontSize: 14,
          lineHeight: 1.55,
          color: isDark ? "rgba(243,239,231,.7)" : "var(--ink-2)",
          maxWidth: 720,
        }}
      >
        This website is a prototype built for testing and research purposes only.
        No commercial activity takes place here — no services are sold, no revenue
        is generated, and no payment is accepted or solicited.
      </p>
    </div>
  );
}
