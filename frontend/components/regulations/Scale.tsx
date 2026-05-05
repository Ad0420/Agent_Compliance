import type { ScalePayload } from "@/lib/regulations-data";

// Stub component for PR 1. Real variant rendering lands in PR 3.
// This file exists so PR 2 (DossierCard re-skin) can wire the slot.

export type { ScalePayload };

export function Scale({ payload }: { payload: ScalePayload }) {
  // Intentional placeholder. Each variant renders a labeled empty box so the
  // dossier card layout has something to slot during Wave 2 development.
  return (
    <div data-scale-kind={payload.kind} aria-label={`Scale module · ${payload.kind} · placeholder`} />
  );
}
