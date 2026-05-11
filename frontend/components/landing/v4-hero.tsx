"use client";

import Link from "next/link";
import { HeroAnimation } from "./v4-hero-animation";

export function V4Hero() {
  return (
    <section
      style={{
        padding: "clamp(48px, 8vw, 88px) var(--gutter) clamp(40px, 6vw, 56px)",
        position: "relative",
        background:
          "radial-gradient(ellipse 1200px 600px at 50% -200px, rgba(10,122,79,.06), transparent 60%), var(--paper)",
      }}
    >
      <h1
        style={{
          fontFamily: "var(--sans)",
          fontSize: "var(--h1)",
          fontWeight: 700,
          lineHeight: 0.95,
          letterSpacing: "-0.045em",
          margin: "0 0 28px",
          maxWidth: 1100,
        }}
      >
        Trust Layer for
        <br />
        <span
          style={{
            fontFamily: "var(--serif)",
            fontStyle: "italic",
            fontWeight: 500,
            color: "var(--ink-2)",
            letterSpacing: "-0.03em",
          }}
        >
          AI Agents
        </span>
      </h1>

      <div
        className="v4-grid-hero"
        style={{ alignItems: "end", marginBottom: "clamp(40px, 6vw, 56px)" }}
      >
        <p
          style={{
            fontSize: "var(--body-lg)",
            lineHeight: 1.45,
            color: "var(--ink)",
            margin: 0,
            maxWidth: 640,
            fontWeight: 400,
          }}
        >
          When a regulator asks or a customer disputes a decision, the answer
          is one attachment away. Vera seals every AI decision the moment it&rsquo;s
          made &mdash; and the seal can&rsquo;t be edited after the fact.
        </p>
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            alignItems: "flex-start",
            gap: 16,
          }}
        >
          <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
            <Link
              href="/register"
              style={{
                background: "var(--ink)",
                color: "var(--paper)",
                border: "1px solid var(--ink)",
                padding: "14px 22px",
                fontSize: 15,
                fontWeight: 600,
                fontFamily: "var(--sans)",
                cursor: "pointer",
                borderRadius: 8,
                boxShadow: "var(--shadow-1)",
                letterSpacing: "-0.005em",
                textDecoration: "none",
                display: "inline-block",
              }}
            >
              Get started free →
            </Link>
            <a
              href="#contact"
              style={{
                background: "var(--paper)",
                color: "var(--ink)",
                border: "1px solid var(--ink-4)",
                padding: "14px 22px",
                fontSize: 15,
                fontWeight: 600,
                fontFamily: "var(--sans)",
                cursor: "pointer",
                borderRadius: 8,
                boxShadow: "var(--shadow-1)",
                textDecoration: "none",
                display: "inline-block",
              }}
            >
              Talk to our team
            </a>
          </div>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 10,
              flexWrap: "wrap",
              fontFamily: "var(--mono)",
              fontSize: 12,
              color: "var(--ink-3)",
            }}
          >
            <span>Free to start · Thirty seconds to your first sealed decision</span>
          </div>
        </div>
      </div>

      <div
        style={{
          position: "relative",
          borderRadius: 14,
          boxShadow: "var(--shadow-3)",
          background: "var(--paper-2)",
          border: "1px solid var(--ink-4)",
          overflow: "hidden",
        }}
      >
        <HeroAnimation />
      </div>

      <div
        style={{
          marginTop: "clamp(32px, 5vw, 48px)",
          paddingTop: 24,
          borderTop: "1px solid var(--ink-4)",
          fontFamily: "var(--mono)",
          fontSize: 12,
          letterSpacing: 1.2,
          color: "var(--ink-3)",
          textTransform: "uppercase",
          fontWeight: 600,
        }}
      >
        For teams running AI in lending, underwriting, clinical decision
        support, and hiring.
      </div>
    </section>
  );
}
