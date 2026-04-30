"use client";

/**
 * `useDecideApproval()` — submit a HITL decision for a pending approval.
 *
 * The approver name is sourced from the auth provider; the view layer just
 * supplies the approval id, the decision, and an optional note.
 */

import * as React from "react";

import { decideApproval } from "@/lib/api/approvals";
import { useAuth } from "./use-auth";

interface UseDecideApprovalResult {
  decide(
    approvalId: string,
    decision: "approve" | "reject",
    note?: string,
  ): Promise<void>;
  isDeciding: boolean;
  error: Error | null;
}

export function useDecideApproval(): UseDecideApprovalResult {
  const { signedInAs } = useAuth();
  const [isDeciding, setIsDeciding] = React.useState<boolean>(false);
  const [error, setError] = React.useState<Error | null>(null);

  const decide = React.useCallback(
    async (
      approvalId: string,
      decision: "approve" | "reject",
      note?: string,
    ) => {
      setIsDeciding(true);
      setError(null);
      try {
        // Fall back to a generic label if the user isn't fully resolved
        // — the backend requires `approver`, and an empty string would
        // fail schema validation.
        const approver = signedInAs ?? "ScribeMD User";
        await decideApproval(approvalId, decision, approver, note);
      } catch (err) {
        const e = err instanceof Error ? err : new Error(String(err));
        setError(e);
        throw e;
      } finally {
        setIsDeciding(false);
      }
    },
    [signedInAs],
  );

  return { decide, isDeciding, error };
}
