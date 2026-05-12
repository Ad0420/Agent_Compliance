import Link from "next/link";
import { PrototypeDisclaimer } from "./brand";

// Keep in lockstep with V4Nav's NAV_ITEMS (see components/landing/v4-nav.tsx).
// If you add a top-level page to the nav, add it here too.
const FOOTER_NAV_ITEMS: Array<[string, string]> = [
  ["Product", "/"],
  ["Regulations", "/regulations"],
  ["Maturity", "/maturity"],
];

export function V4Footer() {
  return (
    <footer
      style={{
        padding: "0 var(--gutter)",
        background: "var(--night)",
        color: "var(--night-text-2)",
      }}
    >
      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          gap: 24,
          padding: "20px 0 0",
          fontFamily: "var(--mono)",
          fontSize: 11,
          letterSpacing: 0.6,
          textTransform: "uppercase",
        }}
      >
        {FOOTER_NAV_ITEMS.map(([label, href]) => (
          <Link
            key={label}
            href={href}
            style={{ color: "rgba(243,239,231,.7)", textDecoration: "none" }}
          >
            {label}
          </Link>
        ))}
      </div>
      <PrototypeDisclaimer tone="dark" />
    </footer>
  );
}
