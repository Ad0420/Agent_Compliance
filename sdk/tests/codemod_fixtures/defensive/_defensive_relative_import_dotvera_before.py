"""Defensive fixture: ``from .vera import audit`` is NOT rewritten.

A relative import to a sibling submodule named ``vera`` is unrelated
to the Vera SDK (some codebases have a local ``vera`` re-export
wrapper). The codemod's relative-import guard skips these — output
is byte-equal to input.
"""

from .vera import audit


@audit("x")
def f():
    return None
