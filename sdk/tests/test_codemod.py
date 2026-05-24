"""Tests for the ``vera codemod audit-to-gate`` LibCST codemod.

Phase 1 PR 9 / Stream D8. Covers:

* All 12 fixtures round-trip from ``<name>_before.py`` to
  ``<name>_after.py`` byte-for-byte.
* Idempotency on every ``<name>_after.py``: running the codemod a
  second time produces zero changes.
* CLI happy path (``--dry-run``, ``--check``, exit codes).
* Directory recursion + prune rules + symlink safety.
* Syntax-error tolerance (per-file failure does NOT abort the whole
  run).
* ``# noqa: VERA-CODEMOD`` per-file opt-out.
* ``--wrap-callsites`` output compiles.

The fixtures live in ``sdk/tests/codemod_fixtures/`` so they're
inspectable in isolation. Each fixture is documented in its own
docstring.
"""

from __future__ import annotations

import os
import textwrap
from pathlib import Path

import pytest
from click.testing import CliRunner

from vera.cli import cli
from vera.codemod import MigrationOptions, migrate_source
from vera.codemod.audit_to_gate import (
    CODEMOD_OPT_OUT_DIRECTIVE,
    iter_python_files,
)


FIXTURE_DIR = Path(__file__).parent / "codemod_fixtures"


# Fixtures that exercise the opt-in transforms (``--wrap-callsites``).
# Everything else runs with the default options.
_WRAP_FIXTURES = {
    "with_existing_try_except",
    "wraps_callsite",
    "wraps_callsite_from_import",
    "wraps_callsite_no_vera_in_scope",
}


def _fixture_names() -> list[str]:
    """Discover fixtures from disk so adding one only requires two files."""
    names: set[str] = set()
    for f in FIXTURE_DIR.glob("*_before.py"):
        names.add(f.name[: -len("_before.py")])
    return sorted(names)


# ---------------------------------------------------------------------------
# Fixture round-trip tests.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", _fixture_names())
def test_fixture_roundtrip(name: str) -> None:
    """Each fixture's ``before`` migrates to byte-equal ``after``."""
    before = (FIXTURE_DIR / f"{name}_before.py").read_text(encoding="utf-8")
    expected = (FIXTURE_DIR / f"{name}_after.py").read_text(encoding="utf-8")

    options = MigrationOptions(
        wrap_callsites=name in _WRAP_FIXTURES,
        init_todo=True,
    )
    result = migrate_source(before, options=options)
    assert result.new_source == expected, (
        f"fixture {name!r}: codemod output differs from expected.\n"
        f"--- expected ---\n{expected}\n"
        f"--- got ---\n{result.new_source}\n"
    )


@pytest.mark.parametrize("name", _fixture_names())
def test_fixture_idempotent(name: str) -> None:
    """Running the codemod on the ``after`` file yields zero changes."""
    expected = (FIXTURE_DIR / f"{name}_after.py").read_text(encoding="utf-8")
    options = MigrationOptions(
        wrap_callsites=name in _WRAP_FIXTURES,
        init_todo=True,
    )
    result = migrate_source(expected, options=options)
    assert not result.changed, (
        f"fixture {name!r}: codemod produced changes on already-migrated "
        f"file (idempotency violation). counters={result.counters}\n"
        f"--- after second run ---\n{result.new_source}"
    )
    assert result.new_source == expected


# ---------------------------------------------------------------------------
# Single-run idempotency: run twice in a row on a before file, the second
# run must produce zero changes. Catches transforms whose first pass
# generates output that the second pass would re-rewrite.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", _fixture_names())
def test_double_run_idempotent(name: str) -> None:
    before = (FIXTURE_DIR / f"{name}_before.py").read_text(encoding="utf-8")
    options = MigrationOptions(
        wrap_callsites=name in _WRAP_FIXTURES,
        init_todo=True,
    )
    first = migrate_source(before, options=options)
    second = migrate_source(first.new_source, options=options)
    assert not second.changed, (
        f"fixture {name!r}: second run produced changes. "
        f"counters={second.counters}\n--- diff ---"
    )


# ---------------------------------------------------------------------------
# CLI tests.
# ---------------------------------------------------------------------------


def test_cli_help_lists_codemod() -> None:
    """``vera --help`` lists the codemod subcommand."""
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "codemod" in result.output


def test_cli_dry_run_prints_diff(tmp_path: Path) -> None:
    """``--dry-run`` prints a diff and does NOT modify the file."""
    target = tmp_path / "x.py"
    original = "import vera\n\n@vera.audit('x')\ndef f():\n    pass\n"
    target.write_text(original)

    runner = CliRunner()
    result = runner.invoke(
        cli, ["codemod", "audit-to-gate", "--dry-run", str(target)]
    )
    assert result.exit_code == 0, result.output
    assert "vera.audit" in result.output
    assert "vera.gate" in result.output
    # File must NOT have been written.
    assert target.read_text() == original


def test_cli_apply_writes_file(tmp_path: Path) -> None:
    """Without --dry-run / --check the codemod writes the file."""
    target = tmp_path / "x.py"
    target.write_text("import vera\n\n@vera.audit('x')\ndef f():\n    pass\n")

    runner = CliRunner()
    result = runner.invoke(
        cli, ["codemod", "audit-to-gate", str(target)]
    )
    assert result.exit_code == 0, result.output
    assert "@vera.gate" in target.read_text()


def test_cli_check_mode_exit_1_on_pending_changes(tmp_path: Path) -> None:
    """``--check`` returns exit 1 when changes are pending."""
    target = tmp_path / "x.py"
    target.write_text("import vera\n\n@vera.audit('x')\ndef f():\n    pass\n")

    runner = CliRunner()
    result = runner.invoke(
        cli, ["codemod", "audit-to-gate", "--check", str(target)]
    )
    assert result.exit_code == 1, result.output
    # And the file MUST NOT have been modified.
    assert "@vera.audit" in target.read_text()


def test_cli_check_mode_exit_0_when_clean(tmp_path: Path) -> None:
    """``--check`` returns exit 0 when nothing would change."""
    target = tmp_path / "x.py"
    target.write_text("import vera\n\n@vera.gate('x')\ndef f():\n    pass\n")

    runner = CliRunner()
    result = runner.invoke(
        cli, ["codemod", "audit-to-gate", "--check", str(target)]
    )
    assert result.exit_code == 0, result.output


def test_cli_directory_recursion(tmp_path: Path) -> None:
    """Directory mode recurses into subdirs and ignores pruned ones."""
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "a.py").write_text(
        "import vera\n@vera.audit('a')\ndef a():\n    pass\n"
    )
    (tmp_path / "pkg" / "__pycache__").mkdir()
    (tmp_path / "pkg" / "__pycache__" / "should_skip.py").write_text(
        "import vera\n@vera.audit('skipped')\ndef s():\n    pass\n"
    )
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "venv_skip.py").write_text(
        "import vera\n@vera.audit('venv')\ndef v():\n    pass\n"
    )
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "nm_skip.py").write_text(
        "import vera\n@vera.audit('nm')\ndef n():\n    pass\n"
    )

    runner = CliRunner()
    result = runner.invoke(
        cli, ["codemod", "audit-to-gate", str(tmp_path)]
    )
    assert result.exit_code == 0, result.output

    # Only the unpruned file was migrated.
    assert "@vera.gate" in (tmp_path / "pkg" / "a.py").read_text()
    assert "@vera.audit" in (
        tmp_path / "pkg" / "__pycache__" / "should_skip.py"
    ).read_text()
    assert "@vera.audit" in (
        tmp_path / ".venv" / "venv_skip.py"
    ).read_text()
    assert "@vera.audit" in (
        tmp_path / "node_modules" / "nm_skip.py"
    ).read_text()


def test_cli_egg_info_pruned(tmp_path: Path) -> None:
    """Directory ending in .egg-info is pruned."""
    (tmp_path / "my_pkg.egg-info").mkdir()
    (tmp_path / "my_pkg.egg-info" / "x.py").write_text(
        "import vera\n@vera.audit('x')\ndef f():\n    pass\n"
    )
    runner = CliRunner()
    result = runner.invoke(
        cli, ["codemod", "audit-to-gate", str(tmp_path)]
    )
    assert result.exit_code == 0
    assert "@vera.audit" in (
        tmp_path / "my_pkg.egg-info" / "x.py"
    ).read_text()


def test_cli_syntax_error_tolerance(tmp_path: Path) -> None:
    """A file with a syntax error is reported, others still process."""
    bad = tmp_path / "bad.py"
    bad.write_text("def f(:\n    pass\n")  # invalid
    good = tmp_path / "good.py"
    good.write_text("import vera\n@vera.audit('x')\ndef f():\n    pass\n")

    runner = CliRunner()
    result = runner.invoke(
        cli, ["codemod", "audit-to-gate", "-v", str(tmp_path)]
    )
    # Exit 0: the good file migrated cleanly, the bad file was
    # reported as skipped (syntax error counts as skipped, not error).
    assert "@vera.gate" in good.read_text()
    assert "syntax error" in result.output


def test_cli_noqa_directive_skips_file(tmp_path: Path) -> None:
    """`# noqa: VERA-CODEMOD` at the top of a file skips it."""
    target = tmp_path / "x.py"
    original = textwrap.dedent(
        f"""\
        {CODEMOD_OPT_OUT_DIRECTIVE}
        import vera

        @vera.audit("untouched")
        def untouched():
            pass
        """
    )
    target.write_text(original)

    runner = CliRunner()
    result = runner.invoke(
        cli, ["codemod", "audit-to-gate", str(target)]
    )
    assert result.exit_code == 0, result.output
    assert target.read_text() == original


def test_cli_noqa_directive_works_after_shebang(tmp_path: Path) -> None:
    """`# noqa: VERA-CODEMOD` after a shebang/encoding still skips."""
    target = tmp_path / "x.py"
    original = textwrap.dedent(
        f"""\
        #!/usr/bin/env python3
        # -*- coding: utf-8 -*-
        {CODEMOD_OPT_OUT_DIRECTIVE}
        import vera

        @vera.audit("untouched")
        def untouched():
            pass
        """
    )
    target.write_text(original)

    runner = CliRunner()
    result = runner.invoke(
        cli, ["codemod", "audit-to-gate", str(target)]
    )
    assert result.exit_code == 0, result.output
    assert target.read_text() == original


# ---------------------------------------------------------------------------
# Symlink safety: a directory symlink that loops MUST NOT spin forever.
# ---------------------------------------------------------------------------


def test_iter_python_files_does_not_follow_dir_symlinks(tmp_path: Path) -> None:
    """``iter_python_files`` does not descend into directory symlinks."""
    real = tmp_path / "real"
    real.mkdir()
    (real / "a.py").write_text("# a\n")

    loop = tmp_path / "loop"
    try:
        loop.symlink_to(real, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not supported on this platform")

    files = sorted(p.name for p in iter_python_files(tmp_path))
    # The real file shows up; the symlinked copy does NOT cause a
    # second yield (followlinks=False).
    assert "a.py" in files
    assert len(files) == 1


# ---------------------------------------------------------------------------
# Wrap-callsites must produce compileable output for every fixture.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(_WRAP_FIXTURES))
def test_wrap_callsites_compiles(name: str) -> None:
    """The wrap-callsites output is valid Python (parses + compiles)."""
    before = (FIXTURE_DIR / f"{name}_before.py").read_text(encoding="utf-8")
    options = MigrationOptions(wrap_callsites=True, init_todo=True)
    result = migrate_source(before, options=options)
    # ``exec`` would actually run the code; ``compile`` just verifies
    # the bytecode generation succeeds, which is what we want here.
    compile(result.new_source, f"<{name}>", "exec")


# ---------------------------------------------------------------------------
# Unit checks for individual transform invariants (not fixture-driven).
# ---------------------------------------------------------------------------


def test_init_todo_dedupes_on_second_run() -> None:
    """Running twice on a vera.init() call doesn't add two TODOs."""
    src = "import vera\n\nvera.init(api_key='k')\n"
    r1 = migrate_source(src)
    r2 = migrate_source(r1.new_source)
    assert r1.new_source.count("TODO(audit-to-gate") == 1
    assert not r2.changed
    assert r2.new_source.count("TODO(audit-to-gate") == 1


def test_positional_first_arg_stays_positional() -> None:
    """``@vera.audit("x")`` stays positional after rewrite."""
    src = "import vera\n\n@vera.audit('x')\ndef f():\n    pass\n"
    r = migrate_source(src)
    assert "@vera.gate('x')" in r.new_source
    assert "action_class=" not in r.new_source


def test_no_init_todo_flag_disables_transform_5() -> None:
    """``init_todo=False`` skips the TODO insertion entirely."""
    src = "import vera\n\nvera.init(api_key='k')\n"
    r = migrate_source(src, options=MigrationOptions(init_todo=False))
    assert "TODO(audit-to-gate" not in r.new_source
    assert not r.changed


def test_unrelated_action_name_kwarg_not_renamed() -> None:
    """A user's own function with ``action_name=`` is NOT touched."""
    src = textwrap.dedent(
        """
        def my_helper(action_name=None):
            return action_name


        x = my_helper(action_name="should-stay")
        """
    )
    r = migrate_source(src)
    assert not r.changed
    assert "action_name" in r.new_source


def test_existing_try_with_pending_and_block_skipped() -> None:
    """An existing ``except (PendingReview, PolicyBlock)`` blocks re-wrap."""
    src = textwrap.dedent(
        """
        import vera


        @vera.audit("x")
        def f():
            pass


        try:
            f()
        except (vera.PendingReview, vera.PolicyBlock):
            pass
        """
    )
    r = migrate_source(
        src, options=MigrationOptions(wrap_callsites=True)
    )
    # Decorator should rewrite, but the try block must NOT be
    # duplicated.
    assert r.new_source.count("try:") == 1
    assert "@vera.gate" in r.new_source


def test_bare_except_skipped() -> None:
    """A bare ``except:`` counts as already-wrapped."""
    src = textwrap.dedent(
        """
        import vera


        @vera.audit("x")
        def f():
            pass


        try:
            f()
        except:  # noqa
            pass
        """
    )
    r = migrate_source(
        src, options=MigrationOptions(wrap_callsites=True)
    )
    assert r.new_source.count("try:") == 1


def test_aliased_vera_import_recognised() -> None:
    """``import vera as v`` + ``@v.audit('x')`` is rewritten."""
    src = textwrap.dedent(
        """
        import vera as v


        @v.audit("x")
        def f():
            pass
        """
    )
    r = migrate_source(src)
    assert "@v.gate" in r.new_source
    assert "@v.audit" not in r.new_source


def test_init_aliased_vera_recognised() -> None:
    """``import vera as v`` + ``v.init(...)`` gets the TODO."""
    src = "import vera as v\n\nv.init(api_key='k')\n"
    r = migrate_source(src)
    assert "TODO(audit-to-gate" in r.new_source


def test_mixed_audit_and_async_audit_collapse_to_single_gate() -> None:
    """``from vera import audit, async_audit`` collapses to ``gate``."""
    src = textwrap.dedent(
        """
        from vera import audit, async_audit


        @audit("s")
        def s():
            pass


        @async_audit("a")
        async def a():
            pass
        """
    )
    r = migrate_source(src)
    # Both decorators rename to ``@gate(...)`` and the two imports
    # collapse into a single ``from vera import gate`` line.
    assert r.new_source.count("from vera import gate") == 1
    assert r.new_source.count("from vera import") == 1
    assert r.new_source.count("@gate") == 2
    # Output must compile.
    compile(r.new_source, "<t>", "exec")


def test_mixed_import_with_unrelated_name_preserves_other_aliases() -> None:
    """``from vera import audit, Redactor`` keeps Redactor intact."""
    src = "from vera import audit, Redactor\n"
    r = migrate_source(src)
    assert "from vera import gate, Redactor" in r.new_source


def test_async_audit_alias_preserved() -> None:
    """``from vera import async_audit as aa`` keeps the local name ``aa``."""
    src = textwrap.dedent(
        """
        from vera import async_audit as aa


        @aa("x")
        async def f():
            pass
        """
    )
    r = migrate_source(src)
    assert "from vera import gate as aa" in r.new_source
    assert "@aa" in r.new_source


def test_import_star_treats_audit_and_async_audit_as_bound() -> None:
    """``from vera import *`` is treated as binding both audit names."""
    src = textwrap.dedent(
        """
        from vera import *


        @audit("a")
        def a():
            pass


        @async_audit("b")
        async def b():
            pass
        """
    )
    r = migrate_source(src)
    assert "@gate" in r.new_source
    assert r.new_source.count("@gate") == 2


def test_wrap_callsites_disabled_by_default() -> None:
    """Default options do NOT wrap call sites (opinionated diff is opt-in)."""
    src = textwrap.dedent(
        """
        import vera


        @vera.audit("x")
        def f():
            pass


        result = f()
        """
    )
    r = migrate_source(src)  # default options
    assert "try:" not in r.new_source
    assert "PendingReview" not in r.new_source
