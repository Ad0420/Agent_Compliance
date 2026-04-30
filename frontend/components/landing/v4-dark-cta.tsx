import Link from "next/link";
import { DarkCtaBackdrop } from "./v4-dark-cta-backdrop";

export function V4DarkCTA() {
  return (
    <section
      style={{
        marginTop: 80,
        background: "var(--night)",
        color: "var(--night-text)",
        position: "relative",
        overflow: "hidden",
      }}
    >
      <DarkCtaBackdrop />
      <div
        style={{
          position: "relative",
          padding: "clamp(48px, 8vw, 80px) var(--gutter)",
          background:
            "linear-gradient(90deg, rgba(14,13,10,.92) 0%, rgba(14,13,10,.78) 60%, rgba(14,13,10,.55) 100%)",
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 14,
            marginBottom: 28,
          }}
        >
          <span
            style={{ width: 28, height: 1, background: "var(--emerald)" }}
          />
          <span
            style={{
              fontFamily: "var(--mono)",
              fontSize: 11,
              fontWeight: 700,
              color: "var(--emerald)",
              letterSpacing: 1.8,
            }}
          >
            SHIP IT
          </span>
        </div>
        <div className="v4-row-stack">
          <h2
            style={{
              fontFamily: "var(--sans)",
              fontSize: "var(--h2-cta)",
              fontWeight: 700,
              letterSpacing: "-0.045em",
              lineHeight: 0.92,
              margin: 0,
              maxWidth: 1100,
            }}
          >
            Set up in
            <br />
            <span
              style={{
                fontFamily: "var(--serif)",
                fontStyle: "italic",
                fontWeight: 500,
                color: "var(--night-text-2)",
              }}
            >
              thirty seconds.
            </span>
          </h2>
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              alignItems: "flex-start",
              gap: 16,
              flexShrink: 0,
            }}
          >
            <Link
              href="/register"
              style={{
                background: "var(--paper)",
                color: "var(--ink)",
                border: "1px solid var(--paper)",
                padding: "16px 26px",
                fontSize: 15,
                fontWeight: 600,
                fontFamily: "var(--sans)",
                cursor: "pointer",
                borderRadius: 8,
                textDecoration: "none",
                display: "inline-block",
              }}
            >
              Get started →
            </Link>
            <span
              style={{
                fontFamily: "var(--mono)",
                fontSize: 12,
                color: "var(--night-text-3)",
              }}
            >
              pip install vera-sdk · 30s to first signed action
            </span>
          </div>
        </div>
      </div>
    </section>
  );
}
