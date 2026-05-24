"""Fixture 07 (--wrap-callsites): bare call gets wrapped."""

import vera


@vera.audit("approve_loan")
def approve_loan(applicant_id):
    return {"approved": True}


result = approve_loan("a-123")
