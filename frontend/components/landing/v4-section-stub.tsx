export function V4SectionStub({
  tag,
  label,
  caption,
  minHeight = 320,
}: {
  tag: string;
  label: string;
  caption: string;
  minHeight?: number;
}) {
  return (
    <section style={{ padding: "120px 88px" }}>
      <div
        className="imgslot"
        style={{
          minHeight,
          borderRadius: 14,
        }}
      >
        <span className="imgslot__tag">{tag}</span>
        <div className="imgslot__body">
          <span
            style={{
              fontFamily: "var(--mono)",
              fontSize: 12,
              letterSpacing: 1.4,
              fontWeight: 700,
              color: "var(--ink-2)",
            }}
          >
            {label}
          </span>
        </div>
        <span className="imgslot__caption">{caption}</span>
      </div>
    </section>
  );
}
