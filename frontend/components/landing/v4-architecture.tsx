import { V4SectionHeader } from "./v4-section-header";
import { TrustPipelineDiagram } from "./v4-trust-pipeline-diagram";

export function V4Architecture() {
  return (
    <section style={{ padding: "120px 88px 0" }}>
      <V4SectionHeader
        kicker="ARCHITECTURE"
        title={
          <>
            Four layers.
            <br />
            <span style={{ color: "var(--ink-2)" }}>
              Each one a fence regulators recognize.
            </span>
          </>
        }
        sub="No black boxes. Each layer maps to a control auditors already know how to verify — so you don't have to teach them a new vocabulary."
      />
      <TrustPipelineDiagram />
    </section>
  );
}
