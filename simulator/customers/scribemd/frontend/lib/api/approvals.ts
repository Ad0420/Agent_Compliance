/**
 * Approvals endpoint — wakes a paused workflow with a physician decision.
 */

import { request } from "./client";
import type { DecideApprovalResponse } from "./types";

/**
 * Submit a HITL decision for a pending approval.
 *
 * The backend forwards the call into the simulator's `physician_callback`,
 * which resumes `run_encounter`. The terminal event arrives shortly after on
 * the SSE stream — callers should not block on this returning to know the
 * workflow finished.
 *
 * @param approvalId  Vera approval id surfaced via the `approval_requested` SSE event.
 * @param decision    `"approve"` or `"reject"`.
 * @param approver    Display name to attribute the decision to (defaults to the signed-in user).
 * @param note        Free-form physician note. Optional.
 *
 * Throws `ApiError(404)` when the approval has already been resolved or
 * never reached the gate.
 */
export async function decideApproval(
  approvalId: string,
  decision: "approve" | "reject",
  approver: string,
  note?: string,
): Promise<DecideApprovalResponse> {
  return request<DecideApprovalResponse>(
    `/api/approvals/${encodeURIComponent(approvalId)}/decide`,
    {
      method: "POST",
      body: {
        decision,
        approver,
        note: note ?? null,
      },
    },
  );
}
