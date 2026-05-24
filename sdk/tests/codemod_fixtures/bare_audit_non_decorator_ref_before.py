"""Fixture 17: non-decorator references to ``audit`` get renamed.

The import rewriter renames ``from vera import audit`` →
``from vera import gate``. Bare uses of ``audit`` outside decorator
context (e.g. ``decorated = audit('y')(fn)``) MUST also be renamed —
otherwise the rewritten module raises NameError at runtime.
"""

from vera import audit


def fn(x):
    return x


decorated = audit("y")(fn)
callback = audit
