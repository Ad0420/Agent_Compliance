"use client";

/**
 * Org-wide AI agent coverage hook (Phase 4 Wave 2 PR C1).
 *
 * The Compliance page's coverage section needs a single sentence —
 * "Runtime posture covers N of M active AI agents." — plus a chip
 * strip showing each ``agent_type`` and whether it has runtime data
 * flowing.
 *
 * v1 has no dedicated org-wide endpoint; we aggregate client-side from
 * ``GET /v1/customers`` (the list) ⨯ ``GET /v1/customers/{id}/agents``
 * (the AI Coverage Matrix per customer). v1 reality is 1-3 customers
 * per org, so the parallel fan-out is bounded and cheap. A dedicated
 * ``GET /v1/organizations/me/agent-coverage`` aggregate is a follow-up
 * once customer counts grow.
 */

import { useQuery } from "@tanstack/react-query";

import {
  getCustomerAgents,
  getCustomers,
  type Coverage,
  type CoverageAgentChip,
} from "@/lib/api-client";
import type { CustomerAgentCoverage } from "@/lib/api-types";

async function fetchOrgCoverage(): Promise<Coverage> {
  // ``getCustomers()`` is the hard prerequisite — if the caller can't
  // read the customer list at all, the coverage section can't render
  // honestly. Let the error propagate so React Query surfaces it.
  const customers = await getCustomers();
  if (customers.items.length === 0) {
    return { covered: 0, detected: 0, items: [] };
  }
  // Per-customer agent fetches are best-effort. A single 403/404 (e.g.
  // for a customer with a different IAM scope) shouldn't blank the
  // page — but we still need to know whether ALL of them failed, in
  // which case React Query should bubble the error rather than show
  // a misleading "0 of 0 covered" line. ``Promise.allSettled`` lets us
  // distinguish.
  const settled = await Promise.all(
    customers.items.map((c) =>
      getCustomerAgents(c.tenant_id).then(
        (r) => ({ ok: true as const, items: r.items }),
        (err) => ({ ok: false as const, err }),
      ),
    ),
  );
  const successes = settled.filter((s) => s.ok);
  if (successes.length === 0) {
    // Every per-customer fetch failed — surface the first error rather
    // than rendering a fake "no agents" state.
    const firstFail = settled.find((s) => !s.ok);
    if (firstFail && !firstFail.ok) {
      throw firstFail.err instanceof Error
        ? firstFail.err
        : new Error("Failed to load coverage");
    }
    throw new Error("Failed to load coverage");
  }
  const agentLists: CustomerAgentCoverage[][] = successes.map(
    (s) => (s as { ok: true; items: CustomerAgentCoverage[] }).items,
  );
  // Roll up across all customers; an ``agent_type`` is "covered" if any
  // customer has runtime data flowing for it. ``detected`` is the
  // de-duplicated count of agent_types that surfaced via any source
  // (auto-discovery, declared, csv_import).
  const typeStatus = new Map<string, "covered" | "uncovered">();
  for (const list of agentLists) {
    for (const row of list) {
      if (row.status !== "active") continue;
      const current = typeStatus.get(row.agent_type);
      const next: "covered" | "uncovered" =
        row.coverage === "covered" ? "covered" : "uncovered";
      // Promote uncovered → covered if any customer's row is covered.
      if (current === "covered") continue;
      typeStatus.set(row.agent_type, next);
    }
  }
  const items: CoverageAgentChip[] = Array.from(typeStatus.entries())
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([agent_type, status]) => ({ agent_type, status }));
  const covered = items.filter((i) => i.status === "covered").length;
  return {
    covered,
    detected: items.length,
    items,
  };
}

export function useOrgCoverage() {
  return useQuery<Coverage>({
    queryKey: ["compliance", "org-coverage"],
    queryFn: fetchOrgCoverage,
    staleTime: 30_000,
  });
}
