"""Fixture 03: action_name= → action_class= (Codex X2)."""

import vera
from vera import Redactor

_REDACTOR = Redactor()


@vera.audit(action_name="loan_approve", redactor=_REDACTOR)
def approve(applicant_id, amount):
    return {"approved": True}
