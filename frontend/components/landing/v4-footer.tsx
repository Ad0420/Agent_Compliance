import Link from "next/link";
import { PrototypeDisclaimer } from "./brand";

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
        <Link
          href="/regulations"
          style={{ color: "rgba(243,239,231,.7)", textDecoration: "none" }}
        >
          Regulations
        </Link>
        <Link
          href="/maturity"
          style={{ color: "rgba(243,239,231,.7)", textDecoration: "none" }}
        >
          Maturity
        </Link>
      </div>
      <PrototypeDisclaimer tone="dark" />
    </footer>
  );
}
