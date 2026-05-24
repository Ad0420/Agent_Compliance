"""Fixture 07 (--wrap-callsites): bare call gets wrapped."""

import vera


@vera.gate("approve_loan")
def approve_loan(applicant_id):
    return {"approved": True}


try:
    result = approve_loan("a-123")
except vera.PendingReview as pending:
    # TODO(audit-to-gate codemod): handle PendingReview (review_id=pending.review_id)
    raise
except vera.PolicyBlock as blocked:
    # TODO(audit-to-gate codemod): handle PolicyBlock (reason=blocked.reason)
    raise
