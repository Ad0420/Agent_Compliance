"""Fixture 05: ``from vera import audit as a`` — alias preserved.

Alias is renamed AT THE IMPORT (so the binding now points at
``vera.gate``) but the local references to ``a`` are left alone.
"""

from vera import gate as a


@a("hiring_decision")
def decide(candidate_id):
    return {"hire": True}
