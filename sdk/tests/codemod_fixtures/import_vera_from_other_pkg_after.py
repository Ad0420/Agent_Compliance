"""Fixture 14: ``from myproject import vera`` binds an unrelated symbol.

The codemod must NOT touch ``vera.audit(...)`` references in this
file — they refer to a user module that happens to be named ``vera``,
not the Vera SDK. Output is byte-equal to input.
"""

from myproject import vera


@vera.audit("compute")
def compute(x):
    return x


vera.init(api_key="k")
