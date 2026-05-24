"""Fixture 15 (--wrap-callsites): from-imported PendingReview / PolicyBlock.

When the user has ``from vera import audit, PendingReview,
PolicyBlock`` but no ``import vera``, the wrap-callsites transform
MUST emit unqualified ``PendingReview`` / ``PolicyBlock`` in the
except handlers — qualified ``vera.PendingReview`` would NameError
at runtime.
"""

from vera import gate, PendingReview, PolicyBlock


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
