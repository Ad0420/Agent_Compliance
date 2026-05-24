"""Fixture 16 (--wrap-callsites): vera unbound + PendingReview unbound.

When neither ``vera`` nor ``PendingReview`` / ``PolicyBlock`` are in
scope, the wrap-callsites transform must inject a fresh
``from vera import PendingReview, PolicyBlock`` after the last
existing import and use unqualified names in the except handlers.
"""

from vera import audit


@audit("f")
def f(x):
    return x


res = f(1)
