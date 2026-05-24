"""Defensive fixture: ``@try_decorator(vera.audit('x'))`` is NOT rewritten.

Known limitation. The codemod only rewrites decorator-shaped Calls
whose direct func is ``vera.audit`` / ``audit``. When ``vera.audit(...)``
is passed as an ARGUMENT to another decorator factory the rewrite
does not fire (we don't recurse into decorator-factory arguments
because we can't tell whether the factory consumes the call or just
passes it through).

If your codebase uses this shape, hand-edit the inner call to
``vera.gate(...)`` after running the codemod.
"""

import vera


def try_decorator(d):
    return d


@try_decorator(vera.audit("x"))
def f():
    return None
