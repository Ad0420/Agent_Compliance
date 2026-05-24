"""LibCST codemod for the ``@vera.audit`` → ``@vera.gate`` migration.

Phase 1 PR 9 / Stream D8. Handles the five mechanical transformation
families documented in ``sdk/MIGRATION.md``:

1. **Import rewrite** — ``from vera import audit`` → ``from vera import gate``
   (alias preserved if present, alias-name local references untouched).
2. **Decorator name swap** — ``@vera.audit(...)`` → ``@vera.gate(...)`` and
   the bare-import form ``@audit(...)`` → ``@gate(...)``.
3. **Kwarg rename** (Codex X2) — ``action_name=`` → ``action_class=`` on
   ``@vera.gate(...)`` calls (applied AFTER the decorator name swap so
   the same pass catches both old and new shapes).
4. **try/except scaffolding** — opt-in via ``--wrap-callsites``. Wraps
   bare call sites of decorated functions in a ``try/except
   (vera.PendingReview, vera.PolicyBlock)`` skeleton. Skipped when the
   call site is already inside a try block that catches a superset of
   those exceptions.
5. **``vera.init()`` agent_type TODO** — when ``vera.init(...)`` lacks
   an ``agent_type=`` kwarg, insert a single-line TODO comment so the
   operator notices Phase 2 will surface a ``new_agent_type_detected``
   event without one.

Every transformation is idempotent: running the codemod twice in a row
on the same source produces zero changes on the second run. This is
asserted on every fixture in ``sdk/tests/test_codemod.py``.

The codemod is intentionally conservative — it WILL NOT decide
domain-specific logic for handling ``PendingReview`` and ``PolicyBlock``.
The wrap-callsites transform leaves ``raise`` placeholders with TODO
comments so the operator can replace them with their own queue / block
handling without the codemod silently inventing semantics.

Per-file opt-out: a file whose first non-blank, non-encoding line is
``# noqa: VERA-CODEMOD`` is skipped entirely. Documented in
MIGRATION.md.
"""

from __future__ import annotations

import difflib
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

import libcst as cst

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public constants.
# ---------------------------------------------------------------------------

#: A file whose first non-blank line matches this directive is skipped
#: entirely. Matches ``ruff``/``flake8`` ``noqa`` convention so editors
#: highlight it consistently.
CODEMOD_OPT_OUT_DIRECTIVE = "# noqa: VERA-CODEMOD"

#: Comment we insert after an unannotated ``vera.init()`` call. The
#: leading text is the dedupe key for transformation #5 — if a TODO
#: with this exact prefix already exists in the file, we do not insert
#: a duplicate.
_INIT_TODO_COMMENT = (
    "# TODO(audit-to-gate codemod): set agent_type= for "
    "new_agent_type_detected event (see MIGRATION.md)"
)

#: Comment block we insert around a wrapped call site. The leading
#: line is the dedupe key (same approach as the init TODO).
_WRAP_CALLSITE_TODO_PENDING = (
    "# TODO(audit-to-gate codemod): handle PendingReview "
    "(review_id=pending.review_id)"
)
_WRAP_CALLSITE_TODO_BLOCK = (
    "# TODO(audit-to-gate codemod): handle PolicyBlock "
    "(reason=blocked.reason)"
)

#: Directory names we never descend into.
_RECURSION_PRUNE = {
    "__pycache__",
    ".git",
    ".hg",
    ".svn",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "venv",
    "env",
    "node_modules",
    "dist",
    "build",
}

#: Glob suffixes we skip even inside an otherwise-walked dir.
_RECURSION_PRUNE_SUFFIX = (".egg-info",)


# ---------------------------------------------------------------------------
# Public data types.
# ---------------------------------------------------------------------------


@dataclass
class MigrationOptions:
    """User-facing knobs controlling which transformations run.

    Defaults match the safest possible migration: imports + decorator
    name + kwarg rename + ``init()`` TODO insertion are on; the
    try/except scaffold is OFF because it produces the most opinionated
    diffs.
    """

    wrap_callsites: bool = False
    init_todo: bool = True


@dataclass
class MigrationResult:
    """Outcome of running the codemod on a single source string.

    ``new_source`` is byte-identical to the input when nothing changed;
    callers should compare ``new_source != original_source`` (cheaper
    than ``changed``) only when they need a fast path. ``changed`` is
    authoritative and is what the CLI uses to decide whether to
    re-write the file.
    """

    new_source: str
    changed: bool
    skipped_reason: Optional[str] = None
    # Per-transform counters — surfaced by ``--verbose`` and useful in
    # tests to assert a specific transform actually fired.
    counters: dict[str, int] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Helpers.
# ---------------------------------------------------------------------------


def _is_opted_out(source: str) -> bool:
    """Return True if the file opts out via the codemod directive.

    Checks only the first non-blank, non-encoding line so adding the
    directive at the top of a file is the canonical opt-out gesture.
    Anywhere else in the file is intentionally ignored — we don't want
    a stale comment buried in the middle of a module to silently
    disable migrations the operator forgot about.
    """
    for raw_line in source.splitlines()[:5]:
        line = raw_line.strip()
        if not line:
            continue
        # PEP 263 encoding cookie / shebang — skip past, keep scanning.
        if line.startswith("#!"):
            continue
        if line.startswith("# -*-") or line.startswith("# coding"):
            continue
        return line.startswith(CODEMOD_OPT_OUT_DIRECTIVE)
    return False


def _bump(counters: dict[str, int], key: str, by: int = 1) -> None:
    counters[key] = counters.get(key, 0) + by


# ---------------------------------------------------------------------------
# Pass 1 — collect import bindings.
# ---------------------------------------------------------------------------


#: Names imported from ``vera`` that the codemod rewrites to the
#: unified ``gate`` decorator. ``async_audit`` is included because the
#: new ``@vera.gate`` handles both sync and async via
#: ``inspect.iscoroutinefunction`` — Codex X2 explicitly called this
#: out. The ``blocking=`` kwarg on ``async_audit`` has no equivalent on
#: ``gate``; the codemod leaves it in place so the runtime error
#: surfaces loudly (documented in MIGRATION.md as a known manual step).
_REWRITTEN_DECORATOR_NAMES = frozenset({"audit", "async_audit"})


@dataclass
class _ImportBindings:
    """What `vera`/`audit` names are in scope in this module.

    Populated by :class:`_ImportCollector` so subsequent passes can
    tell ``@audit("x")`` (bound to the deprecated decorator) apart from
    ``@audit("x")`` that's just a local function the user happens to
    have named ``audit``.
    """

    #: Local names bound to ``vera.audit`` / ``vera.async_audit``
    #: directly via ``from vera import audit`` (no alias). Renamed to
    #: ``gate`` by the import rewriter AND the decorator-name pass.
    bare_audit_names: set[str] = field(default_factory=set)
    #: Local names that are aliases of ``vera.audit`` (e.g.
    #: ``from vera import audit as my_audit``). Import rewriter keeps
    #: the alias; the decorator-name pass leaves the local reference
    #: alone since the alias target already changed via import.
    aliased_audit_names: set[str] = field(default_factory=set)
    #: Local names bound to the ``vera`` module via ``import vera`` or
    #: ``import vera as v``. Used to detect ``@<name>.audit(...)``.
    vera_module_names: set[str] = field(default_factory=set)


class _ImportCollector(cst.CSTVisitor):
    """Scan top-level imports to build :class:`_ImportBindings`."""

    def __init__(self) -> None:
        self.bindings = _ImportBindings()
        # ``vera`` is conventionally available — even when no explicit
        # ``import vera`` exists at the top of the file, callers will
        # often type ``@vera.audit`` after a ``from vera import ...``.
        # We treat ``vera`` as always-in-scope to catch this.
        self.bindings.vera_module_names.add("vera")

    def visit_Import(self, node: cst.Import) -> None:
        for alias in node.names:
            name_node = alias.name
            if isinstance(name_node, cst.Name) and name_node.value == "vera":
                local = (
                    alias.asname.name.value
                    if alias.asname
                    and isinstance(alias.asname.name, cst.Name)
                    else "vera"
                )
                self.bindings.vera_module_names.add(local)

    def visit_ImportFrom(self, node: cst.ImportFrom) -> None:
        module = _flatten_attr(node.module) if node.module else ""
        if module != "vera":
            return
        if isinstance(node.names, cst.ImportStar):
            # ``from vera import *`` — we conservatively assume any
            # ``@audit(...)`` / ``@async_audit(...)`` references the
            # v0 decorator. Add the canonical names; the decorator-
            # rewriter handles them.
            self.bindings.bare_audit_names.update(_REWRITTEN_DECORATOR_NAMES)
            return
        for alias in node.names:
            if not isinstance(alias.name, cst.Name):
                continue
            if alias.name.value not in _REWRITTEN_DECORATOR_NAMES:
                continue
            if alias.asname and isinstance(alias.asname.name, cst.Name):
                self.bindings.aliased_audit_names.add(alias.asname.name.value)
            else:
                self.bindings.bare_audit_names.add(alias.name.value)


def _flatten_attr(node: cst.BaseExpression) -> str:
    """Flatten a dotted ``Attribute`` chain into ``"a.b.c"``.

    Used by :class:`_ImportCollector` to recognise ``from vera import``
    even when nested attribute access is involved. ``Name`` nodes are
    handled trivially; anything else returns the empty string so
    callers can ignore exotic shapes (subscript, call expressions,
    etc.) instead of crashing.
    """
    if isinstance(node, cst.Name):
        return node.value
    if isinstance(node, cst.Attribute):
        base = _flatten_attr(node.value)
        if not base:
            return ""
        return f"{base}.{node.attr.value}"
    return ""


# ---------------------------------------------------------------------------
# Pass 2 — the actual transformer.
# ---------------------------------------------------------------------------


class _AuditToGateTransformer(cst.CSTTransformer):
    """The single multi-pass transformer that owns all 5 rewrites.

    LibCST visits children before parents, which is what we want for
    decorator rewrites (we want the rewritten ``Call`` to be the
    decorator we then optionally apply the kwarg rename to). Import
    rewrites happen via :meth:`leave_ImportFrom`; ``vera.init()`` TODOs
    happen via :meth:`leave_SimpleStatementLine` so we can splice the
    comment-line in next to the existing statement; the try/except
    scaffold happens via :meth:`leave_Module` after we've walked the
    tree once to know which symbols are gate-decorated.
    """

    def __init__(
        self,
        bindings: _ImportBindings,
        options: MigrationOptions,
        original_source: str,
    ) -> None:
        super().__init__()
        self.bindings = bindings
        self.options = options
        self.original_source = original_source
        self.counters: dict[str, int] = {}

        # Populated as we walk decorators — the set of function names
        # that are now ``@vera.gate``-decorated AFTER our rewrite. The
        # try/except scaffold (transform #4) uses this to decide which
        # call sites to wrap.
        self._gate_decorated_funcs: set[str] = set()

        # Used by :meth:`leave_SimpleStatementLine` to know whether the
        # current statement is a ``vera.init(...)`` call missing
        # ``agent_type=``. The flag is set in
        # :meth:`leave_Call` (since that's where we recognise the call
        # shape) and consumed in
        # :meth:`leave_SimpleStatementLine` (which has the trailing-
        # comment slot we need).
        self._pending_init_todo_for_line: bool = False

    # -- Import rewrite (transform #1) --------------------------------

    def leave_ImportFrom(
        self,
        original_node: cst.ImportFrom,
        updated_node: cst.ImportFrom,
    ) -> cst.BaseSmallStatement:
        module_name = _flatten_attr(updated_node.module) if updated_node.module else ""
        if module_name != "vera":
            return updated_node
        if isinstance(updated_node.names, cst.ImportStar):
            return updated_node

        new_aliases: list[cst.ImportAlias] = []
        changed = False
        # ``from vera import gate`` is the rewrite target. If multiple
        # source names collapse to ``gate`` (``audit`` AND
        # ``async_audit`` both imported), we keep only the first to
        # avoid emitting a duplicate import alias. The second is
        # dropped since the local name is the same.
        gate_seen_in_imports = False
        for alias in updated_node.names:
            if (
                isinstance(alias.name, cst.Name)
                and alias.name.value in _REWRITTEN_DECORATOR_NAMES
            ):
                # Rename the IMPORTED name to ``gate``. Preserve the
                # alias verbatim — ``from vera import audit as a``
                # becomes ``from vera import gate as a`` so the local
                # name ``a`` continues to work without touching call
                # sites.
                if not alias.asname:
                    # Bare import collapses to ``gate``. Skip the
                    # second/Nth occurrence to avoid emitting two
                    # ``gate`` aliases in the same import.
                    if gate_seen_in_imports:
                        # Drop this alias and any trailing comma
                        # belongs to the previous one — LibCST handles
                        # comma cleanup when we omit the alias.
                        changed = True
                        _bump(self.counters, "imports")
                        continue
                    gate_seen_in_imports = True
                new_aliases.append(
                    alias.with_changes(name=cst.Name("gate"))
                )
                changed = True
                _bump(self.counters, "imports")
            else:
                if (
                    isinstance(alias.name, cst.Name)
                    and alias.name.value == "gate"
                ):
                    gate_seen_in_imports = True
                new_aliases.append(alias)

        if not changed:
            return updated_node
        # Fix up trailing commas: the last alias must NOT have one.
        if new_aliases:
            last = new_aliases[-1]
            if last.comma is not cst.MaybeSentinel.DEFAULT:
                new_aliases[-1] = last.with_changes(
                    comma=cst.MaybeSentinel.DEFAULT
                )
        return updated_node.with_changes(names=new_aliases)

    # -- Decorator name swap (transform #2) ---------------------------

    def leave_Decorator(
        self,
        original_node: cst.Decorator,
        updated_node: cst.Decorator,
    ) -> cst.Decorator:
        new_decorator_expr = self._maybe_rewrite_decorator_expr(updated_node.decorator)
        if new_decorator_expr is updated_node.decorator:
            return updated_node
        return updated_node.with_changes(decorator=new_decorator_expr)

    def _maybe_rewrite_decorator_expr(
        self, expr: cst.BaseExpression
    ) -> cst.BaseExpression:
        """Rewrite ``@<...>.audit(...)`` / ``@audit(...)`` decorators.

        Two shapes:

        * ``Call(Attribute(Name(<vera-bound>), Name("audit")), ...)``
          — module-attribute access. Rename the attribute.
        * ``Call(Name(<bare-audit-bound>), ...)`` — local reference.
          Rename the call target.

        In both cases we ALSO rewrite the keyword arguments
        (``action_name=`` → ``action_class=``) here so transform #3
        rides on top of transform #2 without a second tree pass.

        Aliased imports (``from vera import audit as my_audit``) are
        intentionally left alone at the call site — the import-rewrite
        pass already renamed the imported binding so ``my_audit``
        already points at ``gate``.
        """
        # Bare reference: ``@audit("x")`` / ``@async_audit("x")``.
        if isinstance(expr, cst.Name) and expr.value in self.bindings.bare_audit_names:
            _bump(self.counters, "decorators")
            return cst.Name("gate")
        if isinstance(expr, cst.Attribute):
            base = expr.value
            attr = expr.attr
            if (
                isinstance(attr, cst.Name)
                and attr.value in _REWRITTEN_DECORATOR_NAMES
                and isinstance(base, cst.Name)
                and base.value in self.bindings.vera_module_names
            ):
                _bump(self.counters, "decorators")
                return expr.with_changes(attr=cst.Name("gate"))
            return expr
        if isinstance(expr, cst.Call):
            inner = self._maybe_rewrite_decorator_expr(expr.func)
            new_args = self._maybe_rewrite_action_name_kwarg(
                expr.args,
                # Only rename ``action_name=`` when the call target is
                # one we recognise as a vera audit/gate decorator. If
                # the user has an unrelated ``foo(action_name="x")`` we
                # MUST leave it alone.
                target_is_vera_decorator=(inner is not expr.func)
                or self._target_is_already_vera_gate(expr.func),
            )
            if inner is expr.func and new_args is expr.args:
                return expr
            return expr.with_changes(func=inner, args=new_args)
        return expr

    def _target_is_already_vera_gate(self, expr: cst.BaseExpression) -> bool:
        """Detect ``@vera.gate(...)`` / ``@gate(...)`` call targets.

        Used for idempotency on the kwarg-rename pass: a second run of
        the codemod over already-migrated code must still rename a
        stray ``action_name=`` if it slipped through, but must NOT
        touch unrelated user code with the same kwarg name.
        """
        if isinstance(expr, cst.Name) and expr.value == "gate":
            # ``gate`` only counts as the vera decorator when it was
            # imported from vera. Bare-import set after rewrite
            # contains the local name pointing at ``vera.gate``.
            return "audit" in self.bindings.bare_audit_names or "gate" in {
                n for n in self.bindings.bare_audit_names
            } or self._import_brings_gate()
        if isinstance(expr, cst.Attribute):
            base = expr.value
            attr = expr.attr
            return (
                isinstance(attr, cst.Name)
                and attr.value == "gate"
                and isinstance(base, cst.Name)
                and base.value in self.bindings.vera_module_names
            )
        return False

    def _import_brings_gate(self) -> bool:
        """True iff ``from vera import gate`` is in scope.

        Cheap-and-cheerful: re-scan the original source for the literal
        substring. Good enough since we only call this on the second
        run of the codemod (where the import was rewritten by the
        first run and we need to still recognise the local ``gate``
        name as vera's gate).
        """
        return bool(
            re.search(
                r"^\s*from\s+vera\s+import\s+[^#\n]*\bgate\b",
                self.original_source,
                re.MULTILINE,
            )
        )

    def _maybe_rewrite_action_name_kwarg(
        self,
        args: tuple[cst.Arg, ...] | list[cst.Arg],
        *,
        target_is_vera_decorator: bool,
    ) -> tuple[cst.Arg, ...]:
        """Rename ``action_name=`` → ``action_class=`` on vera decorators.

        Positional arguments pass through unchanged: ``@vera.audit("x")``
        becomes ``@vera.gate("x")``, NOT ``@vera.gate(action_class="x")``,
        because the new decorator's first positional parameter is also
        ``action_class``.
        """
        if not target_is_vera_decorator:
            return tuple(args)
        new_args: list[cst.Arg] = []
        changed = False
        for arg in args:
            kw = arg.keyword
            if (
                isinstance(kw, cst.Name)
                and kw.value == "action_name"
            ):
                new_args.append(arg.with_changes(keyword=cst.Name("action_class")))
                changed = True
                _bump(self.counters, "kwarg_renames")
            else:
                new_args.append(arg)
        if not changed:
            return tuple(args)
        return tuple(new_args)

    # -- Collect gate-decorated function names (used by transform #4) --

    def leave_FunctionDef(
        self,
        original_node: cst.FunctionDef,
        updated_node: cst.FunctionDef,
    ) -> cst.FunctionDef:
        for dec in updated_node.decorators:
            if self._is_vera_gate_decorator(dec.decorator):
                self._gate_decorated_funcs.add(updated_node.name.value)
                break
        return updated_node

    def _is_vera_gate_decorator(self, expr: cst.BaseExpression) -> bool:
        """Post-rewrite detector for ``@vera.gate`` / ``@gate``.

        Runs AFTER the decorator-name swap (LibCST visits children
        before parents), so a freshly-renamed ``@vera.gate`` is
        recognisable here without a second pass.
        """
        if isinstance(expr, cst.Call):
            return self._is_vera_gate_decorator(expr.func)
        if isinstance(expr, cst.Name):
            return (
                expr.value == "gate"
                and (
                    "audit" in self.bindings.bare_audit_names
                    or self._import_brings_gate()
                )
            )
        if isinstance(expr, cst.Attribute):
            attr = expr.attr
            base = expr.value
            return (
                isinstance(attr, cst.Name)
                and attr.value == "gate"
                and isinstance(base, cst.Name)
                and base.value in self.bindings.vera_module_names
            )
        return False

    # -- vera.init() agent_type TODO (transform #5) -------------------

    def leave_Call(
        self,
        original_node: cst.Call,
        updated_node: cst.Call,
    ) -> cst.BaseExpression:
        if not self.options.init_todo:
            return updated_node
        if not self._is_vera_init_call(updated_node):
            return updated_node
        if self._call_has_agent_type_kwarg(updated_node):
            return updated_node
        self._pending_init_todo_for_line = True
        return updated_node

    def _is_vera_init_call(self, call: cst.Call) -> bool:
        """Recognise ``vera.init(...)`` (and ``v.init`` for aliased imports)."""
        func = call.func
        if not isinstance(func, cst.Attribute):
            return False
        if not isinstance(func.attr, cst.Name) or func.attr.value != "init":
            return False
        base = func.value
        if not isinstance(base, cst.Name):
            return False
        return base.value in self.bindings.vera_module_names

    def _call_has_agent_type_kwarg(self, call: cst.Call) -> bool:
        for arg in call.args:
            if (
                isinstance(arg.keyword, cst.Name)
                and arg.keyword.value == "agent_type"
            ):
                return True
        return False

    def leave_SimpleStatementLine(
        self,
        original_node: cst.SimpleStatementLine,
        updated_node: cst.SimpleStatementLine,
    ) -> cst.BaseStatement:
        """Splice the agent_type TODO comment in after a ``vera.init()`` line.

        Dedupe key: if the existing trailing comment already starts
        with the canonical TODO prefix, skip — running the codemod
        twice must NOT produce two TODO lines.
        """
        if not self._pending_init_todo_for_line:
            return updated_node
        self._pending_init_todo_for_line = False  # consume the flag

        trailing = updated_node.trailing_whitespace
        existing_comment = trailing.comment.value if trailing.comment else ""
        if existing_comment.startswith(_INIT_TODO_COMMENT.split(":", 1)[0]):
            # ``# TODO(audit-to-gate codemod): ...`` already present.
            return updated_node

        # Splice the comment in as a trailing inline comment on the
        # same line, exactly how ``# noqa`` annotations look. Keeps
        # the diff minimal and lets the user delete it with one
        # keystroke once they've added ``agent_type=``.
        _bump(self.counters, "init_todos")
        new_trailing = trailing.with_changes(
            whitespace=cst.SimpleWhitespace("  "),
            comment=cst.Comment(_INIT_TODO_COMMENT),
        )
        return updated_node.with_changes(trailing_whitespace=new_trailing)

    # -- try/except scaffold (transform #4) ---------------------------

    def leave_Module(
        self,
        original_node: cst.Module,
        updated_node: cst.Module,
    ) -> cst.Module:
        if not self.options.wrap_callsites:
            return updated_node
        if not self._gate_decorated_funcs:
            return updated_node
        wrapper = _CallsiteWrapper(
            decorated_funcs=self._gate_decorated_funcs,
            counters=self.counters,
        )
        return updated_node.visit(wrapper)


# ---------------------------------------------------------------------------
# Pass 3 — opt-in callsite wrapper (transform #4).
# ---------------------------------------------------------------------------


class _CallsiteWrapper(cst.CSTTransformer):
    """Wraps bare calls to gate-decorated functions in try/except.

    Run as a separate pass AFTER the main transformer because it needs
    to know the full set of gate-decorated function names in the
    module — which we only have after walking the entire tree once.

    Conservative on shape:

    * Only wraps assignments and bare-expression statements that have
      a Call as their RHS / value (``result = fn(...)`` and
      ``fn(...)``).
    * Skips Call sites whose enclosing statement is already inside a
      try block that catches Exception, BaseException, PendingReview,
      or PolicyBlock. We track this with a depth counter rather than a
      stack of caught exceptions because LibCST visits children first
      — the depth counter is simpler and correct for our nesting
      check.
    """

    def __init__(
        self,
        decorated_funcs: set[str],
        counters: dict[str, int],
    ) -> None:
        super().__init__()
        self.decorated_funcs = decorated_funcs
        self.counters = counters
        self._try_depth_with_safe_except: int = 0

    # -- track enclosing try ------------------------------------------

    def visit_Try(self, node: cst.Try) -> None:
        if _try_catches_pending_or_block(node):
            self._try_depth_with_safe_except += 1

    def leave_Try(
        self,
        original_node: cst.Try,
        updated_node: cst.Try,
    ) -> cst.BaseStatement:
        if _try_catches_pending_or_block(original_node):
            self._try_depth_with_safe_except -= 1
        return updated_node

    # -- the actual wrapping ------------------------------------------

    def leave_SimpleStatementLine(
        self,
        original_node: cst.SimpleStatementLine,
        updated_node: cst.SimpleStatementLine,
    ) -> cst.BaseStatement:
        if self._try_depth_with_safe_except > 0:
            return updated_node
        if len(updated_node.body) != 1:
            return updated_node
        stmt = updated_node.body[0]
        call = _extract_decorated_call(stmt, self.decorated_funcs)
        if call is None:
            return updated_node

        # Build the try/except. Preserve the original statement
        # verbatim inside the try body.
        _bump(self.counters, "wrapped_callsites")
        try_block = cst.Try(
            body=cst.IndentedBlock(
                body=[updated_node.with_changes(leading_lines=[])]
            ),
            handlers=[
                cst.ExceptHandler(
                    type=cst.Attribute(
                        value=cst.Name("vera"),
                        attr=cst.Name("PendingReview"),
                    ),
                    name=cst.AsName(name=cst.Name("pending")),
                    body=cst.IndentedBlock(
                        body=[
                            cst.SimpleStatementLine(
                                body=[cst.Raise()],
                                leading_lines=[
                                    cst.EmptyLine(
                                        comment=cst.Comment(
                                            _WRAP_CALLSITE_TODO_PENDING
                                        )
                                    )
                                ],
                            ),
                        ]
                    ),
                ),
                cst.ExceptHandler(
                    type=cst.Attribute(
                        value=cst.Name("vera"),
                        attr=cst.Name("PolicyBlock"),
                    ),
                    name=cst.AsName(name=cst.Name("blocked")),
                    body=cst.IndentedBlock(
                        body=[
                            cst.SimpleStatementLine(
                                body=[cst.Raise()],
                                leading_lines=[
                                    cst.EmptyLine(
                                        comment=cst.Comment(
                                            _WRAP_CALLSITE_TODO_BLOCK
                                        )
                                    )
                                ],
                            ),
                        ]
                    ),
                ),
            ],
            leading_lines=list(updated_node.leading_lines),
        )
        return try_block


def _try_catches_pending_or_block(node: cst.Try) -> bool:
    """Detect whether a try block's except handlers cover us.

    Considered "safe" (i.e. already wrapped):
    * A bare ``except:`` catches everything.
    * ``except Exception`` / ``except BaseException``.
    * ``except vera.PendingReview`` / ``except vera.PolicyBlock``
      (either separately, both, or in a tuple in any order).
    """
    needed = {"PendingReview", "PolicyBlock"}
    seen: set[str] = set()
    for handler in node.handlers:
        if handler.type is None:
            return True  # bare except
        names = _flatten_exception_types(handler.type)
        if "Exception" in names or "BaseException" in names:
            return True
        for n in names:
            if n in needed:
                seen.add(n)
    return needed.issubset(seen)


def _flatten_exception_types(expr: cst.BaseExpression) -> set[str]:
    """Return the bare exception-class names in an except clause.

    Handles ``except Foo``, ``except module.Foo``, and
    ``except (A, B, module.C)``. Anything more exotic returns an empty
    set — we don't try to be clever about parenthesised expressions
    that aren't tuples.
    """
    out: set[str] = set()
    if isinstance(expr, cst.Name):
        out.add(expr.value)
    elif isinstance(expr, cst.Attribute) and isinstance(expr.attr, cst.Name):
        out.add(expr.attr.value)
    elif isinstance(expr, cst.Tuple):
        for elt in expr.elements:
            if isinstance(elt, cst.Element):
                out |= _flatten_exception_types(elt.value)
    return out


def _extract_decorated_call(
    stmt: cst.BaseSmallStatement,
    decorated_funcs: set[str],
) -> Optional[cst.Call]:
    """Return the Call inside a statement iff it targets a decorated fn.

    Two shapes we wrap:

    * ``result = fn(...)`` — an Assign with a single Call RHS.
    * ``fn(...)`` — a bare Expr-statement.

    Anything else (chained calls, calls inside larger expressions,
    conditional expressions, etc.) is intentionally NOT wrapped — the
    wrap-callsites transform is opportunistic, not exhaustive, and the
    operator can always hand-author the harder shapes.
    """
    if isinstance(stmt, cst.Expr):
        if isinstance(stmt.value, cst.Call):
            return stmt.value if _call_targets_decorated(stmt.value, decorated_funcs) else None
    if isinstance(stmt, cst.Assign):
        if isinstance(stmt.value, cst.Call):
            return stmt.value if _call_targets_decorated(stmt.value, decorated_funcs) else None
    return None


def _call_targets_decorated(call: cst.Call, decorated_funcs: set[str]) -> bool:
    func = call.func
    if isinstance(func, cst.Name):
        return func.value in decorated_funcs
    return False


# ---------------------------------------------------------------------------
# Public entry points.
# ---------------------------------------------------------------------------


def migrate_source(
    source: str,
    *,
    options: Optional[MigrationOptions] = None,
) -> MigrationResult:
    """Run the codemod on a source string.

    Returns the rewritten source plus a per-transform counter dict. If
    the file opts out via the codemod directive, returns the original
    source verbatim with a populated ``skipped_reason``.
    """
    opts = options or MigrationOptions()

    if _is_opted_out(source):
        return MigrationResult(
            new_source=source,
            changed=False,
            skipped_reason="opted out via VERA-CODEMOD directive",
        )

    try:
        module = cst.parse_module(source)
    except cst.ParserSyntaxError as exc:
        return MigrationResult(
            new_source=source,
            changed=False,
            skipped_reason=f"syntax error: {exc}",
        )

    collector = _ImportCollector()
    module.visit(collector)

    transformer = _AuditToGateTransformer(
        bindings=collector.bindings,
        options=opts,
        original_source=source,
    )
    new_module = module.visit(transformer)
    new_source = new_module.code

    return MigrationResult(
        new_source=new_source,
        changed=new_source != source,
        counters=transformer.counters,
    )


def migrate_file(
    path: Path,
    *,
    options: Optional[MigrationOptions] = None,
    write: bool = True,
) -> MigrationResult:
    """Run the codemod on a file on disk.

    When ``write=True`` (the default), rewrites the file in place if
    the codemod produced changes. When ``write=False`` returns the
    rewritten source without touching the file (used by ``--dry-run``
    and ``--check`` modes in the CLI).

    The file is read+written as UTF-8 with universal newlines (Python's
    default ``open``). LibCST preserves line endings as encountered, so
    a CRLF input round-trips as CRLF.
    """
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return MigrationResult(
            new_source="",
            changed=False,
            skipped_reason=f"read error: {exc}",
        )

    result = migrate_source(source, options=options)
    if write and result.changed:
        path.write_text(result.new_source, encoding="utf-8")
    return result


def iter_python_files(root: Path) -> Iterable[Path]:
    """Yield every ``*.py`` file under ``root``, pruning junk dirs.

    Symlinks to directories are NOT followed — symlink loops would
    otherwise wedge the walker. Symlinks to files ARE followed (the
    file is read once and rewritten once, same as any other file).
    """
    if root.is_file():
        if root.suffix == ".py":
            yield root
        return
    seen_dirs: set[tuple[int, int]] = set()
    for dirpath, dirnames, filenames in os.walk(
        root, followlinks=False
    ):
        # Stable inode check guards against directory loops created
        # by hardlinks or filesystem quirks (rare on POSIX, possible
        # on networked FS).
        try:
            st = os.stat(dirpath)
            key = (st.st_dev, st.st_ino)
            if key in seen_dirs:
                dirnames[:] = []
                continue
            seen_dirs.add(key)
        except OSError:
            pass

        # Prune in place so os.walk respects our skip list. Mutating
        # ``dirnames`` is the documented way to do this.
        dirnames[:] = [
            d
            for d in dirnames
            if d not in _RECURSION_PRUNE
            and not any(d.endswith(suf) for suf in _RECURSION_PRUNE_SUFFIX)
        ]
        for name in filenames:
            if name.endswith(".py"):
                yield Path(dirpath) / name


def make_diff(
    original: str, new: str, *, path: str = "<source>"
) -> str:
    """Return a unified diff suitable for ``--dry-run`` output."""
    return "".join(
        difflib.unified_diff(
            original.splitlines(keepends=True),
            new.splitlines(keepends=True),
            fromfile=path,
            tofile=path,
            n=3,
        )
    )


__all__ = [
    "CODEMOD_OPT_OUT_DIRECTIVE",
    "MigrationOptions",
    "MigrationResult",
    "iter_python_files",
    "make_diff",
    "migrate_file",
    "migrate_source",
]
