"use client";

import type { CSSProperties } from "react";
import { Easing, Stage, clamp, useTime } from "./animations";

const HERO_W = 1600;
const HERO_H = 900;
const HERO_DURATION = 12;

const HC = {
  paper: "#F3EFE7",
  paper2: "#EBE6DB",
  ink: "#15140F",
  ink2: "#3A372E",
  ink3: "#6A6557",
  ink4: "#D9D2C2",
  emerald: "#0A7A4F",
  emeraldFaint: "rgba(10,122,79,0.10)",
  amber: "#9A5D12",
  red: "#8C2A1F",
  sans: "'Inter Tight', -apple-system, system-ui, sans-serif",
  mono: "'JetBrains Mono', ui-monospace, monospace",
  serif: "'Newsreader', Georgia, serif",
};

interface Station {
  x: number;
  label: string;
  sub: string;
  kind: "source" | "node" | "sink";
}

const STATIONS: Station[] = [
  { x: 200, label: "AGENT", sub: "decision-agent", kind: "source" },
  { x: 480, label: "INTERCEPT", sub: "DB trigger", kind: "node" },
  { x: 740, label: "HASH", sub: "sha-256", kind: "node" },
  { x: 1000, label: "CHAIN", sub: "linked + ordered", kind: "node" },
  { x: 1260, label: "SIGN", sub: "AWS KMS", kind: "node" },
  { x: 1480, label: "STORE", sub: "WORM", kind: "sink" },
];
const TRACK_Y = 410;

function HeroBackground() {
  const corners: CSSProperties[] = [
    { top: 24, left: 24 },
    { top: 24, right: 24 },
    { bottom: 24, left: 24 },
    { bottom: 24, right: 24 },
  ];
  return (
    <>
      <div
        style={{
          position: "absolute",
          inset: 0,
          background: HC.paper,
        }}
      />
      <div
        style={{
          position: "absolute",
          inset: 0,
          backgroundImage:
            "linear-gradient(" +
            HC.ink4 +
            " 1px, transparent 1px)," +
            "linear-gradient(90deg, " +
            HC.ink4 +
            " 1px, transparent 1px)",
          backgroundSize: "40px 40px",
          opacity: 0.35,
        }}
      />
      <div
        style={{
          position: "absolute",
          inset: 0,
          background:
            "radial-gradient(ellipse at 50% 55%, rgba(243,239,231,0) 0%, " +
            HC.paper +
            " 70%)",
        }}
      />

      {corners.map((p, i) => (
        <div
          key={i}
          style={{
            position: "absolute",
            ...p,
            width: 14,
            height: 14,
            borderTop: p.top != null ? "1.5px solid " + HC.ink : "none",
            borderBottom: p.bottom != null ? "1.5px solid " + HC.ink : "none",
            borderLeft: p.left != null ? "1.5px solid " + HC.ink : "none",
            borderRight: p.right != null ? "1.5px solid " + HC.ink : "none",
          }}
        />
      ))}

      <div
        style={{
          position: "absolute",
          top: 56,
          left: 80,
          fontFamily: HC.mono,
          fontSize: 13,
          fontWeight: 700,
          letterSpacing: 1.6,
          color: HC.ink3,
        }}
      >
        FIG. 01 · RUNTIME TRUST PIPELINE
      </div>
      <div
        style={{
          position: "absolute",
          top: 56,
          right: 80,
          fontFamily: HC.mono,
          fontSize: 13,
          fontWeight: 700,
          letterSpacing: 1.6,
          color: HC.ink3,
        }}
      >
        v1.4 · 6 STAGES · ~8ms
      </div>

      <div
        style={{
          position: "absolute",
          bottom: 52,
          left: 80,
          fontFamily: HC.mono,
          fontSize: 12,
          fontWeight: 700,
          letterSpacing: 1.6,
          color: HC.ink3,
        }}
      >
        EVERY AGENT ACTION → HASHED → CHAINED → SIGNED → SEALED
      </div>
      <div
        style={{
          position: "absolute",
          bottom: 52,
          right: 80,
          fontFamily: HC.mono,
          fontSize: 12,
          fontWeight: 700,
          letterSpacing: 1.6,
          color: HC.emerald,
        }}
      >
        ● LIVE
      </div>
    </>
  );
}

function HeroTrack() {
  return (
    <>
      <div
        style={{
          position: "absolute",
          left: STATIONS[0].x,
          right: HERO_W - STATIONS[STATIONS.length - 1].x,
          top: TRACK_Y - 1,
          height: 2,
          background: HC.ink,
          opacity: 0.8,
        }}
      />
      {STATIONS.map((s, i) => (
        <div
          key={i}
          style={{
            position: "absolute",
            left: s.x,
            top: TRACK_Y - 14,
            width: 2,
            height: 28,
            background: HC.ink,
            transform: "translateX(-1px)",
          }}
        />
      ))}

      {STATIONS.map((s, i) => (
        <div
          key={"l-" + i}
          style={{
            position: "absolute",
            left: s.x,
            top: TRACK_Y + 36,
            transform: "translateX(-50%)",
            textAlign: "center",
            fontFamily: HC.mono,
            fontSize: 13,
            fontWeight: 700,
            letterSpacing: 1.4,
            color: HC.ink,
          }}
        >
          <div>{s.label}</div>
          <div
            style={{
              marginTop: 4,
              fontWeight: 500,
              color: HC.ink3,
              letterSpacing: 1,
              fontSize: 11,
            }}
          >
            {s.sub}
          </div>
          <div
            style={{
              marginTop: 6,
              fontFamily: HC.mono,
              fontSize: 10,
              color: HC.ink3,
            }}
          >
            {String(i).padStart(2, "0")}
          </div>
        </div>
      ))}

      {STATIONS.map((s, i) => {
        if (i === 0 || i === STATIONS.length - 1) return null;
        const dt = ["+0.4ms", "+1.2ms", "+2.1ms", "+5.8ms"][i - 1];
        return (
          <div
            key={"t-" + i}
            style={{
              position: "absolute",
              left: s.x,
              top: TRACK_Y - 56,
              transform: "translateX(-50%)",
              fontFamily: HC.mono,
              fontSize: 11,
              fontWeight: 600,
              color: HC.ink3,
              letterSpacing: 1,
            }}
          >
            {dt}
          </div>
        );
      })}
    </>
  );
}

function HeroTitle() {
  return (
    <div
      style={{
        position: "absolute",
        top: 120,
        left: 80,
        right: 80,
        display: "flex",
        justifyContent: "space-between",
        alignItems: "flex-start",
        gap: 60,
      }}
    >
      <div>
        <div
          style={{
            fontFamily: HC.serif,
            fontStyle: "italic",
            fontSize: 26,
            color: HC.ink2,
            marginBottom: 12,
            fontWeight: 400,
          }}
        >
          One agent action,
        </div>
        <div
          style={{
            fontFamily: HC.sans,
            fontSize: 56,
            fontWeight: 700,
            letterSpacing: "-0.035em",
            lineHeight: 1.0,
            color: HC.ink,
            maxWidth: 760,
          }}
        >
          hashed, chained, and
          <br />
          signed before it lands.
        </div>
      </div>
      <div
        style={{
          textAlign: "right",
          fontFamily: HC.mono,
          fontSize: 13,
          color: HC.ink2,
          lineHeight: 1.6,
        }}
      >
        <div
          style={{
            fontWeight: 700,
            color: HC.ink,
            letterSpacing: 1.2,
          }}
        >
          MEDIAN OVERHEAD
        </div>
        <div
          style={{
            fontFamily: HC.sans,
            fontSize: 56,
            fontWeight: 700,
            letterSpacing: "-0.04em",
            color: HC.emerald,
            lineHeight: 1,
            marginTop: 8,
          }}
        >
          8<span style={{ fontSize: 28, marginLeft: 4 }}>ms</span>
        </div>
        <div style={{ marginTop: 8, color: HC.ink3 }}>p50 · production</div>
      </div>
    </div>
  );
}

function FlowPacket() {
  const time = useTime();
  const cycle = HERO_DURATION;
  const t = time % cycle;
  const travelStart = 1.5;
  const travelEnd = 9.5;
  const travelP = clamp((t - travelStart) / (travelEnd - travelStart), 0, 1);

  const xStart = STATIONS[0].x;
  const xEnd = STATIONS[STATIONS.length - 1].x;
  const x = xStart + (xEnd - xStart) * Easing.easeInOutCubic(travelP);

  const stationIdx = STATIONS.reduce(
    (acc, s, i) =>
      Math.abs(s.x - x) < Math.abs(STATIONS[acc].x - x) ? i : acc,
    0,
  );

  let label = "decide(loan_4821)";
  let mono = false;
  if (stationIdx >= 1) {
    label = "decide(loan_4821)";
    mono = true;
  }
  if (stationIdx >= 2) {
    label = "sha256:7a5e9f06…79ae";
    mono = true;
  }
  if (stationIdx >= 3) {
    label = "#3812 ← #3811 ← #3810";
    mono = true;
  }
  if (stationIdx >= 4) {
    label = "kms-sig: MEUCIQDk3R4o…";
    mono = true;
  }
  if (stationIdx >= 5) {
    label = "WORM ✓ sealed";
    mono = false;
  }

  const visible = t >= travelStart - 0.2 && t <= travelEnd + 0.6;
  if (!visible) return null;

  let opacity = 1;
  if (t < travelStart) opacity = (t - (travelStart - 0.2)) / 0.2;
  if (t > travelEnd) opacity = 1 - (t - travelEnd) / 0.6;
  opacity = clamp(opacity, 0, 1);

  return (
    <>
      <div
        style={{
          position: "absolute",
          left: xStart,
          top: TRACK_Y - 1,
          width: x - xStart,
          height: 2,
          background:
            "linear-gradient(90deg, transparent 0%, " + HC.emerald + " 100%)",
          opacity: 0.5,
        }}
      />

      <div
        style={{
          position: "absolute",
          left: x,
          top: TRACK_Y,
          transform: "translate(-50%, -50%)",
          opacity,
        }}
      >
        <div
          style={{
            background: stationIdx >= 5 ? HC.ink : HC.paper,
            color: stationIdx >= 5 ? HC.paper : HC.ink,
            border: "1.5px solid " + HC.ink,
            padding: "10px 18px",
            fontFamily: mono ? HC.mono : HC.sans,
            fontSize: mono ? 14 : 16,
            fontWeight: mono ? 600 : 700,
            letterSpacing: mono ? 0.3 : "-0.01em",
            whiteSpace: "nowrap",
            boxShadow:
              "0 8px 24px rgba(21,20,15,0.18), 0 1px 0 rgba(21,20,15,1)",
            borderRadius: 4,
          }}
        >
          {label}
        </div>
        <div
          style={{
            position: "absolute",
            inset: -8,
            background:
              "radial-gradient(ellipse, " +
              HC.emeraldFaint +
              " 0%, transparent 70%)",
            pointerEvents: "none",
            zIndex: -1,
          }}
        />
      </div>
    </>
  );
}

function StationStamps() {
  const time = useTime();
  const t = time % HERO_DURATION;
  const travelStart = 1.5;
  const travelEnd = 9.5;
  const travelP = clamp((t - travelStart) / (travelEnd - travelStart), 0, 1);
  const xStart = STATIONS[0].x;
  const xEnd = STATIONS[STATIONS.length - 1].x;
  const packetX = xStart + (xEnd - xStart) * Easing.easeInOutCubic(travelP);

  return (
    <>
      {STATIONS.map((s, i) => {
        const passed = packetX >= s.x - 4;
        const sinceArrival = passed
          ? clamp((packetX - (s.x - 4)) / 60, 0, 1)
          : 0;
        const ringScale = 1 + 0.6 * (1 - sinceArrival);
        const ringOpacity = passed ? 0.7 * (1 - sinceArrival) : 0;
        const isSink = i === STATIONS.length - 1;
        const isSource = i === 0;

        return (
          <div
            key={"s-" + i}
            style={{
              position: "absolute",
              left: s.x,
              top: TRACK_Y,
              transform: "translate(-50%, -50%)",
            }}
          >
            <div
              style={{
                width: isSink || isSource ? 22 : 16,
                height: isSink || isSource ? 22 : 16,
                borderRadius: isSink ? 2 : "50%",
                background: passed ? HC.emerald : HC.paper,
                border: "1.5px solid " + (passed ? HC.emerald : HC.ink),
                transition: "background 80ms linear",
                boxShadow: passed ? "0 0 0 4px " + HC.emeraldFaint : "none",
              }}
            />
            {passed && (
              <div
                style={{
                  position: "absolute",
                  left: "50%",
                  top: "50%",
                  width: 30,
                  height: 30,
                  marginLeft: -15,
                  marginTop: -15,
                  borderRadius: "50%",
                  border: "1.5px solid " + HC.emerald,
                  transform: "scale(" + ringScale + ")",
                  opacity: ringOpacity,
                }}
              />
            )}
          </div>
        );
      })}
    </>
  );
}

interface LedgerRow {
  n: string;
  a: string;
  d: string;
  h: string;
  state: string;
}

function EvidenceLedger() {
  const time = useTime();
  const t = time % HERO_DURATION;

  const rowAppearTimes = [2.3, 3.8, 5.3, 6.8, 8.3];
  const rows: LedgerRow[] = [
    {
      n: "01",
      a: "intercepted",
      d: "0.4 ms",
      h: "decide(loan_4821)",
      state: "ok",
    },
    {
      n: "02",
      a: "hashed",
      d: "0.8 ms",
      h: "sha256:7a5e9f06…79ae",
      state: "ok",
    },
    {
      n: "03",
      a: "chained",
      d: "0.9 ms",
      h: "prev:8f7c2d9b…3d91",
      state: "ok",
    },
    {
      n: "04",
      a: "signed",
      d: "3.7 ms",
      h: "kms:MEUCIQDk3R4o…",
      state: "ok",
    },
    {
      n: "05",
      a: "WORM-stored",
      d: "2.2 ms",
      h: "s3://vera/loans/…",
      state: "ok",
    },
  ];

  return (
    <div
      style={{
        position: "absolute",
        left: 40,
        right: 40,
        bottom: 88,
        border: "1.5px solid " + HC.ink,
        background: HC.paper2,
        padding: "16px 28px 18px",
        borderRadius: 6,
        boxShadow: "0 1px 0 rgba(21,20,15,0.06)",
      }}
    >
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "baseline",
          marginBottom: 10,
          fontFamily: HC.mono,
          fontSize: 11,
          color: HC.ink3,
          letterSpacing: 1.4,
          fontWeight: 700,
        }}
      >
        <span>EVIDENCE LEDGER · loan_4821</span>
        <span>5 RECORDS · sha256-CHAINED · KMS-VERIFIED</span>
      </div>
      <div style={{ height: 1, background: HC.ink4, marginBottom: 6 }} />
      <div style={{ display: "flex", flexDirection: "column", gap: 0 }}>
        {rows.map((r, i) => {
          const visible = t >= rowAppearTimes[i];
          const fade = visible
            ? clamp((t - rowAppearTimes[i]) / 0.4, 0, 1)
            : 0;
          return (
            <div
              key={r.n}
              style={{
                display: "grid",
                gridTemplateColumns: "60px 160px 100px 1fr 30px",
                alignItems: "center",
                gap: 16,
                padding: "9px 0",
                borderBottom:
                  i < rows.length - 1 ? "1px solid " + HC.ink4 : "none",
                opacity: fade,
                transform: "translateY(" + 8 * (1 - fade) + "px)",
              }}
            >
              <span
                style={{
                  fontFamily: HC.mono,
                  fontWeight: 700,
                  fontSize: 12,
                  color: HC.ink3,
                }}
              >
                {r.n}
              </span>
              <span
                style={{
                  fontFamily: HC.sans,
                  fontWeight: 600,
                  fontSize: 14,
                }}
              >
                {r.a}
              </span>
              <span
                style={{
                  fontFamily: HC.mono,
                  fontSize: 12,
                  color: HC.ink3,
                }}
              >
                {r.d}
              </span>
              <span
                style={{
                  fontFamily: HC.mono,
                  fontSize: 13,
                  color: HC.ink2,
                }}
              >
                {r.h}
              </span>
              <span
                style={{
                  width: 20,
                  height: 20,
                  borderRadius: "50%",
                  background: HC.emerald,
                  color: HC.paper,
                  display: "inline-flex",
                  alignItems: "center",
                  justifyContent: "center",
                  fontWeight: 700,
                  fontSize: 11,
                }}
              >
                ✓
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function FinalStamp() {
  const time = useTime();
  const t = time % HERO_DURATION;
  const start = 8.6;
  if (t < start) return null;
  const p = clamp((t - start) / 0.6, 0, 1);
  const scale = 0.6 + 0.4 * Easing.easeOutBack(p);
  const opacity = clamp(p * 1.4, 0, 1);

  return (
    <div
      style={{
        position: "absolute",
        left: STATIONS[STATIONS.length - 1].x + 70,
        top: TRACK_Y - 10,
        transform:
          "translate(-50%, -50%) rotate(-8deg) scale(" + scale + ")",
        opacity,
        pointerEvents: "none",
      }}
    >
      <div
        style={{
          border: "2px solid " + HC.amber,
          background: "rgba(154,93,18,0.08)",
          color: HC.amber,
          padding: "8px 14px",
          fontFamily: HC.mono,
          fontSize: 13,
          fontWeight: 700,
          letterSpacing: 1.6,
          borderRadius: 2,
        }}
      >
        SIGNED · SEALED
      </div>
    </div>
  );
}

function LoopMeta() {
  const time = useTime();
  const t = time % HERO_DURATION;
  return (
    <div
      style={{
        position: "absolute",
        top: 56,
        left: "50%",
        transform: "translateX(-50%)",
        fontFamily: HC.mono,
        fontSize: 11,
        color: HC.ink3,
        letterSpacing: 1.4,
        fontWeight: 700,
      }}
    >
      T+{t.toFixed(2)}s · LOOP
    </div>
  );
}

function HeroScene() {
  return (
    <>
      <HeroBackground />
      <HeroTitle />
      <LoopMeta />
      <HeroTrack />
      <StationStamps />
      <FlowPacket />
      <FinalStamp />
      <EvidenceLedger />
    </>
  );
}

export function HeroAnimation() {
  return (
    <div
      className="hero-anim-host"
      style={{
        width: "100%",
        aspectRatio: "16/9",
        position: "relative",
        overflow: "hidden",
        background: HC.paper,
      }}
    >
      <Stage
        width={HERO_W}
        height={HERO_H}
        duration={HERO_DURATION}
        loop
        autoplay
        background={HC.paper}
      >
        <HeroScene />
      </Stage>
    </div>
  );
}
