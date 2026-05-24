"""Vera SDK codemods (Phase 1 PR 9 / Stream D8).

Mechanical source rewrites for the v1 ``@vera.audit`` → ``@vera.gate``
rename. Driven by `libcst` so existing formatting / comments /
docstrings are preserved byte-for-byte where the codemod doesn't
intentionally touch them — `ast` would round-trip through a re-print
and lose every blank line and comment.

The public surface is :func:`migrate_source` and :func:`migrate_file`,
plus the CLI subcommand wired into :mod:`vera.cli` as
``vera codemod audit-to-gate``.

See ``sdk/MIGRATION.md`` for the human-readable migration guide and
the list of transformations this codemod automates.
"""

from __future__ import annotations

try:
    from .audit_to_gate import (
        CODEMOD_OPT_OUT_DIRECTIVE,
        MigrationOptions,
        MigrationResult,
        iter_python_files,
        make_diff,
        migrate_file,
        migrate_source,
    )
except ImportError as _exc:  # pragma: no cover — depends on install shape
    # LibCST is the only transitive dependency for the codemod. If it's
    # missing we surface a friendly hint at import time instead of an
    # opaque ``No module named 'libcst'`` deep in the stack.
    if _exc.name and _exc.name.split(".")[0] == "libcst":
        raise ImportError(
            "vera.codemod requires libcst. "
            "Install with: pip install 'vera-sdk[codemod]'"
        ) from _exc
    raise

__all__ = [
    "CODEMOD_OPT_OUT_DIRECTIVE",
    "MigrationOptions",
    "MigrationResult",
    "iter_python_files",
    "make_diff",
    "migrate_file",
    "migrate_source",
]
