import { PrototypeDisclaimer } from "./brand";

export function V4Footer() {
  return (
    <footer
      style={{
        padding: "0 88px",
        background: "var(--night)",
        color: "var(--night-text-2)",
      }}
    >
      <PrototypeDisclaimer tone="dark" />
    </footer>
  );
}
