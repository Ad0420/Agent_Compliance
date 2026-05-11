import { Tick } from "./brand";
import { V4SectionHeader } from "./v4-section-header";
import { SignedPdfArtifact } from "./v4-signed-pdf-artifact";

const ITEMS: [string, string][] = [
  [
    "Tamper-evident seal",
    "verified by you, your auditor, or your regulator — with no Vera account needed",
  ],
  ["Step-by-step record of every decision", "every signer, every timestamp"],
  ["Real cryptographic signature", "anchored to a hardware-secured key"],
  [
    "Forwardable proof",
    "your regulator, auditor, or counsel can verify it themselves",
  ],
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
                marginBottom: 12,
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
              <span>VERIFIED INDEPENDENTLY · NO ACCOUNT NEEDED</span>
            </div>
            <ul
              style={{
                margin: 0,
                padding: 0,
                listStyle: "none",
                display: "flex",
                flexDirection: "column",
                gap: 8,
                fontFamily: "var(--sans)",
                fontSize: 14,
                lineHeight: 1.5,
                color: "var(--ink)",
              }}
            >
              <li
                style={{
                  display: "flex",
                  alignItems: "baseline",
                  gap: 10,
                }}
              >
                <span
                  style={{ color: "var(--emerald-ink)", fontWeight: 700 }}
                  aria-hidden
                >
                  ✓
                </span>
                <span>
                  <strong style={{ fontWeight: 600 }}>Chain intact</strong>
                  {" — 13 of 13 decisions verified"}
                </span>
              </li>
              <li
                style={{
                  display: "flex",
                  alignItems: "baseline",
                  gap: 10,
                }}
              >
                <span
                  style={{ color: "var(--emerald-ink)", fontWeight: 700 }}
                  aria-hidden
                >
                  ✓
                </span>
                <span>
                  <strong style={{ fontWeight: 600 }}>Sealed</strong>
                  {" Jan 14, 2026 · 10:21 AM PST"}
                </span>
              </li>
              <li
                style={{
                  display: "flex",
                  alignItems: "baseline",
                  gap: 10,
                }}
              >
                <span
                  style={{ color: "var(--emerald-ink)", fontWeight: 700 }}
                  aria-hidden
                >
                  ✓
                </span>
                <span>
                  <strong style={{ fontWeight: 600 }}>
                    Independent signer
                  </strong>
                  {" — AWS KMS (Virginia)"}
                </span>
              </li>
            </ul>
          </div>
        </div>
        <SignedPdfArtifact />
      </div>
    </section>
  );
}
