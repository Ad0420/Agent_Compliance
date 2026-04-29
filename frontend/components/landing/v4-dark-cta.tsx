import Link from "next/link";
import { DarkCtaBackdrop } from "./v4-dark-cta-backdrop";

export function V4DarkCTA() {
  return (
    <section
      style={{
        marginTop: 144,
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
          padding: "144px 88px 96px",
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
        <h2
          style={{
            fontFamily: "var(--sans)",
            fontSize: 112,
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
            display: "grid",
            gridTemplateColumns: "1.4fr 1fr",
            gap: 64,
            alignItems: "end",
            marginTop: 56,
          }}
        >
          <p
            style={{
              fontSize: 19,
              color: "var(--night-text-2)",
              margin: 0,
              lineHeight: 1.5,
              maxWidth: 560,
            }}
          >
            No credit card. Self-serve free tier. The first signed action lands
            in your chain before your coffee gets cold.
          </p>
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              alignItems: "flex-start",
              gap: 16,
            }}
          >
            <div style={{ display: "flex", gap: 12 }}>
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
              <a
                href="#"
                style={{
                  background: "transparent",
                  color: "var(--paper)",
                  border: "1px solid var(--night-edge-2)",
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
                Talk to founders
              </a>
            </div>
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
