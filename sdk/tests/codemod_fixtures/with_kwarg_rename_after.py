"""Fixture 03: action_name= → action_class= (Codex X2)."""

import vera
from vera import Redactor

_REDACTOR = Redactor()


@vera.gate(action_class="loan_approve", redactor=_REDACTOR)
def approve(applicant_id, amount):
    return {"approved": True}
