type Station = {
  n: string;
  title: string;
  sub: string;
  dt: string;
  control: string;
  emphasis?: boolean;
};

const STATIONS: Station[] = [
  { n: "01", title: "INTERCEPT", sub: "DB trigger", dt: "0.4ms", control: "ISO-27001 A.12.4" },
  { n: "02", title: "HASH", sub: "sha-256", dt: "0.8ms", control: "FIPS 180-4" },
  { n: "03", title: "CHAIN", sub: "linked + ordered", dt: "0.9ms", control: "RFC 6962" },
  { n: "04", title: "SIGN", sub: "AWS KMS / HSM", dt: "3.7ms", control: "FIPS 140-2 L3", emphasis: true },
  { n: "05", title: "STORE", sub: "S3 Object Lock", dt: "2.2ms", control: "WORM · NIST 800-209" },
];

export function TrustPipelineDiagram() {
  return (
    <div
      style={{
        position: "relative",
        borderRadius: 12,
        background: "var(--paper-2)",
        border: "1px solid var(--ink-4)",
        boxShadow: "var(--shadow-2)",
        padding: "32px 28px 28px",
        aspectRatio: "16/10",
        display: "flex",
        flexDirection: "column",
        overflow: "hidden",
      }}
    >
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "baseline",
          marginBottom: 18,
          fontFamily: "var(--mono)",
          fontSize: 10.5,
          fontWeight: 700,
          letterSpacing: 1.4,
          color: "var(--ink-3)",
        }}
      >
        <span>FIG. 02 · TRUST PIPELINE</span>
        <span>agent.write() → WORM · ~8ms p50</span>
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "120px 1fr 90px",
          alignItems: "center",
          marginBottom: 28,
        }}
      >
        <div
          style={{
            fontFamily: "var(--mono)",
            fontSize: 11,
            fontWeight: 700,
            letterSpacing: 1.2,
            color: "var(--ink)",
            padding: "8px 10px",
            border: "1.5px solid var(--ink)",
            background: "var(--paper)",
            textAlign: "center",
          }}
        >
          AGENT
          <div
            style={{
              fontWeight: 500,
              color: "var(--ink-3)",
              fontSize: 9.5,
              marginTop: 3,
              letterSpacing: 1,
            }}
          >
            decision-agent
          </div>
        </div>
        <div
          style={{
            fontFamily: "var(--mono)",
            fontSize: 10,
            color: "var(--ink-3)",
            letterSpacing: 1.4,
            paddingLeft: 14,
          }}
        >
          agent.write(decision)
        </div>
        <div
          style={{
            fontFamily: "var(--mono)",
            fontSize: 10,
            color: "var(--ink-3)",
            letterSpacing: 1.4,
            textAlign: "right",
          }}
        >
          T+0.0ms
        </div>
      </div>

      <div style={{ position: "relative", flex: 1 }}>
        <div
          style={{
            position: "absolute",
            left: 0,
            right: 0,
            top: "50%",
            height: 2,
            background: "var(--ink)",
            transform: "translateY(-1px)",
          }}
        />

        <div
          style={{
            position: "relative",
            display: "grid",
            gridTemplateColumns: "repeat(5, 1fr)",
            height: "100%",
          }}
        >
          {STATIONS.map((s) => {
            const accent = s.emphasis ? "var(--amber-ink)" : "var(--emerald-ink)";
            return (
              <div
                key={s.n}
                style={{
                  position: "relative",
                  display: "flex",
                  flexDirection: "column",
                  alignItems: "center",
                  justifyContent: "center",
                }}
              >
                <div
                  style={{
                    position: "absolute",
                    top: "calc(50% - 78px)",
                    display: "flex",
                    flexDirection: "column",
                    alignItems: "center",
                    gap: 4,
                  }}
                >
                  <span
                    style={{
                      fontFamily: "var(--mono)",
                      fontSize: 10,
                      fontWeight: 700,
                      color: "var(--ink-3)",
                      letterSpacing: 1.2,
                    }}
                  >
                    +{s.dt}
                  </span>
                  <span style={{ width: 1, height: 20, background: "var(--ink-3)" }} />
                </div>

                <div
                  style={{
                    width: 52,
                    height: 52,
                    borderRadius: "50%",
                    background: "var(--paper)",
                    border: "2px solid " + accent,
                    display: "inline-flex",
                    alignItems: "center",
                    justifyContent: "center",
                    fontFamily: "var(--mono)",
                    fontSize: 14,
                    fontWeight: 700,
                    color: accent,
                    letterSpacing: 0,
                    boxShadow:
                      "0 0 0 6px " +
                      (s.emphasis ? "rgba(154,93,18,0.10)" : "rgba(10,122,79,0.10)"),
                    position: "relative",
                    zIndex: 1,
                  }}
                >
                  {s.n}
                </div>

                <div
                  style={{
                    position: "absolute",
                    top: "calc(50% + 40px)",
                    display: "flex",
                    flexDirection: "column",
                    alignItems: "center",
                    gap: 4,
                    textAlign: "center",
                  }}
                >
                  <span
                    style={{
                      fontFamily: "var(--sans)",
                      fontSize: 14,
                      fontWeight: 700,
                      letterSpacing: "-0.01em",
                      color: "var(--ink)",
                    }}
                  >
                    {s.title}
                  </span>
                  <span
                    style={{
                      fontFamily: "var(--mono)",
                      fontSize: 10,
                      fontWeight: 500,
                      letterSpacing: 1.1,
                      color: "var(--ink-3)",
                    }}
                  >
                    {s.sub}
                  </span>
                  <span
                    style={{
                      fontFamily: "var(--mono)",
                      fontSize: 9,
                      fontWeight: 700,
                      letterSpacing: 1.2,
                      color: accent,
                      marginTop: 6,
                      padding: "2px 6px",
                      border: "1px solid " + accent,
                      background: s.emphasis ? "rgba(154,93,18,0.06)" : "rgba(10,122,79,0.05)",
                    }}
                  >
                    {s.control}
                  </span>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      <div
        style={{
          marginTop: 24,
          paddingTop: 14,
          borderTop: "1px solid var(--ink-4)",
          display: "flex",
          justifyContent: "space-between",
          fontFamily: "var(--mono)",
          fontSize: 10,
          color: "var(--ink-3)",
          letterSpacing: 1.3,
          fontWeight: 700,
        }}
      >
        <span>EACH STATION MAPS TO A CONTROL AUDITORS RECOGNIZE</span>
        <span style={{ color: "var(--amber-ink)" }}>● 04 = NON-REPUDIATION (LEGAL CORE)</span>
      </div>
    </div>
  );
}
