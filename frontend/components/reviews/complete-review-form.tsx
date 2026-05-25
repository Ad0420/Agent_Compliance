"use client";

/**
 * CompleteReviewForm — Wave 2D PR C2.
 *
 * Right-panel action box inside the Pattern B detail layout. Reviewer
 * picks Approve or Reject, supplies their role + identifier, and
 * (required) a comment of at least 10 chars — per
 * v1-implementation-plan.md §Phase 2 line 120 + the regulation framing
 * in policy-engine-mvp.md "approval requires comment".
 *
 * "Modify" per the spec is treated as Reject-with-suggestion — the
 * backend's ReviewCompletionInput accepts only ``approve`` / ``reject``
 * (per services/reviews.py), so the Modify button submits ``reject``
 * with a sentinel prefix in the comment. The audit chain captures the
 * full text either way, so the reviewer's intent is preserved.
 *
 * Error surfacing
 * ===============
 * Per dashboard-design-system.md §Voice & copy, critical errors render
 * inline next to the action (not as a transient toast). The
 * ``isReviewerInsufficient`` / ``isAlreadyDecided`` / ``isReviewExpired``
 * helpers from use-complete-review.ts narrow the mutation error and
 * render an actionable message + (for 409/410) prompt the parent to
 * close the detail panel.
 */

import * as React from "react";
import { toast } from "sonner";

import { Textarea } from "@/components/ui/textarea";
import { Loading } from "@/components/ui/loading";
import {
  isAlreadyDecided,
  isReviewerInsufficient,
  isReviewExpired,
  useCompleteReview,
} from "@/hooks/use-complete-review";
import type { Approval, CompleteReviewInput } from "@/lib/api-types";

const MIN_NOTE_LEN = 10;
const NOTE_MAX = 2000;
const ROLE_MAX = 64;
const REVIEWER_ID_MAX = 128;
const MODIFY_NOTE_PREFIX = "[MODIFY] ";

export interface CompleteReviewFormProps {
  approval: Approval;
  /**
   * Called when the mutation returns a 409/410 so the parent can close
   * the detail panel and refresh the queue (the row is no longer valid
   * to act on).
   */
  onTerminalError?: () => void;
  /** Called on a successful 200 so the parent can collapse the panel. */
  onSuccess?: (approval: Approval) => void;
}

type Decision = "approve" | "reject" | "modify";

export function CompleteReviewForm({
  approval,
  onTerminalError,
  onSuccess,
}: CompleteReviewFormProps) {
  const mutation = useCompleteReview();

  const [reviewerRole, setReviewerRole] = React.useState("");
  const [reviewerId, setReviewerId] = React.useState("");
  const [note, setNote] = React.useState("");
  // Tracks which button the reviewer just clicked so we surface the
  // spinner on the right action and route the wire shape correctly.
  const [pendingDecision, setPendingDecision] =
    React.useState<Decision | null>(null);
  // Surfaces field-level validation errors (client-side) and inline
  // mutation errors (server-side) without disturbing the page's
  // top-level toast layer.
  const [fieldError, setFieldError] = React.useState<string | null>(null);

  const submit = (decision: Decision) => {
    setFieldError(null);

    if (!reviewerRole.trim()) {
      setFieldError("Reviewer role is required.");
      return;
    }
    if (!reviewerId.trim()) {
      setFieldError("Reviewer identifier is required.");
      return;
    }
    if (note.trim().length < MIN_NOTE_LEN) {
      setFieldError(
        `Comment is required — provide at least ${MIN_NOTE_LEN} characters explaining the decision.`,
      );
      return;
    }

    const wireDecision: "approve" | "reject" =
      decision === "approve" ? "approve" : "reject";
    const wireNote =
      decision === "modify" ? `${MODIFY_NOTE_PREFIX}${note.trim()}` : note.trim();

    const input: CompleteReviewInput = {
      decision: wireDecision,
      reviewer_role: reviewerRole.trim(),
      reviewer_id: reviewerId.trim(),
      note: wireNote,
    };

    setPendingDecision(decision);
    mutation.mutate(
      { review_id: approval.id, input },
      {
        onSuccess: (resolved) => {
          setPendingDecision(null);
          const verb =
            decision === "approve"
              ? "approved"
              : decision === "modify"
                ? "rejected with modification request"
                : "rejected";
          toast.success(`Review ${verb}.`);
          onSuccess?.(resolved);
        },
        onError: (err) => {
          setPendingDecision(null);
          if (isAlreadyDecided(err) || isReviewExpired(err)) {
            // Auto-close path: the row is no longer actionable.
            onTerminalError?.();
          }
        },
      },
    );
  };

  const err = mutation.error;
  const isBusy = mutation.isPending;

  return (
    <form
      data-slot="complete-review-form"
      data-review-id={approval.id}
      onSubmit={(e) => e.preventDefault()}
      className="space-y-4"
    >
      <FieldLabel htmlFor="reviewer-role">Reviewer role</FieldLabel>
      <input
        id="reviewer-role"
        type="text"
        value={reviewerRole}
        onChange={(e) => setReviewerRole(e.target.value)}
        maxLength={ROLE_MAX}
        autoComplete="off"
        placeholder="attending_physician"
        data-testid="complete-review-form-role"
        className="block w-full rounded-[8px] border border-[color:var(--ink-4)] bg-[color:var(--paper)] px-3 py-2 text-[14px] text-[color:var(--ink)] placeholder:text-[color:var(--ink-3)] focus-visible:outline-none focus-visible:border-[color:var(--ink)]"
      />

      <FieldLabel htmlFor="reviewer-id">Reviewer ID</FieldLabel>
      <input
        id="reviewer-id"
        type="text"
        value={reviewerId}
        onChange={(e) => setReviewerId(e.target.value)}
        maxLength={REVIEWER_ID_MAX}
        autoComplete="off"
        placeholder="alice@hospital.example"
        data-testid="complete-review-form-reviewer-id"
        className="block w-full rounded-[8px] border border-[color:var(--ink-4)] bg-[color:var(--paper)] px-3 py-2 text-[14px] text-[color:var(--ink)] placeholder:text-[color:var(--ink-3)] focus-visible:outline-none focus-visible:border-[color:var(--ink)]"
      />

      <Textarea
        label="Comment"
        value={note}
        onChange={(e) => setNote(e.target.value)}
        maxLength={NOTE_MAX}
        helpText={`Required. Minimum ${MIN_NOTE_LEN} characters — surfaces on the audit chain.`}
        placeholder="Why are you approving / rejecting this decision?"
        data-testid="complete-review-form-note"
      />

      {fieldError ? (
        <p
          role="alert"
          data-testid="complete-review-form-field-error"
          className="rounded-[6px] bg-[color:var(--brick-bg)] px-3 py-2 text-[13px] text-[color:var(--brick)]"
        >
          {fieldError}
        </p>
      ) : null}

      {err && isReviewerInsufficient(err) ? (
        <p
          role="alert"
          data-testid="complete-review-form-error-insufficient-role"
          className="rounded-[6px] bg-[color:var(--brick-bg)] px-3 py-2 text-[13px] text-[color:var(--brick)]"
        >
          Your role &lsquo;{err.detail.reviewer_role}&rsquo; is insufficient.
          This decision requires &lsquo;
          {err.detail.required_role ?? "an authorized role"}&rsquo;.
        </p>
      ) : null}

      {err && isAlreadyDecided(err) ? (
        <p
          role="alert"
          data-testid="complete-review-form-error-already-decided"
          className="rounded-[6px] bg-[color:var(--paper-3)] px-3 py-2 text-[13px] text-[color:var(--ink-2)]"
        >
          This review has already been decided.
        </p>
      ) : null}

      {err && isReviewExpired(err) ? (
        <p
          role="alert"
          data-testid="complete-review-form-error-expired"
          className="rounded-[6px] bg-[color:var(--paper-3)] px-3 py-2 text-[13px] text-[color:var(--ink-2)]"
        >
          This review has expired and cannot be completed.
        </p>
      ) : null}

      {err &&
      !isReviewerInsufficient(err) &&
      !isAlreadyDecided(err) &&
      !isReviewExpired(err) ? (
        // TS narrows ``err`` to ``never`` after the three guards (the
        // guards consume the full ApiError variant); the runtime value
        // is still an ApiError — pull the message via a cast so the
        // generic error case stays informative for unexpected statuses
        // (e.g. 500, 502).
        <p
          role="alert"
          data-testid="complete-review-form-error-generic"
          className="rounded-[6px] bg-[color:var(--brick-bg)] px-3 py-2 text-[13px] text-[color:var(--brick)]"
        >
          {(mutation.error as Error | null)?.message ?? "Something went wrong."}
        </p>
      ) : null}

      <div className="grid grid-cols-3 gap-2 pt-2">
        <ActionButton
          variant="approve"
          onClick={() => submit("approve")}
          loading={isBusy && pendingDecision === "approve"}
          disabled={isBusy}
          testId="complete-review-form-approve"
        >
          Approve
        </ActionButton>
        <ActionButton
          variant="modify"
          onClick={() => submit("modify")}
          loading={isBusy && pendingDecision === "modify"}
          disabled={isBusy}
          testId="complete-review-form-modify"
        >
          Modify
        </ActionButton>
        <ActionButton
          variant="reject"
          onClick={() => submit("reject")}
          loading={isBusy && pendingDecision === "reject"}
          disabled={isBusy}
          testId="complete-review-form-reject"
        >
          Reject
        </ActionButton>
      </div>
    </form>
  );
}

interface FieldLabelProps {
  htmlFor: string;
  children: React.ReactNode;
}
function FieldLabel({ htmlFor, children }: FieldLabelProps) {
  return (
    <label
      htmlFor={htmlFor}
      className="mb-1.5 block text-[12px] font-medium uppercase tracking-[0.06em] text-[color:var(--ink-2)]"
    >
      {children}
    </label>
  );
}

interface ActionButtonProps {
  variant: "approve" | "modify" | "reject";
  onClick: () => void;
  loading: boolean;
  disabled: boolean;
  testId: string;
  children: React.ReactNode;
}
function ActionButton({
  variant,
  onClick,
  loading,
  disabled,
  testId,
  children,
}: ActionButtonProps) {
  // Approve = primary ink; Modify = amber; Reject = brick. All three
  // share the same shape so the row reads as a single decision band.
  const variantClasses: Record<ActionButtonProps["variant"], string> = {
    approve:
      "bg-[color:var(--ink)] text-[color:var(--paper)] hover:bg-[color:var(--ink-hover)]",
    modify:
      "bg-[color:var(--amber-bg)] text-[color:var(--amber)] hover:bg-[color:var(--amber-bg)]/80 border border-[color:var(--amber)]/30",
    reject:
      "bg-[color:var(--brick-bg)] text-[color:var(--brick)] hover:bg-[color:var(--brick-bg)]/80 border border-[color:var(--brick)]/30",
  };

  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      data-testid={testId}
      className={
        "inline-flex h-9 items-center justify-center gap-2 rounded-[10px] px-4 " +
        "text-[14px] font-medium transition-colors " +
        "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 " +
        "focus-visible:outline-[color:var(--ink)] " +
        "disabled:cursor-not-allowed disabled:opacity-50 " +
        variantClasses[variant]
      }
    >
      {loading ? <Loading.Spinner size={14} label="Submitting" /> : null}
      <span>{children}</span>
    </button>
  );
}
