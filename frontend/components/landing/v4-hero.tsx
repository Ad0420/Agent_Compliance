"use client";

import Link from "next/link";
import { HeroAnimation } from "./v4-hero-animation";

export function V4Hero() {
  return (
    <section
      style={{
        padding: "88px 88px 56px",
        position: "relative",
        background:
          "radial-gradient(ellipse 1200px 600px at 50% -200px, rgba(10,122,79,.06), transparent 60%), var(--paper)",
      }}
    >
      <h1
        style={{
          fontFamily: "var(--sans)",
          fontSize: 96,
          fontWeight: 700,
          lineHeight: 0.95,
          letterSpacing: "-0.045em",
          margin: "0 0 28px",
          maxWidth: 1100,
        }}
      >
        Trust Layer for AI Agents
      </h1>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1.3fr 1fr",
          gap: 56,
          alignItems: "end",
          marginBottom: 56,
        }}
      >
        <p
          style={{
            fontSize: 21,
            lineHeight: 1.45,
            color: "var(--ink)",
            margin: 0,
            maxWidth: 640,
            fontWeight: 400,
          }}
        >
          Vera records every agent action into a tamper-proof, cryptographically-
          signed audit chain. So when something goes wrong, or a regulator asks,
          the answer is provable in seconds.
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
                background: "var(--emerald)",
                color: "var(--paper)",
                border: "1px solid var(--emerald)",
                padding: "14px 22px",
                fontSize: 15,
                fontWeight: 600,
                fontFamily: "var(--sans)",
                cursor: "pointer",
                borderRadius: 8,
                boxShadow: "var(--shadow-glow-em)",
                letterSpacing: "-0.005em",
                textDecoration: "none",
                display: "inline-block",
              }}
            >
              Get started free →
            </Link>
            <a
              href="#"
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
              View docs
            </a>
          </div>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 10,
              fontFamily: "var(--mono)",
              fontSize: 12,
              color: "var(--ink-3)",
            }}
          >
            <span
              style={{
                padding: "5px 10px",
                background: "var(--paper-2)",
                border: "1px solid var(--ink-4)",
                borderRadius: 6,
              }}
            >
              pip install vera-sdk
            </span>
            <span>·</span>
            <span>30s · no credit card</span>
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
    </section>
  );
}
