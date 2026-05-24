"""Build-artifact sanity test (Phase 1 PR 10 / D9.7).

Catches pyproject.toml typos / missing files / packaging regressions
before the release runbook runs. The test:

1. Runs ``python -m build`` against the SDK directory in a tmpdir.
2. Verifies both a wheel and an sdist were produced and carry the
   pyproject.toml version.
3. Creates a fresh venv, ``pip install``s the wheel into it.
4. Verifies key public exports are importable.
5. Verifies ``pip install '...[codemod]'`` works (catches the
   extras_require regression PR #208 found the hard way).

Marked ``slow`` — the full run is 30s+ on commodity hardware
(subprocess build + venv create + pip install). Default-skipped via
``pyproject.toml::tool.pytest.ini_options.addopts = "-m 'not slow'"``;
opt in with ``pytest -m slow``.

If running this test is too slow / fiddly on your CI hardware, treat
the sequence in ``sdk/RELEASE.md::Step 3`` as the manual smoke-test
substitute.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import venv
from pathlib import Path

import pytest


pytestmark = pytest.mark.slow


SDK_DIR = Path(__file__).resolve().parent.parent
EXPECTED_VERSION = "1.0.0"


def _read_pyproject_version() -> str:
    """Parse the version string out of sdk/pyproject.toml.

    Avoids ``tomllib`` dependency churn on Python <3.11 by string-scanning.
    The format is locked-down enough that this is safe.
    """
    text = (SDK_DIR / "pyproject.toml").read_text()
    for line in text.splitlines():
        if line.startswith("version = "):
            return line.split('"')[1]
    raise RuntimeError("could not parse version from pyproject.toml")


@pytest.fixture(scope="module")
def built_artifacts(tmp_path_factory):
    """Run ``python -m build`` once for the whole module.

    Returns ``(wheel_path, sdist_path)``. Skips the entire suite if
    ``python -m build`` isn't available (CI without the build extras
    installed shouldn't fail loudly here).
    """
    try:
        import build  # noqa: F401
    except ImportError:
        pytest.skip("python `build` package not installed; run `pip install build`")

    outdir = tmp_path_factory.mktemp("dist")
    result = subprocess.run(
        [sys.executable, "-m", "build", "--outdir", str(outdir), str(SDK_DIR)],
        capture_output=True,
        text=True,
        timeout=180,
    )
    if result.returncode != 0:
        pytest.fail(
            f"python -m build failed (rc={result.returncode}):\n"
            f"STDOUT:\n{result.stdout}\n"
            f"STDERR:\n{result.stderr}"
        )

    wheels = list(outdir.glob("*.whl"))
    sdists = list(outdir.glob("*.tar.gz"))
    assert len(wheels) == 1, f"expected 1 wheel, got {wheels}"
    assert len(sdists) == 1, f"expected 1 sdist, got {sdists}"
    return wheels[0], sdists[0]


def test_version_consistency():
    """pyproject.toml + setup.py + CHANGELOG must all agree on the version."""
    pyproject_version = _read_pyproject_version()
    assert pyproject_version == EXPECTED_VERSION, (
        f"pyproject.toml version is {pyproject_version!r}, expected "
        f"{EXPECTED_VERSION!r}. Update EXPECTED_VERSION in this test or "
        f"the version in pyproject.toml."
    )

    setup_text = (SDK_DIR / "setup.py").read_text()
    assert f'version="{EXPECTED_VERSION}"' in setup_text, (
        f"setup.py does not match pyproject.toml version "
        f"{EXPECTED_VERSION!r}. Bump both together."
    )

    changelog_text = (SDK_DIR / "CHANGELOG.md").read_text()
    assert f"## [{EXPECTED_VERSION}]" in changelog_text, (
        f"CHANGELOG.md is missing a [{EXPECTED_VERSION}] section. "
        f"Every release version must have a changelog entry."
    )


def test_build_produces_wheel_and_sdist(built_artifacts):
    """Sanity-check the build output filenames."""
    wheel, sdist = built_artifacts
    expected_wheel = f"vera_sdk-{EXPECTED_VERSION}-"
    expected_sdist = f"vera_sdk-{EXPECTED_VERSION}.tar.gz"
    assert wheel.name.startswith(expected_wheel), (
        f"wheel {wheel.name} doesn't carry version {EXPECTED_VERSION}"
    )
    assert sdist.name == expected_sdist, (
        f"sdist {sdist.name} doesn't match {expected_sdist}"
    )


def test_wheel_installs_and_imports_in_fresh_venv(built_artifacts, tmp_path):
    """Install the wheel in a brand-new venv and verify imports.

    This catches pyproject.toml regressions that don't surface in the
    -e dev install (missing package data, broken entry points, etc.).
    """
    wheel, _ = built_artifacts
    venv_dir = tmp_path / "venv"
    venv.create(venv_dir, with_pip=True, clear=True)

    if sys.platform == "win32":
        py = venv_dir / "Scripts" / "python.exe"
    else:
        py = venv_dir / "bin" / "python"

    assert py.exists(), f"venv python not found at {py}"

    # Install the wheel (no [codemod] extra — that's tested separately).
    result = subprocess.run(
        [str(py), "-m", "pip", "install", "--quiet", str(wheel)],
        capture_output=True,
        text=True,
        timeout=180,
    )
    if result.returncode != 0:
        pytest.fail(
            f"pip install failed (rc={result.returncode}):\n"
            f"STDOUT:\n{result.stdout}\n"
            f"STDERR:\n{result.stderr}"
        )

    # Verify the public API surface is importable.
    smoke_script = (
        "import vera; "
        "from vera import (init, get_client, gate, audit, "
        "PolicyBlock, PendingReview, WrongKeyTier, "
        "TenantMissingOrInvalid, ReviewerCredentialsInsufficient, "
        "VeraError, Redactor, tenant, set_default_tenant); "
        "from vera.testing import bypass_gates, bypass_gates_cm; "
        "from importlib.metadata import version; "
        f"assert version('vera-sdk') == '{EXPECTED_VERSION}', "
        f"f'version mismatch: {{version(\"vera-sdk\")}} != {EXPECTED_VERSION}'; "
        "print('smoke ok')"
    )
    result = subprocess.run(
        [str(py), "-c", smoke_script],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        pytest.fail(
            f"smoke script failed (rc={result.returncode}):\n"
            f"STDOUT:\n{result.stdout}\n"
            f"STDERR:\n{result.stderr}"
        )
    assert "smoke ok" in result.stdout


def test_wheel_installs_with_codemod_extra(built_artifacts, tmp_path):
    """Install the wheel with the [codemod] extra and import LibCST glue.

    Catches the extras_require regression PR #208 fixed (libcst was
    pulled to runtime dependency by accident — making the SDK ~15MB
    heavier for installs that didn't need it). If the extras_require
    line gets dropped, this test fails at import time.
    """
    wheel, _ = built_artifacts
    venv_dir = tmp_path / "venv-codemod"
    venv.create(venv_dir, with_pip=True, clear=True)

    if sys.platform == "win32":
        py = venv_dir / "Scripts" / "python.exe"
    else:
        py = venv_dir / "bin" / "python"

    # The extras syntax is ``<wheel>[extra]``; pip resolves that the
    # same as a named install ``vera-sdk[codemod]``.
    install_target = f"{wheel}[codemod]"
    result = subprocess.run(
        [str(py), "-m", "pip", "install", "--quiet", install_target],
        capture_output=True,
        text=True,
        timeout=240,
    )
    if result.returncode != 0:
        pytest.fail(
            f"pip install [codemod] failed (rc={result.returncode}):\n"
            f"STDOUT:\n{result.stdout}\n"
            f"STDERR:\n{result.stderr}"
        )

    # Confirm libcst is pulled in and the codemod's public API is importable.
    # ``vera.codemod.__all__`` is the contract; if any of these symbols
    # disappear we've broken the migration tool for existing users.
    smoke_script = (
        "import libcst; "
        "from vera.codemod import (MigrationOptions, MigrationResult, "
        "migrate_source, migrate_file, iter_python_files, make_diff, "
        "CODEMOD_OPT_OUT_DIRECTIVE); "
        "assert callable(migrate_source); "
        "print('codemod smoke ok')"
    )
    result = subprocess.run(
        [str(py), "-c", smoke_script],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        pytest.fail(
            f"codemod smoke script failed (rc={result.returncode}):\n"
            f"STDOUT:\n{result.stdout}\n"
            f"STDERR:\n{result.stderr}"
        )
    assert "codemod smoke ok" in result.stdout
