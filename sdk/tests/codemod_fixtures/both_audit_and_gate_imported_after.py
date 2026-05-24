"""Fixture 18: ``from vera import audit, gate`` collapses to single gate.

When both names are already imported, the codemod must not produce
``from vera import gate, gate`` (a SyntaxError-free but semantically
malformed alias list). Drop the ``audit`` entry entirely.
"""

from vera import gate


@gate("a")
def a():
    pass


@gate("b")
def b():
    pass
