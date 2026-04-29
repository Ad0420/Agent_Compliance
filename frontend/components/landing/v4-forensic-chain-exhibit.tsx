"use client";

import React from "react";

interface ChainRow {
  n: string;
  action: string;
  agent: string;
  hash: string;
  ts: string;
  prev: string;
}

const BASE_ROWS: ChainRow[] = [
  { n: "01", action: "fetch_credit_report", agent: "data-agent", hash: "d93c9c02…0011", ts: "10:21:03.412", prev: "00000000…0000" },
  { n: "02", action: "analyze_application", agent: "analysis-agent", hash: "f706a2b4…c188", ts: "10:21:03.418", prev: "d93c9c02…0011" },
  { n: "03", action: "assess_risk", agent: "risk-agent", hash: "1d9f7b2e…aa5c", ts: "10:21:03.421", prev: "f706a2b4…c188" },
  { n: "04", action: "human_approval", agent: "compliance", hash: "a91e0c45…8842", ts: "10:21:03.503", prev: "1d9f7b2e…aa5c" },
  { n: "05", action: "make_decision", agent: "decision-agent", hash: "7a5e9f06…79ae", ts: "10:21:03.509", prev: "a91e0c45…8842" },
  { n: "06", action: "notify_applicant", agent: "notify-agent", hash: "4b2ee3c1…91f0", ts: "10:21:03.512", prev: "7a5e9f06…79ae" },
  { n: "07", action: "log_outcome", agent: "audit-agent", hash: "9c0f8d77…2256", ts: "10:21:03.515", prev: "4b2ee3c1…91f0" },
  { n: "08", action: "checkpoint_kms", agent: "kms-signer", hash: "5e1a4bc9…a3df", ts: "10:21:03.547", prev: "9c0f8d77…2256" },
];

const TAMPERED_FROM_IDX = 3;

export function ForensicChainExhibit() {
  const [tampered, setTampered] = React.useState<boolean>(true);
  const [inspectIdx, setInspectIdx] = React.useState<number | null>(null);

  const handleToggleTamper = (): void => {
    setTampered((t) => !t);
  };

  const handleRowClick = (i: number): void => {
    setInspectIdx((cur) => (cur === i ? null : i));
  };

  return (
    <div
      style={{
        position: "relative",
        borderRadius: 14,
        overflow: "hidden",
        background: "var(--paper-2)",
        border: "1.5px solid var(--ink)",
        boxShadow: "var(--shadow-3)",
        fontFamily: "var(--mono)",
        display: "flex",
        flexDirection: "column",
      }}
    >
      <div
        style={{
          padding: "14px 22px",
          borderBottom: "1.5px solid var(--ink)",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "baseline",
          background: "var(--ink)",
          color: "var(--paper)",
          fontSize: 10.5,
          fontWeight: 700,
          letterSpacing: 1.6,
        }}
      >
        <span>EXHIBIT A · CHAIN INTEGRITY</span>
        <span>application_4821 · 8 RECORDS</span>
      </div>

      <div
        style={{
          padding: "10px 22px",
          borderBottom: "1px solid var(--ink-4)",
          background: tampered ? "rgba(140,42,31,0.08)" : "rgba(10,122,79,0.06)",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 16,
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 12,
          }}
        >
          <span
            style={{
              width: 10,
              height: 10,
              borderRadius: "50%",
              background: tampered ? "var(--red)" : "var(--emerald-ink)",
              boxShadow:
                "0 0 0 4px " +
                (tampered ? "rgba(140,42,31,0.18)" : "rgba(10,122,79,0.14)"),
            }}
          />
          <span
            style={{
              fontSize: 11,
              fontWeight: 700,
              letterSpacing: 1.4,
              color: tampered ? "var(--red)" : "var(--emerald-ink)",
            }}
          >
            {tampered
              ? "CHAIN BROKEN AT RECORD 04"
              : "CHAIN VERIFIED · 8/8 RECORDS INTACT"}
          </span>
        </div>
        <button
          onClick={handleToggleTamper}
          style={{
            fontFamily: "var(--mono)",
            fontSize: 10,
            fontWeight: 700,
            letterSpacing: 1.4,
            padding: "5px 9px",
            background: "var(--paper)",
            color: "var(--ink)",
            border: "1px solid var(--ink)",
            cursor: "pointer",
            borderRadius: 3,
          }}
        >
          {tampered ? "RESTORE ▶" : "TAMPER ◉"}
        </button>
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "44px 1fr 110px 150px 28px",
          gap: 12,
          padding: "10px 22px",
          fontSize: 9.5,
          fontWeight: 700,
          letterSpacing: 1.3,
          color: "var(--ink-3)",
          borderBottom: "1px solid var(--ink)",
        }}
      >
        <span>#</span>
        <span>ACTION</span>
        <span>AGENT</span>
        <span>SHA-256</span>
        <span></span>
      </div>

      <div style={{ position: "relative" }}>
        {BASE_ROWS.map((r, i) => {
          const isTamperedRow = tampered && i === TAMPERED_FROM_IDX;
          const isBrokenDownstream = tampered && i >= TAMPERED_FROM_IDX;
          const showHash = isTamperedRow ? "INVALID──HASH" : r.hash;
          const isInspecting = inspectIdx === i;
          return (
            <React.Fragment key={r.n}>
              <div
                onClick={() => handleRowClick(i)}
                style={{
                  display: "grid",
                  gridTemplateColumns: "44px 1fr 110px 150px 28px",
                  gap: 12,
                  padding: "11px 22px",
                  alignItems: "center",
                  fontSize: 11.5,
                  borderBottom:
                    i < BASE_ROWS.length - 1
                      ? "1px solid var(--ink-4)"
                      : "none",
                  color: isBrokenDownstream ? "var(--red)" : "var(--ink)",
                  background: isInspecting
                    ? "var(--paper)"
                    : isTamperedRow
                    ? "rgba(140,42,31,0.10)"
                    : "transparent",
                  position: "relative",
                  cursor: "pointer",
                  transition: "background 120ms ease",
                }}
              >
                <span
                  style={{
                    fontWeight: 700,
                    color: isBrokenDownstream ? "var(--red)" : "var(--ink-3)",
                  }}
                >
                  {r.n}
                </span>
                <span
                  style={{
                    fontFamily: "var(--mono)",
                    fontWeight: 600,
                    textDecoration: isTamperedRow ? "line-through" : "none",
                  }}
                >
                  {r.action}
                </span>
                <span
                  style={{
                    color: isBrokenDownstream ? "var(--red)" : "var(--ink-2)",
                  }}
                >
                  {r.agent}
                </span>
                <span
                  style={{
                    fontFamily: "var(--mono)",
                    color: isTamperedRow
                      ? "var(--red)"
                      : isBrokenDownstream
                      ? "var(--red)"
                      : "var(--ink-2)",
                    letterSpacing: 0.3,
                    fontWeight: isTamperedRow ? 700 : 500,
                  }}
                >
                  sha256:{showHash}
                </span>
                <span
                  style={{
                    width: 18,
                    height: 18,
                    borderRadius: "50%",
                    display: "inline-flex",
                    alignItems: "center",
                    justifyContent: "center",
                    background: isBrokenDownstream
                      ? "var(--red)"
                      : "var(--emerald-ink)",
                    color: "var(--paper)",
                    fontSize: 10,
                    fontWeight: 700,
                  }}
                >
                  {isBrokenDownstream ? "✕" : "✓"}
                </span>

                {isTamperedRow && (
                  <div
                    style={{
                      position: "absolute",
                      right: -6,
                      top: "50%",
                      transform: "translate(100%, -50%) rotate(-2deg)",
                      display: "flex",
                      alignItems: "center",
                      gap: 8,
                      pointerEvents: "none",
                    }}
                  >
                    <span
                      style={{
                        width: 30,
                        height: 1,
                        background: "var(--red)",
                      }}
                    />
                    <span
                      style={{
                        fontFamily: "var(--mono)",
                        fontSize: 9.5,
                        fontWeight: 700,
                        letterSpacing: 1.3,
                        color: "var(--red)",
                        border: "1px solid var(--red)",
                        padding: "3px 6px",
                        background: "var(--paper)",
                        whiteSpace: "nowrap",
                      }}
                    >
                      TAMPERED
                    </span>
                  </div>
                )}
              </div>

              {isInspecting && (
                <div
                  style={{
                    background: "var(--paper)",
                    borderTop:
                      "1px dashed " +
                      (isBrokenDownstream ? "var(--red)" : "var(--ink-3)"),
                    borderBottom:
                      i < BASE_ROWS.length - 1
                        ? "1px solid var(--ink-4)"
                        : "none",
                    padding: "12px 22px 14px 66px",
                    display: "grid",
                    gridTemplateColumns: "auto 1fr",
                    rowGap: 5,
                    columnGap: 14,
                    fontSize: 10.5,
                    color: isBrokenDownstream ? "var(--red)" : "var(--ink-2)",
                    letterSpacing: 0.4,
                  }}
                >
                  <span
                    style={{
                      color: "var(--ink-3)",
                      fontWeight: 700,
                      letterSpacing: 1.2,
                    }}
                  >
                    TIMESTAMP
                  </span>
                  <span>{r.ts} UTC</span>
                  <span
                    style={{
                      color: "var(--ink-3)",
                      fontWeight: 700,
                      letterSpacing: 1.2,
                    }}
                  >
                    PREV·HASH
                  </span>
                  <span
                    style={{
                      textDecoration: isBrokenDownstream
                        ? "line-through"
                        : "none",
                    }}
                  >
                    sha256:{r.prev}
                  </span>
                  <span
                    style={{
                      color: "var(--ink-3)",
                      fontWeight: 700,
                      letterSpacing: 1.2,
                    }}
                  >
                    VERIFY
                  </span>
                  <span style={{ fontWeight: 700 }}>
                    {isBrokenDownstream
                      ? isTamperedRow
                        ? "✕ HASH MISMATCH · payload modified after sign"
                        : "✕ PREV·HASH does not match record " +
                          String(i).padStart(2, "0")
                      : "✓ chain link OK · sha256(prev || payload) verified"}
                  </span>
                </div>
              )}
            </React.Fragment>
          );
        })}
      </div>

      <div
        style={{
          padding: "12px 22px",
          borderTop: "1.5px solid var(--ink)",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          fontSize: 10,
          color: "var(--ink-3)",
          letterSpacing: 1.3,
          fontWeight: 700,
        }}
      >
        <span>
          {inspectIdx == null
            ? "▸ CLICK ANY RECORD TO INSPECT"
            : "▾ INSPECTING RECORD " + BASE_ROWS[inspectIdx].n}
        </span>
        <span
          style={{
            color: tampered ? "var(--red)" : "var(--emerald-ink)",
          }}
        >
          {tampered ? "● MODIFICATION DETECTED" : "● ROOT: 7a5e9f06…79ae"}
        </span>
      </div>

      <div
        style={{
          position: "absolute",
          left: -34,
          bottom: 60,
          transform: "rotate(-90deg)",
          transformOrigin: "left bottom",
          fontFamily: "var(--mono)",
          fontSize: 10,
          fontWeight: 700,
          letterSpacing: 6,
          color: "var(--ink-3)",
          opacity: 0.55,
          pointerEvents: "none",
          whiteSpace: "nowrap",
        }}
      >
        EXHIBIT · INTERACTIVE
      </div>
    </div>
  );
}
