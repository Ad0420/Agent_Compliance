import type { CSSProperties } from "react";
import type { Metadata } from "next";
import { HashStamp } from "@/components/landing/brand";
import { V4Footer } from "@/components/landing/v4-footer";
import { V4Nav } from "@/components/landing/v4-nav";

export const metadata: Metadata = {
  title: "Maturity — Vera",
  description:
    "Honest assessment of Vera's pilot-grade systems and the work required to reach production-grade. Updated continuously.",
};

// LAST_UPDATED is injected at build time from the git commit timestamp of
// this file (see next.config.ts). Falls back to "now" if the env var is
// missing (dev without the build wrapper). Render via <time dateTime> so
// crawlers + screen readers can parse it.
const LAST_UPDATED_RAW =
  process.env.NEXT_PUBLIC_MATURITY_LAST_UPDATED ?? new Date().toISOString();

type Tier =
  | "pilot"
  | "pilot-partial"
  | "production"
  | "enterprise"
  | "roadmap";

type SystemRow = {
  system: string;
  detail: string;
  current: string;
  tier: Tier;
  prod: string;
};

const ROWS: SystemRow[] = [
  {
    system: "Cryptographic audit chain",
    detail: "SHA-256 hash chain, KMS-signed exports",
    current: "Pilot-grade",
    tier: "pilot",
    prod:
      "Independent legal opinion on FRE 901/902 admissibility (Q3 2026); third-party verification tool.",
  },
  {
    system: "HITL approval workflow",
    detail: "Clerk-RBAC; audit-of-audit on every approval",
    current: "Pilot-grade",
    tier: "pilot",
    prod:
      "SLA on approver response times; mobile push notifications; escalation policies.",
  },
  {
    system: "PHI redaction",
    detail: "Redactor.medtech() + schema-driven mode",
    current: "Pilot-grade",
    tier: "pilot",
    prod:
      "Customer-specific schema validation tooling; full FHIR resource-type coverage; quarterly red-team review.",
  },
  {
    system: "Durable encrypted spool",
    detail: "AES-256-GCM + SQLite WAL on the SDK side",
    current: "Pilot-grade",
    tier: "pilot",
    prod:
      "Multi-region replication; per-tenant key rotation tooling; documented RPO/RTO.",
  },
  {
    system: "Policy engine",
    detail: "Guardrails (alerting rules) only",
    current: "Guardrails only",
    tier: "pilot-partial",
    prod:
      "Customer-defined DSL for policy rules; policy versioning and rollback; dry-run mode.",
  },
  {
    system: "Authentication",
    detail: "Clerk JWT for dashboard; API keys for SDK",
    current: "Pilot-grade",
    tier: "pilot",
    prod:
      "Enterprise SSO (SAML, OIDC, SCIM); IP allowlisting; org-scoped API keys with rotation policy.",
  },
  {
    system: "Clerk role-drift reconciler",
    detail: "Svix-verified webhooks + periodic re-fetch fallback",
    current: "Webhook-driven + periodic re-fetch fallback",
    tier: "pilot",
    prod:
      "SLA on webhook delivery; reconciliation worker for missed events; per-org audit dashboard of role drift events.",
  },
  {
    system: "SDK fork safety",
    detail: "gunicorn, Celery, multiprocessing.Pool",
    current: "Tested for fork",
    tier: "pilot",
    prod:
      "Full spawn/forkserver support; managed connection pool; Windows process model support.",
  },
  {
    system: "Compliance evidence export",
    detail: "PDF + CSV export of signed audit chain",
    current: "Available; not third-party audited",
    tier: "pilot",
    prod:
      "Third-party audit of export shape; templated per-jurisdiction (EU AI Act Art. 13 vs. ISO 42001 vs. HIPAA).",
  },
  {
    system: "Insurance underwriting data feed",
    detail: "Continuous telemetry for underwriters",
    current: "Roadmap (Act 2 vision)",
    tier: "roadmap",
    prod:
      "6+ months of runtime telemetry across regulated verticals; partnership with a licensed carrier.",
  },
];

const TIER_BADGE: Record<Tier, { label: string; bg: string; fg: string; border: string }> = {
  pilot: {
    label: "PILOT",
    bg: "var(--amber-paper)",
    fg: "var(--amber-ink)",
    border: "var(--amber-ink)",
  },
  "pilot-partial": {
    label: "PILOT · PARTIAL",
    bg: "var(--amber-paper)",
    fg: "var(--amber-ink)",
    border: "var(--amber-ink)",
  },
  production: {
    label: "PRODUCTION",
    bg: "var(--emerald-paper)",
    fg: "var(--emerald-ink)",
    border: "var(--emerald-ink)",
  },
  enterprise: {
    label: "ENTERPRISE",
    bg: "var(--emerald-paper)",
    fg: "var(--emerald-ink)",
    border: "var(--emerald-ink)",
  },
  roadmap: {
    label: "ROADMAP",
    bg: "var(--paper-2)",
    fg: "var(--ink-2)",
    border: "var(--ink-4)",
  },
};

const sectionLabelStyle: CSSProperties = {
  fontFamily: "var(--mono)",
  fontSize: 11,
  color: "var(--ink-3)",
  fontWeight: 700,
  letterSpacing: 1.8,
  margin: 0,
};

const proseStyle: CSSProperties = {
  fontSize: 17,
  lineHeight: 1.6,
  color: "var(--ink)",
  margin: 0,
  maxWidth: 760,
  fontWeight: 400,
};

const LAST_UPDATED_DISPLAY = new Date(LAST_UPDATED_RAW).toLocaleDateString(
  "en-US",
  { year: "numeric", month: "long", day: "numeric" },
);

export default function MaturityPage() {
  return (
    <div
      style={{
        background: "var(--paper)",
        color: "var(--ink)",
        fontFamily: "var(--sans)",
      }}
    >
      <V4Nav />

      {/* Header */}
      <section className="v3-section" style={{ paddingTop: 56, paddingBottom: 32 }}>
        <div style={{ display: "flex", alignItems: "baseline", gap: 18, marginBottom: 24 }}>
          <span
            style={{
              fontFamily: "var(--mono)",
              fontSize: 11,
              color: "var(--amber-ink)",
              fontWeight: 700,
              letterSpacing: 1.8,
            }}
          >
            EXHIBIT M · MATURITY MANIFEST
          </span>
          <span style={{ flex: 1, height: 1, background: "var(--ink-4)" }} />
          <HashStamp
            value={
              <>
                last updated ·{" "}
                <time dateTime={LAST_UPDATED_RAW}>{LAST_UPDATED_DISPLAY}</time>
              </>
            }
            tone="amber"
          />
        </div>

        <h1 className="v3-hero-h1" style={{ marginBottom: 22, fontSize: "clamp(40px, 7.2vw, 88px)" }}>
          Pilot maturity,{" "}
          <span style={{ color: "var(--ink-2)" }}>not production maturity</span>{" "}
          <span
            style={{
              fontFamily: "var(--serif)",
              fontStyle: "italic",
              fontWeight: 500,
              letterSpacing: "-0.03em",
            }}
          >
            (yet).
          </span>
        </h1>

        <p style={{ ...proseStyle, marginBottom: 14 }}>
          Vera is in pilot deployment with our first design partner. Here&apos;s the honest
          state of every system, and what it takes to reach production-grade.
        </p>

        <p
          style={{
            fontFamily: "var(--serif)",
            fontStyle: "italic",
            fontSize: 13.5,
            lineHeight: 1.6,
            color: "var(--ink-2)",
            margin: 0,
            maxWidth: 720,
            paddingLeft: 14,
            borderLeft: "2px solid var(--ink-4)",
          }}
        >
          This page is the proactive companion to our public collateral. Most early-stage
          compliance vendors overclaim. We&apos;d rather you ask sharp questions on day one.
        </p>
      </section>

      {/* Tier definitions */}
      <section className="v3-section" style={{ paddingTop: 24, paddingBottom: 48 }}>
        <div style={{ display: "flex", alignItems: "baseline", gap: 14, marginBottom: 24 }}>
          <h2 style={sectionLabelStyle}>§ 01 · THE THREE TIERS</h2>
          <span style={{ flex: 1, height: 1, background: "var(--ink-4)" }} />
        </div>

        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))",
            gap: 20,
          }}
        >
          <TierCard
            label="Pilot-grade"
            tone="amber"
            blurb="Ships today. Tested in design-partner staging, behavior known. Suitable for non-critical AI workflows and for design partners aligned on the maturity tradeoffs."
          />
          <TierCard
            label="Production-grade"
            tone="emerald"
            blurb="Survives a real audit. Tested under load. All known failure modes have explicit handling. Suitable for regulated production deployments."
          />
          <TierCard
            label="Enterprise-grade"
            tone="ink"
            blurb="Survives a security review at a Fortune 500. SSO, SOC 2 Type II, BAA-by-default, dedicated infra. Not on the 6-month roadmap."
          />
        </div>
      </section>

      {/* System-by-system table */}
      <section className="v3-section" style={{ paddingTop: 24, paddingBottom: 64 }}>
        <div style={{ display: "flex", alignItems: "baseline", gap: 14, marginBottom: 24 }}>
          <h2 style={sectionLabelStyle}>§ 02 · SYSTEM BY SYSTEM</h2>
          <span style={{ flex: 1, height: 1, background: "var(--ink-4)" }} />
        </div>

        <p style={{ ...proseStyle, marginBottom: 28 }}>
          Every row is something that runs in pilot today or sits on the roadmap. The
          right column describes the engineering and process work between now and the
          production-grade tier above &mdash; not a marketing promise.
        </p>

        <div
          style={{
            border: "1px solid var(--ink)",
            background: "var(--paper-2)",
            overflow: "hidden",
          }}
        >
          <table className="mat-table">
            <caption className="mat-table__caption">
              Vera systems by current maturity tier and what production-grade requires.
            </caption>
            <thead>
              <tr className="mat-row mat-row--head">
                <th scope="col">SYSTEM</th>
                <th scope="col">CURRENT TIER</th>
                <th scope="col">PRODUCTION-GRADE REQUIRES</th>
              </tr>
            </thead>
            <tbody>
              {ROWS.map((row, i) => {
                const badge = TIER_BADGE[row.tier];
                return (
                  <tr
                    key={row.system}
                    className="mat-row"
                    style={{
                      borderTop: i === 0 ? "none" : "1px solid var(--ink-4)",
                    }}
                  >
                    <th scope="row" data-label="System" className="mat-cell mat-cell--system">
                      <div
                        style={{
                          fontWeight: 700,
                          fontSize: 16,
                          letterSpacing: "-0.01em",
                          marginBottom: 4,
                        }}
                      >
                        {row.system}
                      </div>
                      <div
                        style={{
                          fontFamily: "var(--mono)",
                          fontSize: 12,
                          color: "var(--ink-3)",
                          lineHeight: 1.5,
                          fontWeight: 400,
                        }}
                      >
                        {row.detail}
                      </div>
                    </th>

                    <td data-label="Current tier" className="mat-cell">
                      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                        <span
                          style={{
                            display: "inline-flex",
                            alignItems: "center",
                            gap: 6,
                            alignSelf: "flex-start",
                            fontFamily: "var(--mono)",
                            fontSize: 10.5,
                            fontWeight: 700,
                            letterSpacing: 1.6,
                            padding: "4px 8px",
                            background: badge.bg,
                            color: badge.fg,
                            border: `1px solid ${badge.border}`,
                            borderRadius: 3,
                          }}
                        >
                          {badge.label}
                        </span>
                        <span
                          style={{
                            fontSize: 13,
                            color: "var(--ink-2)",
                            lineHeight: 1.45,
                          }}
                        >
                          {row.current}
                        </span>
                      </div>
                    </td>

                    <td
                      data-label="Production-grade requires"
                      className="mat-cell"
                      style={{
                        fontSize: 14.5,
                        color: "var(--ink)",
                        lineHeight: 1.55,
                      }}
                    >
                      {row.prod}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>

      {/* Why we publish this */}
      <section
        className="v3-section"
        style={{
          paddingTop: 80,
          paddingBottom: 80,
          borderTop: "1px solid var(--ink)",
          background: "var(--ink)",
          color: "var(--paper)",
        }}
      >
        <div style={{ display: "flex", alignItems: "baseline", gap: 14, marginBottom: 22 }}>
          <h2
            style={{
              fontFamily: "var(--mono)",
              fontSize: 11,
              color: "rgba(243,239,231,.55)",
              fontWeight: 700,
              letterSpacing: 1.8,
              margin: 0,
            }}
          >
            § 03 · WHY WE PUBLISH THIS
          </h2>
          <span style={{ flex: 1, height: 1, background: "rgba(243,239,231,.18)" }} />
        </div>

        <div style={{ maxWidth: 760 }}>
          <p
            style={{
              fontSize: 19,
              lineHeight: 1.55,
              color: "var(--paper)",
              margin: "0 0 18px",
              fontWeight: 400,
            }}
          >
            Most early-stage compliance vendors overclaim. We&apos;ve seen the failure mode:
            a buyer asks a sharp question in week 2 of a pilot, the vendor doesn&apos;t have
            an answer, the deal stalls.
          </p>
          <p
            style={{
              fontSize: 17,
              lineHeight: 1.6,
              color: "rgba(243,239,231,.78)",
              margin: "0 0 18px",
            }}
          >
            We&apos;d rather lose deals at week 1 to honesty than lose them at week 6 to
            surprises. If the gap between pilot-grade and your needs is too wide, we&apos;ll
            say so. If it&apos;s bridgeable on a known timeline, this page tells you when.
          </p>
          <p
            style={{
              fontSize: 17,
              lineHeight: 1.6,
              color: "rgba(243,239,231,.78)",
              margin: "0 0 28px",
            }}
          >
            The pilot-grade items above are real product today. The production-grade
            column is real engineering work we know how to do, sequenced by customer
            demand. Email us if your use case demands a tier we haven&apos;t shipped yet
            &mdash; we&apos;ll tell you straight.
          </p>

          <a
            href="mailto:hello@usevera.xyz?subject=Maturity%20question"
            style={{
              display: "inline-block",
              background: "var(--paper)",
              color: "var(--ink)",
              border: "1px solid var(--paper)",
              padding: "14px 22px",
              fontSize: 15,
              fontWeight: 600,
              fontFamily: "var(--sans)",
              textDecoration: "none",
            }}
          >
            hello@usevera.xyz &rarr;
          </a>
        </div>
      </section>

      <V4Footer />
    </div>
  );
}

function TierCard({
  label,
  blurb,
  tone,
}: {
  label: string;
  blurb: string;
  tone: "amber" | "emerald" | "ink";
}) {
  const palette =
    tone === "emerald"
      ? {
          bg: "var(--emerald-paper)",
          accent: "var(--emerald-ink)",
          border: "var(--emerald-ink)",
        }
      : tone === "amber"
        ? {
            bg: "var(--amber-paper)",
            accent: "var(--amber-ink)",
            border: "var(--amber-ink)",
          }
        : {
            bg: "var(--paper-2)",
            accent: "var(--ink)",
            border: "var(--ink)",
          };

  return (
    <div
      style={{
        background: palette.bg,
        border: `1px solid ${palette.border}`,
        padding: "22px 22px 24px",
      }}
    >
      <div
        style={{
          fontFamily: "var(--mono)",
          fontSize: 11,
          fontWeight: 700,
          letterSpacing: 1.8,
          color: palette.accent,
          marginBottom: 12,
        }}
      >
        TIER · {label.toUpperCase()}
      </div>
      <h3
        style={{
          margin: "0 0 12px",
          fontSize: 22,
          fontWeight: 700,
          letterSpacing: "-0.02em",
        }}
      >
        {label}
      </h3>
      <p
        style={{
          margin: 0,
          fontSize: 14.5,
          lineHeight: 1.55,
          color: "var(--ink)",
        }}
      >
        {blurb}
      </p>
    </div>
  );
}
