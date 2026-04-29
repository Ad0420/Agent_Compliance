import { HashStamp, PrototypeDisclaimer, Wordmark } from "./brand";

const COLUMNS = [
  { h: "Product", links: ["Docs", "Pricing", "Changelog", "Status"] },
  { h: "Regulations", links: ["EU AI Act", "Colorado", "GDPR", "SEC 17a-4"] },
  { h: "Company", links: ["About", "Blog", "Contact", "Press"] },
  { h: "Legal", links: ["Privacy", "Terms", "Security", "DPA"] },
];

export function V4Footer() {
  return (
    <footer
      style={{
        padding: "0 88px 32px",
        background: "var(--night)",
        color: "var(--night-text-2)",
      }}
    >
      <div
        style={{
          padding: "32px 0",
          display: "grid",
          gridTemplateColumns: "2fr repeat(4, 1fr)",
          gap: 32,
          borderTop: "1px solid var(--night-edge)",
        }}
      >
        <div>
          <Wordmark size={16} color="var(--paper)" />
          <p
            style={{
              margin: "16px 0 0",
              fontSize: 13,
              lineHeight: 1.5,
              color: "var(--night-text-3)",
              maxWidth: 280,
            }}
          >
            Runtime trust layer for AI agents. Tamper-proof evidence,
            cryptographically signed, regulator-ready.
          </p>
        </div>
        {COLUMNS.map((col) => (
          <div key={col.h}>
            <div
              style={{
                fontFamily: "var(--mono)",
                fontSize: 10.5,
                color: "var(--night-text-3)",
                fontWeight: 700,
                letterSpacing: 1.5,
                marginBottom: 14,
                textTransform: "uppercase",
              }}
            >
              {col.h}
            </div>
            <ul
              style={{
                listStyle: "none",
                padding: 0,
                margin: 0,
                display: "flex",
                flexDirection: "column",
                gap: 8,
              }}
            >
              {col.links.map((l) => (
                <li key={l}>
                  <a
                    href="#"
                    style={{
                      fontSize: 13,
                      color: "var(--night-text-2)",
                      textDecoration: "none",
                    }}
                  >
                    {l}
                  </a>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
      <PrototypeDisclaimer tone="dark" />
      <div
        style={{
          padding: "16px 0",
          display: "flex",
          alignItems: "center",
          gap: 16,
          fontFamily: "var(--mono)",
          fontSize: 11,
          color: "var(--night-text-3)",
          letterSpacing: 0.5,
          borderTop: "1px solid var(--night-edge)",
        }}
      >
        <span>© 2026 Vera Labs · file no. vera/0.1.0</span>
        <span style={{ flex: 1 }} />
        <HashStamp value="sha256:7a5e9f06d2c41b…79ae" tone="emerald" />
      </div>
    </footer>
  );
}
