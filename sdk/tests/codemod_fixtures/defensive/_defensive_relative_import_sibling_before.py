"""Defensive fixture: ``from . import audit`` is NOT rewritten.

A sibling-package import binding a symbol named ``audit`` is
unrelated to the Vera SDK. The codemod must leave it alone — output
is byte-equal to input.
"""

from . import audit


@audit("x")
def f():
    return None
