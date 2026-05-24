"""Fixture 13: ``@vera.async_audit`` and bare ``@async_audit`` (Codex X2).

``@vera.gate`` unifies sync/async — the codemod renames
``async_audit`` to ``gate`` so the new decorator does the right thing
at runtime. The ``blocking=`` kwarg is left in place so it raises
loudly at runtime (gate has no such kwarg); see MIGRATION.md for the
manual cleanup step.
"""

import vera
from vera import gate


@vera.gate(action_class="sync_one")
def sync_one(x):
    return x


@gate("async_two", blocking=False)
async def async_two(y):
    return y
