export function SignedPdfArtifact() {
  const rows: [string, string, string][] = [
    ["00:00:00", "kms/audit-prod-01", "✓"],
    ["10:21:09", "kms/audit-prod-01", "✓"],
    ["10:21:14", "kms/audit-prod-01", "✓"],
  ];
  return (
    <div
      style={{
        position: "relative",
        borderRadius: 12,
        background: "var(--paper)",
        border: "1px solid var(--ink-4)",
        boxShadow: "var(--shadow-3)",
        overflow: "hidden",
        aspectRatio: "4/5",
        padding: "40px 44px",
        fontFamily: "var(--sans)",
      }}
    >
      <div
        style={{
          position: "absolute",
          inset: 0,
          backgroundImage:
            "radial-gradient(rgba(21,20,15,0.025) 1px, transparent 1px)",
          backgroundSize: "3px 3px",
          pointerEvents: "none",
        }}
      />
      <div
        style={{
          position: "relative",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "baseline",
          marginBottom: 8,
        }}
      >
        <span
          style={{
            fontFamily: "var(--mono)",
            fontSize: 10,
            fontWeight: 700,
            color: "var(--ink-3)",
            letterSpacing: 1.4,
          }}
        >
          VERA EVIDENCE PDF · v1
        </span>
        <span
          style={{
            fontFamily: "var(--mono)",
            fontSize: 10,
            fontWeight: 700,
            color: "var(--amber-ink)",
            letterSpacing: 1.4,
          }}
        >
          FRE 901/902
        </span>
      </div>
      <h3
        style={{
          position: "relative",
          margin: "0 0 4px",
          fontSize: 26,
          fontWeight: 700,
          letterSpacing: "-0.025em",
        }}
      >
        Audit Report
      </h3>
      <p
        style={{
          position: "relative",
          margin: 0,
          fontSize: 12.5,
          color: "var(--ink-2)",
          marginBottom: 22,
        }}
      >
        application_4821 · 13 records · sha256-chained · KMS-verified
      </p>

      <div
        style={{
          position: "relative",
          border: "1.5px solid var(--emerald-ink)",
          borderRadius: 8,
          padding: "14px 16px",
          marginBottom: 22,
          display: "flex",
          alignItems: "center",
          gap: 14,
          background: "rgba(10,122,79,0.04)",
        }}
      >
        <span
          style={{
            width: 28,
            height: 28,
            borderRadius: "50%",
            background: "var(--emerald-ink)",
            color: "var(--paper)",
            display: "inline-flex",
            alignItems: "center",
            justifyContent: "center",
            fontWeight: 700,
            fontSize: 14,
          }}
        >
          ✓
        </span>
        <div>
          <div
            style={{
              fontSize: 13.5,
              fontWeight: 700,
              letterSpacing: "-0.005em",
            }}
          >
            CHAIN INTEGRITY VERIFIED
          </div>
          <div
            style={{
              fontFamily: "var(--mono)",
              fontSize: 10,
              color: "var(--ink-2)",
              marginTop: 2,
            }}
          >
            13/13 records · root: 7a5e9f06d2c41b…79ae
          </div>
        </div>
      </div>

      <div style={{ position: "relative", marginBottom: 22 }}>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "1fr 1fr auto",
            fontFamily: "var(--mono)",
            fontSize: 9,
            color: "var(--ink-3)",
            letterSpacing: 1.2,
            fontWeight: 700,
            paddingBottom: 6,
            borderBottom: "1px solid var(--ink)",
          }}
        >
          <span>CHECKPOINT</span>
          <span>KMS KEY</span>
          <span>STATUS</span>
        </div>
        {rows.map((r, i) => (
          <div
            key={i}
            style={{
              display: "grid",
              gridTemplateColumns: "1fr 1fr auto",
              fontFamily: "var(--mono)",
              fontSize: 11,
              color: "var(--ink-2)",
              padding: "8px 0",
              borderBottom: "1px solid var(--ink-4)",
            }}
          >
            <span>{r[0]}</span>
            <span>{r[1]}</span>
            <span style={{ color: "var(--emerald-ink)", fontWeight: 700 }}>
              {r[2]}
            </span>
          </div>
        ))}
      </div>

      <div
        style={{
          position: "relative",
          border: "1px dashed var(--ink-3)",
          padding: "12px 14px",
          marginBottom: 22,
        }}
      >
        <div
          style={{
            fontFamily: "var(--mono)",
            fontSize: 9.5,
            color: "var(--ink-3)",
            letterSpacing: 1.4,
            fontWeight: 700,
            marginBottom: 6,
          }}
        >
          KMS SIGNATURE BLOCK
        </div>
        <div
          style={{
            fontFamily: "var(--mono)",
            fontSize: 10,
            color: "var(--ink-2)",
            lineHeight: 1.5,
            wordBreak: "break-all",
          }}
        >
          MEUCIQDk3R4o8QmF…vEaA2bC4Z9Lp7Fp
          <br />
          n0xWZcJ3+fK9uHr1…Kt8YdvpL2wQ==
        </div>
      </div>

      <div
        style={{
          position: "absolute",
          left: 44,
          right: 44,
          bottom: 36,
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          paddingTop: 12,
          borderTop: "1px solid var(--ink-4)",
          fontFamily: "var(--mono)",
          fontSize: 10,
          color: "var(--ink-3)",
          letterSpacing: 1.2,
          fontWeight: 600,
        }}
      >
        <span>VERIFY OFFLINE: vera-cli verify report.pdf</span>
        <span>PAGE 1 / 4</span>
      </div>

      <div
        style={{
          position: "absolute",
          top: 24,
          right: 28,
          transform: "rotate(8deg)",
          border: "1.5px solid var(--amber-ink)",
          color: "var(--amber-ink)",
          padding: "5px 9px",
          fontFamily: "var(--mono)",
          fontSize: 9.5,
          fontWeight: 700,
          letterSpacing: 1.4,
          background: "rgba(154,93,18,0.06)",
        }}
      >
        SIGNED
      </div>
    </div>
  );
}
