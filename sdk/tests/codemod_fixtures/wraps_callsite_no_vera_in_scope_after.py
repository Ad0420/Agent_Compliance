"""Fixture 16 (--wrap-callsites): vera unbound + PendingReview unbound.

When neither ``vera`` nor ``PendingReview`` / ``PolicyBlock`` are in
scope, the wrap-callsites transform must inject a fresh
``from vera import PendingReview, PolicyBlock`` after the last
existing import and use unqualified names in the except handlers.
"""

from vera import gate
from vera import PendingReview, PolicyBlock


@gate("f")
def f(x):
    return x


try:
    res = f(1)
except PendingReview as pending:
    # TODO(audit-to-gate codemod): handle PendingReview (review_id=pending.review_id)
    raise
except PolicyBlock as blocked:
    # TODO(audit-to-gate codemod): handle PolicyBlock (reason=blocked.reason)
    raise
