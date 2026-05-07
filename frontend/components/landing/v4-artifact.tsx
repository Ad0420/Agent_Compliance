import { Tick } from "./brand";
import { V4SectionHeader } from "./v4-section-header";
import { SignedPdfArtifact } from "./v4-signed-pdf-artifact";

const ITEMS: [string, string][] = [
  ["Tamper-evident seal", "verified without our help"],
  ["Step-by-step record of every decision", "every signer, every timestamp"],
  ["Real cryptographic signature", "anchored to a hardware-secured key"],
  ["Forwardable proof", "your regulator, auditor, or counsel can verify it themselves"],
];

export function V4Artifact() {
  return (
    <section className="v4-section">
      <V4SectionHeader
        kicker="THE ARTIFACT"
        accent="amber"
        title={
          <>
            One click.{" "}
            <span style={{ color: "var(--amber-ink)" }}>
              Regulator-ready PDF.
            </span>
          </>
        }
        sub="When the regulator emails, you respond with one attachment. Sealed, signed, and verifiable by anyone, without a Vera account or special software."
      />
      <div className="v4-grid-2" style={{ alignItems: "center" }}>
        <div>
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              gap: 18,
              marginBottom: 28,
            }}
          >
            {ITEMS.map((p, i) => (
              <div
                key={i}
                style={{
                  display: "flex",
                  gap: 14,
                  alignItems: "flex-start",
                }}
              >
                <Tick size={18} tone="amber" />
                <div>
                  <div
                    style={{
                      fontSize: 17,
                      fontWeight: 600,
                      letterSpacing: "-0.01em",
                    }}
                  >
                    {p[0]}
                  </div>
                  <div
                    style={{
                      fontSize: 14,
                      color: "var(--ink-2)",
                      marginTop: 2,
                    }}
                  >
                    {p[1]}
                  </div>
                </div>
              </div>
            ))}
          </div>
          <button
            style={{
              background: "var(--amber)",
              color: "var(--paper)",
              border: "1px solid var(--amber)",
              padding: "14px 22px",
              fontSize: 14.5,
              fontWeight: 600,
              fontFamily: "var(--sans)",
              cursor: "pointer",
              borderRadius: 8,
              boxShadow: "var(--shadow-1)",
              marginBottom: 28,
            }}
          >
            Download example PDF →
          </button>

          <div
            style={{
              background: "var(--paper-2)",
              border: "1px solid var(--ink-4)",
              borderRadius: 10,
              padding: "16px 18px",
              boxShadow: "var(--shadow-1)",
            }}
          >
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 10,
                marginBottom: 10,
                fontFamily: "var(--mono)",
                fontSize: 10.5,
                fontWeight: 700,
                letterSpacing: 1.4,
                color: "var(--ink-3)",
              }}
            >
              <span
                style={{
                  width: 6,
                  height: 6,
                  borderRadius: "50%",
                  background: "var(--amber-ink)",
                }}
              />
              <span>VERIFY OFFLINE · ~30 SECONDS</span>
            </div>
            <pre
              style={{
                margin: 0,
                fontFamily: "var(--mono)",
                fontSize: 12.5,
                lineHeight: 1.7,
                color: "var(--ink)",
                whiteSpace: "pre-wrap",
              }}
            >
              <span style={{ color: "var(--ink-3)" }}>$ </span>
              <span>vera verify report.pdf</span>
              {"\n"}
              <span
                style={{ color: "var(--emerald-ink)", fontWeight: 600 }}
              >
                ✓ chain intact · 13/13
              </span>
              {"\n"}
              <span
                style={{ color: "var(--emerald-ink)", fontWeight: 600 }}
              >
                ✓ root: 7a5e9f06…79ae
              </span>
              {"\n"}
              <span
                style={{ color: "var(--emerald-ink)", fontWeight: 600 }}
              >
                ✓ kms sig: kms/audit-prod-01
              </span>
            </pre>
          </div>
        </div>
        <SignedPdfArtifact />
      </div>
    </section>
  );
}
