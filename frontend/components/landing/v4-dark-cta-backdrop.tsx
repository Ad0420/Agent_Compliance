type Crosshair = {
  top?: number;
  left?: number;
  right?: number;
  bottom?: number;
};

const HASHES: string[] = [
  "7a5e9f06d2c41b",
  "8f7c2d9b6e4a1c",
  "1d9f7b2eaa5cab",
  "a91e0c4588421f",
  "d93c9c020011fe",
  "f706a2b4c1880b",
];

const CROSSHAIRS: Crosshair[] = [
  { top: 24, left: 24 },
  { top: 24, right: 24 },
  { bottom: 24, left: 24 },
  { bottom: 24, right: 24 },
];

export function DarkCtaBackdrop() {
  const rows = Array.from({ length: 14 });
  return (
    <div
      style={{
        position: "absolute",
        inset: 0,
        overflow: "hidden",
        pointerEvents: "none",
      }}
    >
      <div
        style={{
          position: "absolute",
          right: -40,
          top: 60,
          bottom: 0,
          left: "40%",
          opacity: 0.18,
          fontFamily: "var(--mono)",
          fontSize: 12,
          lineHeight: 1.9,
          color: "#F3EFE7",
          whiteSpace: "nowrap",
          letterSpacing: 0.4,
        }}
      >
        {rows.map((_, i) => (
          <div key={i} style={{ opacity: 1 - i * 0.05 }}>
            {HASHES.map((h, j) => (
              <span key={j} style={{ marginRight: 28 }}>
                <span style={{ color: "#0A7A4F" }}>✓</span>{" "}
                sha256:{h}…
                {(j + i).toString(16).padStart(2, "0")}
                {((i * 7 + j) % 16).toString(16)}
                {((i * 13 + j * 3) % 16).toString(16)}
              </span>
            ))}
          </div>
        ))}
      </div>

      <div
        style={{
          position: "absolute",
          right: "8%",
          top: 0,
          bottom: 0,
          width: 1,
          background:
            "linear-gradient(180deg, transparent 0%, rgba(10,122,79,0.45) 50%, transparent 100%)",
        }}
      />

      {CROSSHAIRS.map((p, i) => (
        <div
          key={i}
          style={{
            position: "absolute",
            ...p,
            width: 10,
            height: 10,
            borderTop:
              p.top != null ? "1px solid rgba(243,239,231,0.25)" : "none",
            borderBottom:
              p.bottom != null ? "1px solid rgba(243,239,231,0.25)" : "none",
            borderLeft:
              p.left != null ? "1px solid rgba(243,239,231,0.25)" : "none",
            borderRight:
              p.right != null ? "1px solid rgba(243,239,231,0.25)" : "none",
          }}
        />
      ))}
    </div>
  );
}
