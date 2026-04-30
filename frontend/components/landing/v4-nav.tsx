import Link from "next/link";
import { Wordmark } from "./brand";

const NAV_ITEMS: Array<[string, boolean]> = [
  ["Product", true],
  ["Regulations", false],
];

export function V4Nav() {
  return (
    <nav
      style={{
        position: "sticky",
        top: 0,
        zIndex: 10,
        backdropFilter: "blur(14px)",
        WebkitBackdropFilter: "blur(14px)",
        background: "rgba(243,239,231,.78)",
        borderBottom: "1px solid var(--ink-4)",
        padding: "16px 88px",
        display: "flex",
        alignItems: "center",
        gap: 24,
      }}
    >
      <Wordmark size={17} />
      <span style={{ flex: 1 }} />
      {NAV_ITEMS.map(([label, hot]) => (
        <a
          key={label}
          href="#"
          style={{
            fontSize: 14,
            color: hot ? "var(--ink)" : "var(--ink-2)",
            textDecoration: "none",
            fontWeight: 500,
            letterSpacing: "-0.005em",
          }}
        >
          {label}
        </a>
      ))}
      <span style={{ width: 6 }} />
      <Link
        href="/login"
        style={{
          fontSize: 14,
          color: "var(--ink-2)",
          textDecoration: "none",
          fontWeight: 500,
        }}
      >
        Sign in
      </Link>
      <Link
        href="/register"
        style={{
          background: "var(--ink)",
          color: "var(--paper)",
          border: "1px solid var(--ink)",
          padding: "9px 16px",
          fontSize: 13.5,
          fontWeight: 600,
          fontFamily: "var(--sans)",
          cursor: "pointer",
          borderRadius: 6,
          boxShadow: "var(--shadow-1)",
          textDecoration: "none",
          display: "inline-block",
        }}
      >
        Get started →
      </Link>
    </nav>
  );
}
