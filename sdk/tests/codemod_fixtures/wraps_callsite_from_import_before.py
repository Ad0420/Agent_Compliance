"""Fixture 15 (--wrap-callsites): from-imported PendingReview / PolicyBlock.

When the user has ``from vera import audit, PendingReview,
PolicyBlock`` but no ``import vera``, the wrap-callsites transform
MUST emit unqualified ``PendingReview`` / ``PolicyBlock`` in the
except handlers — qualified ``vera.PendingReview`` would NameError
at runtime.
"""

from vera import audit, PendingReview, PolicyBlock


@audit("f")
def f(x):
    return x


res = f(1)
