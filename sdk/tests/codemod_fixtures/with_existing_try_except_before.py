"""Fixture 06 (--wrap-callsites): existing try/except — DO NOT double-wrap."""

import vera


@vera.audit("risky")
def risky(x):
    return x * 2


try:
    result = risky(5)
except Exception:
    result = 0
